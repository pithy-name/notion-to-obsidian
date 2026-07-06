#!/usr/bin/env python3
"""
B6: cross-export `.html` links and in-page `#fragment` links must never
survive as raw, broken hrefs in the output. When a link can't be resolved —
its target isn't a node in THIS export (a cross-export link, or the target's
filename diverged), or it's a `#fragment` heading anchor this converter
doesn't track — convert it to plain visible text (drop the href, keep the
label) instead of shipping a dead `.html`/`#fragment` link.

Run: /usr/bin/python3 test_unresolved_link_fallback.py
"""
import unittest

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _conv(inner_html: str, wikilink_map=None, warnings=None):
    body = BeautifulSoup(
        f'<div class="page-body">{inner_html}</div>', "html.parser"
    ).find("div", class_="page-body")
    return n.convert_body(
        body, entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map=wikilink_map or {},
        warnings=warnings,
    )


class UnresolvedCrossExportLink(unittest.TestCase):
    def test_unresolved_html_link_becomes_plain_text(self):
        md = _conv('<a href="Other%20Export%20abc123.html">See other page</a>')
        self.assertNotIn(".html", md)
        self.assertNotIn("[[", md)
        self.assertIn("See other page", md)

    def test_unresolved_html_link_logs_a_warning(self):
        warnings = []
        _conv('<a href="Other%20Export%20abc123.html">See other page</a>', warnings=warnings)
        self.assertTrue(
            any("unresolved" in w and "cross-export" in w for w in warnings),
            f"expected an unresolved cross-export warning, got: {warnings}",
        )

    def test_resolved_html_link_still_becomes_wikilink(self):
        # A known node must still resolve to [[wikilink]], not fall through
        # to the new plain-text fallback.
        md = _conv(
            '<a href="Aromatherapy%20def.html">Aromatherapy</a>',
            wikilink_map={"Aromatherapy def.html": "Aromatherapy"},
        )
        self.assertIn("[[Aromatherapy]]", md)


class HtmlLinkWithFragment(unittest.TestCase):
    """
    F4 (B6 gap): "<node>.html#some-block-id" links to ANOTHER node's specific
    block — not a bare in-page "#anchor" (handled separately above) — must
    resolve via wikilink_map on the pre-fragment part, or fall back to plain
    text + warning when unresolved. Before the fix, this shape matched
    NEITHER check (wikilink_map is keyed with no fragment; the unresolved-
    ".html" fallback's `.endswith(".html")` check fails once "#fragment" is
    appended) and fell through untouched as a raw, dead href.
    """

    def test_resolved_html_link_with_fragment_becomes_wikilink_fragment_dropped(self):
        md = _conv(
            '<a href="Aromatherapy%20def.html#block-123">Aromatherapy</a>',
            wikilink_map={"Aromatherapy def.html": "Aromatherapy"},
        )
        self.assertIn("[[Aromatherapy]]", md)
        self.assertNotIn("#block-123", md)

    def test_unresolved_html_link_with_fragment_becomes_plain_text(self):
        md = _conv('<a href="Other%20Export%20abc123.html#block-123">See other page</a>')
        self.assertNotIn(".html", md)
        self.assertNotIn("#block-123", md)
        self.assertNotIn("[[", md)
        self.assertIn("See other page", md)

    def test_unresolved_html_link_with_fragment_logs_a_warning(self):
        warnings = []
        _conv(
            '<a href="Other%20Export%20abc123.html#block-123">See other page</a>',
            warnings=warnings,
        )
        self.assertTrue(
            any("unresolved" in w and "cross-export" in w for w in warnings),
            f"expected an unresolved cross-export warning, got: {warnings}",
        )


class HashInTitleLink(unittest.TestCase):
    """
    G1 (regression from the F4 fix): a title containing a literal "#" (e.g.
    "C# Notes") is exported percent-encoded ("%23"). The F4 fragment split
    ran AFTER unquote(href), so unquote turned "%23" into a literal "#" and
    the fragment-split truncated the lookup at the title's own "#" —
    the link missed wikilink_map, missed the ".html" fallback (the ".html"
    was sliced into the discarded "fragment" half), and fell through with
    NO warning. Splitting on the RAW (still-encoded) href fixes this: a
    real fragment delimiter is always literal in the raw href, while a "#"
    that's part of the title itself only appears after decoding.
    """

    def test_html_link_to_hash_title_becomes_wikilink(self):
        md = _conv(
            '<a href="C%23%20Notes%20abc123.html">C# Notes</a>',
            wikilink_map={"C# Notes abc123.html": "C# Notes"},
        )
        self.assertIn("[[C# Notes]]", md)
        self.assertNotIn(".html", md)

    def test_html_link_to_unresolved_hash_title_falls_back_with_warning(self):
        warnings = []
        md = _conv(
            '<a href="C%23%20Notes%20abc123.html">C# Notes</a>',
            warnings=warnings,
        )
        self.assertNotIn(".html", md)
        self.assertNotIn("[[", md)
        self.assertIn("C# Notes", md)
        self.assertTrue(
            any("unresolved" in w and "cross-export" in w for w in warnings),
            f"expected an unresolved cross-export warning, got: {warnings}",
        )


class QueryStringOnHtmlLink(unittest.TestCase):
    """
    G2 (F4 gap): a query string on a cross-node href ("Node.html?src=abc",
    optionally with a "#fragment" too) matched neither wikilink_map (keyed
    on the bare filename) nor the ".html" fallback (`.endswith(".html")`
    fails once "?query" is attached) — a silent drop. Strip the query
    (and fragment) before the lookup/fallback check.
    """

    def test_unresolved_html_link_with_query_falls_back_with_warning(self):
        warnings = []
        md = _conv(
            '<a href="Other%20Export%20abc123.html?src=abc">See other page</a>',
            warnings=warnings,
        )
        self.assertNotIn(".html", md)
        self.assertNotIn("[[", md)
        self.assertIn("See other page", md)
        self.assertTrue(
            any("unresolved" in w and "cross-export" in w for w in warnings),
            f"expected an unresolved cross-export warning, got: {warnings}",
        )

    def test_resolved_html_link_with_query_becomes_wikilink(self):
        md = _conv(
            '<a href="Aromatherapy%20def.html?src=abc">Aromatherapy</a>',
            wikilink_map={"Aromatherapy def.html": "Aromatherapy"},
        )
        self.assertIn("[[Aromatherapy]]", md)

    def test_resolved_html_link_with_query_and_fragment_becomes_wikilink(self):
        md = _conv(
            '<a href="Aromatherapy%20def.html?src=abc#block-123">Aromatherapy</a>',
            wikilink_map={"Aromatherapy def.html": "Aromatherapy"},
        )
        self.assertIn("[[Aromatherapy]]", md)
        self.assertNotIn("#block-123", md)


class UnresolvedFragmentLink(unittest.TestCase):
    def test_fragment_link_becomes_plain_text(self):
        md = _conv('<a href="#heading-123">Jump to section</a>')
        self.assertNotIn("#heading-123", md)
        self.assertIn("Jump to section", md)

    def test_fragment_link_logs_a_warning(self):
        warnings = []
        _conv('<a href="#heading-123">Jump to section</a>', warnings=warnings)
        self.assertTrue(
            any("unresolved" in w and "anchor" in w for w in warnings),
            f"expected an unresolved anchor warning, got: {warnings}",
        )

    def test_no_warnings_list_does_not_error(self):
        # warnings=None (the default) must not raise.
        md = _conv('<a href="#heading-123">Jump to section</a>')
        self.assertIn("Jump to section", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
