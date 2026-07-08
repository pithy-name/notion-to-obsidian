#!/usr/bin/env python3
"""
B9: a Notion date RANGE property ("Jan 2, 2024 → Jan 5, 2024") must not
silently drop its end date. `parse_notion_date` keeps only the start (used
for the property's own frontmatter value, unaffected); the end date is
additionally emitted as a companion `<Prop> (end)` frontmatter property —
per README Known Issues' recommended option (A): both stay date-typed/sortable.

Run: /usr/bin/python3 test_date_range_end.py
"""
import json
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


class EmitTypesJsonRealEndPropertyNeverClobbered(unittest.TestCase):
    """
    G4 (F5 incomplete): the F5 collision guard was added to `write_entry` but
    not to `emit_types_json`. When a real property literally named
    "Duration (end)" is iterated (in schema order) AFTER a date property
    "Duration", the synthetic end-key registration below already occupies
    `types_map["Duration (end)"]` = "datetime", so `if key not in types_map`
    is False for the real property and it never gets its own true type
    registered — it's permanently mistyped in `.obsidian/types.json`.
    """

    def test_real_end_property_keeps_its_own_type(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()
        schema = OrderedDict()
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        schema["Duration (end)"] = {"types": Counter({"text": 1}), "key": "Duration (end)"}
        n.emit_types_json(out_root, schema, force=False, overwrite_log=[], dry_run=False)
        import json
        types_doc = json.loads((out_root / ".obsidian" / "types.json").read_text(encoding="utf-8"))
        self.assertEqual(types_doc["types"].get("Duration"), "datetime")
        self.assertEqual(types_doc["types"].get("Duration (end)"), "text")

    def test_real_end_property_keeps_its_own_type_declared_first(self):
        # NOTE (H3, round-3 red-team): this only re-confirms that the
        # WITHIN-CALL `real_keys` precomputation (G4) is order-independent
        # -- with "Duration (end)" declared first, it's already written
        # with its true type before "Duration"'s synthetic registration is
        # even attempted, so `real_keys` never has to intervene. This test
        # stays green even with H2's force-overwrite hunk fully reverted
        # (verified) -- it gives ZERO signal for H2's cross-run
        # force-overwrite logic. That logic (a stale ON-DISK synthetic
        # entry from a PRIOR run must not preempt a real property in a
        # LATER run) is exercised instead by
        # EmitTypesJsonCrossRunRealPropertyWins, the only scenario where
        # `real_keys`'s within-call guard can't help and the force-
        # overwrite has to do the work.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()
        schema = OrderedDict()
        schema["Duration (end)"] = {"types": Counter({"text": 1}), "key": "Duration (end)"}
        schema["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        n.emit_types_json(out_root, schema, force=False, overwrite_log=[], dry_run=False)
        import json
        types_doc = json.loads((out_root / ".obsidian" / "types.json").read_text(encoding="utf-8"))
        self.assertEqual(types_doc["types"].get("Duration"), "datetime")
        self.assertEqual(types_doc["types"].get("Duration (end)"), "text")


class EmitTypesJsonNeverClobbersUserCustomization(unittest.TestCase):
    """
    I2 (round-4 red-team, H2 over-correction): H2's fix for the cross-run
    "<Prop> (end)" collision (`if types_map.get(key) != otype: types_map[key]
    = otype`) force-overwrote `types_map[key]` for ANY real property whose
    on-disk type differs from the current run's inference -- not just the
    narrow stale-synthetic-"(end)"-key case it targeted. That silently
    reverts a user's manual Obsidian-UI type customization on EVERY re-run:
    infer "Legs" as `number`, the user retypes it `text` in Obsidian, re-run
    the SAME conversion (same schema) and H2's code stomps it back to
    `number` -- worse than the rare bug H2 fixed, and it contradicts the
    tool's own advertised "never clobber existing entries" contract
    (docstring / --no-types help / README / console line all still claim the
    old, safer behavior). Fixed: restored `if key not in types_map` for the
    on-disk merge -- an existing entry, however it got there, is never
    touched; only a genuinely missing key is added.
    """

    def test_user_customized_type_survives_a_rerun_with_same_schema(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()

        schema = OrderedDict()
        schema["Legs"] = {"types": Counter({"number": 1}), "key": "Legs"}

        # Run 1: infers Legs=number, writes it to disk.
        n.emit_types_json(out_root, schema, force=True, overwrite_log=[], dry_run=False)
        types_path = out_root / ".obsidian" / "types.json"
        doc = json.loads(types_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["types"].get("Legs"), "number")

        # User manually retypes it to `text` in Obsidian's UI.
        doc["types"]["Legs"] = "text"
        types_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

        # Run 2: the SAME conversion re-run (same schema, same inferred
        # type). The user's customization must survive.
        n.emit_types_json(out_root, schema, force=True, overwrite_log=[], dry_run=False)
        doc2 = json.loads(types_path.read_text(encoding="utf-8"))
        self.assertEqual(
            doc2["types"].get("Legs"), "text",
            "BUG: a user's manual Obsidian-UI type customization was "
            f"reverted by a re-run with the same inferred schema; got: {doc2['types']}",
        )


class EmitTypesJsonSchemaMergedLogOnlyCountsNewKeys(unittest.TestCase):
    """
    I3 (round-4 red-team, largely resolved by I2): the run summary's
    SCHEMA-MERGED overwrite_log line and the console "(no existing keys
    touched)" wording are only true if the on-disk merge genuinely never
    overwrites an existing key. Confirms that end-to-end: a re-run with an
    existing (user-customized) on-disk entry logs a SCHEMA-MERGED entry
    that reports only genuinely-new keys added by THIS run, never the
    customized one that was left untouched.
    """

    def test_rerun_schema_merge_log_never_mentions_untouched_existing_key(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()

        schema_run1 = OrderedDict()
        schema_run1["Legs"] = {"types": Counter({"number": 1}), "key": "Legs"}
        n.emit_types_json(out_root, schema_run1, force=True, overwrite_log=[], dry_run=False)

        types_path = out_root / ".obsidian" / "types.json"
        doc = json.loads(types_path.read_text(encoding="utf-8"))
        doc["types"]["Legs"] = "text"  # user customization
        types_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

        # Run 2: same "Legs" property (would-be no-op) plus one genuinely
        # NEW property "Color".
        schema_run2 = OrderedDict()
        schema_run2["Legs"] = {"types": Counter({"number": 1}), "key": "Legs"}
        schema_run2["Color"] = {"types": Counter({"select": 1}), "key": "Color"}
        log: list = []
        n.emit_types_json(out_root, schema_run2, force=True, overwrite_log=log, dry_run=False)

        # The customization survives untouched (I2).
        doc2 = json.loads(types_path.read_text(encoding="utf-8"))
        self.assertEqual(doc2["types"].get("Legs"), "text")

        schema_events = [w for w in log if "types.json" in w]
        self.assertTrue(schema_events, "expected a types.json log entry")
        merged_text = " ".join(schema_events)
        self.assertIn("Color", merged_text)
        self.assertNotIn("Legs", merged_text)


class EmitTypesJsonCrossRunRealPropertyWins(unittest.TestCase):
    """
    I2 (round-4 red-team): H2's fix for this cross-run "<Prop> (end)"
    collision (a stale on-disk synthetic "<Prop> (end)"=datetime from a
    prior run shadowing a genuinely real, differently-typed property of that
    exact name in a later run) was a force-overwrite far broader than this
    narrow case -- see EmitTypesJsonNeverClobbersUserCustomization. The
    never-clobber-on-disk contract is restored (I2), so this specific
    collision is no longer "fixed" by overwriting; it is a documented,
    accepted trade-off instead (see README Known Issues,
    2026-07-06): a real property is only mistyped in this specific,
    rare cross-run collision scenario (an actual property must be named
    literally "<X> (end)" and collide with a prior run's date-range
    companion key of the same name) -- narrower and far less damaging than
    reverting every user customization on every run.
    """

    def test_stale_synthetic_end_key_is_never_clobbered_documented_limitation(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out_root = Path(td.name) / "out"
        out_root.mkdir()

        # Run 1: a date-range property "Duration" synthesizes
        # "Duration (end)" = datetime into types.json.
        schema_run1 = OrderedDict()
        schema_run1["Duration"] = {"types": Counter({"date": 1}), "key": "Duration"}
        n.emit_types_json(out_root, schema_run1, force=True, overwrite_log=[], dry_run=False)

        # Run 2 (a separate conversion invocation onto the same output
        # vault): no "Duration" date property this time, but a REAL
        # property literally named "Duration (end)" of type rich_text.
        schema_run2 = OrderedDict()
        schema_run2["Duration (end)"] = {
            "types": Counter({"rich_text": 1}), "key": "Duration (end)"
        }
        n.emit_types_json(out_root, schema_run2, force=True, overwrite_log=[], dry_run=False)

        types_doc = json.loads((out_root / ".obsidian" / "types.json").read_text(encoding="utf-8"))
        # Documented known limitation (I2, 2026-07-06): the never-clobber
        # contract means the stale on-disk synthetic entry wins here, not
        # run 2's real property -- the accepted trade-off vs. H2's
        # force-overwrite, which fixed this at the cost of reverting user
        # customizations on every run.
        self.assertEqual(
            types_doc["types"].get("Duration (end)"), "datetime",
            f"expected the documented never-clobber limitation; got: {types_doc['types']}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
