#!/usr/bin/env python3
"""
Filenames are unique vault-wide: two entries with the same title in different
databases get distinct names (the later one gets a short Notion-id suffix), so
name-based `[[wikilinks]]` stay unambiguous.

Run: /usr/bin/python3 test_unique_filenames.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import _db
import notion_db_to_obsidian as n


class VaultUniqueFilenames(unittest.TestCase):
    def setUp(self):
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
