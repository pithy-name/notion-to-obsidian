#!/usr/bin/env python3
"""
B11: a top-level DB home note must not print "# <DB>" then immediately
"## <DB>" — the owned-DB section heading repeating the page title verbatim.
When a database's index/landing page is named identically to the database
itself (a common shape: a database's own index page named after the
database), the redundant "## <name>" heading is omitted; the .base embed and
entry list still follow directly under the page's own "# <name>" H1.

Run: /usr/bin/python3 test_owned_db_heading_dedup.py
"""
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

import notion_db_to_obsidian as n


class OwnedDbHeadingDedup(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _write(self, page_title: str, db_name: str) -> str:
        src = self.tmp / "src"; src.mkdir()
        out = self.tmp / "out"; out.mkdir()
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": page_title,
            "notion_uuid": None,
            "properties": [],
            "body": None,
        }
        n.write_entry(
            entry, out, OrderedDict(), {}, {},
            owned_dbs=[{"name": db_name, "base_name": db_name, "children": ["A", "B"]}],
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        return (out / f"{page_title}.md").read_text(encoding="utf-8")

    def test_identical_name_omits_redundant_heading(self):
        text = self._write("Notes", "Notes")
        self.assertNotIn("## Notes", text)
        self.assertIn("\n# Notes\n", text)
        self.assertIn("![[Notes.base]]", text)  # base embed still present

    def test_different_name_keeps_heading(self):
        text = self._write("Field Guide", "Steps")
        self.assertIn("# Field Guide", text)
        self.assertIn("## Steps", text)

    def test_case_insensitive_match_omits_redundant_heading(self):
        # F9 (B11 exact-match gap): "# Animals" page title vs "## animals" db
        # name is the SAME name modulo case — the exact `!=` compare treated
        # them as different and kept the redundant heading.
        text = self._write("Animals", "animals")
        self.assertNotIn("## animals", text)
        self.assertIn("\n# Animals\n", text)
        self.assertIn("![[animals.base]]", text)

    def test_whitespace_normalized_match_omits_redundant_heading(self):
        # "Notes" vs " Notes " (stray leading/trailing whitespace) is also
        # the same name for dedup purposes.
        text = self._write("Notes", " Notes ")
        self.assertNotIn("##  Notes ", text)
        self.assertIn("\n# Notes\n", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
