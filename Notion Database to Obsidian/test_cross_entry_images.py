#!/usr/bin/env python3
"""
Tests for inplace-mode attachment link rewriting.

Notion exports every entry's HTML into one shared folder, so every local
attachment href is relative to that folder — whether it points at the entry's
OWN attachment dir or at a SIBLING entry's dir (cross-entry references, common
when one report embeds another's screenshots).

In inplace mode the output .md lives elsewhere, so each local href must be
rewritten to a relative path back into the source export. The fix is a single
prefix (the relpath from the output dir to the source folder) prepended to
EVERY local href — which fixes same-entry and cross-entry uniformly.

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_cross_entry_images.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).with_name("notion_db_to_obsidian.py")
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def conv(html: str, prefix):
    soup = BeautifulSoup(f'<div class="page-body">{html}</div>', "html.parser")
    body = soup.find("div", class_="page-body")
    return ndo.convert_body(
        body,
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
        inplace_link_prefix=prefix,
    )


class InplaceCrossEntry(unittest.TestCase):
    def test_same_and_cross_entry_images_both_prefixed(self):
        html = (
            '<p><img src="EntryA-uuid/own.png"/></p>'
            '<p><img src="EntryB-uuid/other.png"/></p>'
        )
        md = conv(html, "../..")
        self.assertIn("![](../../EntryA-uuid/own.png)", md)   # same-entry
        self.assertIn("![](../../EntryB-uuid/other.png)", md)  # cross-entry

    def test_non_image_local_link_prefixed(self):
        md = conv('<p><a href="EntryC-uuid/doc.pdf">doc</a></p>', "../..")
        self.assertIn("(../../EntryC-uuid/doc.pdf)", md)

    def test_external_links_untouched(self):
        html = '<p><a href="https://example.com/x">e</a><img src="https://cdn.example/z.png"/></p>'
        md = conv(html, "../..")
        self.assertIn("https://example.com/x", md)
        self.assertNotIn("../../https", md)

    def test_spaces_in_path_url_encoded(self):
        md = conv('<p><img src="My Entry abc/My File.png"/></p>', "..")
        self.assertIn("![](../My%20Entry%20abc/My%20File.png)", md)

    def test_none_prefix_leaves_href_unchanged(self):
        # copy/symlink path: no inplace prefix -> existing behavior preserved.
        md = conv('<p><img src="EntryA-uuid/own.png"/></p>', None)
        self.assertIn("![](EntryA-uuid/own.png)", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
