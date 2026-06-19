#!/usr/bin/env python3
"""
How databases are wired into the Obsidian graph: a same-level-scoped `.base`
per database (plus the vault-wide base), each database's "home" note embedding
its base and listing its entries as `[[wikilinks]]`, each entry's
`↑ Part of [[home]]` backlink, and vault-unique filenames so name-based links
resolve unambiguously.

Run: /usr/bin/python3 test_database_links_and_bases.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build
import notion_db_to_obsidian as n


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class Piece3(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        build(self.src)
        n.run_conversion(self.src, self.out, attachment_mode="inplace")

    def tearDown(self):
        self._td.cleanup()

    # --- AC5: per-level .base per database + vault-wide base ---------------
    def test_per_level_base_files_exist(self):
        self.assertTrue((self.out / "Animals" / "Animals.base").is_file())
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Breeds.base").is_file())
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby" / "Photos" / "Photos.base").is_file())
        self.assertTrue((self.out / "Field Guide" / "Steps" / "Steps.base").is_file())

    def test_per_level_base_is_folder_scoped(self):
        text = _read(self.out / "Animals" / "Cat" / "Breeds" / "Breeds.base")
        self.assertIn('file.folder == "Animals/Cat/Breeds"', text)

    def test_vault_wide_base_still_exists(self):
        bases = list(self.out.glob("*.base"))
        self.assertTrue(bases, "no vault-wide .base at the output root")

    # --- AC6: home embeds child base + lists links; children backlink -----
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

    # --- item 68: DB index/landing pages are written as notes -------------
    def test_index_pages_written_as_notes(self):
        self.assertTrue((self.out / "Animals.md").is_file())


class VaultUniqueFilenames(unittest.TestCase):
    """AC7: two entries with the same title in different databases must get
    distinct, vault-unique filenames so name-based wikilinks stay unambiguous."""

    def setUp(self):
        from synthetic_export import _db
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir(parents=True)
        _db(self.src, "Alpha", [("Shared", [("X", "text", "1")], "")])
        _db(self.src, "Beta", [("Shared", [("X", "text", "2")], "")])
        n.run_conversion(self.src, self.out, attachment_mode="inplace")

    def tearDown(self):
        self._td.cleanup()

    def test_collision_is_disambiguated(self):
        bare = list(self.out.rglob("Shared.md"))
        suffixed = list(self.out.rglob("Shared (*.md"))
        self.assertEqual(len(bare), 1, [str(p) for p in bare])
        self.assertEqual(len(suffixed), 1, [str(p) for p in suffixed])


if __name__ == "__main__":
    unittest.main(verbosity=2)
