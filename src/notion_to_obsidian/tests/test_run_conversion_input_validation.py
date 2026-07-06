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
