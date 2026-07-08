#!/usr/bin/env python3
"""
Tests for text properties whose value is a hyperlink.

A Notion `text` property can hold a single <a> link (e.g. a Slack channel).
Emitting it as `[label](url)` is noise inside a YAML frontmatter value, so a
sole link collapses to the bare URL — detected on the HTML (so any URL works,
including ones containing ')'). Mixed content is preserved as Markdown.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def td(inner: str):
    return BeautifulSoup(f"<td>{inner}</td>", "html.parser").find("td")


class TextPropertyWithLink(unittest.TestCase):
    def test_sole_link_becomes_bare_url(self):
        cell = td('<a href="https://example.com/chan">#channel-name</a>')
        self.assertEqual(ndo.convert_property_value("text", cell), "https://example.com/chan")

    def test_sole_link_with_parens_in_url(self):
        # The old regex approach missed URLs containing ')'; the HTML approach handles it.
        cell = td('<a href="https://en.wikipedia.org/wiki/Foo_(bar)">label</a>')
        self.assertEqual(
            ndo.convert_property_value("text", cell),
            "https://en.wikipedia.org/wiki/Foo_(bar)",
        )

    def test_text_around_link_is_kept_as_markdown(self):
        cell = td('see <a href="https://example.com/x">label</a> now')
        value = ndo.convert_property_value("text", cell)
        self.assertIn("[label](https://example.com/x)", value)  # not unwrapped

    def test_two_links_kept_as_markdown(self):
        cell = td('<a href="https://a.com">one</a> and <a href="https://b.com">two</a>')
        value = ndo.convert_property_value("text", cell)
        self.assertIn("[one](https://a.com)", value)
        self.assertIn("[two](https://b.com)", value)

    def test_plain_text_unchanged(self):
        self.assertEqual(ndo.convert_property_value("text", td("just text")), "just text")

    def test_empty_is_none(self):
        self.assertIsNone(ndo.convert_property_value("text", td("")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
