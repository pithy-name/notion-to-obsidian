#!/usr/bin/env python3
"""
B4: two different databases that merely SHARE a display name must not merge
into one output directory.

`mirror_output_dir` maps a source folder to its output path by stripping the
Notion hex id from every path component. Two distinct sibling databases named
identically (their source folders are "<Name> <hexA>/" and "<Name> <hexB>/",
each carrying its own unique hex) both hex-strip to the same "<Name>/" output
path — their entries would land in one shared folder, silently interleaving
two different databases' rows.

Fixture: two (or three, for the ordering test) databases named "Notes", SAME
parent (the export root), each with its own unique 32-hex Notion id and its
own single entry. This is the actual collision shape the B4 fix guards
against — the PREVIOUS fixture here put the two "Notes" DBs under different
parent pages ("Left"/"Right"), so their paths never collided in the first
place and the test passed even with the disambiguation code
(notion_db_to_obsidian.py run_conversion, db_out_dir_claims, ~line 2106-2124)
fully reverted. That made the test vacuous for the bug it claimed to cover.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import _entry_html, _index_html, _write, folder
import notion_db_to_obsidian as n

HEX_A = "a" * 32
HEX_B = "b" * 32
HEX_C = "c" * 32


def _db_with_hex(parent_dir: Path, display_name: str, hex_id: str, entries) -> Path:
    """
    Write a database directly under `parent_dir` using an EXPLICIT hex id
    rather than one derived from `display_name` (synthetic_export's `_db`
    helper derives the hex from the name via `folder()`, so it cannot express
    two same-named-but-different-id databases). `entries` is a list of
    (title, props, body) tuples, same shape as `_db`.
    """
    stem = f"{display_name} {hex_id}"
    _write(parent_dir / f"{stem}.html", _index_html(display_name))
    edir = parent_dir / stem
    edir.mkdir(parents=True, exist_ok=True)
    for title, props, body in entries:
        _write(edir / f"{folder(title)}.html", _entry_html(title, props, body))
    return edir


def _build_colliding_dbs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    # Two DBs named "Notes", SAME parent (root), different hex ids.
    _db_with_hex(root, "Notes", HEX_A, [("A", [("Order", "number", "1")], "")])
    _db_with_hex(root, "Notes", HEX_B, [("B", [("Order", "number", "1")], "")])


class SiblingDbNameCollision(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        _build_colliding_dbs(self.src)
        self.summary = n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_two_distinct_output_dirs_exist(self):
        # First claimant keeps the plain name; the second gets a short-id
        # suffix (e.g. "Notes (bbbbbb)") — see db_out_dir_claims in
        # run_conversion. We assert two DISTINCT dirs exist and one is the
        # plain "Notes"; the exact disambiguation-order rule (which sibling
        # keeps the plain name under 3+ collisions) is covered separately by
        # DeterministicDisambiguationOrder below.
        dirs = sorted(p for p in self.out.iterdir() if p.is_dir() and p.name.startswith("Notes"))
        self.assertEqual(len(dirs), 2, f"expected 2 distinct Notes dirs, got {dirs}")
        names = {d.name for d in dirs}
        self.assertIn("Notes", names)

    def test_entries_are_not_interleaved(self):
        dirs = sorted(p for p in self.out.iterdir() if p.is_dir() and p.name.startswith("Notes"))
        all_entry_stems = sorted(
            sorted(p.stem for p in d.glob("*.md") if p.stem != d.name)
            for d in dirs
        )
        # Each db's own entry landed in its own dir, not both in one.
        self.assertEqual(all_entry_stems, [["A"], ["B"]])

    def test_two_databases_discovered(self):
        self.assertEqual(len(self.summary["databases"]), 2)

    def test_no_dropped_entries(self):
        self.assertEqual(self.summary["total_entries"], 2)


class DeterministicDisambiguationOrder(unittest.TestCase):
    """
    F1(c): with 3+ same-named siblings, `databases.sort(key=...str(entries_folder))`
    makes processing order (and therefore which sibling keeps the plain name)
    deterministic — lexicographic by source entries_folder path, i.e. by hex id
    since the display name is identical across all of them. HEX_A < HEX_B <
    HEX_C lexicographically, so "Notes" (plain) must be HEX_A's db, and the
    others get short-id suffixes in the same order.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir(parents=True, exist_ok=True)
        _db_with_hex(self.src, "Notes", HEX_A, [("A", [("Order", "number", "1")], "")])
        _db_with_hex(self.src, "Notes", HEX_B, [("B", [("Order", "number", "1")], "")])
        _db_with_hex(self.src, "Notes", HEX_C, [("C", [("Order", "number", "1")], "")])
        self.summary = n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_three_distinct_dirs(self):
        dirs = sorted(p.name for p in self.out.iterdir() if p.is_dir() and p.name.startswith("Notes"))
        self.assertEqual(len(dirs), 3, f"expected 3 distinct Notes dirs, got {dirs}")

    def test_first_by_sort_order_keeps_plain_name(self):
        # HEX_A sorts first among entries_folder paths -> its db keeps "Notes".
        plain = self.out / "Notes"
        self.assertTrue(plain.is_dir())
        entry_stems = sorted(p.stem for p in plain.glob("*.md") if p.stem != "Notes")
        self.assertEqual(entry_stems, ["A"])

    def test_later_siblings_get_short_id_suffix(self):
        b_suffix = HEX_B[-6:]
        c_suffix = HEX_C[-6:]
        b_dir = self.out / f"Notes ({b_suffix})"
        c_dir = self.out / f"Notes ({c_suffix})"
        self.assertTrue(b_dir.is_dir(), f"expected {b_dir} to exist")
        self.assertTrue(c_dir.is_dir(), f"expected {c_dir} to exist")
        self.assertEqual(sorted(p.stem for p in b_dir.glob("*.md") if p.stem != b_dir.name), ["B"])
        self.assertEqual(sorted(p.stem for p in c_dir.glob("*.md") if p.stem != c_dir.name), ["C"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
