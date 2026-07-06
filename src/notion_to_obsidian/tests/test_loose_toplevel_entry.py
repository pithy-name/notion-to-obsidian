#!/usr/bin/env python3
"""
M1 (2026-07-06 round-10 red-team): a loose top-level `.html` file directly
under the export root whose markup happens to contain the substring
`class="properties"` (e.g. an empty properties table, as when a user exports
a single database row as its own standalone HTML export) gets misclassified
as a database "entry" by `classify_html`'s naive substring match. Its
`entries_folder` then resolves to `src` itself, and the old code crashed with
an unhandled `ValueError` from `mirror_output_dir` (`relative_to` on a path
ABOVE `src_root`) — killing the ENTIRE run, no output, no report.

Fix: `discover_tree` detects an entries_folder == src (no real parent
structure to nest under) and folds each such entry into the standalone-pages
list instead, with an explicit warning so nothing is silently dropped. The
rest of the export must still convert normally and the run must exit 0 with
a written report.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import notion_db_to_obsidian as ndo
import synthetic_export as sx

_LOOSE_NAME = "Loose Row.html"
_LOOSE_HTML = (
    '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
    '<article class="page sans"><table class="properties"><tbody></tbody>'
    '</table></article></body></html>'
)


class LooseTopLevelEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ndo-loose-"))
        sx.build(self.tmp)
        (self.tmp / _LOOSE_NAME).write_text(_LOOSE_HTML, encoding="utf-8")
        self.out = Path(tempfile.mkdtemp(prefix="ndo-loose-out-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_classified_as_entry_by_naive_match(self):
        # Confirms the premise: the substring match alone would call this an
        # "entry" (classify_html itself is NOT being changed by this fix).
        self.assertEqual(ndo.classify_html(self.tmp / _LOOSE_NAME), "entry")

    def test_discover_tree_folds_loose_entry_into_pages_with_warning(self):
        tree = ndo.discover_tree(self.tmp)
        # Not left behind as a fake database rooted at src itself.
        self.assertTrue(
            all(db["entries_folder"] != self.tmp for db in tree["databases"])
        )
        # Every real database from the synthetic fixture still discovered.
        self.assertEqual(
            {d["name"] for d in tree["databases"]},
            {"Animals", "Breeds", "Photos", "Steps"},
        )
        page_paths = {p["path"] for p in tree["pages"]}
        self.assertIn(self.tmp / _LOOSE_NAME, page_paths)
        self.assertTrue(
            any("Loose Row.html" in w for w in tree["warnings"]),
            f"expected a warning naming the loose file, got {tree['warnings']!r}",
        )

    def test_run_conversion_does_not_raise_and_writes_report(self):
        # Before the fix this raised ValueError from mirror_output_dir and
        # aborted the entire run with no output and no report.
        summary = ndo.run_conversion(self.tmp, self.out)
        report = self.out / "_conversion_report.md"
        self.assertTrue(report.exists(), "run must still write a report")
        self.assertTrue(
            any("Loose Row.html" in w for w in summary["warnings"]),
            "the loose file must be named in the run's warnings, not silently dropped",
        )

    def test_normal_content_still_converts(self):
        summary = ndo.run_conversion(self.tmp, self.out)
        self.assertEqual(summary["total_entries"], 8)  # Animals/Breeds/Photos/Steps x2
        cat_md = next(self.out.rglob("Cat.md"), None)
        self.assertIsNotNone(cat_md, "a normal entry (Cat) must still convert")

    def test_loose_entry_converted_as_standalone_page(self):
        # Chosen degradation behavior: convert as a standalone page at the
        # output root (its own filename), not a WARN+skip with no output.
        summary = ndo.run_conversion(self.tmp, self.out)
        loose_md = self.out / "Loose Row.md"
        self.assertTrue(
            loose_md.exists(),
            f"expected the loose entry converted as a standalone page at {loose_md}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
