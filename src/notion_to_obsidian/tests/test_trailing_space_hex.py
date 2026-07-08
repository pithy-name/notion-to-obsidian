#!/usr/bin/env python3
"""
Notion sometimes exports folder names with a trailing space after the 32-char
hex id: "Title <hex> " instead of "Title <hex>". NOTION_ID_RE must match and
strip both the hex and the trailing space so the output path is clean.

Run: /usr/bin/python3 test_trailing_space_hex.py
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder, hex_id
import notion_db_to_obsidian as n


class TrailingSpaceStrip(unittest.TestCase):
    """strip_notion_id and extract_notion_id handle trailing-space hex names."""

    HEX = "0123456789abcdef0123456789abcdef"

    def test_strip_removes_hex_and_trailing_space(self):
        name = f"Section {self.HEX} "
        self.assertEqual(n.strip_notion_id(name), "Section")

    def test_strip_without_trailing_space_unchanged(self):
        name = f"Section {self.HEX}"
        self.assertEqual(n.strip_notion_id(name), "Section")

    def test_extract_finds_hex_with_trailing_space(self):
        name = f"Section {self.HEX} "
        self.assertEqual(n.extract_notion_id(name), self.HEX.lower())

    def test_extract_finds_hex_without_trailing_space(self):
        name = f"Section {self.HEX}"
        self.assertEqual(n.extract_notion_id(name), self.HEX.lower())


class TrailingSpaceIntegration(unittest.TestCase):
    """
    A trailing-space hex folder in the source must NOT appear as a ghost
    hex directory in the output. The hex (with trailing space) must be
    stripped from every path component by mirror_output_dir.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        # Build minimal source: a container folder whose name has a trailing
        # space after the hex, with a nested DB inside it.
        h = hex_id("Container")
        container = self.src / f"Container {h} "   # trailing space
        container.mkdir(parents=True)

        db_h = hex_id("Items")
        db_dir = container / f"Items {db_h}"
        db_dir.mkdir()
        entry_h = hex_id("Entry1")
        (db_dir / f"Entry1 {entry_h}.html").write_text(
            f'<html><body><article id="{n.hex_to_uuid(entry_h)}" class="page sans">'
            '<h1 class="page-title">Entry1</h1>'
            '<div class="page-body"></div></article></body></html>',
            encoding="utf-8",
        )
        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_no_hex_dirs_in_output(self):
        import re
        HEX_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)
        leaked = [
            str(p.relative_to(self.out))
            for p in self.out.rglob("*")
            if p.is_dir() and HEX_RE.search(p.name)
        ]
        self.assertEqual(leaked, [], f"hex dirs leaked into output: {leaked}")

    def test_entry_note_written_under_clean_path(self):
        # Entry1.md should appear under Container/Items/Entry1.md — no hex in path.
        expected = self.out / "Container" / "Items" / "Entry1.md"
        self.assertTrue(expected.is_file(), f"note not found at expected clean path {expected}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
