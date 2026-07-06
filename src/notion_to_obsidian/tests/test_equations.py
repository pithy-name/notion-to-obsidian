#!/usr/bin/env python3
"""
B7: equations must never be dropped. Notion's HTML export renders an
equation as a `<figure class="equation">` containing an
`<annotation encoding="application/x-tex">...LaTeX...</annotation>`.
markdownify has no fallback for this and drops it entirely — genuine data
loss. Convert to fenced LaTeX Obsidian's built-in MathJax renderer typesets
natively: `$$...$$` for a block equation, `$...$` for inline.

Run: /usr/bin/python3 test_equations.py
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


class BlockEquations(unittest.TestCase):
    def test_block_equation_preserved_as_dollar_dollar_fence(self):
        md = _conv(
            '<figure class="equation">'
            '<div class="equation-container">'
            '<annotation encoding="application/x-tex">E = mc^2</annotation>'
            '</div></figure>'
        )
        self.assertIn("$$E = mc^2$$", md)

    def test_block_equation_not_dropped_amid_other_content(self):
        md = _conv(
            '<p>Before.</p>'
            '<figure class="equation">'
            '<annotation encoding="application/x-tex">a^2 + b^2 = c^2</annotation>'
            '</figure>'
            '<p>After.</p>'
        )
        self.assertIn("Before.", md)
        self.assertIn("$$a^2 + b^2 = c^2$$", md)
        self.assertIn("After.", md)

    def test_empty_equation_figure_does_not_crash(self):
        md = _conv('<figure class="equation"></figure>')
        self.assertNotIn("$$$$", md)


class InlineEquations(unittest.TestCase):
    def test_bare_tex_annotation_not_in_figure_treated_as_inline(self):
        # Best-effort: any TeX annotation not consumed by the block pass is
        # wrapped as inline math rather than silently dropped.
        md = _conv(
            '<p>The value <span><annotation encoding="application/x-tex">x</annotation></span> '
            'is unknown.</p>'
        )
        self.assertIn("$x$", md)
        self.assertIn("is unknown", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
