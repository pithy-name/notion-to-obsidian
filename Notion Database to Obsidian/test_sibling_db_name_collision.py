#!/usr/bin/env python3
"""
B4: two different databases that merely SHARE a display name must not merge
into one output directory.

`mirror_output_dir` maps a source folder to its output path by stripping the
Notion hex id from every path component. Two distinct sibling databases named
identically (their source folders are "<Name> <hexA>/" and "<Name> <hexB>/",
each carrying its own unique hex) both hex-strip to the same "<Name>/" output
path — their entries would land in one shared folder, silently interleaving
two different databases' rows.

Fixture: two standalone pages "Left" and "Right", each owning its own child
database named "Notes" (same display name, different Notion hex ids).

Run: /usr/bin/python3 test_sibling_db_name_collision.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import _db, _page_html, _write, folder, uuid_of
import notion_db_to_obsidian as n


def _build_colliding_dbs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write(root / f"{folder('Left')}.html", _page_html("Left", "<p>left</p>"))
    left_dir = root / folder("Left")
    _db(left_dir, "Notes", [("A", [("Order", "number", "1")], "")])

    _write(root / f"{folder('Right')}.html", _page_html("Right", "<p>right</p>"))
    right_dir = root / folder("Right")
    _db(right_dir, "Notes", [("B", [("Order", "number", "1")], "")])


class SiblingDbNameCollision(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        _build_colliding_dbs(self.src)
        self.summary = n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_two_distinct_output_dirs_exist(self):
        left_notes = self.out / "Left" / "Notes"
        right_notes = self.out / "Right" / "Notes"
        self.assertTrue(left_notes.is_dir(), "Left's Notes db should get its own dir")
        self.assertTrue(right_notes.is_dir(), "Right's Notes db should get its own dir")

    def test_entries_are_not_interleaved(self):
        left_entries = sorted(p.stem for p in (self.out / "Left" / "Notes").glob("*.md")
                               if p.stem != "Notes")
        right_entries = sorted(p.stem for p in (self.out / "Right" / "Notes").glob("*.md")
                                if p.stem != "Notes")
        self.assertEqual(left_entries, ["A"])
        self.assertEqual(right_entries, ["B"])

    def test_two_databases_discovered(self):
        self.assertEqual(len(self.summary["databases"]), 2)

    def test_no_dropped_entries(self):
        self.assertEqual(self.summary["total_entries"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
