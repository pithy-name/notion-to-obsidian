#!/usr/bin/env python3
"""
B9: a Notion date RANGE property ("Jan 2, 2024 → Jan 5, 2024") must not
silently drop its end date. `parse_notion_date` keeps only the start (used
for the property's own frontmatter value, unaffected); the end date is
additionally emitted as a companion `<Prop> (end)` frontmatter property —
per TODO.md's recommended option (A): both stay date-typed/sortable.

Run: /usr/bin/python3 test_date_range_end.py
"""
import tempfile
import unittest
from collections import Counter, OrderedDict
from pathlib import Path

from bs4 import BeautifulSoup
import notion_db_to_obsidian as n


def _date_td(text: str):
    return BeautifulSoup(f"<td>{text}</td>", "html.parser").find("td")


class ParseNotionDateRangeEnd(unittest.TestCase):
    def test_range_returns_end_iso_date(self):
        self.assertEqual(
            n.parse_notion_date_range_end("January 2, 2024 → January 5, 2024"),
            "2024-01-05",
        )

    def test_non_range_returns_none(self):
        self.assertIsNone(n.parse_notion_date_range_end("January 2, 2024"))

    def test_unparseable_end_falls_back_to_raw_text(self):
        self.assertEqual(
            n.parse_notion_date_range_end("January 2, 2024 → some garbage"),
            "some garbage",
        )


class WriteEntryEmitsCompanionEndProperty(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_range_value_emits_companion_end_property(self):
        src = self.tmp / "src"; src.mkdir()
        out = self.tmp / "out"; out.mkdir()
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [
                ("Duration", "date", _date_td("January 2, 2024 → January 5, 2024")),
            ],
            "body": None,
        }
        schema = OrderedDict()
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        text = (out / "Item.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^Duration:\s*'?2024-01-02'?\s*$")
        self.assertRegex(text, r"(?m)^Duration \(end\):\s*'?2024-01-05'?\s*$")

    def test_plain_date_has_no_companion_end_property(self):
        src = self.tmp / "src"; src.mkdir()
        out = self.tmp / "out"; out.mkdir()
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [("Due", "date", _date_td("January 2, 2024"))],
            "body": None,
        }
        schema = OrderedDict()
        schema["Due"] = {"types": Counter({"date": 1}), "key": "Due"}
        n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        text = (out / "Item.md").read_text(encoding="utf-8")
        self.assertNotIn("(end)", text)


class EmitTypesJsonRegistersEndKey(unittest.TestCase):
    def test_end_key_registered_as_datetime(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()
        schema = OrderedDict()
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        n.emit_types_json(out_root, schema, force=False, overwrite_log=[], dry_run=False)
        import json
        types_doc = json.loads((out_root / ".obsidian" / "types.json").read_text(encoding="utf-8"))
        self.assertEqual(types_doc["types"].get("Duration"), "datetime")
        self.assertEqual(types_doc["types"].get("Duration (end)"), "datetime")


if __name__ == "__main__":
    unittest.main(verbosity=2)
