"""
Test package for notion_to_obsidian.

The individual test_*.py files use BARE imports (`import notion_db_to_obsidian
as n`, `from synthetic_export import build, folder`) rather than package-
relative imports — this matches their pre-packaging style and needed the
least import-shim hackery to keep working after the src-layout move.

Making this directory a package means `unittest discover` (and pytest) import
this `__init__.py` before collecting any test_*.py module inside it, so the
sys.path insert below runs exactly once per test session and makes the bare
imports resolve to the sibling modules in `src/notion_to_obsidian/` — with NO
installed package required. (An editable `pip install -e .` also works, since
this insert is idempotent and just adds a path pip already made
importable-by-package.)
"""

import sys
from pathlib import Path

_PACKAGE_DIR = str(Path(__file__).resolve().parent.parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)
