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

All three live in `legacy/` since 2026-05-04. They do the same shape of job: take a Notion DB CSV, match each row to its per-page body file, and emit a fatter CSV with a `Body` column. They were intended for use with Obsidian's Importer plugin, which throws away property *types* on the way in. Use `notion_db_to_obsidian.py` instead unless you have a specific reason to stay in CSV-land.

### `legacy/merge_notion_db_html.py`

The original script. Outputs **raw HTML** in the Body column. Accepts any folder via CLI, auto-discovers the CSV (same strategy as `merge_notion_db_markdown.py`). Kept as the historical starting point; use `merge_notion_db_markdown.py` for new work since it converts the body to Markdown.


### `legacy/merge_notion_db_markdown.py`

Generalized version of the above. Same CSV+HTML inputs, but accepts any folder via CLI, auto-discovers the CSV, handles Notion's filename truncation/punctuation-stripping with prefix matching, and runs the body through `markdownify` so the Body column is **simplified Markdown** instead of raw HTML. Requires `markdownify`.

### `legacy/merge_notion_db_from_md.py`

For the case where the Notion export gave you `.md` files instead of `.html`. No conversion needed, no external dependencies. Strips YAML frontmatter from each `.md` by default (since the same fields are already in the CSV); pass `--keep-frontmatter` to retain it. Handles both Notion-style filenames (`Title abc123.md`) and clean ones (`Title.md`).


---

## Utility

### `Notion Database to Obsidian/fix_frontmatter_dates.py`

Migration helper for vaults built by an older version of `notion_db_to_obsidian.py` (before `parse_notion_date()` was added). Walks `.md` files in a folder, finds date-keyed frontmatter values (`created_time`, `last_edited_time`, `created`, `published`, `date`), and rewrites human-readable Notion strings ("April 12, 2022 11:38 AM") to ISO-8601 (`2022-04-12T11:38:00`) so Obsidian Bases types them as datetime instead of text. Idempotent (already-ISO values are skipped). Pure stdlib, zero network. Supports `--dry-run`.

Only touches the *first* YAML frontmatter block at the top of each file — second-block content (e.g., from Obsidian Web Clipper) is left alone since Obsidian doesn't read it as properties anyway.


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
