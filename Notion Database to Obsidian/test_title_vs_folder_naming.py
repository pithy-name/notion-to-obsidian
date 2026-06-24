#!/usr/bin/env python3
"""
A node's note, its attachment folder, and its children must share ONE directory.

Notion names a node's on-disk file/folder from a filesystem-sanitized form of its
title — dropping characters like square brackets. Its H1 title keeps them. If the
note is named from the H1 title while its children (and the source folder) mirror
under the sanitized folder name, the two diverge into duplicate sibling dirs:
e.g. attachments land in "Hub [v2]/" while children land in "Hub/".

The note name must come from the source stem (already Notion's filesystem-safe
name, and exactly what the mirror layout uses), so everything nests under one
folder. The H1 title (with brackets) is still preserved as the body heading.

Run: /usr/bin/python3 test_title_vs_folder_naming.py
"""
import tempfile
import unittest
from pathlib import Path

import synthetic_export as se
import notion_db_to_obsidian as n


class TitleFolderMismatch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        self.src, self.out = tmp / "src", tmp / "out"
        self.src.mkdir(parents=True)
        hexid = se.hex_id("Hub")
        # On disk Notion drops the brackets: file/folder stem is "Hub <hex>",
        # but the H1 title keeps them ("Hub [v2]").
        se._write(self.src / f"Hub {hexid}.html", se._index_html("Hub [v2]"))
        hub_dir = self.src / f"Hub {hexid}"
        hub_dir.mkdir(parents=True, exist_ok=True)
        (hub_dir / "logo.png").write_bytes(b"\x89PNG fake")
        se._db(hub_dir, "Stuff", [("Item", [("X", "select", "1")], "")])
        n.run_conversion(self.src, self.out)  # default copy

    def tearDown(self):
        self._td.cleanup()

    def test_note_named_from_stem(self):
        self.assertTrue((self.out / "Hub.md").is_file())

    def test_no_title_named_split_dir(self):
        self.assertFalse((self.out / "Hub [v2]").exists(),
                         "attachments/note must not land in a separate title-named dir")

    def test_attachment_and_children_share_one_dir(self):
        self.assertTrue((self.out / "Hub" / "logo.png").is_file())
        self.assertTrue((self.out / "Hub" / "Stuff" / "Item.md").is_file())

    def test_title_preserved_as_body_heading(self):
        text = (self.out / "Hub.md").read_text(encoding="utf-8")
        self.assertIn("# Hub [v2]", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
