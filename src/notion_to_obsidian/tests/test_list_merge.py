#!/usr/bin/env python3
"""
Tests for tight-list conversion of Notion HTML exports.

Notion exports every bullet/number as its OWN single-item <ul>/<ol>, which
markdownify renders as a "loose" list (a blank line between every item).
convert_body() must merge runs of adjacent same-kind sibling lists into one
list first, so the output is a tight Markdown list.

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_list_merge.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

# Load the space-named module by path.
_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def convert(html: str) -> str:
    """Wrap an HTML fragment in a page-body div and convert it."""
    soup = BeautifulSoup(f'<div class="page-body">{html}</div>', "html.parser")
    body = soup.find("div", class_="page-body")
    return ndo.convert_body(
        body,
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
    )


class TightBulletLists(unittest.TestCase):
    def test_adjacent_single_item_uls_merge_to_tight_list(self):
        # Notion's real shape: one <ul class="bulleted-list"> per bullet.
        html = (
            '<ul class="bulleted-list"><li>alpha</li></ul>'
            '<ul class="bulleted-list"><li>beta</li></ul>'
            '<ul class="bulleted-list"><li>gamma</li></ul>'
        )
        md = convert(html)
        self.assertIn("- alpha\n- beta\n- gamma", md)
        # No blank line between bullets.
        self.assertNotIn("- alpha\n\n- beta", md)


class TightNumberedLists(unittest.TestCase):
    def test_adjacent_single_item_ols_merge_and_renumber(self):
        html = (
            '<ol class="numbered-list" start="1"><li>first</li></ol>'
            '<ol class="numbered-list" start="2"><li>second</li></ol>'
        )
        md = convert(html)
        self.assertIn("1. first\n2. second", md)
        self.assertNotIn("1. first\n\n2. second", md)


class NestedLists(unittest.TestCase):
    def test_nested_single_item_uls_merge(self):
        # Parent bullet whose children are two separate single-item <ul>s.
        html = (
            '<ul class="bulleted-list"><li>parent'
            '<ul class="bulleted-list"><li>child one</li></ul>'
            '<ul class="bulleted-list"><li>child two</li></ul>'
            "</li></ul>"
        )
        md = convert(html)
        self.assertIn("- parent", md)
        # Children are tight and indented under the parent.
        self.assertIn("  - child one\n  - child two", md)


class ListsSeparatedByContentStaySeparate(unittest.TestCase):
    def test_paragraph_between_lists_is_preserved(self):
        html = (
            '<ul class="bulleted-list"><li>before</li></ul>'
            "<p>a real paragraph</p>"
            '<ul class="bulleted-list"><li>after</li></ul>'
        )
        md = convert(html)
        # The paragraph must remain block-separated from both bullets.
        self.assertIn("- before\n\na real paragraph\n\n- after", md)

    def test_different_kinds_do_not_merge(self):
        # A bulleted list directly followed by a numbered list: distinct kinds.
        html = (
            '<ul class="bulleted-list"><li>bullet</li></ul>'
            '<ol class="numbered-list" start="1"><li>number</li></ol>'
        )
        md = convert(html)
        self.assertIn("- bullet", md)
        self.assertIn("1. number", md)
        # They are two separate lists -> a blank line between them.
        self.assertIn("- bullet\n\n1. number", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
