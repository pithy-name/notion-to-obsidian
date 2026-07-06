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

Installed as a package (see the repo root [`README.md`](../../README.md) for
the `pip install` command) — this gets you the `notion2obsidian` /
`notion2obsidian-fix-dates` console scripts and an importable `notion_to_obsidian`
package. If you'd rather run this file directly without installing anything:

```bash
pip install beautifulsoup4 markdownify pyyaml
python3 notion_db_to_obsidian.py ...
```

Python 3.9+.

## Usage

Point it at the **export root**, an **entries folder**, or any folder
containing entry `.html` files at any depth — the script walks
recursively, classifies every `.html` as a database entry, parent
page, or standalone page, and processes every database it finds:

```bash
# Entries folder directly:
notion2obsidian "My Notion Export/My Database abc123/"

# Or the export root (handles multiple databases in one run):
notion2obsidian "My Notion Export/"
```

Default output: a sibling folder named `<source name> (Obsidian)`.
Override with `-o`:

```bash
notion2obsidian \
  "My Notion Export/My Database abc123/" \
  -o "/path/to/output_vault_folder/"
```

(Not installed the package? Substitute
`python3 notion_db_to_obsidian.py` for `notion2obsidian` in any command
on this page — same flags, same behavior.)

### What `-o` does to attachments (default behavior)

By default, `-o` writes a **fully self-contained** output folder. Every
per-entry attachment directory in the source export (PDFs, images,
audio, video, etc.) is copied into the output via `shutil.copytree`,
and md hrefs are rewritten to point at the new copies. On a **nested**
export an entry's folder also contains its child nodes (their
`<Child> <hex>.html` files and folders); the copy **filters those out**
and copies only genuine attachments, so child nodes appear once — as
their own converted note — never also as a raw duplicate. The copy step
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
| `copy` (default) | ~2× (attachments only) | Real attachment dirs (child-node HTML/folders filtered out) | None — output is self-contained | Tested in production |
| `--symlink-attachments` | ~1× | Real dir of per-file symlinks pointing at source (child-node HTML/folders filtered out, same as copy mode) | Source dir must stay where it is | Filesystem-level OK; Obsidian render UNVERIFIED |
| `--inplace-attachments` | ~1× | None for attachments | Source dir must stay at the same relative path from the output | Filesystem-level OK; Obsidian render UNVERIFIED |

**`--symlink-attachments`** — Each entry's attachment directory is
created in the output as a REAL directory containing one symlink per
genuine attachment file, pointing at the source file's absolute path —
the same child-node filter copy mode uses decides what's genuine, so a
Notion node's own `.html`/hex-folder is never symlinked (an earlier
version symlinked the whole source directory, which exposed that
content). Md hrefs still reference `<NewDB>/<Entry>/file.pdf` exactly
as they would in copy mode; the OS resolves each per-file symlink when
Obsidian opens an embedded file. If you later move or delete the
source export, all symlinks (and any md links into them) break.

When you eventually want to consolidate (e.g. retire the source export
once you trust the new vault), resolve each attachment dir's per-file
symlinks to real copies in place — e.g. per entry dir:
`cp -RL "<NewDB>/<Entry>" "<NewDB>/<Entry>.real" && rm -rf "<NewDB>/<Entry>" && mv "<NewDB>/<Entry>.real" "<NewDB>/<Entry>"`
(`-L` follows symlinks during the copy) — then delete the source. That
collapses the two-location footprint without rewriting any md links.

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
  **"Overwrites (--force)"**. Exception: if the source folder holds only
  child-node content (no genuine attachment survives the copy filter),
  there is nothing to recopy, so the existing dir is **kept** rather than
  deleted (logged as "KEPT").

A `--force` run also cleans up stale `.new` siblings left behind by a
prior safe-mode run: when the script overwrites `MyDB.base`, it also
deletes `MyDB.base.new` if present (and same for `<entry>.md.new`).
Only the exact pair gets cleaned up — unrelated `.new` files are
never touched. Each cleanup is logged.

**Re-running never removes stale files or folders.** The script only
writes (or, with `--force`, overwrites) the notes, attachments, and
`.base` files the *current* run produces — it never deletes things a
*previous* run made that this one doesn't. So if you rename or
restructure the source export, delete an entry, or upgrade the script
to a version that names things differently, the old output is left
behind alongside the new (you can end up with both an old and a new
copy of a renamed note or folder). `--force` does not fix this; it
overwrites matching targets but never prunes orphans. For a guaranteed-
clean result, convert into a **fresh, empty output folder**, or delete
the old output folder first.

## What you get

The output mirrors the export's folder structure. One `.md` per node, a
folder-scoped `.base` per database plus a vault-wide one, and attachments
copied alongside the note they belong to:

```
<source name> (Obsidian)/
  .obsidian/
    types.json                 # Obsidian property-type declarations (datetime,
                               # tags, multitext, etc.) — vault-wide, merged
                               # across all discovered databases. See --no-types.
  <source name>.base           # vault-wide table view (every note)
  _conversion_report.md        # schema, drift warnings, per-node warnings, skipped pages
  Animals.md                   # a database's landing/home note (embeds Animals.base, lists entries)
  Animals.base                 # folder-scoped table view, sibling to Animals/
  Animals/                     # one folder per database, at its real depth
    Cat.md                     # one note per entry
    Cat/                       # Cat's attachments AND anything Cat owns:
      photo.png                #   - a genuine attachment
      Breeds.base              #   - Cat owns a nested "Breeds" database…
      Breeds/
        Tabby.md               #   …whose entries are real notes, at any depth
    Dog.md
```

A standalone page (or the export's own root/landing page) becomes a note the
same way, at the spot it occupies in the tree.

Each `.md` has YAML frontmatter like:

```yaml
---
notion_uuid: <notion-uuid>
tags:
  - <tag-1>
  - <tag-2>
publisher: <publisher>
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

## Nesting (any depth)

There is **no depth limit** and **no requirement that a database exist**. The
tool converts a single page, a flat database, or databases nested inside entries
inside databases to any depth. It walks the export recursively and reproduces
the folder structure in the vault, so every node becomes a real note:

- **Database entries** → one note each, at the depth they appear.
- **Standalone pages** → one note each.
- **Database index / landing pages** (Notion's `collection-content` pages,
  including the export's own root page) → one note each.

When a node owns a database (a database folder sits inside that node's folder),
that node is the database's **home**: its note embeds the database's `.base`
(`![[<DB>.base]]`) and lists the entries as `[[wikilinks]]`, and each entry gets
an `↑ Part of [[home]]` backlink. Wikilinks are name-based, so they survive moves
within the vault; filenames are made vault-unique (a short Notion id is appended
on collision). A note's filename comes from Notion's on-disk file name (the
title as Notion sanitized it for the filesystem, e.g. with square brackets
dropped), so it can differ slightly from the page title — the full title is still
shown as the note's `# H1`. Using the on-disk name keeps each note, its
attachments, and its children in one folder.

If Notion embedded a static snapshot of an owned database as an inline `<table>`
in the owner's HTML body, that table is stripped before conversion so the output
doesn't duplicate the generated base + links.

`.base` files and `![[…]]` embeds require Obsidian 1.9+; the notes and
`[[wikilinks]]` work in any version.

## Known limitations

Bug IDs (`B1`, `B3`, …) below refer to the fuller writeup in the repo's
local (gitignored) `TODO.md` bug-tracking table — not committed, since it's
a working task list, but the summary here is the durable public record.

- **Strikethrough — reverify against a real export.** The code-level claim
  that used to be here ("`html_to_md` is markdownify with no strikethrough
  config") is **disproven**: the pinned `markdownify` (1.2.2+) already
  aliases both `<s>` and `<del>` to `~~text~~` — verified directly
  (`markdownify('<s>x</s>')` and `markdownify('<del>x</del>')` both →
  `'~~x~~'`). If strikethrough still comes through unstyled on a real
  export, the more likely cause is Notion emitting
  `<span style="text-decoration:line-through">` rather than `<s>`/`<del>` —
  unverifiable here without a real export sample.
- **A landing/root page's own cover image isn't rewritten** to its copied
  vault path (regular in-body entry images rewrite fine). Attempted and
  blocked: there's no real Notion export sample available in this repo to
  confirm where the cover-image markup actually lives (`parse_entry` only
  reads `<div class="page-body">`), so shipping a fix verified only
  against invented markup risked doing nothing — or the wrong thing —
  against a real export. See the comment at `parse_entry` in
  `notion_db_to_obsidian.py`.
- **A directory that's ambiguously shaped like a Notion node's attachment
  folder gets filtered, and there's no content-based way to tell it apart
  from unrelated user content.** `_attachment_copy_ignore`'s two
  directory-filtering rules (a sibling `<name>.html`, or a folder holding a
  hex-named `.html`) can't distinguish a genuine node folder from a
  same-shaped coincidence without reading file contents — out of scope by
  design. Every such filter now emits an explicit `WARN (B3, known
  limitation): ...` line naming the path into `_conversion_report.md`, so
  the loss is surfaced rather than silent, but the underlying ambiguity is
  not eliminated.
- **`--symlink-attachments` and `--inplace-attachments` remain
  experimental.** Both are filesystem-level tested (symlinks/relative
  hrefs point at the right targets) but **Obsidian's actual rendering is
  not yet verified** — spot-check one entry in Obsidian before relying on
  either mode for anything important.
- **Rich-text styling is largely stripped.** Indentation and colorized
  text get flattened by `markdownify`; no current workaround.
- **URLs in output are live** (planned: defang). Converted bodies keep
  clickable URLs; a future option will break/defang them so they don't
  resolve on accidental click.
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
  in older vaults: `notion2obsidian-fix-dates` (rewrites human-
  readable Notion dates to ISO 8601 in place; idempotent).
- **A stale synthetic `<Prop> (end)` entry can permanently mistype a same-
  named real property across separate runs (documented known issue,
  restored 2026-07-06 after I2 red-team; see also H2).** `.obsidian/types.json`
  never clobbers an existing entry — only missing keys are added, so a
  manual Obsidian-UI type override always survives a re-run of the
  converter onto the same output vault. H2 (round-3) had instead made a
  real property's type force-overwrite whatever was already in
  `types.json`, which fixed one narrow cross-run collision but broke that
  guarantee for every property on every re-run (a genuine user
  customization got silently reverted every time). I2 (round-4) reverted
  the force-overwrite and restored the never-clobber contract, accepting
  the narrow collision as a known limitation instead: if run 1's schema
  has a date-range property "Duration" (synthesizing a companion
  "Duration (end)" = `datetime` into `types.json`), and a LATER, separate
  run onto the SAME output vault has a genuinely real property literally
  named "Duration (end)" of a different type, that real property's true
  type is never registered — the stale synthetic entry wins, silently.
  Reachable only when an actual Notion property is named exactly
  `<other property> (end)` and collides with a prior run's date-range
  companion key of the same name — rare. Work around it by hand-editing
  `.obsidian/types.json` (or setting the type via Obsidian's UI) if hit.
- **Notion blocks with no clean Markdown equivalent** (column layouts,
  synced blocks, complex embeds) get best-effort flattened by
  markdownify. Bookmark cards, local-file figures, and equations get a
  custom pre-pass for cleaner output; if another block type comes out
  garbled, look at the original `.html` and we can add a similar
  pre-pass.
- **Inline equations use a best-effort fallback; minor adjacent "residue"
  text is a known, accepted trade-off.** Notion's documented, confirmed
  export shape for a BLOCK equation
  (`<figure class="equation"><annotation encoding="application/x-tex">`)
  converts to a proper `$$...$$` fence and is unaffected by anything below.
  Any bare TeX annotation not inside that figure is treated as inline
  (`$...$`) — reasonable, but Notion's exact inline-equation markup isn't
  confirmed against a real export sample, so this is a best-effort
  fallback rather than a verified path.

  Inline conversion (J1, definitive fix) replaces ONLY the `<annotation>`
  node itself — it never decomposes or replaces any ancestor (`<math>`,
  `<span>`, `<semantics>`, ...). Four consecutive red-team rounds (G3, H1,
  I1, and a final round) each found a NEW silent-data-loss or crash bug in
  decompose/replace-the-ancestor logic: sibling prose deleted, a sibling
  equation deleted, a crash on a detached node, and — the shape that
  forced this rewrite — N-1 of N equations silently lost when they shared
  one `<math>` wrapper under realistic MathJax `<semantics>/<mrow>`
  nesting, because mutating an ancestor mid-loop corrupted the tree the
  next iteration was still scoping against. Replacing only the annotation
  node is safe by construction: no ancestor is ever touched, so there is
  no wrapper-scoping decision left to get wrong and no
  mutation-during-iteration hazard, regardless of markup shape, nesting
  depth, or how many equations share a wrapper.

  **Accepted trade-off:** sibling presentation MathML (`<mrow>`, `<mi>`,
  `<mo>`, ...) is left in the tree, so markdownify may render it as
  adjacent plain-text "residue" next to the `$tex$` in the note. This is
  cosmetic — strictly preferable to the silent data loss the prior
  wrapper-removal approach caused.
- **Query-string-only or empty-after-strip relative `<a href>`s pass
  through unmodified with no warning (H4).** A relative href like
  `?query` alone, or `#frag?query` where the path portion is empty after
  stripping, falls through all link-resolution branches (absolute URL,
  `.html` wikilink resolution, bare `#fragment`) untouched. Notion's own
  export doesn't produce this shape — internal links are always absolute
  URLs, `<Node>.html[...]`, or a bare `#fragment` — so reachability from a
  real export is nil. Found by the 2026-07-06 round-3 red-team panel;
  deferred as out-of-scope/unreachable, no code fix implemented.
- **The root/landing page's body is best-effort.** A page that owns
  databases is written as a note and becomes their home (base embeds +
  entry links), but its own body — Notion's `collection-content` gallery
  of those databases — is converted by markdownify as-is, so it may read
  as a plain table or list above the generated home sections rather than a
  polished landing page.
- **By design, not a bug:** relation properties emit as plain title
  strings, not `[[wikilinks]]` (same-database relations could in principle
  resolve to entry notes — not implemented). Page-level icons (emoji/image
  in the page header) aren't captured. There's no `--flat` output-layout
  flag and no Windows `MAX_PATH` (260-char) handling for deep mirrored
  paths — a very deeply nested export could hit that limit on Windows.
- **A corrupt/truncated entry HTML is silently dropped (Q1).** If
  `parse_entry` returns `None` for an entry or standalone page (truncated
  HTML, or a file that substring-matches the properties/collection
  markers without being a real article), no `.md` is written and no
  warning is logged. The persisted `_conversion_report.md` also
  overstates the per-database entry count in this case (it reports the
  pre-filter count). Found by the 2026-07-06 red-team panel; deferred.
- **Pointing the converter at a non-Notion-export directory used to
  silently "succeed" (Q2, partially fixed).** `run_conversion` now detects
  the "0 database entries AND 0 standalone pages found" case — the shape a
  non-Notion directory actually produces — and prints an explicit
  `WARNING: no Notion content found in <path>...` line, plus sets
  `summary["no_content_found"] = True` so a library caller can check for it
  without diffing file counts. It still exits 0 (a genuinely empty export
  directory is a legitimate, non-error input), but the outcome is now loud
  and machine-detectable instead of looking identical to a real
  conversion. Remaining gap: a stray non-node `.html` file sitting
  *alongside* real content that WAS found is still silently dropped (not
  converted, not copied as an orphan) — this warning only fires on the
  all-zero case. Found by the 2026-07-06 red-team panel; the all-zero case
  fixed alongside K1 (`run_conversion` input validation).
- **An uncaught mid-run exception loses the accumulated report (Q3,
  reachability unconfirmed).** `_emit_conversion_report` only runs at the
  very end of `run_conversion`; an exception anywhere earlier (e.g. inside
  the unhandled `_symlink_filtered_attachments`) means every warning
  accumulated for whatever partial output was already written is lost,
  with no report file at all. Found by the 2026-07-06 red-team panel;
  deferred.
- **`notion2obsidian-fix-dates` exits 0 even with unparseable values
  (Q4).** Unparseable date-keyed values are logged as `WARN` lines but
  don't affect the process exit code, so a scripted/CI caller can't
  detect a partial failure from the exit status alone. Pre-existing;
  found by the 2026-07-06 red-team panel; deferred.

### Maintenance

This is a personal tool, shared as-is. Issues and PRs are welcome, but
there's no response SLA.

---

- **Decision log:** see [`CHANGELOG.md`](../../CHANGELOG.md) for context, alternatives, and trade-offs behind each significant change.
- **Roadmap:** see [`ROADMAP.md`](../../ROADMAP.md) for larger, not-yet-started ideas (e.g. a generic multi-source converter).
