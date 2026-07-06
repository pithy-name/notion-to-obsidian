#!/usr/bin/env python3
"""
Build a synthetic, PII-free Notion HTML export for tests.

Mirrors Notion's on-disk export shape (entry/index HTML + per-node attachment
folders named "<Title> <32-hex-id>") and exercises:
  - arbitrary nesting: a top-level DB → nested DB → deeper DB (depths 0/2/4),
  - multiple children at each level,
  - a standalone page with no children,
  - a standalone PAGE that owns a database,
  - a <table> inside an entry body (must stay a Markdown table, NOT be treated
    as a nested database).

IDs are deterministic (md5 of the title) so fixtures are reproducible.

    from synthetic_export import build
    info = build(Path(tmpdir))   # writes the export; returns expected-structure facts
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List


def hex_id(name: str) -> str:
    """Deterministic 32-char hex id for a node (md5 of its title)."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def uuid_of(name: str) -> str:
    h = hex_id(name)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def folder(name: str) -> str:
    """Notion-style "<Title> <hex>" folder/file stem."""
    return f"{name} {hex_id(name)}"


def _entry_html(title: str, props: List[tuple], body: str = "") -> str:
    rows = "".join(
        f'<tr class="property-row property-row-{ptype}">'
        f'<th><span class="icon">📄</span>{pname}</th><td>{value}</td></tr>'
        for pname, ptype, value in props
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        f'<article id="{uuid_of(title)}" class="page sans">'
        f'<header><h1 class="page-title">{title}</h1>'
        f'<table class="properties"><tbody>{rows}</tbody></table></header>'
        f'<div class="page-body">{body}</div></article></body></html>'
    )


def _page_html(title: str, body: str = "") -> str:
    """Standalone page: an article with NO properties table and NO collection."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        f'<article id="{uuid_of(title)}" class="page sans">'
        f'<h1 class="page-title">{title}</h1>'
        f'<div class="page-body">{body}</div></article></body></html>'
    )


def _index_html(title: str) -> str:
    """A database's index/parent page: has collection-content, no properties."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        f'<article id="{uuid_of(title)}" class="page sans">'
        f'<h1 class="page-title">{title}</h1>'
        '<div class="page-body"><table class="collection-content"><tbody></tbody>'
        '</table></div></article></body></html>'
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _db(parent_dir: Path, name: str, entries: List[tuple]) -> Path:
    """
    Write a database under parent_dir: an index page "<name> <hex>.html" plus an
    entries folder "<name> <hex>/" containing one HTML per entry. Returns the
    entries folder so callers can nest deeper DBs inside an entry's own folder.
    `entries` is a list of (title, props, body).
    """
    _write(parent_dir / f"{folder(name)}.html", _index_html(name))
    edir = parent_dir / folder(name)
    edir.mkdir(parents=True, exist_ok=True)
    for title, props, body in entries:
        _write(edir / f"{folder(title)}.html", _entry_html(title, props, body))
    return edir


def build(root: Path) -> Dict:
    """Create the synthetic export under `root`; return expected-structure facts."""
    root.mkdir(parents=True, exist_ok=True)

    # An entry body containing a real <table> block — the conversion must keep
    # this as a Markdown table and must NOT mistake it for a nested database.
    cat_body = (
        "<p>About cats.</p>"
        "<table><thead><tr><th>Trait</th><th>Value</th></tr></thead>"
        "<tbody><tr><td>Sound</td><td>Meow</td></tr></tbody></table>"
    )

    # Top-level database "Animals" with entries Cat, Dog.
    animals_dir = _db(root, "Animals", [
        ("Cat", [("Species", "select", "Feline"), ("Legs", "number", "4")], cat_body),
        ("Dog", [("Species", "select", "Canine"), ("Legs", "number", "4")], ""),
    ])

    # Cat owns nested DB "Breeds" (inside Cat's attachment folder).
    cat_dir = animals_dir / folder("Cat")
    breeds_dir = _db(cat_dir, "Breeds", [
        ("Tabby", [("Pattern", "select", "striped")], ""),
        ("Siamese", [("Pattern", "select", "pointed")], ""),
    ])

    # Tabby owns deeper DB "Photos" (depth 4).
    tabby_dir = breeds_dir / folder("Tabby")
    _db(tabby_dir, "Photos", [
        ("Photo1", [("Year", "number", "2020")], ""),
        ("Photo2", [("Year", "number", "2021")], ""),
    ])

    # Standalone page with no children.
    _write(root / f"{folder('About')}.html", _page_html("About", "<p>Just a page.</p>"))

    # Standalone PAGE that owns a database "Steps".
    _write(root / f"{folder('Field Guide')}.html", _page_html("Field Guide", "<p>How to.</p>"))
    guide_dir = root / folder("Field Guide")
    _db(guide_dir, "Steps", [
        ("Step One", [("Order", "number", "1")], ""),
        ("Step Two", [("Order", "number", "2")], ""),
    ])

    return {
        "root": str(root),
        # database name -> list of its entry titles
        "databases": {
            "Animals": ["Cat", "Dog"],
            "Breeds": ["Tabby", "Siamese"],
            "Photos": ["Photo1", "Photo2"],
            "Steps": ["Step One", "Step Two"],
        },
        # ownership: child DB -> owning node title
        "owned_by": {"Breeds": "Cat", "Photos": "Tabby", "Steps": "Field Guide"},
        "standalone_pages": ["About", "Field Guide"],
        # the deepest owner chain (illustrates arbitrary depth)
        "deep_chain": ["Cat", "Breeds", "Tabby", "Photos"],
        # entry whose body has a <table> that must stay a Markdown table
        "body_table_entry": "Cat",
    }


if __name__ == "__main__":
    import sys
    import tempfile
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    info = build(out)
    print("built synthetic export at:", out)
    for p in sorted(out.rglob("*")):
        rel = p.relative_to(out)
        print(("  [d] " if p.is_dir() else "  [f] ") + str(rel))
    print("\nfacts:", info)
