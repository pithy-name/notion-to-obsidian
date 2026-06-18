#!/usr/bin/env python3
"""
Bookmark <figure> conversion.

A Notion link bookmark exports as
  <figure><a class="bookmark source" href="URL"> … bookmark-title / bookmark-href … </a></figure>
When Notion never fetched a page title, `bookmark-title` is EMPTY. The
conversion must still keep the URL — a title-less bookmark whose body is only
that figure used to convert to an empty note, silently dropping the link.

Run: /usr/bin/python3 test_bookmark_figures.py
"""
import unittest

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _body(inner_html: str):
    html = f'<div class="page-body">{inner_html}</div>'
    return BeautifulSoup(html, "html.parser").find("div", class_="page-body")


def _convert(inner_html: str) -> str:
    return n.convert_body(
        _body(inner_html),
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
    )


URL = "https://example.com/blog?s=heuristic"


class BookmarkFigures(unittest.TestCase):
    def test_empty_title_bookmark_keeps_url(self):
        # bookmark-title is empty; the visible URL lives in bookmark-href.
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-info"><div class="bookmark-text">'
            f'<div class="bookmark-title"></div></div>'
            f'<div class="bookmark-href">{URL}</div></div></a></figure>'
        )
        self.assertTrue(md.strip(), "body converted to empty string — link dropped")
        self.assertIn(URL, md)

    def test_empty_title_no_href_div_falls_back_to_href(self):
        # Degenerate bookmark: empty title, no bookmark-href div either.
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-title"></div></a></figure>'
        )
        self.assertTrue(md.strip())
        self.assertIn(URL, md)

    def test_titled_bookmark_links_title(self):
        # Normal case: a fetched title is used as the link text.
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-info"><div class="bookmark-text">'
            f'<div class="bookmark-title">Adam’s Blog</div></div>'
            f'<div class="bookmark-href">{URL}</div></div></a></figure>'
        )
        self.assertIn("Adam", md)
        self.assertIn(URL, md)

    def test_titled_bookmark_shows_url_as_visible_subtitle(self):
        # HTML render is the benchmark: the bookmark card displays the URL as
        # visible text IN ADDITION to the title link. The Markdown must show the
        # URL visibly too (an autolink <url>), not only as the [title](url)
        # link target (which renders invisibly).
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-info"><div class="bookmark-text">'
            f'<div class="bookmark-title">Some Title</div></div>'
            f'<div class="bookmark-href">{URL}</div></div></a></figure>'
        )
        self.assertIn("Some Title", md)
        self.assertIn(f"<{URL}>", md)  # URL shown as a visible autolink

    def test_empty_title_bookmark_does_not_duplicate_url(self):
        # When the title falls back to the URL, don't also append a URL subtitle.
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-title"></div>'
            f'<div class="bookmark-href">{URL}</div></a></figure>'
        )
        self.assertEqual(md.count(URL), 1, f"URL duplicated: {md!r}")

    def test_description_is_preserved(self):
        md = _convert(
            f'<figure><a class="bookmark source" href="{URL}">'
            f'<div class="bookmark-info"><div class="bookmark-text">'
            f'<div class="bookmark-title">T</div>'
            f'<div class="bookmark-description">A short blurb</div></div>'
            f'<div class="bookmark-href">{URL}</div></div></a></figure>'
        )
        self.assertIn("A short blurb", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
