# Recover Notion Databases — Scripts

Tools for getting Notion databases out of Notion and into Obsidian. The project started as a script to merge a Notion CSV with its per-page bodies; on **2026-04-30** it pivoted to a direct HTML → Obsidian-vault converter (no CSV detour). The older CSV-merge scripts are kept for reference but `notion_db_to_obsidian.py` is the current path forward.

---

## Current tool

### `Notion Database to Obsidian/notion_db_to_obsidian.py`

The canonical migration tool. Takes a Notion HTML export (the entries folder, the export root, or anything in between) and writes a drop-in Obsidian vault: one `.md` per entry with **type-aware** YAML frontmatter (multi-selects → YAML lists, dates → ISO-8601, checkboxes → bools, etc.), a sibling `.base` file scoped to the database folder, an `.obsidian/types.json` so Obsidian Bases types each property correctly (date/datetime, multitext, tags), copied attachment subfolders, and rewritten cross-entry links as `[[wikilinks]]`. Walks recursively, so it handles multiple databases in one pass. **Nested databases** (depth-2 sub-folders under a top-level entry) are rendered as inline GFM tables appended to the parent entry body — columns: Topic, Notion properties, Notes (body text). Depth ≥ 3 nesting is a fatal error. Zero network access — URLs in the source are treated as opaque strings.

- **Input:** HTML export folder. CSV is ignored (Notion's HTML carries richer property-type info).
- **Output:** `<source name> (Obsidian)/` with `.md` entries, `.base` view, attachments, and a `_conversion_report.md`.
- **Safe re-runs:** by default, existing `.base`/`.md` files and attachment dirs in the output folder are preserved; new `.base`/`.md` content lands at `<name>.new` siblings, and every collision is logged in `_conversion_report.md`. Pass `--force` to overwrite (which also refreshes attachment dirs and cleans up stale `.new` siblings from prior safe-mode runs). `--dry-run` previews every filesystem op without writing anything (output folder is not created).
- **Attachment modes:** by default, `-o` produces a self-contained output by *copying* every per-entry attachment dir, which roughly doubles disk usage. Two new flags avoid that doubling: `--symlink-attachments` (symlinks the source dirs into the output) and `--inplace-attachments` (no output-side attachment objects at all; md hrefs point back at the source via relative paths). Both filesystem-level tested 2026-05-05; Obsidian rendering not yet verified. Both leave the output dependent on the source export staying put. See the per-script README for details.
- **Dependencies:** `beautifulsoup4`, `markdownify`, `pyyaml`.
- **Detailed README:** [`Notion Database to Obsidian/README.md`](./Notion%20Database%20to%20Obsidian/README.md).
- **Decision log:** see [`CHANGELOG.md`](./CHANGELOG.md) for context, alternatives, and trade-offs behind each significant change.

---

## Legacy CSV-merge scripts (reference only) — `legacy/`

Three older scripts that merge a Notion CSV with per-page body files into a fatter CSV with a `Body` column. Kept for reference; `notion_db_to_obsidian.py` is the current path. See [`legacy/README.md`](./legacy/README.md) for per-script details.

---

## Decision tree

```
Starting from a Notion HTML export and want an Obsidian vault?
└── Use Notion Database to Obsidian/notion_db_to_obsidian.py.

Stuck with the CSV-merge approach for some reason?
├── Bodies are .html → legacy/merge_notion_db_markdown.py
├── Bodies are .md   → legacy/merge_notion_db_from_md.py
└── Want raw HTML in the Body column → legacy/merge_notion_db_html.py
```

## Privacy posture

Per project policy: **all scripts here run fully local with zero network access.** Links in source exports are preserved as opaque strings — never fetched, validated, or followed. If a future change to any script introduces network access, that's a breaking policy change and needs to be called out explicitly.
