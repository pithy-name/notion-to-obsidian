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


class RealEndPropertyNeverClobbered(unittest.TestCase):
    """
    F5 (B9 collision): the synthetic "<Prop> (end)" key must not clobber, or
    be silently shadowed by, a REAL Notion property that happens to be named
    exactly that. Fixture: a date-range property "Duration" AND a real,
    independent property literally named "Duration (end)" in the same
    schema. Before the fix, `write_entry` did a blind
    `frontmatter[f"{key} (end)"] = end_value` with no existence check, so
    whichever assignment ran last (schema iteration order) won silently —
    either the real property's value was overwritten by the synthetic range
    end, or (depending on order) the real value happened to survive with no
    signal that the range's end date was dropped instead. Either way it's
    unpredictable data loss with no warning.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _run(self, real_end_value: str):
        src = self.tmp / "src"; src.mkdir(exist_ok=True)
        out = self.tmp / "out"; out.mkdir(exist_ok=True)
        entry = {
            "path": src / "Item aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html",
            "title": "Item",
            "notion_uuid": None,
            "properties": [
                ("Duration", "date", _date_td("January 2, 2024 → January 5, 2024")),
                ("Duration (end)", "text", _date_td(real_end_value)),
            ],
            "body": None,
        }
        schema = OrderedDict()
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        schema["Duration (end)"] = {"types": Counter({"text": 1}), "key": "Duration (end)"}
        _path, warnings = n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        text = (out / "Item.md").read_text(encoding="utf-8")
        return text, warnings

    def test_real_end_property_value_survives(self):
        text, warnings = self._run("not a date, a real value")
        self.assertIn("not a date, a real value", text)
        # The synthetic range-end date must NOT have overwritten it.
        self.assertNotRegex(text, r"(?m)^Duration \(end\):\s*'?2024-01-05'?\s*$")

    def test_collision_is_warned(self):
        _text, warnings = self._run("not a date, a real value")
        self.assertTrue(
            any("Duration (end)" in w and "collis" in w.lower() for w in warnings),
            f"expected a collision warning mentioning 'Duration (end)', got: {warnings}",
        )

    def test_real_end_property_survives_even_when_declared_first(self):
        # Schema order is NOT the collision-safety mechanism — the real
        # property must survive regardless of which schema position it's in.
        # With the real "Duration (end)" declared BEFORE "Duration" (so it's
        # written to frontmatter first), the unguarded blind-assignment bug
        # would have the synthetic range-end value clobber it on the LATER
        # "Duration" iteration — the actual data-loss direction of B9's gap
        # (the other schema order merely happens to leave the real value
        # surviving last, which is what test_real_end_property_value_survives
        # exercises).
        src = self.tmp / "src"; src.mkdir(exist_ok=True)
        out = self.tmp / "out2"; out.mkdir(exist_ok=True)
        entry = {
            "path": src / "Item2 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.html",
            "title": "Item2",
            "notion_uuid": None,
            "properties": [
                ("Duration (end)", "text", _date_td("not a date, a real value")),
                ("Duration", "date", _date_td("January 2, 2024 → January 5, 2024")),
            ],
            "body": None,
        }
        schema = OrderedDict()
        schema["Duration (end)"] = {"types": Counter({"text": 1}), "key": "Duration (end)"}
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        _path, warnings = n.write_entry(
            entry, out, schema, {}, {},
            force=True, overwrite_log=[], attachment_mode="inplace", dry_run=False,
        )
        text = (out / "Item2.md").read_text(encoding="utf-8")
        self.assertIn("not a date, a real value", text)
        self.assertNotRegex(text, r"(?m)^Duration \(end\):\s*'?2024-01-05'?\s*$")
        self.assertTrue(
            any("Duration (end)" in w and "collis" in w.lower() for w in warnings),
            f"expected a collision warning mentioning 'Duration (end)', got: {warnings}",
        )


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
