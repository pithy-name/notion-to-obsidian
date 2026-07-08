#!/usr/bin/env python3
"""
Tests for Notion to-do → Obsidian task-list conversion.

Notion exports a to-do as
    <ul class="to-do-list"><li><div class="checkbox checkbox-on|off"></div>
        <span class="to-do-children-…">text</span></li></ul>
which should become `- [x] text` (checked) / `- [ ] text` (unchecked).

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def conv(html: str) -> str:
    soup = BeautifulSoup(f'<div class="page-body">{html}</div>', "html.parser")
    return ndo.convert_body(
        soup.find("div", class_="page-body"),
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
    )


def todo(state: str, text: str) -> str:
    cls = "checkbox-on" if state == "on" else "checkbox-off"
    child = "to-do-children-checked" if state == "on" else "to-do-children-unchecked"
    return (
        f'<ul class="to-do-list"><li><div class="checkbox {cls}"></div>'
        f'<span class="{child}">{text}</span></li></ul>'
    )


class Checkboxes(unittest.TestCase):
    def test_unchecked_becomes_open_task(self):
        self.assertIn("- [ ] Task A", conv(todo("off", "Task A")))

    def test_checked_becomes_done_task(self):
        self.assertIn("- [x] Task B", conv(todo("on", "Task B")))

    def test_adjacent_todos_form_one_tight_task_list(self):
        md = conv(todo("off", "one") + todo("on", "two"))
        self.assertIn("- [ ] one\n- [x] two", md)

    def test_regular_bullets_unaffected(self):
        md = conv('<ul class="bulleted-list"><li>plain bullet</li></ul>')
        self.assertIn("- plain bullet", md)
        self.assertNotIn("[ ]", md)
        self.assertNotIn("[x]", md)

    def test_nested_todo_indents_under_parent(self):
        # Audit item 8: a to-do with a nested child to-do must keep both states
        # and indent the child — the `to-do-children` span must leave no artifact.
        html = (
            '<ul class="to-do-list"><li>'
            '<div class="checkbox checkbox-on"></div>'
            '<span class="to-do-children-checked">Parent task</span>'
            '<ul class="to-do-list"><li>'
            '<div class="checkbox checkbox-off"></div>'
            '<span class="to-do-children-unchecked">Child task</span>'
            '</li></ul></li></ul>'
        )
        md = conv(html)
        self.assertIn("- [x] Parent task", md)
        self.assertIn("  - [ ] Child task", md)
        self.assertNotIn("to-do-children", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
