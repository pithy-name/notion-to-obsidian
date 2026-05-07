# Notion Database → Obsidian Converter

Converts a Notion database HTML export directly into an Obsidian-ready
folder of `.md` files with type-aware YAML frontmatter, plus a starter
`.base` file. **No CSV needed or used.** **Zero network access.**

## Why this exists

The scripts in the parent folder (`merge_notion_db_*.py`) merged the
Notion CSV with the per-page HTML/MD body into a single CSV with a
`Body` column, intended to be imported into Obsidian via the Obsidian
Importer plugin. That round-trip drops type information: tags become
strings instead of YAML lists, dates become quoted strings instead of
date types, etc.

This script skips the CSV stage entirely. Notion's HTML export already
encodes each property's *type* (in the `<tr>` class as
`property-row-{type}`), and the script uses that to write properly
typed YAML — multi-selects as lists, dates as ISO-8601, numbers
unquoted, etc. The output folder is a drop-in for a fresh Obsidian
vault.

## Setup

```bash
pip install beautifulsoup4 markdownify pyyaml
```

Python 3.8+.

## Usage

Point it at the **export root**, an **entries folder**, or any folder
containing entry `.html` files at any depth — the script walks
recursively, classifies every `.html` as a database entry, parent
page, or standalone page, and processes every database it finds:

```bash
# Entries folder directly:
python3 notion_db_to_obsidian.py \
  "My Notion Export/My Database abc123/"

# Or the export root (handles multiple databases in one run):
python3 notion_db_to_obsidian.py "My Notion Export/"
```

Default output: a sibling folder named `<source name> (Obsidian)`.
Override with `-o`:

```bash
python3 notion_db_to_obsidian.py \
  "My Notion Export/My Database abc123/" \
  -o "/path/to/output_vault_folder/"
```

### What `-o` does to attachments (default behavior)

By default, `-o` writes a **fully self-contained** output folder. Every
per-entry attachment directory in the source export (PDFs, images,
audio, video, etc.) is copied into the output via `shutil.copytree`,
and md hrefs are rewritten to point at the new copies. The copy step
means:

- The output folder works on its own, even if you later delete the
  source export.
- Disk usage roughly doubles for the attachment payload — if your
  source export has 5 GB of PDFs, you'll have ~10 GB on disk while
  both folders coexist.

If disk space is tight and you don't want attachments stored in two
places, use one of the attachment-mode flags below. **Both have been
exercised at the filesystem level only** — symlinks are created with
correct targets, in-place mode rewrites md hrefs to correct relative
paths, and `--force` correctly switches between modes (symlink →
copy, copy → symlink). **Neither has been verified inside Obsidian
yet** — i.e., we have not yet confirmed that Obsidian on macOS
renders embedded PDFs/images through a symlinked attachment dir or
through a relative-path href that crosses out of the vault folder.
Spot-check one entry in Obsidian before relying on either mode.

### Attachment handling: copy, symlink, or in-place

The script accepts two mutually-exclusive flags that change how each
entry's attachment directory is materialized in the output:

| Mode | Disk usage | Output filesystem objects | Source dependency | Status |
|------|-----------|---------------------------|-------------------|--------|
| `copy` (default) | ~2× | Real attachment dirs | None — output is self-contained | Tested in production |
| `--symlink-attachments` | ~1× | Symlinks pointing at source | Source dir must stay where it is | Filesystem-level OK; Obsidian render UNVERIFIED |
| `--inplace-attachments` | ~1× | None for attachments | Source dir must stay at the same relative path from the output | Filesystem-level OK; Obsidian render UNVERIFIED |

**`--symlink-attachments`** — Each entry's attachment directory is
created in the output as a symlink to the source dir's *absolute*
path. Md hrefs still reference `<NewDB>/<Entry>/file.pdf` exactly as
they would in copy mode; the OS resolves the symlink when Obsidian
opens an embedded file. If you later move or delete the source export,
all symlinks (and any md links into them) break.

When you eventually want to consolidate (e.g. retire the source export
once you trust the new vault), replace each symlink with a real copy
via `rsync -aL <symlink> <symlink>` (the `-L` flag follows symlinks
during the copy) or `cp -RL`, then delete the source. That collapses
the two-location footprint without rewriting any md links.

**`--inplace-attachments`** — No output-side directories or symlinks
are created for attachments at all. Md hrefs are rewritten to point at
the source attachment dir via a relative path computed from the new md
file's parent directory. The output is *zero filesystem objects* for
attachments — only md and `.base` files. If you later move the source
export, every md link breaks; there's no symlink layer to fix in one
place. Use this when the output is a throwaway evaluation vault and
you're certain you don't want any attachment artifacts in it, even
empty directories.

Either flag is the right tool when you want to evaluate the new vault
without committing to a full second copy of your attachments. Pick
`--symlink-attachments` if you may eventually want to consolidate;
pick `--inplace-attachments` if the output is purely temporary and
you want the lightest possible footprint. Both flags have been
exercised end-to-end against a synthetic fixture (the symlink target
is correct, the relative path resolves to the real source file, and
`--force` correctly switches modes). They have **not** yet been
opened in Obsidian, so confirm one entry's PDF/image actually renders
in Obsidian's UI before relying on either mode at scale.

Other flags:
- `--db-name "Display Name"` — overrides the auto-derived database
  name (used in the folder name and the `.base` folder filter). Only
  honored when exactly one database is found; ignored with a warning
  otherwise.
- `--no-base` — skip generating the starter `.base` file(s).
- `--no-types` — skip generating/updating
  `<output>/.obsidian/types.json`. By default the script writes Obsidian
  property-type declarations for every discovered Notion property, so
  date columns surface as `datetime`, multi-selects as `multitext` (or
  `tags` when the key is named `tags`), etc. Without this file, Obsidian
  Bases falls back to value-heuristic detection, which is unreliable for
  ISO-8601 datetime values and silently makes them act like text. The
  generated/updated file never clobbers existing entries — only missing
  keys are added — so it's safe to re-run on a vault you've already
  customized.
- `--force` — overwrite existing `.base` and `.md` files in the output
  folder. **Default behavior is safe:** if a target file already
  exists, the new content is written next to it as `<original>.new`
  (e.g. `MyDB.base` is preserved and the would-be replacement lands at
  `MyDB.base.new`). Every collision is recorded in
  `_conversion_report.md` so re-runs can never silently destroy a
  hand-customized `.base` or hand-edited `.md`.
- `--dry-run` — walk the source, parse every entry, build the schema,
  and print every filesystem operation that *would* happen if you ran
  without `--dry-run` (counts of databases/entries, schema with drift
  warnings, planned filenames including any collision suffixes,
  planned attachment ops under the chosen attachment mode, planned
  `.obsidian/types.json` key additions). The output folder is **not
  created**; nothing on disk changes. Combine freely with
  `--symlink-attachments`, `--inplace-attachments`, `--force`,
  `--db-name`, `--no-base`, `--no-types` to preview exactly what each
  combination would do. Useful for sanity-checking before committing
  to a big run.

## Re-running into an existing output folder

When the output folder already contains files from a previous run (or
from a previous CSV-import workflow), the script defaults to **safe
mode**:

- Existing `.base` and `.md` files are left untouched.
- New content is written next to them with a `.new` suffix appended to
  the full filename (`MyDB.base` → `MyDB.base.new`, `Entry.md` →
  `Entry.md.new`). Obsidian ignores `.new` files, so they don't
  pollute the vault — diff them against the originals and merge by
  hand.
- Every collision is logged in `_conversion_report.md` under
  **"Skipped overwrites"**.
- The terminal output prints a `PRESERVED N existing file(s)` summary
  so it's hard to miss.

Pass `--force` if you actually want the script to overwrite. In that
mode the same collisions are logged under **"Overwrites (--force)"**.

Attachment directories follow the same safe-by-default contract:

- Default mode: an existing attachment dir at the target path is
  preserved (any hand-added files in it stay), and the skip is logged
  under **"Skipped overwrites"**. The source attachments from this
  run are not copied — if you want them, re-run with `--force`.
- `--force`: the existing attachment dir is removed and replaced with
  a fresh copy from the source export. Any hand-added files inside
  the existing dir are lost. The refresh is logged under
  **"Overwrites (--force)"**.

A `--force` run also cleans up stale `.new` siblings left behind by a
prior safe-mode run: when the script overwrites `MyDB.base`, it also
deletes `MyDB.base.new` if present (and same for `<entry>.md.new`).
Only the exact pair gets cleaned up — unrelated `.new` files are
never touched. Each cleanup is logged.

## What you get

```
<source name> (Obsidian)/
  .obsidian/
    types.json                 # Obsidian property-type declarations (datetime,
                               # tags, multitext, etc.) — vault-wide, merged
                               # across all discovered databases. See --no-types.
  <DB Name>.base               # folder-scoped table view, sibling to <DB Name>/
  _conversion_report.md        # schema, drift warnings, per-entry warnings, skipped pages
  <DB Name>/                   # one folder per discovered database
    Entry Title.md             # one per Notion entry
    Entry Title/               # that entry's attachments (PDFs etc.), if any
      file.pdf
    Another Entry.md
    …
  <Another DB Name>.base       # if multiple databases were discovered
  <Another DB Name>/
    …
```

Each `.md` has YAML frontmatter like:

```yaml
---
notion_uuid: af5b29a2-4d10-45ef-8f7e-bcd1f757fd47
tags:
  - communication
  - skills
publisher: Ministry of Testing
publish_year: '2020'
---
```

Plus the page body converted to Markdown.

**Note on `tags`:** when a Notion property maps to the `tags` YAML key,
each value is sanitized for Obsidian's tag syntax — whitespace becomes
hyphens, parens/commas/dots are stripped (e.g., `"test plan"` →
`"test-plan"`). This is so Obsidian renders them as real tag pills
instead of struck-through text.

## Importing to Obsidian

1. Drop the output folder into an Obsidian vault (or open it as a new
   vault).
2. The `.base` file works out of the box — open it to see the table
   view of all entries. Or right-click the folder → **New base** to
   build your own from scratch.
3. Sort, filter, add views via Obsidian's UI as you like.

## Privacy & network

This script makes **zero** network calls. URLs in the export are
treated as opaque strings — they're never fetched, validated, or
followed. Local attachments (PDFs etc.) that Notion already downloaded
into per-entry sibling folders are copied to the output folder and
links are rewritten to point to the new location. External URLs in the
body (like third-party-hosted images) are preserved verbatim as
Markdown image/link references; whether they still load when you open
the note is up to those external servers.

## Nested databases

When Notion exports a database whose entries contain inline sub-databases
(e.g., a test-report entry that embeds a "Discoveries" tracking table),
the sub-database entries live in a depth-2 subfolder:

```
src/
  ParentEntry UUID.html          ← top-level DB entry
  ParentEntry UUID/              ← attachment folder (depth 1)
    NestedDB UUID/               ← nested DB entries folder (depth 2)
      row1.html
      row2.html
```

The script auto-detects these and **renders each nested database as an
inline GFM table** appended to the parent entry's `.md` body instead of
producing a separate output folder. Table columns are:

| Topic | \<Notion property columns\> | Notes |
|---|---|---|
| Entry title | One column per Notion property | Plain-text body of the nested entry |

**Depth rules:**
- Depth 0 → top-level DB (processed normally)
- Depth 2 → nested DB → rendered as inline table in parent entry
- Depth ≥ 3 → fatal error: the script prints all offending folders and exits. Only one level of nesting is supported.

If Notion also embedded a static snapshot of the nested DB as an inline
`<table>` in the parent HTML body, that table is **replaced** (stripped
before body conversion) so the output does not contain duplicates.

**Known limitation:** the generated table is always appended at the end
of the parent entry body. The original Notion inline table may have been
mid-document (e.g., under a `## Bugs` heading). Position-preserving
injection is a planned future improvement.

## Known limitations

- **Text-typed properties stay as text.** If your Notion `Publish Year`
  was a `text` property (not a `number`), it'll be a quoted string in
  YAML. That's faithful to the source; coerce it manually in Obsidian
  if you want number sorting.
- **Property types not yet stress-tested:** number, checkbox, person,
  file, formula, rollup, relation. The code paths exist and are
  defensible, but the test fixture only exercises
  `select`, `multi_select`, and `text`. `date`/`created_time`/
  `last_edited_time` were exercised on 2026-05-04 and 2026-05-06
  (the `parse_notion_date()` path produces correct ISO-8601 for month-
  name formats and MM/DD/YYYY; `@`-prefixed date mentions are stripped
  automatically). Real exports of the other types will probably surface
  edge cases — check `_conversion_report.md` for drift warnings.
- **Obsidian Bases & datetime detection:** Bases types properties by
  the value-types its YAML parser returns, and the parser doesn't
  reliably auto-detect ISO-8601 datetime strings as date objects —
  it leaves them as plain strings, so a column ends up "text" even
  though the underlying values are perfectly formatted. The fix is
  the explicit `.obsidian/types.json` declaration this script writes
  by default. If you opt out (`--no-types`) and find a date column
  showing as text in Bases, either re-run without `--no-types`, set
  the type via Obsidian's UI (right-click a property → Set type →
  Date & time), or hand-edit `.obsidian/types.json`. There's a
  helper script for fixing already-typed-as-text frontmatter values
  in older vaults: `fix_frontmatter_dates.py` (rewrites human-
  readable Notion dates to ISO 8601 in place; idempotent).
- **Notion blocks with no clean Markdown equivalent** (column layouts,
  synced blocks, complex embeds) get best-effort flattened by
  markdownify. Bookmark cards and local-file figures get a custom
  pre-pass for cleaner output; if another block type comes out
  garbled, look at the original `.html` and we can add a similar
  pre-pass.
- **Parent pages and standalone pages aren't converted yet.** Scope
  is database-only. Parent pages (those with `class="collection-content"`)
  and standalone pages are detected and listed in
  `_conversion_report.md` but not written to `.md`.

---

- **Decision log:** see [`CHANGELOG.md`](../CHANGELOG.md) for context, alternatives, and trade-offs behind each significant change.
