#!/usr/bin/env python3
"""
B5: `--symlink` mode must NOT expose child-node content.

The old implementation created ONE directory symlink pointing at the whole
source attachment dir, so anything walking the output (Obsidian included)
could see straight through it to every child node's raw ".html" file and
hex-named folder — exactly the content copy mode's `_attachment_copy_ignore`
filter exists to hide. Symlink mode must apply the same filter: only genuine
attachments get a (per-file) symlink.

F8 (test-adequacy): `pathlib.Path.rglob` does NOT follow directory symlinks
(a documented Python stdlib behavior) — so the two "no leaked content
reachable" checks below, when written with `self.out.rglob(...)`, could
NEVER fail regardless of whether the leak actually exists. If B5's fix were
fully reverted (a single whole-directory symlink straight to the source
attachment dir), `rglob` simply refuses to descend PAST that directory
symlink at all, so it would never even reach the leaked ".html"/hex-named
content behind it to report it — the assertion passes for the wrong reason
every time. Rewritten with `os.walk(..., followlinks=True)`, which DOES
traverse through symlinked directories, so these checks actually exercise
the traversal a real filesystem walker (or Obsidian's own file indexer)
would perform.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder
import notion_db_to_obsidian as n

HEX_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)


def _walk_all_paths_following_symlinks(root: Path):
    """Every file/dir path under `root`, descending THROUGH directory
    symlinks (unlike Path.rglob, which refuses to follow them)."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dp = Path(dirpath)
        for name in dirnames:
            yield dp / name
        for name in filenames:
            yield dp / name


class SymlinkModeFiltersNodeContent(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        build(self.src)
        cat_dir = self.src / folder("Animals") / folder("Cat")
        (cat_dir / "cat-photo.png").write_bytes(b"\x89PNG fake bytes")
        n.run_conversion(self.src, self.out, attachment_mode="symlink")

    def tearDown(self):
        self._td.cleanup()

    def test_attachment_dir_is_a_real_directory_not_a_whole_dir_symlink(self):
        cat_out = self.out / "Animals" / "Cat"
        self.assertTrue(cat_out.is_dir())
        self.assertFalse(
            cat_out.is_symlink(),
            "the whole attachment dir must not itself be a symlink (B5)",
        )

    def test_genuine_attachment_is_symlinked(self):
        link = self.out / "Animals" / "Cat" / "cat-photo.png"
        self.assertTrue(link.is_symlink(), "genuine attachment should be a symlink")
        self.assertTrue(link.resolve().is_file())
        self.assertEqual(link.read_bytes(), b"\x89PNG fake bytes")

    def test_no_raw_node_html_reachable_through_symlinks(self):
        # os.walk(followlinks=True) — NOT rglob, which never descends past a
        # directory symlink and so could never observe a leak behind one (F8).
        leaked = sorted(
            str(p.relative_to(self.out))
            for p in _walk_all_paths_following_symlinks(self.out)
            if p.name.lower().endswith(".html")
        )
        self.assertEqual(leaked, [], f"raw node HTML reachable via symlink mode: {leaked}")

    def test_no_hex_named_entries_reachable_through_symlinks(self):
        # os.walk(followlinks=True) — see note above.
        leaked = sorted(
            str(p.relative_to(self.out))
            for p in _walk_all_paths_following_symlinks(self.out)
            if HEX_RE.search(p.name)
        )
        self.assertEqual(leaked, [], f"hex-named node content reachable via symlinks: {leaked}")

    def test_child_notes_still_written(self):
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
