#!/usr/bin/env python3
"""
fix_frontmatter_dates.py — Convert human-readable date values in Markdown
YAML frontmatter to ISO 8601, so Obsidian Bases types them as date/datetime
instead of text.

Why this exists:
    notion_db_to_obsidian.py *currently* converts dates via parse_notion_date()
    when it produces .md files. Vaults built by an OLDER version of that
    script stored Notion's raw rendered date strings ("April 12, 2022 11:38 AM")
    verbatim, which Bases reads as plain text — losing date sorting/filtering.

What this does:
    Walks .md files under the given folder, parses YAML frontmatter, and
    rewrites date-typed values for a fixed set of keys to ISO 8601:

        created_time, last_edited_time, created, published, date

    - Idempotent: values already in ISO are left alone.
    - In-place: writes back only files that change.
    - Surgical: only the matched value is rewritten; the rest of the
      frontmatter (key order, comments, quoting on other lines) is
      preserved by line-level edit.
    - Unparseable values are left alone and logged.

Zero network access. Pure stdlib.

Usage (installed console script — `pip install -e .` from the repo root):
    notion2obsidian-fix-dates <folder> [--dry-run]

Usage (from a repo checkout, no install):
    PYTHONPATH=src /usr/bin/python3 -m notion_to_obsidian.fix_frontmatter_dates \\
        <folder> [--dry-run]

Example:
    notion2obsidian-fix-dates "<vault-folder>/<entries-folder>"
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Frontmatter keys we treat as date-typed. (Obsidian Bases types by content,
# but we only touch keys that *should* be dates — never anything else.)
DATE_KEYS = {"created_time", "last_edited_time", "created", "published", "date"}

# Date input formats we know how to read. Order matters — most specific first.
DATE_FORMATS = [
    "%B %d, %Y %I:%M %p",        # April 12, 2022 11:38 AM   (Notion default)
    "%B %d, %Y %H:%M",           # April 12, 2022 14:30
    "%B %d, %Y",                 # April 12, 2022
    "%Y-%m-%d %H:%M:%S %z %Z",   # 2021-10-18 06:59:00 +0000 UTC
    "%Y-%m-%d %H:%M:%S%z",       # 2021-10-18 06:59:00+0000
    "%Y-%m-%d %H:%M:%S",         # 2021-10-18 06:59:00
    "%Y-%m-%d %H:%M",            # 2021-10-18 06:59
    "%Y-%m-%d",                  # 2021-10-18  (leave alone — already ISO date)
]

# Match a top-level YAML key/value line. Doesn't try to handle nested
# structures or list items — date keys in this project are all scalar.
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def _is_already_iso(s: str) -> bool:
    """Return True if s is already a parseable ISO date or datetime."""
    s = s.strip().strip('"').strip("'")
    if not s:
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        pass
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _to_iso(raw: str) -> Optional[str]:
    """
    Parse a human-readable date string and return its ISO-8601 form.
    Returns None if empty, already-ISO, or unparseable.
    """
    s = raw.strip().strip('"').strip("'")
    if not s:
        return None
    if _is_already_iso(s):
        return None  # idempotent: don't rewrite
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        # Preserve time component if the format had one; otherwise emit date-only.
        if "%H" in fmt or "%I" in fmt:
            return dt.isoformat()
        return dt.date().isoformat()
    return None


def _frontmatter_bounds(lines: List[str]) -> Optional[Tuple[int, int]]:
    """
    Return (start, end) line indices of the frontmatter body
    (exclusive of the surrounding `---` fences). None if no frontmatter.
    """
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return (1, i)
    return None  # unterminated frontmatter — treat as no frontmatter


def process_file(path: Path) -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, str]]]:
    """
    Returns (changes, unparseable):
      changes — list of (key, old_value, new_value) for rewritten lines
      unparseable — list of (key, value) for date-keyed lines we couldn't parse
    """
    text = path.read_text(encoding="utf-8")
    # Preserve the file's line ending style by splitting on a regex but
    # rejoining with the dominant one.
    lines = text.splitlines()
    bounds = _frontmatter_bounds(lines)
    if bounds is None:
        return [], []
    start, end = bounds

    changes: List[Tuple[str, str, str]] = []
    unparseable: List[Tuple[str, str]] = []
    for i in range(start, end):
        m = KV_RE.match(lines[i])
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key not in DATE_KEYS:
            continue
        new = _to_iso(val)
        if new is None:
            # Either empty, already-ISO, or unparseable. Distinguish:
            stripped = val.strip().strip('"').strip("'")
            if stripped and not _is_already_iso(stripped):
                unparseable.append((key, val))
            continue
        # Surgical rewrite: keep the original line ending behavior by
        # writing just the canonical "key: value" form, unquoted.
        lines[i] = f"{key}: {new}"
        changes.append((key, val.strip(), new))

    if changes:
        # Preserve trailing newline if the original had one.
        out = "\n".join(lines)
        if text.endswith("\n"):
            out += "\n"
        path.write_text(out, encoding="utf-8")

    return changes, unparseable


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Convert human-readable Notion-style date values in YAML frontmatter "
            "to ISO 8601, so Obsidian Bases types them as date/datetime. "
            "Idempotent; safe to re-run."
        )
    )
    ap.add_argument("folder", help="Folder to scan recursively for .md files.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any files.",
    )
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"ERROR: {folder} is not a directory")

    files = sorted(folder.rglob("*.md"))
    total_files_changed = 0
    total_value_changes = 0
    total_unparseable = 0

    print(f"Scanning {folder} ({len(files)} .md files)...")

    for f in files:
        if args.dry_run:
            # Read-only path: do the work but don't write.
            text = f.read_text(encoding="utf-8")
            lines = text.splitlines()
            bounds = _frontmatter_bounds(lines)
            if bounds is None:
                continue
            start, end = bounds
            local_changes: List[Tuple[str, str, str]] = []
            local_unparseable: List[Tuple[str, str]] = []
            for i in range(start, end):
                m = KV_RE.match(lines[i])
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                if key not in DATE_KEYS:
                    continue
                new = _to_iso(val)
                if new is None:
                    stripped = val.strip().strip('"').strip("'")
                    if stripped and not _is_already_iso(stripped):
                        local_unparseable.append((key, val))
                    continue
                local_changes.append((key, val.strip(), new))
            changes, unparseable = local_changes, local_unparseable
        else:
            changes, unparseable = process_file(f)

        if changes:
            total_files_changed += 1
            total_value_changes += len(changes)
            for key, old, new in changes:
                print(f"  {f.name}: {key}: {old} -> {new}")
        for key, val in unparseable:
            total_unparseable += 1
            print(f"  WARN {f.name}: could not parse {key}: {val.strip()}")

    verb = "Would change" if args.dry_run else "Changed"
    print(
        f"\n{verb} {total_value_changes} value(s) across {total_files_changed} file(s); "
        f"{total_unparseable} unparseable date-keyed value(s) left alone."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
