#!/usr/bin/env python3
"""
Each database gets its own same-level-scoped `.base` (`file.folder == "<path>"`,
non-recursive) at its folder, and the vault-wide `.base` at the output root
still exists alongside them.

Run: /usr/bin/python3 test_per_level_bases.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build
import notion_db_to_obsidian as n


class PerLevelBases(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.out = self.tmp / "out"
        build(self.tmp / "src")
        n.run_conversion(self.tmp / "src", self.out, attachment_mode="inplace")

    def tearDown(self):
        self._td.cleanup()

    def test_per_level_base_files_exist(self):
        self.assertTrue((self.out / "Animals" / "Animals.base").is_file())
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Breeds.base").is_file())
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby" / "Photos" / "Photos.base").is_file())
        self.assertTrue((self.out / "Field Guide" / "Steps" / "Steps.base").is_file())

    def test_per_level_base_is_folder_scoped(self):
        text = (self.out / "Animals" / "Cat" / "Breeds" / "Breeds.base").read_text(encoding="utf-8")
        self.assertIn('file.folder == "Animals/Cat/Breeds"', text)

    def test_vault_wide_base_still_exists(self):
        self.assertTrue(list(self.out.glob("*.base")), "no vault-wide .base at the output root")


if __name__ == "__main__":
    unittest.main(verbosity=2)
