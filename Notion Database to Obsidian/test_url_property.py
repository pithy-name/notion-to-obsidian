#!/usr/bin/env python3
"""
Tests for text properties whose value is a hyperlink.

A Notion `text` property can hold a single <a> link (e.g. a Slack channel).
markdownify renders it `[label](url)`, which is noise inside a YAML frontmatter
value — collapse a sole link to the bare URL. Mixed content is preserved.

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_url_property.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).with_name("notion_db_to_obsidian.py")
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def td(inner: str):
    return BeautifulSoup(f"<td>{inner}</td>", "html.parser").find("td")


class TextPropertyWithLink(unittest.TestCase):
    def test_sole_link_becomes_bare_url(self):
        cell = td('<a href="https://example.com/chan">#channel-name</a>')
        self.assertEqual(ndo.convert_property_value("text", cell), "https://example.com/chan")

    def test_text_around_link_is_kept_as_markdown(self):
        cell = td('see <a href="https://example.com/x">label</a> now')
        value = ndo.convert_property_value("text", cell)
        self.assertIn("[label](https://example.com/x)", value)  # not unwrapped

    def test_plain_text_unchanged(self):
        self.assertEqual(ndo.convert_property_value("text", td("just text")), "just text")

    def test_empty_is_none(self):
        self.assertIsNone(ndo.convert_property_value("text", td("")))


class UnwrapHelper(unittest.TestCase):
    def test_unwraps_single_link(self):
        self.assertEqual(ndo._unwrap_sole_markdown_link("[a](https://x.com/y)"), "https://x.com/y")

    def test_leaves_non_link(self):
        self.assertEqual(ndo._unwrap_sole_markdown_link("plain text"), "plain text")

    def test_leaves_mixed(self):
        s = "prefix [a](https://x.com/y)"
        self.assertEqual(ndo._unwrap_sole_markdown_link(s), s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
