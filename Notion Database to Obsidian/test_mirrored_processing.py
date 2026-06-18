#!/usr/bin/env python3
"""
Piece 2 — recursive MIRRORED processing.

Every node (DB entry at any depth + standalone page) becomes a real .md note
at a path that mirrors the source nesting, with the Notion hex id stripped from
every path component. No depth ceiling; no "database required" rule.

Run: /usr/bin/python3 test_mirrored_processing.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build
import notion_db_to_obsidian as n


def _convert(tmp: Path) -> Path:
    """Build the synthetic export under tmp/src, convert into tmp/out, return out."""
    src = tmp / "src"
    out = tmp / "out"
    build(src)
    # inplace: don't copy/symlink owner subfolders (which now hold child nodes).
    n.run_conversion(src, out, attachment_mode="inplace")
    return out


class MirroredProcessing(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.out = _convert(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def test_top_level_db_entries_become_notes(self):
        self.assertTrue((self.out / "Animals" / "Cat.md").is_file())
        self.assertTrue((self.out / "Animals" / "Dog.md").is_file())

    def test_nested_db_entries_become_notes_mirrored(self):
        # Breeds is owned by Cat → lives under Cat's own folder.
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby.md").is_file())
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Siamese.md").is_file())

    def test_deep_db_beyond_old_depth_limit(self):
        # Photos sits at a depth that the old depth-2 ceiling would have aborted on.
        photos = self.out / "Animals" / "Cat" / "Breeds" / "Tabby" / "Photos"
        self.assertTrue((photos / "Photo1.md").is_file())
        self.assertTrue((photos / "Photo2.md").is_file())

    def test_standalone_pages_become_notes(self):
        self.assertTrue((self.out / "About.md").is_file())
        self.assertTrue((self.out / "Field Guide.md").is_file())

    def test_page_owned_db_mirrors_under_the_page(self):
        steps = self.out / "Field Guide" / "Steps"
        self.assertTrue((steps / "Step One.md").is_file())
        self.assertTrue((steps / "Step Two.md").is_file())

    def test_entry_note_and_child_folder_coexist(self):
        # The note + its children folder are siblings (Obsidian note+folder pattern).
        self.assertTrue((self.out / "Animals" / "Cat.md").is_file())
        self.assertTrue((self.out / "Animals" / "Cat").is_dir())

    def test_note_body_starts_with_title_heading(self):
        # Notion renders the page title at the top of the page; the note body
        # should open with an `# <Title>` H1 (item 65).
        text = (self.out / "Animals" / "Cat.md").read_text(encoding="utf-8")
        after_fm = text.split("---", 2)[-1].lstrip()
        self.assertTrue(after_fm.startswith("# Cat"), after_fm[:80])

    def test_body_table_stays_markdown_table(self):
        # Cat's body has a real <table> — must render as a Markdown table,
        # never be mistaken for a nested database.
        text = (self.out / "Animals" / "Cat.md").read_text(encoding="utf-8")
        self.assertIn("| Trait", text)
        self.assertIn("Meow", text)

    def test_total_note_count(self):
        # 8 DB entries + 2 standalone pages = 10 notes. Exclude .base/report.
        notes = [p for p in self.out.rglob("*.md") if not p.name.startswith("_")]
        self.assertEqual(len(notes), 10, sorted(str(p.relative_to(self.out)) for p in notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
