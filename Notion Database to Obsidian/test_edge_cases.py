#!/usr/bin/env python3
"""
Piece 4 — edge cases for the nested-directory feature (spec "Edge cases").

Run: /usr/bin/python3 test_edge_cases.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, _db, folder, _page_html, _write
import notion_db_to_obsidian as n


class EdgeCases(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def _run(self, **kw):
        return n.run_conversion(self.src, self.out, attachment_mode="inplace", **kw)

    def test_page_only_export(self):
        # No database at all → pages become notes, no "database required" fatal.
        _write(self.src / f"{folder('Note A')}.html", _page_html("Note A", "<p>a</p>"))
        _write(self.src / f"{folder('Note B')}.html", _page_html("Note B", "<p>b</p>"))
        summary = self._run()
        self.assertTrue((self.out / "Note A.md").is_file())
        self.assertTrue((self.out / "Note B.md").is_file())
        self.assertEqual(summary["total_entries"], 0)

    def test_single_entry_database(self):
        _db(self.src, "Solo", [("Only", [("X", "text", "1")], "")])
        self._run()
        home = (self.out / "Solo.md").read_text(encoding="utf-8")
        self.assertIn("![[Solo.base]]", home)
        self.assertIn("[[Only]]", home)
        self.assertIn("Part of [[Solo]]", (self.out / "Solo" / "Only.md").read_text(encoding="utf-8"))

    def test_node_owning_multiple_child_dbs(self):
        root_entries = _db(self.src, "Root", [("Parent", [("X", "text", "1")], "")])
        parent_dir = root_entries / folder("Parent")
        _db(parent_dir, "Alpha", [("a1", [("X", "text", "1")], "")])
        _db(parent_dir, "Beta", [("b1", [("X", "text", "1")], "")])
        self._run()
        parent = (self.out / "Root" / "Parent.md").read_text(encoding="utf-8")
        self.assertIn("![[Alpha.base]]", parent)
        self.assertIn("![[Beta.base]]", parent)
        self.assertIn("[[a1]]", parent)
        self.assertIn("[[b1]]", parent)

    def test_folder_missing_hex_does_not_crash_and_warns(self):
        # A nested DB whose owner folder was renamed (no hex id) can't be mapped.
        root_entries = _db(self.src, "Root", [("Parent", [("X", "text", "1")], "")])
        renamed = root_entries / "Parent"  # no hex id
        _db(renamed, "Child", [("c1", [("X", "text", "1")], "")])
        summary = self._run()  # must not raise
        self.assertTrue(any((self.out).rglob("c1.md")))  # child entry still written
        self.assertTrue(
            any("Parent" in w or "map" in w.lower() or "renamed" in w.lower()
                for w in summary["warnings"]),
            summary["warnings"],
        )

    def test_copy_mode_on_nested_export_does_not_crash(self):
        # Default attachment mode on a deeply nested export must not raise.
        build(self.src)
        summary = n.run_conversion(self.src, self.out, attachment_mode="copy")
        self.assertTrue((self.out / "Animals" / "Cat.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
