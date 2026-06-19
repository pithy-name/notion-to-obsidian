#!/usr/bin/env python3
"""
A database's "home" note embeds its `.base` and lists its entries as
`[[wikilinks]]`; each entry carries an `↑ Part of [[home]]` backlink. The home is
the owning entry/page for a nested database, or the index/landing page for a
top-level database — so database index/landing pages are written as notes too.

Run: /usr/bin/python3 test_home_notes_and_backlinks.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build
import notion_db_to_obsidian as n


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class HomeNotesAndBacklinks(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.out = self.tmp / "out"
        build(self.tmp / "src")
        n.run_conversion(self.tmp / "src", self.out, attachment_mode="inplace")

    def tearDown(self):
        self._td.cleanup()

    def test_top_level_db_home_embeds_base_and_links(self):
        home = _read(self.out / "Animals.md")          # the DB index page is the home
        self.assertIn("![[Animals.base]]", home)
        self.assertIn("[[Cat]]", home)
        self.assertIn("[[Dog]]", home)

    def test_nested_db_owner_is_home(self):
        cat = _read(self.out / "Animals" / "Cat.md")
        self.assertIn("![[Breeds.base]]", cat)         # Cat owns Breeds
        self.assertIn("[[Tabby]]", cat)
        self.assertIn("[[Siamese]]", cat)

    def test_child_has_part_of_backlink(self):
        self.assertIn("Part of [[Animals]]", _read(self.out / "Animals" / "Cat.md"))
        self.assertIn("Part of [[Cat]]", _read(self.out / "Animals" / "Cat" / "Breeds" / "Tabby.md"))

    def test_page_can_own_a_database(self):
        fg = _read(self.out / "Field Guide.md")
        self.assertIn("![[Steps.base]]", fg)
        self.assertIn("[[Step One]]", fg)
        step = _read(self.out / "Field Guide" / "Steps" / "Step One.md")
        self.assertIn("Part of [[Field Guide]]", step)

    def test_index_pages_written_as_notes(self):
        self.assertTrue((self.out / "Animals.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
