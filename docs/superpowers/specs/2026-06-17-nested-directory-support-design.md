# Nested-directory (arbitrary-depth) support — design

- **Date:** 2026-06-17
- **Status:** approved design, pre-implementation
- **Branch:** `feat/nested-db-depth` (git worktree)

## TL;DR
Kill the depth-2 ceiling and the "must have a database" rule. Convert any Notion export — pages and/or databases nested to any depth — into mirrored Obsidian notes, wired by wikilinks (graph) with a `.base` per database.

## Acceptance criteria
1. An export nested to **any depth** converts with no "nested too deeply" error.
2. A **page-only** export (no database) converts with no "no database found" error; pages become notes.
3. **Every entry and page, at every depth, becomes a real `.md` note.**
4. Output **mirrors** the Notion folder hierarchy.
5. Each database has its own **same-level-scoped `.base`**; the **vault-wide `.base` still exists**.
6. A node that owns a child DB **embeds the child's `.base`** and lists `[[child]]` links; each child has an `↑ Part of [[parent]]` backlink.
7. Wikilinks are **name-based**; filenames are **unique vault-wide**.
8. A `<table>` in a page body **stays a Markdown table** (never a database).
9. Existing conversion behavior (callouts, toggles, checkboxes, highlights, code-langs, lists, frontmatter, attachments) is **unchanged** (regression-tested).
10. All of the above are covered by tests (synthetic deep-nest fixtures + regression + edge cases), all green.

## Problem

`discover_databases` classifies databases by hard-coded depth: depth 0 → top-level DB, depth 2 → nested DB (inline GFM table appended to the parent entry), and depth 1 or ≥3 → `sys.exit` (fatal). It also `sys.exit`s when no top-level database is found. Two limits hurt real use:

1. **Depth ceiling.** A nested DB renders as an inline table *inside the parent note*, but a depth-2 entry is a table **row**, not a note — so a DB nested inside it (depth 4) has nothing to attach to, and GFM tables can't nest. Hence the depth-≥3 fatal.
2. **Database-required.** Page-only exports (no database) abort.

**Goal:** support arbitrary nesting depth and page-only / standalone exports, rendering naturally in the Obsidian ecosystem (real notes + graph links + Bases).

## Approved decisions

- Every Notion node → **one Obsidian note** (DB entries, standalone pages, DB index pages).
- **Real notes at every depth** (no inline-table-only nested entries).
- **Mirrored** folder layout (a nested DB folder lives under its parent entry's folder). `--flat` is deferred.
- **Parent → child:** the parent note **embeds the child DB's `.base`** (`![[Child.base]]`) *and* lists explicit `[[child]]` wikilinks; each child carries an `↑ Part of [[parent]]` backlink. (Drives the graph; no static summary table — embedding is documented Obsidian behavior.)
- **`.base` files:** keep the existing **vault-wide** `.base`; **add** one **same-level-scoped** `.base` per database at every level, scoped via `file.folder == "<exact path>"` (non-recursive).
- **Wikilinks:** **name-based** (`[[Name]]`/`[[Name|Alias]]`) with **vault-unique filenames** — move-proof; supersedes path-qualified links.
- **Standalone pages supported;** the "must have a database" fatal is removed.
- A **nested database** (folder of entry-HTMLs) is never conflated with a **`<table>` block** in a page body (which stays an ordinary Markdown table).
- All existing body conversions (callouts, toggles, checkboxes, highlights, code-block languages, tight lists, attachment rewriting) apply to every note.

## Unified node model

| Notion node (HTML) | Detection | Becomes |
|---|---|---|
| DB entry | has `<table class="properties">` | Note: type-aware frontmatter (original Notion property names + `notion_uuid`) + converted body |
| Standalone page | no properties, no collection | Note: converted body; minimal frontmatter (`notion_uuid`) |
| DB index page (collection-content) | has `class="collection-content"`, no properties | Plain note (its own description/body, if any). It is **not** a second base-embed — see "Database home" below. |
| Node that **owns** a child DB | a sub-folder of entry-HTMLs sits in its attachment folder | The node's note embeds `![[Child.base]]` + lists `[[child]]` links; children backlink `↑ Part of [[node]]` |

**Database home (one per DB, no double-embed):** each database has exactly one note that embeds its `.base` + lists its entry links. For a **nested** DB that home is its **owning entry**; for a **top-level** DB it is the DB's **index page** (or the output-root README if there's no index page). A nested DB's own index page, when present, is converted as a plain note only (no second embed).

## Architecture

### Discovery — replace depth 0/2/fatal with a nesting tree
- Walk the export; classify every `.html` (`entry` / `index` / `page`) using the existing `classify_html`.
- Build a **tree** keyed by the folder hierarchy: a *database* is a folder of entry-HTMLs; it is **nested under** the entry/page whose attachment folder (matched by that entry's 32-char hex ID in the path) contains the DB folder. Pages may own databases and sub-pages.
- No depth limit; no "database required" check. An export that is purely pages produces purely page-notes.

### Output — mirrored
- Each node → a `.md` note at its mirrored path (`out/<TopDB>/<parent entry>/<Child DB>/<entry>.md`).
- Each database folder → its own same-level-scoped `.base` placed at that folder.
- The vault-wide `.base` is still written at the output root.

### Linking & graph
- **Vault-unique filenames:** extend the current per-folder collision disambiguation (append the short Notion ID) to be **vault-wide**, so every note name is unique.
- **Name-based wikilinks** everywhere (`[[Name]]`, `[[Name|Alias]]` for display) — location-independent and move-proof; Obsidian auto-updates them on in-app rename.
- Parent notes: embed the owned child DB's `.base` + a list of `[[child]]` links. Children: `↑ Part of [[parent]]` backlink.
- Existing in-body cross-entry links (`OtherEntry.html` → `[[Title]]`) now always resolve, because every referenced node is a real note.

### Guard — nested DB ≠ page table
A database is only ever a *folder of entry-HTMLs*. A `<table>` inside a page/entry body (not `class="properties"`) is converted by markdownify to a GFM table and never treated as a database. (Invariant to preserve + test.)

## Edge cases
- **Page-only export** (no databases) → notes only, no fatal.
- **Single-entry DB; empty DB; node owning multiple child DBs** (multiple embeds/links).
- **Title collisions vault-wide** → filename disambiguation (short Notion ID suffix), bare link + alias.
- **Folder name missing a hex ID** (e.g. user-renamed) → warn and best-effort; nesting that can't be mapped is reported, not silently dropped.
- **Attachment modes** (copy / symlink / inplace) must still work under deep mirrored paths.

## Testing
- **Synthetic, no-PII fixtures:** a small generated export mixing standalone pages and databases nested to ~depth 6 with multiple children per level. Assert: a note exists at every depth; mirrored paths; one same-level `.base` per DB + the vault-wide `.base`; parent embeds + `[[links]]`; child backlinks; page-only sub-tree works; no database-required fatal; nested-DB-vs-body-table guard holds.
- **Regression on the real depth-2 export:** convert it and assert the new expected structure (parity for top-level entries; nested DBs now real notes + per-level base instead of inline tables).
- **Broad regression (refactor touches the whole pipeline):** unit tests asserting body conversions (callouts/toggles/checkboxes/highlights/code-langs/tight lists), frontmatter (original-name keys, person avatar, sole-link URL), attachment rewriting, and `.base`/`types.json` generation are unchanged.
- **Edge tests:** page-only export, single-entry DB, vault-wide filename collision, node with multiple child DBs, folder missing its hex ID.

## Out of scope / deferred
- `--flat` output layout flag and Windows `MAX_PATH` handling (deferred; mirrored is the only mode for now).
- Anything beyond *basic* standalone-page conversion (full page-import polish is a possible later effort).

## Risks / concerns
- **Wikilink robustness on move:** mitigated by name-based links + vault-unique filenames; moving files *outside* Obsidian remains a general Obsidian caveat.
- **Windows `MAX_PATH` (260)** with deep mirrored paths — real for other users; deferred mitigation (`--flat` + warning).
- **Bases requirement:** `.base` files and `![[*.base]]` embeds need Obsidian 1.9+. The `.md` notes and `[[links]]` work without Bases (progressive enhancement).
- **`.base` proliferation:** one per nested DB; acceptable, noted in docs.
- **Public repo:** the tool still requires a *Notion HTML export* shaped like Notion's (hex IDs in folder names) to detect nesting; renamed/ID-stripped exports degrade to best-effort.
