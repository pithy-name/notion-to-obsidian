#!/usr/bin/env python3
"""
Tests for frontmatter key naming.

The converter used to lowercase/underscore property names ("Created time" ->
created_time, "Tester(s)" -> tester_s), which (a) reads poorly and (b) breaks
Obsidian Bases built around the original Notion property names. We now preserve
the original Notion property name verbatim (trimmed) as the frontmatter key.

The one special case is the tag property: a "Tags" multi_select must still map
to Obsidian's tag system, matched case-insensitively.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import importlib.util
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


class PropertyKeyNaming(unittest.TestCase):
    def test_preserves_original_name_verbatim(self):
        self.assertEqual(ndo.property_key("Created time"), "Created time")
        self.assertEqual(ndo.property_key("Tester(s)"), "Tester(s)")
        self.assertEqual(ndo.property_key("Full UAs"), "Full UAs")
        self.assertEqual(ndo.property_key("Areas Under Test"), "Areas Under Test")

    def test_trims_surrounding_whitespace(self):
        self.assertEqual(ndo.property_key("  Platform  "), "Platform")

    def test_empty_name_falls_back(self):
        self.assertEqual(ndo.property_key(""), "property")
        self.assertEqual(ndo.property_key("   "), "property")


class TagPropertyStillMapsToObsidianTags(unittest.TestCase):
    def test_tags_type_is_case_insensitive(self):
        self.assertEqual(ndo.obsidian_type_for("Tags", "multi_select"), "tags")
        self.assertEqual(ndo.obsidian_type_for("tags", "multi_select"), "tags")

    def test_non_tags_property_unaffected(self):
        self.assertEqual(ndo.obsidian_type_for("Platform", "multi_select"), "multitext")


if __name__ == "__main__":
    unittest.main(verbosity=2)
