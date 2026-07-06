#!/usr/bin/env python3
"""
B7: equations must never be dropped. Notion's HTML export renders an
equation as a `<figure class="equation">` containing an
`<annotation encoding="application/x-tex">...LaTeX...</annotation>`.
markdownify has no fallback for this and drops it entirely — genuine data
loss. Convert to fenced LaTeX Obsidian's built-in MathJax renderer typesets
natively: `$$...$$` for a block equation, `$...$` for inline.

Also covers the F2 escaping fix: `_convert_equations` inserts the literal
`$$tex$$` text into the soup, but the WHOLE body still goes through
markdownify afterward, which backslash-escapes markdown-special characters
(`_`, `*`) in every text node — corrupting LaTeX like `$$x_i * c$$` into
`$$x\_i \* c$$`. The fix placeholder-protects the raw TeX and substitutes it
back in after markdownify runs.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import unittest

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _conv(inner_html: str, warnings=None) -> str:
    body = BeautifulSoup(
        f'<div class="page-body">{inner_html}</div>', "html.parser"
    ).find("div", class_="page-body")
    return n.convert_body(
        body, entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None, wikilink_map={},
        warnings=warnings,
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


class EquationEscapingSurvivesMarkdownify(unittest.TestCase):
    """F2: markdownify must not backslash-escape `_`/`*` inside the raw TeX."""

    def test_underscore_asterisk_and_frac_survive_exactly(self):
        tex = r"x_i * c + \frac{a}{b}"
        md = _conv(
            '<figure class="equation">'
            f'<annotation encoding="application/x-tex">{tex}</annotation>'
            '</figure>'
        )
        self.assertIn(f"$${tex}$$", md)
        # Guard against the specific corruption this fix targets: markdownify
        # would otherwise have inserted backslashes before `_`/`*`.
        self.assertNotIn(r"\_i", md)
        self.assertNotIn(r"\*", md.replace(r"\frac", ""))

    def test_inline_underscore_survives_exactly(self):
        tex = r"a_1 * b_2"
        md = _conv(
            f'<p>See <annotation encoding="application/x-tex">{tex}</annotation> here.</p>'
        )
        self.assertIn(f"${tex}$", md)


class EmptyEquationWarns(unittest.TestCase):
    """F2 (silent-failure): a dropped empty/missing-TeX equation must warn."""

    def test_empty_block_equation_dropped_and_warns(self):
        warnings = []
        md = _conv('<figure class="equation"></figure>', warnings=warnings)
        self.assertNotIn("$$", md)
        self.assertTrue(
            any("equation" in w.lower() and "empty" in w.lower() for w in warnings),
            f"expected an empty-equation warning, got: {warnings}",
        )

    def test_empty_inline_annotation_dropped_and_warns(self):
        warnings = []
        md = _conv(
            '<p>See <span><annotation encoding="application/x-tex"></annotation></span> here.</p>',
            warnings=warnings,
        )
        self.assertNotIn("$$", md)
        self.assertTrue(
            any("equation" in w.lower() and "empty" in w.lower() for w in warnings),
            f"expected an empty-equation warning, got: {warnings}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
