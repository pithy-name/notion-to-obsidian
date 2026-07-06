#!/usr/bin/env python3
"""
Tests for Notion callout → Obsidian callout conversion.

Notion exports a callout as
    <figure class="… callout"><div>[emoji]</div><div>[content]</div></figure>
which should become an Obsidian callout:
    > [!tip] 💡
    > content

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_callouts.py"
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


def callout(emoji: str, body: str) -> str:
    icon = f'<div style="font-size:1.5em"><span class="icon">{emoji}</span></div>' if emoji else ""
    return f'<figure class="block-color-purple_background callout">{icon}<div style="width:100%">{body}</div></figure>'


class Callouts(unittest.TestCase):
    def test_mapped_emoji_sets_type_and_keeps_emoji(self):
        md = conv(callout("💡", "<strong>Note:</strong> hello"))
        self.assertIn("> [!tip] 💡", md)
        self.assertIn("**Note:**", md)
        self.assertIn("hello", md)

    def test_warning_emoji_maps_to_warning(self):
        self.assertIn("> [!warning] ❗", conv(callout("❗", "careful")))

    def test_unmapped_emoji_defaults_to_note_and_keeps_emoji(self):
        self.assertIn("> [!note] 🎠", conv(callout("🎠", "carousel")))

    def test_no_icon_defaults_to_note(self):
        md = conv('<figure class="callout"><div style="width:100%">body text</div></figure>')
        self.assertIn("> [!note]", md)
        self.assertIn("body text", md)

    def test_content_is_flush_inside_callout(self):
        # Title and content must share the same `> ` prefix (a well-formed
        # Obsidian callout), not have the content indented or left loose.
        md = conv(callout("💡", "line one"))
        self.assertIn("> [!tip] 💡\n>\n> line one", md)

    def test_icon_and_content_in_one_div_keeps_content(self):
        # Degenerate layout: icon and body share a single <div>. Content must
        # not be dropped.
        html = '<figure class="callout"><div><span class="icon">💡</span> inline body kept</div></figure>'
        md = conv(html)
        self.assertIn("> [!tip]", md)
        self.assertIn("inline body kept", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
