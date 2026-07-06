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

    def test_empty_inline_annotation_with_mathml_sibling_leaves_no_residue(self):
        """
        G3: real Notion inline-equation markup carries presentational MathML
        alongside the (possibly empty) TeX annotation:
            <span class="math"><math>...<mrow><mi>x</mi>...</mrow>
              <annotation encoding="application/x-tex"></annotation></math></span>
        `annotation.decompose()` only removes the <annotation> node, leaving
        the sibling <mrow><mi>x</mi>... MathML in the tree — markdownify then
        renders it as ordinary prose text ("x+2"), silently injected into the
        paragraph even though the warning claims "nothing to preserve." The
        fix must decompose the whole wrapper, not just the annotation.
        """
        warnings = []
        md = _conv(
            '<p>Before '
            '<span class="math"><math>'
            '<mrow><mi>x</mi><mo>+</mo><mn>2</mn></mrow>'
            '<annotation encoding="application/x-tex"></annotation>'
            '</math></span>'
            ' after.</p>',
            warnings=warnings,
        )
        self.assertNotIn("x+2", md)
        self.assertNotIn("+2", md)
        self.assertIn("Before", md)
        self.assertIn("after", md)
        self.assertTrue(
            any("equation" in w.lower() and "empty" in w.lower() for w in warnings),
            f"expected an empty-equation warning, got: {warnings}",
        )


class PlaceholderSubstitutionCollisionSafe(unittest.TestCase):
    """
    G7: the placeholder-restore loop is a naive sequential
    `for placeholder, raw_tex in equation_map.items(): md = md.replace(...)`.
    If an earlier equation's raw TeX literally contains a LATER equation's
    placeholder token, that sequential replace corrupts/splices the two
    equations together — the earlier substitution injects text that the
    later iteration's `.replace()` call then matches and mangles. Real-world
    reachability is essentially nil (requires the source doc to contain the
    internal placeholder token format), but the mechanism itself must be
    collision-safe (single-pass / non-recursive substitution).
    """

    def test_earlier_tex_containing_later_placeholder_does_not_splice(self):
        # Force a specific two-equation ordering: eq0's raw TeX literally
        # contains the exact placeholder token that eq1 will get
        # ("NOTIONEQPLACEHOLDER1ENDPLACEHOLDER").
        tex0 = r"x = NOTIONEQPLACEHOLDER1ENDPLACEHOLDER + 1"
        tex1 = r"y = 2"
        md = _conv(
            '<figure class="equation">'
            f'<annotation encoding="application/x-tex">{tex0}</annotation>'
            '</figure>'
            '<figure class="equation">'
            f'<annotation encoding="application/x-tex">{tex1}</annotation>'
            '</figure>'
        )
        self.assertIn(f"$${tex0}$$", md)
        self.assertIn(f"$${tex1}$$", md)

    def test_leftover_placeholder_after_substitution_warns(self):
        # Defensive signal: if a placeholder token somehow survives
        # restoration, that's a silent-corruption risk and must warn rather
        # than ship a raw internal token in the user's markdown.
        warnings = []
        md = _conv(
            '<figure class="equation">'
            '<annotation encoding="application/x-tex">a = b</annotation>'
            '</figure>',
            warnings=warnings,
        )
        self.assertIn("$$a = b$$", md)
        self.assertNotIn("NOTIONEQPLACEHOLDER", md)
        # No leftover in the happy path -> no leftover-placeholder warning.
        self.assertFalse(
            any("placeholder" in w.lower() and "leftover" in w.lower() for w in warnings)
        )


class InlineEquationWrapperOverDeletion(unittest.TestCase):
    """
    H1 (round-3 red-team, CRITICAL regression of G3): `find_parent(["math",
    "span"])` returns the NEAREST span/math ancestor, which can be shared by
    unrelated content -- either a second, real annotation, or plain prose --
    and G3's "decompose/replace the whole wrapper" fix inherited that same
    over-broad blast radius. The wrapper selected for decompose/replace must
    be unambiguously scoped to exactly this one equation; anything else must
    fall back to touching only the <annotation> node itself.
    """

    def test_two_annotations_sharing_one_span_second_equation_survives(self):
        # Shape (a): two <annotation> siblings share one span. The first is
        # empty (nothing to preserve); the second is a real equation. Naively
        # decomposing the shared span on the first (empty) annotation would
        # silently destroy the second, real equation before the loop ever
        # reaches it -- plus a false "nothing to preserve" warning for what
        # is, net, a real equation loss.
        warnings = []
        md = _conv(
            '<p><span class="equation-inline">'
            '<annotation encoding="application/x-tex"></annotation>'
            '<annotation encoding="application/x-tex">x+2</annotation>'
            '</span></p>',
            warnings=warnings,
        )
        self.assertIn("$x+2$", md)
        empty_eq_warnings = [
            w for w in warnings if "equation" in w.lower() and "empty" in w.lower()
        ]
        self.assertEqual(
            len(empty_eq_warnings), 1,
            f"expected exactly one empty-equation warning, got: {warnings}",
        )

    def test_span_wrapping_unrelated_prose_is_not_deleted(self):
        # Shape (b): the nearest span wraps real prose alongside the empty
        # annotation. The span is not equation-scoped (no equation/math
        # class), so it must never be decomposed -- only the empty
        # <annotation> node itself may be removed.
        md = _conv(
            '<p>Before <span>IMPORTANT real content '
            '<annotation encoding="application/x-tex"></annotation>'
            '</span> after</p>'
        )
        self.assertIn("IMPORTANT real content", md)
        self.assertIn("Before", md)
        self.assertIn("after", md)

    def test_nonempty_equation_in_span_with_unrelated_prose_preserves_prose(self):
        # Same over-broad-wrapper risk applies to the NON-empty inline path
        # (`wrapper.replace_with(...)`), not just the empty-decompose path.
        md = _conv(
            '<p>Before <span>IMPORTANT real content '
            '<annotation encoding="application/x-tex">x+2</annotation>'
            '</span> after</p>'
        )
        self.assertIn("IMPORTANT real content", md)
        self.assertIn("$x+2$", md)
        self.assertIn("Before", md)
        self.assertIn("after", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
