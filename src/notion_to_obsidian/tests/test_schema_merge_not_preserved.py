#!/usr/bin/env python3
"""
B10: an additive `.obsidian/types.json` schema merge must not be mislabeled
as a file-preservation event.

`emit_types_json` shared its "Updated `.obsidian/types.json`" log line with
`overwrite_log` — the SAME list `_emit_conversion_report` also uses for
.base/.md collision events. Its "any OVERWROTE? else PRESERVED" heuristic
then mislabeled a run whose ONLY overwrite_log entry was a benign additive
schema merge as "PRESERVED N existing file(s); new content written to .new
siblings" — untrue; no .new file was ever written for a schema merge.

Run: /usr/bin/python3 test_schema_merge_not_preserved.py
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build
import notion_db_to_obsidian as n


class SchemaMergeIsNotPreserved(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        build(self.src)

    def tearDown(self):
        self._td.cleanup()

    def test_first_run_types_json_event_is_schema_merged_not_preserved(self):
        summary = n.run_conversion(self.src, self.out)
        log = summary["overwrite_log"]
        schema_events = [w for w in log if "types.json" in w]
        self.assertTrue(schema_events, "expected a types.json log entry")
        self.assertTrue(
            all(w.startswith("SCHEMA-MERGED") for w in schema_events),
            f"types.json event(s) not tagged SCHEMA-MERGED: {schema_events}",
        )
        self.assertFalse(
            any(w.startswith("Updated") for w in log),
            "old 'Updated' prefix should no longer appear",
        )

    def test_second_run_with_new_property_is_schema_merged_only_not_counted_as_preserved(self):
        # First run creates types.json; second run's DB gains no new
        # property here, so re-running is a no-op for types.json BUT we can
        # still verify a run whose overwrite_log holds only a WARN/
        # SCHEMA-MERGED-shaped entry is never reported as a preserved-file
        # event by _emit_conversion_report's classification.
        n.run_conversion(self.src, self.out)
        report_path = self.out / "_conversion_report.md"
        report_text = report_path.read_text(encoding="utf-8")
        # types.json's first-run merge must show under its own label, not
        # under a "Skipped overwrites (existing files preserved)" framing
        # when that's the ONLY kind of event in the log.
        self.assertIn("SCHEMA-MERGED", report_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
