#!/usr/bin/env python3
"""
Tests for Notion toggle → Obsidian foldable callout conversion.

Notion exports a toggle as
    <ul class="toggle"><li><details [open]><summary>Title</summary>body</details></li></ul>
which should become an EXPANDED, still-collapsible Obsidian callout:
    > [!note]+ Title
    > body

(Notion's export marks every toggle <details open>, so the attribute carries
no real state; we default to expanded — content visible, still click-to-collapse.)

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_toggles.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def conv(html: str) -> str:
    soup = BeautifulSoup(f'<div class="page-body">{html}</div>', "html.parser")
    return ndo.convert_body(
        soup.find("div", class_="page-body"),
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
    )


class Toggles(unittest.TestCase):
    def test_toggle_becomes_expanded_foldable_callout(self):
        html = '<ul class="toggle"><li><details><summary>Details title</summary><p>hidden content</p></details></li></ul>'
        md = conv(html)
        self.assertIn("> [!note]+ Details title", md)
        self.assertIn("> hidden content", md)
        self.assertNotIn("- > ", md)  # no stray bullet wrapping the callout

    def test_open_attr_ignored_default_expanded(self):
        # Notion marks every toggle <details open>; we always emit expanded `+`.
        html = '<ul class="toggle"><li><details open><summary>Open one</summary><p>body</p></details></li></ul>'
        md = conv(html)
        self.assertIn("> [!note]+ Open one", md)
        self.assertNotIn("[!note]-", md)

    def test_standalone_details_heading(self):
        md = conv('<details><summary>Bare</summary><p>x</p></details>')
        self.assertIn("> [!note]+ Bare", md)
        self.assertIn("> x", md)

    def test_toggle_nested_in_bullet_keeps_parent_bullet(self):
        html = (
            '<ul class="bulleted-list"><li>Parent'
            '<ul class="toggle"><li><details><summary>Child toggle</summary><p>c</p></details></li></ul>'
            "</li></ul>"
        )
        md = conv(html)
        self.assertIn("- Parent", md)
        self.assertIn("> [!note]+ Child toggle", md)

    def test_toggle_heading_becomes_real_markdown_heading(self):
        # Audit item 5: a toggle whose summary IS a heading keeps its heading
        # level as a real Markdown heading (Obsidian folds headings natively),
        # rather than flattening to a callout that loses the level.
        md = conv('<details><summary><h3>Section</h3></summary><p>body text</p></details>')
        self.assertIn("### Section", md)
        self.assertIn("body text", md)
        self.assertNotIn("[!note]", md)  # a real heading, not a callout


if __name__ == "__main__":
    unittest.main(verbosity=2)
