# Recover Notion Databases — Scripts

Tools for getting Notion databases out of Notion and into Obsidian. The project started as a script to merge a Notion CSV with its per-page bodies; on **2026-04-30** it pivoted to a direct HTML → Obsidian-vault converter (no CSV detour). The older CSV-merge scripts are kept for reference but `notion_db_to_obsidian.py` is the current path forward.

---

## Current tool

### `Notion Database to Obsidian/notion_db_to_obsidian.py`

The canonical migration tool. Takes a Notion HTML export (the entries folder, the export root, or anything in between) and writes a drop-in Obsidian vault: one `.md` per **node** — every database entry, standalone page, and database index/landing page — with **type-aware** YAML frontmatter (multi-selects → YAML lists, dates → ISO-8601, checkboxes → bools, etc.), an `.obsidian/types.json` so Obsidian Bases types each property correctly (date/datetime, multitext, tags), copied attachments, and rewritten cross-entry links as `[[wikilinks]]`. **Nesting has no depth limit and no database is required:** the tool walks recursively and reproduces the export's folder structure, so a database nested under an entry (under another database, to any depth) becomes real notes at that depth — not a flattened table. Each database gets its own folder-scoped `.base` alongside a vault-wide one; the entry or page that owns a nested database is its "home" — it embeds that database's `.base` and lists its entries as `[[wikilinks]]`, and each entry gets an `↑ Part of [[home]]` backlink. `.base` files and embeds need Obsidian 1.9+; the notes and `[[links]]` work in any version. Zero network access — URLs in the source are treated as opaque strings.

- **Input:** HTML export folder. CSV is ignored (Notion's HTML carries richer property-type info).
- **Output:** `<source name> (Obsidian)/` mirroring the export's folders, with one `.md` per node, a per-database `.base` plus a vault-wide one, attachments, and a `_conversion_report.md`.
- **Safe re-runs:** by default, existing `.base`/`.md` files and attachment dirs in the output folder are preserved; new `.base`/`.md` content lands at `<name>.new` siblings, and every collision is logged in `_conversion_report.md`. Pass `--force` to overwrite (which also refreshes attachment dirs and cleans up stale `.new` siblings from prior safe-mode runs). `--dry-run` previews every filesystem op without writing anything (output folder is not created).
- **Attachment modes:** by default, `-o` produces a self-contained output by *copying* every per-entry attachment dir (genuine attachments only — on nested exports, child-node HTML/folders are converted to notes, not copied), which roughly doubles the attachment payload on disk. Two new flags avoid that doubling: `--symlink-attachments` (symlinks the source dirs into the output) and `--inplace-attachments` (no output-side attachment objects at all; md hrefs point back at the source via relative paths). Both filesystem-level tested 2026-05-05; Obsidian rendering not yet verified. Both leave the output dependent on the source export staying put. See the per-script README for details.
- **Dependencies:** `beautifulsoup4`, `markdownify`, `pyyaml`.
- **Detailed README:** [`Notion Database to Obsidian/README.md`](./Notion%20Database%20to%20Obsidian/README.md).
- **Decision log:** see [`CHANGELOG.md`](./CHANGELOG.md) for context, alternatives, and trade-offs behind each significant change.

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
