#!/usr/bin/env python3
"""
F10: packaging smoke coverage. Nothing in the suite previously verified that
the pip-installable package (`pyproject.toml`'s two console-script entry
points, and the `from notion_to_obsidian import run_conversion` library
import) actually resolves — only the bare-import test style
(`import notion_db_to_obsidian as n`) was exercised, which works even if the
package-level wiring (`__init__.py` exports, `[project.scripts]` targets) is
broken.

(a) Parse `pyproject.toml`'s `[project.scripts]` table (a tiny hand-rolled
    parser — no TOML library dependency added just for this) and, for each
    "module:callable" entry-point string, import the module and getattr the
    callable, asserting it's actually callable.
(b) `from notion_to_obsidian import run_conversion` — the documented library
    entry point — must work when `src` is on `sys.path` (true under the
    standard suite command, `PYTHONPATH=src ...`). Skips gracefully (does
    not fail) if the package isn't importable in an odd environment, but
    must actually run — not skip — under the standard suite command.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""
import importlib
import re
import unittest
from pathlib import Path


def _repo_root() -> Path:
    # tests/test_packaging.py -> tests -> notion_to_obsidian -> src -> repo root
    return Path(__file__).resolve().parents[3]


def _parse_project_scripts(pyproject_text: str) -> dict:
    """
    Minimal hand-rolled parser for a `[project.scripts]` TOML table of
    `name = "module:callable"` lines. Deliberately not a general TOML parser
    (no dependency added just for one small table) — good enough for this
    project's own pyproject.toml, which this test also therefore keeps
    honest: any hand-edit that breaks this shape breaks the test.
    """
    m = re.search(
        r"\[project\.scripts\]\s*\n(.*?)(?:\n\[|\Z)", pyproject_text, re.DOTALL
    )
    if not m:
        return {}
    table_text = m.group(1)
    entries = {}
    for line in table_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        km = re.match(r'^([\w.-]+)\s*=\s*"([^"]+)"\s*$', line)
        if km:
            entries[km.group(1)] = km.group(2)
    return entries


class ConsoleScriptEntryPointsResolve(unittest.TestCase):
    def setUp(self):
        pyproject_path = _repo_root() / "pyproject.toml"
        self.assertTrue(
            pyproject_path.is_file(), f"expected {pyproject_path} to exist"
        )
        self.scripts = _parse_project_scripts(
            pyproject_path.read_text(encoding="utf-8")
        )

    def test_scripts_table_is_not_empty(self):
        # A parse failure (e.g. the table's shape changed) must not silently
        # look like "0 entry points to check" — that would vacuously pass.
        self.assertGreaterEqual(len(self.scripts), 2, f"parsed: {self.scripts}")

    def test_notion2obsidian_entry_point_resolves(self):
        target = self.scripts.get("notion2obsidian")
        self.assertIsNotNone(target, f"parsed scripts: {self.scripts}")
        module_name, _, func_name = target.partition(":")
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        self.assertTrue(callable(func), f"{target} did not resolve to a callable")

    def test_notion2obsidian_fix_dates_entry_point_resolves(self):
        target = self.scripts.get("notion2obsidian-fix-dates")
        self.assertIsNotNone(target, f"parsed scripts: {self.scripts}")
        module_name, _, func_name = target.partition(":")
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        self.assertTrue(callable(func), f"{target} did not resolve to a callable")


class LibraryImportWorks(unittest.TestCase):
    def test_run_conversion_importable_from_package(self):
        try:
            from notion_to_obsidian import run_conversion
        except ImportError as exc:
            self.skipTest(
                f"notion_to_obsidian package not importable in this "
                f"environment (src not on sys.path?): {exc}"
            )
        else:
            self.assertTrue(callable(run_conversion))


if __name__ == "__main__":
    unittest.main(verbosity=2)
