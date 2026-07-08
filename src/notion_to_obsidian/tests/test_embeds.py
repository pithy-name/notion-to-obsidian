#!/usr/bin/env python3
"""
Item 32: iframe embeds (YouTube, Maps, Figma, …) must not be dropped.
markdownify discards <iframe> entirely; we keep the embed URL as a link so the
content is reachable (HTML render is the benchmark — the embed is visible there).

Run: /usr/bin/python3 test_embeds.py
"""
import unittest

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _conv(inner_html: str) -> str:
    body = BeautifulSoup(
        f'<div class="page-body">{inner_html}</div>', "html.parser"
    ).find("div", class_="page-body")
    return n.convert_body(
        body, entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None, wikilink_map={},
    )


class Embeds(unittest.TestCase):
    def test_figure_iframe_keeps_url(self):
        md = _conv('<figure><iframe src="https://www.youtube.com/embed/abc123"></iframe></figure>')
        self.assertIn("https://www.youtube.com/embed/abc123", md)

    def test_bare_iframe_keeps_url(self):
        md = _conv('<iframe src="https://example.com/embed/map"></iframe>')
        self.assertIn("https://example.com/embed/map", md)

    def test_iframe_without_src_is_dropped_cleanly(self):
        # No src → nothing to keep; must not crash or leave an empty link.
        md = _conv('<p>before</p><iframe></iframe><p>after</p>')
        self.assertIn("before", md)
        self.assertIn("after", md)
        self.assertNotIn("[]()", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
