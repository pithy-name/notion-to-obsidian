# notion-to-obsidian

Tools for getting Notion databases out of Notion and into Obsidian. The project started as a script to merge a Notion CSV with its per-page bodies; on **2026-04-30** it pivoted to a direct HTML → Obsidian-vault converter (no CSV detour). The older CSV-merge scripts are kept for reference but `notion_db_to_obsidian.py` (packaged as **notion-to-obsidian**) is the current path forward.

---

## Install

```bash
pip install git+https://github.com/pithy-name/notion-to-obsidian.git
```

Or for local development (editable install, from a repo checkout):

```bash
python3 -m venv .venv && .venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

Requires Python 3.9+. Dependencies (`beautifulsoup4`, `markdownify`, `pyyaml`) install automatically.

**Editable installs need pip >= 21.3.** This project is a `pyproject.toml`-only,
setuptools-based layout (no `setup.py`). Python 3.9's *bundled* pip (21.2.4)
predates [PEP 660](https://peps.python.org/pep-0660/) and fails `pip install
-e .` with `ERROR: Project ... has a 'pyproject.toml' and its build backend
is missing the 'build_editable' hook` / "editable mode currently requires a
setuptools-based build". Either upgrade pip inside the venv first (the
`--upgrade pip` step above), or drop `-e` and use a plain `pip install .` —
that always works regardless of pip version, you just lose live-reload of
local edits.

## CLI usage

Installing the package puts two console scripts on your `PATH`:

```bash
# Convert a Notion HTML export into an Obsidian vault:
notion2obsidian "My Notion Export/" -o "/path/to/output_vault/"

# One-time migration helper for vaults built by an older version of this
# tool (rewrites human-readable dates in frontmatter to ISO-8601):
notion2obsidian-fix-dates "/path/to/vault/" --dry-run
```

Full flag reference (attachment modes, `--force`, `--dry-run`, nesting behavior, etc.): [`src/notion_to_obsidian/README.md`](./src/notion_to_obsidian/README.md).

## Library usage

```python
from pathlib import Path
from notion_to_obsidian import run_conversion

summary = run_conversion(
    Path("My Notion Export/"),
    Path("/path/to/output_vault/"),
)
print(summary["total_entries"], "entries written")
```

`run_conversion` is the same function the CLI calls — see its docstring in `src/notion_to_obsidian/notion_db_to_obsidian.py` for the full parameter list (attachment mode, `--force`/`--dry-run` equivalents, etc.) and the summary dict's shape.

`run_conversion` validates its `src` path itself (the CLI's check isn't the only guard): a nonexistent path raises `FileNotFoundError`, and an existing path that isn't a directory raises `NotADirectoryError`. A valid-but-empty export directory does **not** raise (a legitimate empty conversion) — instead the returned summary dict carries `summary["no_content_found"] == True` and a warning is printed, so a library caller can detect "nothing to convert" without mistaking it for a real conversion. This accounts for orphaned-file copies too: `no_content_found` is only `True` when NOTHING was written to the output — zero database entries, zero standalone pages, AND zero orphaned (non-HTML) files present in the output. A directory holding only loose attachments or a PDF-only export section still gets those files copied by the orphan pass, so it correctly reports `no_content_found == False` — including on a re-run against the same output, where the orphan pass skips re-copying an already-identical file but the flag still reflects that the file is there.

## Current tool

### `src/notion_to_obsidian/notion_db_to_obsidian.py`

The canonical migration tool. Takes a Notion HTML export (the entries folder, the export root, or anything in between) and writes a drop-in Obsidian vault: one `.md` per **node** — every database entry, standalone page, and database index/landing page — with **type-aware** YAML frontmatter (multi-selects → YAML lists, dates → ISO-8601, checkboxes → bools, etc.), an `.obsidian/types.json` so Obsidian Bases types each property correctly (date/datetime, multitext, tags), copied attachments, and rewritten cross-entry links as `[[wikilinks]]`. **Nesting has no depth limit and no database is required:** the tool walks recursively and reproduces the export's folder structure, so a database nested under an entry (under another database, to any depth) becomes real notes at that depth — not a flattened table. Each database gets its own folder-scoped `.base` alongside a vault-wide one; the entry or page that owns a nested database is its "home" — it embeds that database's `.base` and lists its entries as `[[wikilinks]]`, and each entry gets an `↑ Part of [[home]]` backlink. `.base` files and embeds need Obsidian 1.9+; the notes and `[[links]]` work in any version. Zero network access — URLs in the source are treated as opaque strings.

- **Input:** HTML export folder. CSV is ignored (Notion's HTML carries richer property-type info).
- **Output:** `<source name> (Obsidian)/` mirroring the export's folders, with one `.md` per node, a per-database `.base` plus a vault-wide one, attachments, and a `_conversion_report.md`.
- **Safe re-runs:** by default, existing `.base`/`.md` files and attachment dirs in the output folder are preserved; new `.base`/`.md` content lands at `<name>.new` siblings, and every collision is logged in `_conversion_report.md`. Pass `--force` to overwrite (which also refreshes attachment dirs and cleans up stale `.new` siblings from prior safe-mode runs). `--dry-run` previews every filesystem op without writing anything (output folder is not created). **Re-running never deletes stale files/folders** a previous run produced (e.g. after renaming the source or upgrading the script) — `--force` overwrites matching targets but never prunes orphans, so convert into a fresh/empty output folder for a guaranteed-clean result.
- **Attachment modes:** by default, `-o` produces a self-contained output by *copying* every per-entry attachment dir (genuine attachments only — on nested exports, child-node HTML/folders are converted to notes, not copied), which roughly doubles the attachment payload on disk. Two flags avoid that doubling: `--symlink-attachments` (per-file symlinks into the source dirs — only genuine attachments, same filter as copy mode) and `--inplace-attachments` (no output-side attachment objects at all; md hrefs point back at the source via relative paths). Both filesystem-level tested; Obsidian rendering not yet verified. Both leave the output dependent on the source export staying put. See the per-script README for details.
- **Dependencies:** `beautifulsoup4`, `markdownify`, `pyyaml` (installed automatically via `pip install`).
- **Detailed README:** [`src/notion_to_obsidian/README.md`](./src/notion_to_obsidian/README.md) — includes the full **Known Issues** list.
- **Decision log:** see [`CHANGELOG.md`](./CHANGELOG.md) for context, alternatives, and trade-offs behind each significant change.
- **Roadmap:** see [`ROADMAP.md`](./ROADMAP.md).

---

## Utility

### `src/notion_to_obsidian/fix_frontmatter_dates.py` (console script: `notion2obsidian-fix-dates`)

Migration helper for vaults built by an older version of `notion_db_to_obsidian.py` (before `parse_notion_date()` was added). Walks `.md` files in a folder, finds date-keyed frontmatter values (`created_time`, `last_edited_time`, `created`, `published`, `date`), and rewrites human-readable Notion strings ("April 12, 2022 11:38 AM") to ISO-8601 (`2022-04-12T11:38:00`) so Obsidian Bases types them as datetime instead of text. Idempotent (already-ISO values are skipped). Pure stdlib, zero network. Supports `--dry-run`.

Only touches the *first* YAML frontmatter block at the top of each file — second-block content (e.g., from Obsidian Web Clipper) is left alone since Obsidian doesn't read it as properties anyway.

---

## Maintenance

This is a personal tool, shared as-is. Issues and PRs are welcome, but there's no response SLA.

## Decision tree

```
Starting from a Notion HTML export and want an Obsidian vault?
└── Use `notion2obsidian` (pip install this repo — see Install above).

Stuck with the CSV-merge approach for some reason?
├── Bodies are .html → legacy/merge_notion_db_markdown.py
├── Bodies are .md   → legacy/merge_notion_db_from_md.py
└── Want raw HTML in the Body column → legacy/merge_notion_db_html.py
```

## Privacy posture

Per project policy: **all scripts here run fully local with zero network access.** Links in source exports are preserved as opaque strings — never fetched, validated, or followed. If a future change to any script introduces network access, that's a breaking policy change and needs to be called out explicitly.
