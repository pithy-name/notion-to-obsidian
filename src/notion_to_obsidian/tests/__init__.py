"""
Test package for notion_to_obsidian.

The individual test_*.py files use BARE imports (`import notion_db_to_obsidian
as n`, `from synthetic_export import build, folder`) rather than package-
relative imports — this matches their pre-packaging style and needed the
least import-shim hackery to keep working after the src-layout move.

Making this directory a package means `unittest discover` (and pytest) import
this `__init__.py` before collecting any test_*.py module inside it, so the
sys.path inserts below run exactly once per test session and make the bare
imports resolve — with NO installed package required. (An editable
`pip install -e .` also works, since these inserts are idempotent and just
add paths pip already made importable-by-package.)

Two directories are added:
  - `_PACKAGE_DIR` (the `notion_to_obsidian` package root) — resolves
    `import notion_db_to_obsidian`, `import fix_frontmatter_dates`, etc.
  - `_TESTS_DIR` (this directory) — resolves `from synthetic_export import
    ...`. F11: `synthetic_export.py` is a test-fixture builder, not shipped
    product code, so it lives HERE (under `tests/`, which
    `pyproject.toml`'s `[tool.setuptools.packages.find]` excludes from the
    wheel) rather than in the package root where it used to sit and would
    otherwise ship in every install.
"""

import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
_PACKAGE_DIR = str(Path(__file__).resolve().parent.parent)
for _dir in (_PACKAGE_DIR, _TESTS_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
