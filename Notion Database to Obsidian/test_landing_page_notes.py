#!/usr/bin/env python3
"""
A collection/landing page that owns databases but is not itself a database's
index becomes a real note.

Notion's export root (and any "hub" page) is a page WITH a collection-content
table — so it classifies as a database parent — yet its own folder holds child
*databases*, not entry HTMLs. Its hex therefore matches no entries-folder, so it
was silently dropped: no note, its inline images orphaned, and every database it
owns reported "no home note found".

Such a page must be written as a note with its attachments copied. Because it is
a *collection/landing* page (its body is just a list of databases), it does NOT
become their home — each database it owns uses its OWN index note as home (embeds
the `.base`, lists entries, receives the `↑ Part of` backlinks); the landing page
stays a plain landing. (A genuine *content* page that owns a database — see
test_home_notes_and_backlinks — still acts as that database's home.)

Run: /usr/bin/python3 test_landing_page_notes.py
"""
import tempfile
import unittest
from pathlib import Path

import synthetic_export as se
import notion_db_to_obsidian as n


class LandingPageBecomesNote(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        self.src, self.out = tmp / "src", tmp / "out"
        self.src.mkdir(parents=True)
        # Top-level landing page "Hub": collection-content => classified 'parent'.
        se._write(self.src / f"{se.folder('Hub')}.html", se._index_html("Hub"))
        hub_dir = self.src / se.folder("Hub")
        hub_dir.mkdir(parents=True, exist_ok=True)
        # A genuine attachment that belongs to the landing page.
        (hub_dir / "logo.png").write_bytes(b"\x89PNG fake bytes")
        # Hub owns a database "Stuff" (its entries live inside Hub's folder).
        se._db(hub_dir, "Stuff", [
            ("Item A", [("X", "select", "1")], ""),
            ("Item B", [("X", "select", "2")], ""),
        ])
        n.run_conversion(self.src, self.out)  # default copy

    def tearDown(self):
        self._td.cleanup()

    def test_landing_page_is_written_as_a_note(self):
        self.assertTrue((self.out / "Hub.md").is_file())

    def test_landing_page_attachment_is_copied(self):
        self.assertTrue((self.out / "Hub" / "logo.png").is_file())

    def test_owned_database_entries_still_written(self):
        self.assertTrue((self.out / "Hub" / "Stuff" / "Item A.md").is_file())
        self.assertTrue((self.out / "Hub" / "Stuff" / "Item B.md").is_file())

    def test_db_index_is_home_not_the_landing_page(self):
        # A collection/landing page defers to the database's OWN index note as
        # home: Stuff.md embeds the base + lists entries; the landing page does
        # not (it is a plain landing, not a mega-hub).
        index = (self.out / "Hub" / "Stuff.md").read_text(encoding="utf-8")
        self.assertIn("![[Stuff.base]]", index)
        self.assertIn("[[Item A]]", index)
        landing = (self.out / "Hub.md").read_text(encoding="utf-8")
        self.assertNotIn("![[Stuff.base]]", landing)

    def test_owned_entries_backlink_to_db_index(self):
        text = (self.out / "Hub" / "Stuff" / "Item A.md").read_text(encoding="utf-8")
        self.assertIn("Part of [[Stuff]]", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
