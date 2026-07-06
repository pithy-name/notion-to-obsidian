"""
notion_to_obsidian — convert a Notion HTML export into an Obsidian-ready vault.

Library entry point:

    from notion_to_obsidian import run_conversion
    run_conversion(src, out_root, ...)

See `run_conversion` in `notion_db_to_obsidian.py` for the full parameter
list, or run `notion2obsidian --help` for the CLI.
"""

from .notion_db_to_obsidian import run_conversion

__all__ = ["run_conversion"]
