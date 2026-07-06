#!/usr/bin/env python3
"""
"Present-but-empty" hardening: elements that EXIST but are empty must fall back,
not yield an empty string. (A truthiness check `X.get_text() if X else fallback`
treats an empty X as truthy and returns "".)

Run: /usr/bin/python3 test_empty_values.py
"""
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _write_entry_html(tmp: Path, stem: str, title_html: str) -> Path:
    f = tmp / f"{stem}.html"
    f.write_text(
        '<!DOCTYPE html><html><body>'
        f'<article id="x" class="page"><header>'
        f'<h1 class="page-title">{title_html}</h1>'
        f'<table class="properties"><tbody></tbody></table></header>'
        f'<div class="page-body"></div></article></body></html>',
        encoding="utf-8",
    )
    return f


class EmptyTitle(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_empty_page_title_falls_back_to_stem(self):
        # <h1 class="page-title"></h1> is present but empty.
        f = _write_entry_html(self.tmp, "Untitled abc123def456abc123def456abc12345", "")
        parsed = n.parse_entry(f)
        self.assertTrue(parsed["title"], "empty page-title produced an empty title")
        self.assertEqual(parsed["title"], "Untitled")  # stem with the hex id stripped

    def test_present_nonempty_title_unchanged(self):
        f = _write_entry_html(self.tmp, "Real abcdef0123456789abcdef0123456789", "Real Title")
        self.assertEqual(n.parse_entry(f)["title"], "Real Title")


class EmptyToggleSummary(unittest.TestCase):
    def _convert(self, inner):
        body = BeautifulSoup(
            f'<div class="page-body">{inner}</div>', "html.parser"
        ).find("div", class_="page-body")
        return n.convert_body(
            body,
            entry_attachment_dir_basename=None,
            new_attachment_dir_basename=None,
            wikilink_map={},
        )

    def test_empty_summary_toggle_keeps_content_and_has_title(self):
        md = self._convert(
            '<ul class="toggle"><li><details open>'
            '<summary></summary>'
            '<div>inner content here</div>'
            '</details></li></ul>'
        )
        self.assertIn("inner content here", md)        # content preserved
        self.assertIn("Toggle", md)                     # non-empty fallback title


class EmptyProperties(unittest.TestCase):
    """Item 64: a property empty for this entry still appears in YAML (as null),
    so every note shows the database's full property set (Notion shows the
    column for every row)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _td_tag(self, html):
        return BeautifulSoup(f"<td>{html}</td>", "html.parser").find("td")

    def _write(self):
        from collections import Counter, OrderedDict
        src = self.tmp / "src"; src.mkdir()
        out = self.tmp / "out"; out.mkdir()
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [("Name", "text", self._td_tag("hello"))],
            "body": None,
        }
        schema = OrderedDict()
        schema["Name"] = {"types": Counter({"text": 1}), "key": "Name"}
        schema["Extra"] = {"types": Counter({"text": 1}), "key": "Extra"}
        n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        return (out / "Item.md").read_text(encoding="utf-8")

    def test_present_property_keeps_value(self):
        self.assertRegex(self._write(), r"(?m)^Name:\s*hello\s*$")

    def test_missing_property_emitted_as_null(self):
        text = self._write()
        self.assertRegex(text, r"(?m)^Extra:\s*(null)?\s*$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
