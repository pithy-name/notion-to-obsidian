#!/usr/bin/env python3
"""
Tests for discover_tree(): builds the full nesting tree at any depth, with no
depth ceiling and no "database required" rule. Run against the synthetic export.

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_discover_tree.py"
"""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ndo = _load("notion_db_to_obsidian", "notion_db_to_obsidian.py")
sx = _load("synthetic_export", "synthetic_export.py")


class DiscoverTree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ndo-tree-"))
        sx.build(self.tmp)
        self.tree = ndo.discover_tree(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)  # the test's own tmpdir

    def _db(self, name):
        return next(d for d in self.tree["databases"] if d["name"] == name)

    def test_all_databases_found_at_any_depth(self):
        self.assertEqual(
            {d["name"] for d in self.tree["databases"]},
            {"Animals", "Breeds", "Photos", "Steps"},
        )

    def test_depth_beyond_old_limit(self):
        # Breeds (depth 3) and Photos (depth 5) were fatal under the depth-2 cap.
        self.assertGreater(self._db("Breeds")["depth"], 2)
        self.assertGreater(self._db("Photos")["depth"], 2)

    def test_ownership_by_hex(self):
        self.assertIsNone(self._db("Animals")["owner_hex"])     # top-level
        self.assertEqual(self._db("Breeds")["owner_hex"], sx.hex_id("Cat"))
        self.assertEqual(self._db("Photos")["owner_hex"], sx.hex_id("Tabby"))
        self.assertEqual(self._db("Steps")["owner_hex"], sx.hex_id("Field Guide"))  # a PAGE owns it

    def test_entries_per_database(self):
        for name in ("Animals", "Breeds", "Photos", "Steps"):
            self.assertEqual(len(self._db(name)["entry_paths"]), 2)

    def test_each_database_has_index_page(self):
        for name in ("Animals", "Breeds", "Photos", "Steps"):
            self.assertIsNotNone(self._db(name)["index_path"])

    def test_standalone_pages(self):
        names = {p["name"] for p in self.tree["pages"]}
        self.assertEqual(names, {"About", "Field Guide"})
        about = next(p for p in self.tree["pages"] if p["name"] == "About")
        self.assertIsNone(about["owner_hex"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
