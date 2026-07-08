#!/usr/bin/env python3
"""
K1 — run_conversion (the public library API) must validate its input path
itself, not rely on the CLI's pre-check in main(). Before this fix, a library
caller passing a nonexistent/non-directory path got a fake "successful empty
conversion" (report + .base written, normal summary dict, no error).

Covers:
  - run_conversion raises on a nonexistent path.
  - run_conversion raises on a path that exists but isn't a directory.
  - main() (the CLI) still gives a clean error + non-zero exit, no traceback,
    for a bad path.
  - run_conversion on a valid but EMPTY directory does NOT raise (that's a
    legitimate empty conversion) but signals "nothing found" via the returned
    summary dict.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import notion_db_to_obsidian as n


class RunConversionInputValidation(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_nonexistent_path_raises(self):
        bad_src = self.tmp / "does-not-exist-xyz"
        out = self.tmp / "out"
        with self.assertRaises(FileNotFoundError):
            n.run_conversion(bad_src, out)

    def test_non_directory_path_raises(self):
        # A real file (not a directory) passed as src.
        file_src = self.tmp / "not-a-dir.txt"
        file_src.write_text("hello", encoding="utf-8")
        out = self.tmp / "out"
        with self.assertRaises(NotADirectoryError):
            n.run_conversion(file_src, out)

    def test_valid_empty_directory_does_not_raise_and_signals_no_content(self):
        empty_src = self.tmp / "empty-export"
        empty_src.mkdir()
        out = self.tmp / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = n.run_conversion(empty_src, out)
        self.assertTrue(summary["no_content_found"])
        self.assertEqual(summary["total_entries"], 0)
        self.assertEqual(summary["pages_written"], 0)
        self.assertIn("no Notion content found", buf.getvalue())

    def test_orphan_only_directory_is_not_no_content_found(self):
        # L1: a directory holding ONLY non-HTML orphan files (no .html at all)
        # is a real, if HTML-less, conversion once copy_orphaned_files runs.
        # no_content_found must be False, the files must land in out_root, and
        # the "no content found" warning must NOT be printed.
        src_dir = self.tmp / "orphans-only"
        sub = src_dir / "Screenshots"
        sub.mkdir(parents=True)
        (sub / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
        (sub / "doc.pdf").write_bytes(b"%PDF-1.4 fake pdf bytes")
        out = self.tmp / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = n.run_conversion(src_dir, out)
        self.assertFalse(summary["no_content_found"])
        self.assertEqual(summary["total_entries"], 0)
        self.assertEqual(summary["pages_written"], 0)
        self.assertEqual(summary["orphaned_files"], 2)
        self.assertTrue((out / "Screenshots" / "photo.png").exists())
        self.assertTrue((out / "Screenshots" / "doc.pdf").exists())
        self.assertNotIn("no Notion content found", buf.getvalue())

    def test_orphan_only_directory_rerun_does_not_flip_to_no_content_found(self):
        # L1 follow-up: copy_orphaned_files treats a byte-identical file
        # already on disk as "nothing new to do" and does not count it in its
        # returned `copied` total (idempotent re-run design). A naive fix that
        # keys no_content_found purely off that per-run `copied` count would
        # then read no_content_found=True on the SECOND run against the same
        # src/out pair, even though the output vault still holds the file
        # from the first run. no_content_found must reflect "does the output
        # contain content", not "did this specific invocation copy anything
        # new".
        src_dir = self.tmp / "orphans-only-rerun"
        src_dir.mkdir()
        (src_dir / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
        out = self.tmp / "out"
        buf1 = io.StringIO()
        with contextlib.redirect_stdout(buf1):
            n.run_conversion(src_dir, out)
        self.assertTrue((out / "photo.png").exists())
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            summary2 = n.run_conversion(src_dir, out)
        self.assertFalse(summary2["no_content_found"])
        self.assertTrue((out / "photo.png").exists())
        self.assertNotIn("no Notion content found", buf2.getvalue())

    def test_genuinely_empty_directory_still_signals_no_content(self):
        # Regression guard for K1's original case: truly nothing (no files at
        # all, not even orphans) still signals no_content_found + warns.
        empty_src = self.tmp / "truly-empty"
        empty_src.mkdir()
        out = self.tmp / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = n.run_conversion(empty_src, out)
        self.assertTrue(summary["no_content_found"])
        self.assertEqual(summary["orphaned_files"], 0)
        self.assertIn("no Notion content found", buf.getvalue())

    def test_real_html_entries_are_not_no_content_found(self):
        # Regression guard: real HTML content -> no_content_found is False.
        # (Covered implicitly by other test files' fixtures too, but pinned
        # here directly against the corrected predicate.)
        src_dir = self.tmp / "real-page"
        src_dir.mkdir()
        (src_dir / "Hello 1111111111111111111111111111abcd.html").write_text(
            "<html><body><div class=\"page-title\">Hello</div>"
            "<div class=\"page-body\"></div></body></html>",
            encoding="utf-8",
        )
        out = self.tmp / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = n.run_conversion(src_dir, out)
        self.assertFalse(summary["no_content_found"])
        self.assertNotIn("no Notion content found", buf.getvalue())

    def test_cli_gives_clean_error_not_traceback_for_bad_path(self):
        bad_src = self.tmp / "does-not-exist-xyz"
        script = Path(n.__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(script), str(bad_src)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
