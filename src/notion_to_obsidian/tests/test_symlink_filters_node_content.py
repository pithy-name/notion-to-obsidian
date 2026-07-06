#!/usr/bin/env python3
"""
B5: `--symlink` mode must NOT expose child-node content.

The old implementation created ONE directory symlink pointing at the whole
source attachment dir, so anything walking the output (Obsidian included)
could see straight through it to every child node's raw ".html" file and
hex-named folder — exactly the content copy mode's `_attachment_copy_ignore`
filter exists to hide. Symlink mode must apply the same filter: only genuine
attachments get a (per-file) symlink.

Run: /usr/bin/python3 test_symlink_filters_node_content.py
"""
import re
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder
import notion_db_to_obsidian as n

HEX_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)


class SymlinkModeFiltersNodeContent(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        build(self.src)
        cat_dir = self.src / folder("Animals") / folder("Cat")
        (cat_dir / "cat-photo.png").write_bytes(b"\x89PNG fake bytes")
        n.run_conversion(self.src, self.out, attachment_mode="symlink")

    def tearDown(self):
        self._td.cleanup()

    def test_attachment_dir_is_a_real_directory_not_a_whole_dir_symlink(self):
        cat_out = self.out / "Animals" / "Cat"
        self.assertTrue(cat_out.is_dir())
        self.assertFalse(
            cat_out.is_symlink(),
            "the whole attachment dir must not itself be a symlink (B5)",
        )

    def test_genuine_attachment_is_symlinked(self):
        link = self.out / "Animals" / "Cat" / "cat-photo.png"
        self.assertTrue(link.is_symlink(), "genuine attachment should be a symlink")
        self.assertTrue(link.resolve().is_file())
        self.assertEqual(link.read_bytes(), b"\x89PNG fake bytes")

    def test_no_raw_node_html_reachable_through_symlinks(self):
        leaked = sorted(
            str(p.relative_to(self.out)) for p in self.out.rglob("*.html")
        )
        self.assertEqual(leaked, [], f"raw node HTML reachable via symlink mode: {leaked}")

    def test_no_hex_named_entries_reachable_through_symlinks(self):
        leaked = sorted(
            str(p.relative_to(self.out))
            for p in self.out.rglob("*")
            if HEX_RE.search(p.name)
        )
        self.assertEqual(leaked, [], f"hex-named node content reachable via symlinks: {leaked}")

    def test_child_notes_still_written(self):
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
