#!/usr/bin/env python3
"""
F6: `total_warnings` (schema type-drift, unresolved links, filename
collisions, dropped equations, ...) is written to `_conversion_report.md`
but the non-dry-run CONSOLE output never mentioned it — not even a count.
Contrast: `overwrite_log`'s WARN events DO get a console count line
("N WARN(s) — known limitations flagged..."). A user running for real,
watching the console rather than opening the report file afterward, had no
signal that anything needed attention.

Fixture: a standalone page whose body contains an unresolved cross-export
`.html` link (see test_unresolved_link_fallback.py / B6) — this produces
exactly one `total_warnings` entry via `write_entry` -> `convert_body`,
aggregated by `run_conversion`, with NO other overwrite_log WARN events to
confound the assertion.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from synthetic_export import _write, folder, uuid_of
import notion_db_to_obsidian as n


def _page_with_unresolved_link_html(title: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        f'<article id="{uuid_of(title)}" class="page sans">'
        f'<h1 class="page-title">{title}</h1>'
        '<div class="page-body">'
        '<a href="Other%20Export%20abc123.html">See other page</a>'
        '</div></article></body></html>'
    )


class WarningsPrintedToConsole(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir(parents=True, exist_ok=True)
        _write(
            self.src / f"{folder('Notes')}.html",
            _page_with_unresolved_link_html("Notes"),
        )

    def tearDown(self):
        self._td.cleanup()

    def test_console_prints_a_warning_count_line(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = n.run_conversion(self.src, self.out)
        self.assertGreaterEqual(len(summary["warnings"]), 1)
        stdout = buf.getvalue()
        self.assertRegex(
            stdout,
            r"\d+ conversion warning\(s\)",
            f"expected a warning-count line in console output, got:\n{stdout}",
        )
        self.assertIn("_conversion_report.md", stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
