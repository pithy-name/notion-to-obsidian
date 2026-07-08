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
        # J1 (round-5 fix): the annotation-only-mutation approach never
        # touches the <math>/<mrow> ancestors, so this sibling presentation
        # MathML ("x+2") is now expected to survive as cosmetic residue next
        # to the (removed) empty annotation -- see README Known Issues. The
        # non-negotiable safety property this test now checks is narrower:
        # nothing CRASHES and the real prose "Before"/"after" survives. The
        # old assertNotIn("x+2", md) / assertNotIn("+2", md) asserted
        # residue-ABSENCE, which required decomposing the <math> ancestor --
        # exactly the operation that caused the round-5 silent-data-loss bug
        # (an ancestor shared by other equations). Residue is now an
        # accepted trade-off, not a defect.
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


class MathWrapperOverDeletion(unittest.TestCase):
    """
    I1 (round-4 red-team, CRITICAL regression of H1): H1 added
    `_is_equation_scoped_span` to protect the `<span>` branch of the wrapper
    lookup, but left the `<math>` branch
    (`wrapper = annotation.find_parent("math")`) UNGUARDED -- it is taken
    unconditionally whenever a `<math>` ancestor exists, regardless of
    whether that `<math>` is exclusively scoped to this one equation. Same
    blast-radius bug H1 fixed for `<span>`, reopened for `<math>`.
    """

    def test_two_real_annotations_sharing_one_math_no_crash_second_survives(self):
        # Shape (a): two REAL <annotation> siblings share one <math>. The
        # first annotation's `wrapper.replace_with(...)` detaches the shared
        # <math> from the tree entirely. The loop then reaches the second
        # annotation, `find_parent("math")` returns that now-detached tag,
        # and `replace_with` raises ValueError -- an unhandled crash that
        # kills the whole run.
        md = _conv(
            '<p><math>'
            '<annotation encoding="application/x-tex">a</annotation>'
            '<annotation encoding="application/x-tex">b</annotation>'
            '</math></p>'
        )
        self.assertIn("$a$", md)
        self.assertIn("$b$", md)

    def test_math_wrapping_unrelated_prose_is_not_deleted(self):
        # Shape (b): <math> wraps unrelated prose alongside one real
        # annotation. Unconditionally decomposing/replacing the whole <math>
        # silently deletes "IMPORTANT real content" -- no warning, no crash,
        # just gone.
        md = _conv(
            '<p>Before <math>IMPORTANT real content '
            '<annotation encoding="application/x-tex">x</annotation>'
            '</math> after</p>'
        )
        self.assertIn("IMPORTANT real content", md)
        self.assertIn("Before", md)
        self.assertIn("after", md)
        self.assertIn("$x$", md)

    def test_empty_and_real_annotation_sharing_one_math_real_survives_one_warning(self):
        # Shape (c): one empty + one real annotation share a <math>. The
        # unconditional wrapper decomposes the WHOLE <math> (destroying the
        # real "y" equation too) on the first (empty) annotation, then
        # logs "empty TeX (nothing to preserve)" for BOTH annotations --
        # silent loss of a real equation plus a false diagnostic claiming
        # nothing was lost.
        warnings = []
        md = _conv(
            '<p><math>'
            '<annotation encoding="application/x-tex"></annotation>'
            '<annotation encoding="application/x-tex">y</annotation>'
            '</math></p>',
            warnings=warnings,
        )
        self.assertIn("$y$", md)
        empty_eq_warnings = [
            w for w in warnings if "equation" in w.lower() and "empty" in w.lower()
        ]
        self.assertEqual(
            len(empty_eq_warnings), 1,
            f"expected exactly one empty-equation warning, got: {warnings}",
        )


class RealisticNestedSharedMathWrapper(unittest.TestCase):
    """
    J1 (round-5 red-team, CRITICAL regression of I1): I1's
    `_is_equation_scoped_wrapper` check walks descendants and re-evaluates
    "is this <math> exclusively scoped to one equation" fresh for each
    annotation in the loop. With REALISTIC MathJax nesting -- each equation
    wrapped in its own `<semantics><mrow>...</mrow><annotation>...</annotation
    ></semantics>` sibling under one shared `<math>` -- processing the first
    annotation decomposes/replaces its `<semantics>` (or the shared `<math>`
    itself, depending on scoping), mutating the tree the loop is still
    iterating. The live re-check on the next annotation then sees a
    corrupted/partial tree and either mis-scopes or the annotation's own
    ancestor chain has already been detached -- N-1 of N equations sharing
    one `<math>` are silently lost.

    J1's fix eliminates the whole bug class by construction: replace ONLY
    the `<annotation>` node being iterated, never any ancestor
    (`<math>`, `<span>`, `<semantics>`, `<mrow>`, ...). Because no ancestor
    is ever mutated, there is no shared-wrapper scoping decision to get
    wrong, and no mutation-during-iteration hazard -- regardless of how many
    equations share a `<math>`, or how deep the MathJax nesting is.
    """

    def test_two_equations_sharing_one_math_with_semantics_nesting_both_survive(self):
        # Exact round-5 repro shape: 2 equations, each in its own
        # <semantics><mrow>...</mrow><annotation>...</annotation></semantics>,
        # sharing one <math>.
        md = _conv(
            '<p><math>'
            '<semantics><mrow><mi>a</mi></mrow>'
            '<annotation encoding="application/x-tex">a=1</annotation>'
            '</semantics>'
            '<semantics><mrow><mi>b</mi></mrow>'
            '<annotation encoding="application/x-tex">b=2</annotation>'
            '</semantics>'
            '</math></p>'
        )
        self.assertIn("$a=1$", md)
        self.assertIn("$b=2$", md)

    def test_three_equations_sharing_one_math_with_semantics_nesting_all_survive(self):
        md = _conv(
            '<p><math>'
            '<semantics><mrow><mi>a</mi></mrow>'
            '<annotation encoding="application/x-tex">a=1</annotation>'
            '</semantics>'
            '<semantics><mrow><mi>b</mi></mrow>'
            '<annotation encoding="application/x-tex">b=2</annotation>'
            '</semantics>'
            '<semantics><mrow><mi>c</mi></mrow>'
            '<annotation encoding="application/x-tex">c=3</annotation>'
            '</semantics>'
            '</math></p>'
        )
        self.assertIn("$a=1$", md)
        self.assertIn("$b=2$", md)
        self.assertIn("$c=3$", md)

    def test_two_equations_sharing_one_span_equation_wrapper_with_semantics_nesting_both_survive(self):
        # Same realistic nesting, but under one shared <span class="equation">
        # instead of a shared <math>.
        md = _conv(
            '<p><span class="equation">'
            '<math><semantics><mrow><mi>a</mi></mrow>'
            '<annotation encoding="application/x-tex">a=1</annotation>'
            '</semantics></math>'
            '<math><semantics><mrow><mi>b</mi></mrow>'
            '<annotation encoding="application/x-tex">b=2</annotation>'
            '</semantics></math>'
            '</span></p>'
        )
        self.assertIn("$a=1$", md)
        self.assertIn("$b=2$", md)

    def test_math_wrapping_unrelated_prose_plus_one_annotation_prose_and_tex_both_survive(self):
        # Round-4 shape, must still hold under the new approach.
        md = _conv(
            '<p>Before <math>IMPORTANT real content '
            '<annotation encoding="application/x-tex">x</annotation>'
            '</math> after</p>'
        )
        self.assertIn("IMPORTANT real content", md)
        self.assertIn("Before", md)
        self.assertIn("after", md)
        self.assertIn("$x$", md)

    def test_two_bare_annotations_no_semantics_wrapper_both_survive(self):
        # Round-4 shape (no <semantics> nesting at all), must still hold.
        md = _conv(
            '<p><math>'
            '<annotation encoding="application/x-tex">a</annotation>'
            '<annotation encoding="application/x-tex">b</annotation>'
            '</math></p>'
        )
        self.assertIn("$a$", md)
        self.assertIn("$b$", md)

    def test_empty_and_real_annotation_sharing_math_with_semantics_nesting_one_warning(self):
        warnings = []
        md = _conv(
            '<p><math>'
            '<semantics><mrow><mi>x</mi></mrow>'
            '<annotation encoding="application/x-tex"></annotation>'
            '</semantics>'
            '<semantics><mrow><mi>y</mi></mrow>'
            '<annotation encoding="application/x-tex">y</annotation>'
            '</semantics>'
            '</math></p>',
            warnings=warnings,
        )
        self.assertIn("$y$", md)
        empty_eq_warnings = [
            w for w in warnings if "equation" in w.lower() and "empty" in w.lower()
        ]
        self.assertEqual(
            len(empty_eq_warnings), 1,
            f"expected exactly one empty-equation warning, got: {warnings}",
        )


class CommonCaseRegressionCoverage(unittest.TestCase):
    """
    J1: common-case sanity coverage under the new annotation-only-mutation
    approach. Residue MAY be present (sibling presentation MathML is never
    touched) -- these tests assert the equation is emitted and nothing is
    LOST, not residue-absence.
    """

    def test_single_block_equation_converts_to_dollar_dollar_fence(self):
        md = _conv(
            '<figure class="equation">'
            '<annotation encoding="application/x-tex">E = mc^2</annotation>'
            '</figure>'
        )
        self.assertIn("$$E = mc^2$$", md)

    def test_single_inline_equation_with_semantics_nesting_converts_to_dollar_fence(self):
        md = _conv(
            '<p><span class="math"><math><semantics><mrow>'
            '<mi>x</mi>'
            '</mrow>'
            '<annotation encoding="application/x-tex">x</annotation>'
            '</semantics></math></span></p>'
        )
        self.assertIn("$x$", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
