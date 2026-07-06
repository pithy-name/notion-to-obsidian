#!/usr/bin/env python3
"""
B8: schema type-drift must never collapse a multi-value property.

When a property's dominant inferred type across a database is single-value
(select/status) but one specific entry's raw HTML actually carries MULTIPLE
`selected-value` spans (i.e. that entry's real Notion type was multi_select),
converting under the dominant type used to grab only the first span and
silently drop the rest. All values for that entry must survive as a list,
regardless of the dominant schema type, and a divergence warning must be
logged.

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


class SchemaDriftMultivalue(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_convert_property_value_preserves_all_values_under_select_type(self):
        # Directly exercises the converter: dominant type "select" is passed,
        # but the td holds 2 selected-value spans (drift case).
        td = _select_td("Red", "Blue")
        value = n.convert_property_value("select", td)
        self.assertEqual(value, ["Red", "Blue"])

    def test_convert_property_value_single_value_unaffected(self):
        td = _select_td("Red")
        value = n.convert_property_value("select", td)
        self.assertEqual(value, "Red")

    def test_write_entry_preserves_drifted_multivalue_and_warns(self):
        src = self.tmp / "src"; src.mkdir()
        out = self.tmp / "out"; out.mkdir()
        # Entry whose OWN row is really multi_select (2 spans) but the
        # database's dominant/discovered type for "Category" is "select"
        # (as would happen if most other entries only ever had 1 value).
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [("Category", "multi_select", _select_td("Red", "Blue"))],
            "body": None,
        }
        schema = OrderedDict()
        schema["Category"] = {
            "types": Counter({"select": 3, "multi_select": 1}),
            "key": "Category",
        }
        _path, warnings = n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        text = (out / "Item.md").read_text(encoding="utf-8")
        # F13: assertIn("Red", text) would also pass on a joined string like
        # "Category: RedBlue" or "Category: Red, Blue" — neither is a real
        # YAML list, and the original assertions couldn't tell the
        # difference. Parse the frontmatter for real and assert list
        # equality, so a regression back to a glued/joined string (rather
        # than a proper 2-item YAML list) is actually caught.
        fm_text = text.split("---", 2)[1]
        frontmatter = yaml.safe_load(fm_text)
        self.assertEqual(frontmatter["Category"], ["Red", "Blue"])
        self.assertTrue(
            any("Category" in w for w in warnings),
            "expected a schema-drift warning mentioning the property name",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
