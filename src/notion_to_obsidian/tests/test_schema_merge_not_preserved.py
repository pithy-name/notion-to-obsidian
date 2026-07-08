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

F7 (test-adequacy): the ORIGINAL version of
`test_second_run_with_new_property_is_schema_merged_only_not_counted_as_preserved`
below only asserted `"SCHEMA-MERGED" in report_text` — the raw log-LINE
text, which `_emit_conversion_report` echoes verbatim under whichever
section heading it picks (every overwrite_log entry, regardless of event
kind, gets printed as `f"- {w}"` under SOME heading). That means the test
passed even with ONLY the heading-classification fix reverted (confirmed
in a scratch copy — see the second test below), because the string
"SCHEMA-MERGED" is present in the log entry's own text either way; the
test never actually checked WHICH heading the entry landed under.
Strengthened to assert the entry appears under the correct "## Notes"
heading AND that the wrong "## Skipped overwrites (existing files
preserved)" heading is ABSENT for a run whose only overwrite_log events
are additive (SCHEMA-MERGED/WARN).

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
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
        # F7: assert the entry lands under the CORRECT heading, not merely
        # that the literal string "SCHEMA-MERGED" appears somewhere in the
        # report (every overwrite_log line is echoed verbatim regardless of
        # which heading classification picked for it).
        self.assertIn("## Notes", report_text)
        notes_section = report_text.split("## Notes", 1)[1]
        self.assertIn("SCHEMA-MERGED", notes_section)
        self.assertNotIn("## Skipped overwrites (existing files preserved)", report_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
