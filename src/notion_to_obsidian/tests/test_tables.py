#!/usr/bin/env python3
"""
Item 21: a real <table> in a note body converts to a GFM Markdown table.
GFM has no colspan/rowspan, so merged cells are flattened — but their TEXT must
never be lost. (A nested-database snapshot table is stripped elsewhere; this is
about ordinary content tables.)

Run: /usr/bin/python3 test_tables.py
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


class BodyTables(unittest.TestCase):
    def test_simple_table_becomes_gfm(self):
        md = _conv(
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
        )
        self.assertIn("| A | B |", md)
        self.assertIn("| 1 | 2 |", md)

    def test_merged_cell_text_is_preserved(self):
        # colspan can't be represented in GFM; the cell text must still survive.
        md = _conv(
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            '<tbody><tr><td colspan="2">merged value</td></tr>'
            "<tr><td>x</td><td>y</td></tr></tbody></table>"
        )
        self.assertIn("merged value", md)
        self.assertIn("| x | y |", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
