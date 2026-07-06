#!/usr/bin/env python3
"""
Tests for Notion background-color → Obsidian highlight (==text==).

Notion marks highlighted text with `block-color-*_background`. We wrap such an
element's inline content in `==`. Block-container backgrounds are skipped, plain
text colors are left alone, and callouts (handled earlier) are excluded.

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_highlights.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).with_name("notion_db_to_obsidian.py")
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


class Highlights(unittest.TestCase):
    def test_background_paragraph_becomes_highlight(self):
        self.assertIn("==highlighted text==", conv('<p class="block-color-purple_background">highlighted text</p>'))

    def test_inline_formatting_preserved_inside_highlight(self):
        md = conv('<p class="block-color-yellow_background"><strong>bold</strong> word</p>')
        self.assertIn("==**bold** word==", md)

    def test_block_container_background_not_wrapped(self):
        md = conv('<div class="block-color-blue_background"><p>a</p><p>b</p></div>')
        self.assertNotIn("==", md)

    def test_plain_text_color_left_alone(self):
        md = conv('<p class="block-color-gray">gray text</p>')
        self.assertIn("gray text", md)
        self.assertNotIn("==", md)

    def test_callout_background_not_highlighted(self):
        # The callout figure carries _background but is converted to a callout
        # before highlights run, so it must NOT also get ==.
        html = '<figure class="block-color-purple_background callout"><div><span class="icon">💡</span></div><div>body</div></figure>'
        md = conv(html)
        self.assertIn("> [!tip]", md)
        self.assertNotIn("==", md)

    def test_empty_background_not_wrapped(self):
        self.assertNotIn("==", conv('<p class="block-color-pink_background">   </p>'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
