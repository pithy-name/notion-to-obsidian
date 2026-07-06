#!/usr/bin/env python3
"""
F3 (B8 gap): the B8 fix in `convert_property_value` only guards the
select/status branches — a cell with 2+ `selected-value` spans converted
under any OTHER dominant type still drops or corrupts data:

  - dominant `checkbox`: `convert_property_value` checks for
    `checkbox-on`/`checkbox-off` classes or specific raw-text tokens; a
    multi-select-drifted cell matches none of those -> `False`. TOTAL
    silent data loss (2 real values become a boolean).
  - dominant `date`/`number`/`person`/`text`/etc.: these branches call
    `td.get_text(strip=True)` (`raw_text`), which concatenates the spans
    with NO separator ("Red" + "Blue" -> "RedBlue") -> corrupted, unusable
    single string, not the intended 2 values.

`write_entry` must detect 2+ `selected-value` spans BEFORE dispatching on
`dominant_type` and preserve every value as a list whenever `dominant_type`
is anything other than `multi_select` — the same rendering B8 already gives
dominant select/status — plus the existing type-mismatch warning.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import tempfile
import unittest
from collections import Counter, OrderedDict
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _select_td(*values: str):
    spans = "".join(f'<span class="selected-value">{v}</span>' for v in values)
    return BeautifulSoup(f"<td>{spans}</td>", "html.parser").find("td")


class MultivalueUnderNonSelectDominant(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _write(self, ptype: str, dominant_type: str, values):
        src = self.tmp / "src"; src.mkdir(exist_ok=True)
        out = self.tmp / f"out-{dominant_type}"; out.mkdir(exist_ok=True)
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [("Category", ptype, _select_td(*values))],
            "body": None,
        }
        schema = OrderedDict()
        schema["Category"] = {
            "types": Counter({dominant_type: 3, ptype: 1}),
            "key": "Category",
        }
        return n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        ), out

    @staticmethod
    def _frontmatter(text: str) -> dict:
        # G6 (F13 backport): the original assertions here used assertIn/
        # assertNotIn on raw text, which stays GREEN even if the fix
        # regresses to a glued string ("Red, Blue" still contains "Red",
        # doesn't contain "RedBlue"/"1234"). Parse the actual YAML
        # frontmatter and assert list equality instead, matching the
        # pattern F13 (0f109c6) applied to the sibling B8 test one commit
        # later — never backported here until now.
        fm_text = text.split("---", 2)[1]
        return yaml.safe_load(fm_text)

    def test_dominant_checkbox_preserves_values_not_false(self):
        (_path, warnings), out = self._write("multi_select", "checkbox", ["Red", "Blue"])
        text = (out / "Item.md").read_text(encoding="utf-8")
        frontmatter = self._frontmatter(text)
        self.assertEqual(frontmatter["Category"], ["Red", "Blue"])
        self.assertTrue(
            any("Category" in w for w in warnings),
            "expected a schema-drift warning mentioning the property name",
        )

    def test_dominant_date_preserves_values_not_glued(self):
        (_path, warnings), out = self._write("multi_select", "date", ["Red", "Blue"])
        text = (out / "Item.md").read_text(encoding="utf-8")
        frontmatter = self._frontmatter(text)
        self.assertEqual(frontmatter["Category"], ["Red", "Blue"])
        self.assertTrue(
            any("Category" in w for w in warnings),
            "expected a schema-drift warning mentioning the property name",
        )

    def test_dominant_number_preserves_values_not_glued(self):
        (_path, warnings), out = self._write("multi_select", "number", ["12", "34"])
        text = (out / "Item.md").read_text(encoding="utf-8")
        frontmatter = self._frontmatter(text)
        self.assertEqual(frontmatter["Category"], ["12", "34"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
