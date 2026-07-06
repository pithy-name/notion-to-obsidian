#!/usr/bin/env python3
"""
Body links to other notes become `[[wikilinks]]` even when the href carries a
folder prefix.

`wikilink_map` is keyed on each node's filename (basename). An entry links to a
sibling with a bare-basename href, which matches directly. But an index/landing
page links DOWN into a subfolder, so its hrefs look like
"Resources abc/Aromatherapy def.html" — a folder-prefixed path that misses the
basename-keyed map and used to be left as a raw `.html` link (broken in
Obsidian). Filenames are vault-unique, so a basename fallback resolves these
unambiguously.

Run: /usr/bin/python3 test_wikilink_rewrite.py
"""
import unittest

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _conv(inner_html: str, wikilink_map: dict) -> str:
    body = BeautifulSoup(
        f'<div class="page-body">{inner_html}</div>', "html.parser"
    ).find("div", class_="page-body")
    return n.convert_body(
        body, entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None, wikilink_map=wikilink_map,
    )


class WikilinkRewrite(unittest.TestCase):
    def test_bare_basename_link_rewrites(self):
        # The pre-existing sibling case must keep working.
        md = _conv('<a href="Aromatherapy%20def.html">Aromatherapy</a>',
                   {"Aromatherapy def.html": "Aromatherapy"})
        self.assertIn("[[Aromatherapy]]", md)
        self.assertNotIn(".html", md)

    def test_folder_prefixed_link_rewrites(self):
        # An index/landing page links into a subfolder; the folder-prefixed href
        # must still resolve to the target note by basename.
        md = _conv('<a href="Resources%20abc/Aromatherapy%20def.html">Aromatherapy</a>',
                   {"Aromatherapy def.html": "Aromatherapy"})
        self.assertIn("[[Aromatherapy]]", md)
        self.assertNotIn(".html", md)

    def test_unknown_basename_is_not_wikilinked(self):
        # A href whose basename is not a known node must NOT become a wikilink
        # (e.g. an image attachment) — it falls through to attachment handling.
        md = _conv('<a href="Resources%20abc/photo.png">pic</a>',
                   {"Aromatherapy def.html": "Aromatherapy"})
        self.assertNotIn("[[", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
