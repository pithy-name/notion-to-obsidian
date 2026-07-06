#!/usr/bin/env python3
"""
B3 (safe partial, no clean structural fix): a directory filtered out of the
attachment copy by the sibling-html rule or the contains-node-html rule must
never be dropped SILENTLY. There is no content-based way to tell a genuine
Notion node folder from an unrelated user directory that coincidentally
matches the same naming shape (`<name>` + sibling `<name>.html`, or a folder
containing a hex-named `.html`), so this is not "fixed" — but every such
filter decision must now surface an explicit WARN line naming the path, so a
user can go check it by hand instead of silently losing files.

Run: /usr/bin/python3 test_ambiguous_dir_filter_warns.py
"""
import os
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder
import notion_db_to_obsidian as n


class AmbiguousDirFilterWarnsUnit(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_sibling_html_dir_filter_emits_warning(self):
        (self.d / "Memo 0123456789abcdef0123456789abcdef.html").write_text(
            "x", encoding="utf-8")
        (self.d / "Memo 0123456789abcdef0123456789abcdef").mkdir()
        warn_log = []
        n._attachment_copy_ignore(str(self.d), os.listdir(self.d), warn_log=warn_log)
        self.assertTrue(
            any("B3" in w and "Memo 0123456789abcdef0123456789abcdef" in w for w in warn_log),
            f"expected a B3 WARN naming the filtered directory, got: {warn_log}",
        )

    def test_nested_db_dir_filter_emits_warning(self):
        db_dir = self.d / "Bug Catalog 0123456789abcdef0123456789abcdef"
        db_dir.mkdir()
        (db_dir / "Entry One fedcba9876543210fedcba9876543210.html").write_text(
            "<html></html>", encoding="utf-8")
        warn_log = []
        n._attachment_copy_ignore(str(self.d), os.listdir(self.d), warn_log=warn_log)
        self.assertTrue(
            any("B3" in w and "Bug Catalog" in w for w in warn_log),
            f"expected a B3 WARN naming the filtered directory, got: {warn_log}",
        )

    def test_no_warn_log_arg_does_not_error(self):
        # Backward compatibility: callers that don't pass warn_log (existing
        # tests, and the copy_has_attachments pre-check style call) must not break.
        (self.d / "Memo 0123456789abcdef0123456789abcdef.html").write_text(
            "x", encoding="utf-8")
        (self.d / "Memo 0123456789abcdef0123456789abcdef").mkdir()
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertIn("Memo 0123456789abcdef0123456789abcdef", ignored)

    def test_no_duplicate_warning_for_same_directory(self):
        (self.d / "Memo 0123456789abcdef0123456789abcdef.html").write_text(
            "x", encoding="utf-8")
        (self.d / "Memo 0123456789abcdef0123456789abcdef").mkdir()
        warn_log = []
        n._attachment_copy_ignore(str(self.d), os.listdir(self.d), warn_log=warn_log)
        n._attachment_copy_ignore(str(self.d), os.listdir(self.d), warn_log=warn_log)
        matches = [w for w in warn_log if "Memo 0123456789abcdef0123456789abcdef" in w]
        self.assertEqual(len(matches), 1, f"expected exactly one WARN, got: {matches}")


class AmbiguousDirFilterWarnsFullConversion(unittest.TestCase):
    def test_run_conversion_surfaces_warning_for_nested_db_folder(self):
        # A normal nested-DB export (Cat owns "Breeds") IS the ambiguous shape
        # by construction — the converter cannot tell it apart from a
        # coincidentally-named unrelated user folder by name alone, so the
        # WARN must appear in the run's overwrite_log/report even for this
        # everyday case.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        summary = n.run_conversion(src, out)
        self.assertTrue(
            any("B3" in w for w in summary["overwrite_log"]),
            "expected at least one B3 WARN in the conversion's overwrite_log",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
