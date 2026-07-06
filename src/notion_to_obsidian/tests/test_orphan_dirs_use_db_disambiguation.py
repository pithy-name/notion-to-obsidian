#!/usr/bin/env python3
"""
F1(b): `copy_orphaned_files` must land a loose orphan file in the SAME
disambiguated output dir its owning database's entries went to — not in a
raw `mirror_output_dir(path.parent, src, out_root)` destination that ignores
the `db_out_dir_claims` disambiguation map `run_conversion` builds for B4.

Repro: two databases named "Notes", SAME parent (export root), different
32-hex ids, EACH with a loose non-HTML file sitting directly in its entries
folder (not in any entry's own attachment subfolder, so `write_entry` never
copies it — it's an orphan). Both source folders hex-strip to the same
"Notes" output-dir base. The first DB's entries claim "Notes/"; the second
DB's entries get disambiguated into "Notes (bbbbbb)/" (short id suffix). Before
the fix, `copy_orphaned_files` computed its destination independently of that
claim, so the second DB's orphan file was written into the FIRST db's output
dir (as a byte-different collision, renamed "readme (2).txt") instead of
landing in "Notes (bbbbbb)/readme.txt" alongside its own database's entries.

Deliberately NO index/landing page for either database: when a DB's index
page shares its folder's exact name (the common Notion shape), that index
node's own attachment dir IS the entries folder, which already covers a
loose file sitting there via the ordinary `covered_dirs` membership test —
that would mask this bug. Dropping the index page isolates the actual gap:
a loose file in an entries folder that belongs to no node's own attach dir.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import tempfile
import unittest
from pathlib import Path

from synthetic_export import _entry_html, _write, folder
import notion_db_to_obsidian as n

HEX_A = "a" * 32
HEX_B = "b" * 32


def _db_with_hex_no_index(parent_dir: Path, display_name: str, hex_id: str, entries) -> Path:
    """Entries folder only — no index/landing page HTML alongside it."""
    stem = f"{display_name} {hex_id}"
    edir = parent_dir / stem
    edir.mkdir(parents=True, exist_ok=True)
    for title, props, body in entries:
        _write(edir / f"{folder(title)}.html", _entry_html(title, props, body))
    return edir


class OrphanFileLandsInDisambiguatedDbDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir(parents=True, exist_ok=True)

        a_dir = _db_with_hex_no_index(
            self.src, "Notes", HEX_A, [("A", [("Order", "number", "1")], "")]
        )
        b_dir = _db_with_hex_no_index(
            self.src, "Notes", HEX_B, [("B", [("Order", "number", "1")], "")]
        )
        # Loose, non-HTML files directly in each DB's entries folder — not
        # inside any entry's own attachment subfolder, so write_entry never
        # touches them (they are true orphans, covered only by the orphan
        # pass). Distinct content on purpose: if they land in the SAME output
        # dir, the byte-difference forces the collision-rename path, which is
        # exactly the failure mode this test is guarding against.
        (a_dir / "readme.txt").write_text("from A\n", encoding="utf-8")
        (b_dir / "readme.txt").write_text("from B\n", encoding="utf-8")

        self.summary = n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_each_orphan_lands_in_its_own_db_dir(self):
        a_readme = self.out / "Notes" / "readme.txt"
        b_readme = self.out / f"Notes ({HEX_B[-6:]})" / "readme.txt"
        self.assertTrue(a_readme.is_file(), f"expected {a_readme} to exist")
        self.assertTrue(b_readme.is_file(), f"expected {b_readme} to exist")
        self.assertEqual(a_readme.read_text(encoding="utf-8"), "from A\n")
        self.assertEqual(b_readme.read_text(encoding="utf-8"), "from B\n")

    def test_no_collision_rename_needed(self):
        # If disambiguation is threaded through correctly, the two orphans
        # never contend for the same destination, so no "(2)" collision
        # rename should appear anywhere in the output tree.
        collided = list(self.out.rglob("readme (*).txt"))
        self.assertEqual(collided, [], f"unexpected collision-renamed files: {collided}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
