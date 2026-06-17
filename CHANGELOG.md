# Changelog

Decision log for this project. Each entry records what changed, why, what was considered, and what was traded away. Git history has the exact diffs.

---

## 2026-06-16 — text properties: bare URL instead of a Markdown link

Decision: when a Notion `text` property's value is exactly one hyperlink, emit the bare URL in frontmatter instead of a `[label](url)` Markdown link (`_unwrap_sole_markdown_link`). Mixed content (text around a link, multiple links) is left as Markdown.
Why: Obsidian doesn't render Markdown inside YAML frontmatter, so a single-link property came out as the literal string `[label](url)`. The bare URL is clean and usable.
Tests: `Notion Database to Obsidian/test_url_property.py` (TDD, 7 cases).

---

## 2026-06-16 — revive Notion to-do items as Obsidian task lists

Decision: convert Notion to-do items (`<li>` with `<div class="checkbox checkbox-on|off">`) into Markdown task syntax (`_convert_checkboxes`, pre-pass) — `- [x] text` (checked) / `- [ ] text` (unchecked). Adjacent to-do lists merge into one tight task list.
Why: markdownify dropped the checkbox and rendered a plain bullet, losing the checked/unchecked state.
Tests: `Notion Database to Obsidian/test_checkboxes.py` (TDD, 4 cases). Verified on a real export (13 task items in a sample entry).

---

## 2026-06-16 — revive Notion toggles as Obsidian foldable callouts

Decision: convert Notion toggles (`<details>`, exported wrapped in `<ul class="toggle">`) into Obsidian foldable callouts (`_convert_toggles`, pre-pass) — `> [!note]- Title` collapsed, `> [!note]+ Title` when the source `<details open>`. The `<ul class="toggle"><li>` wrapper is dropped when it holds only the toggle, so no stray bullet remains.
Why: markdownify dropped the collapse and flattened toggles to plain bullets, losing the fold and (for nested toggles) the structure.
Note: in this DB all toggles are plain (no heading semantics in the HTML), so foldable callouts are the only faithful target. Nested toggles become nested callouts (`> >`); a deeply toggle-nested page becomes deeply nested callouts — faithful but visually heavy.
Tests: `Notion Database to Obsidian/test_toggles.py` (TDD, 4 cases). Verified on a real export (68 toggles in one entry).

---

## 2026-06-16 — revive Notion callouts as Obsidian callouts

Decision: convert `<figure class="… callout">` into an Obsidian callout (`_convert_callouts`, a pre-pass before markdownify) — a `> [!type] emoji` blockquote with the content quoted beneath it. The callout emoji maps to a type (💡→tip, ❗→warning, ℹ️→info, ✅→success, ❌→failure, 🐛→bug, ❓→question; default note) and is kept in the title.
Why: markdownify flattened callouts to a stray emoji line plus loose content, losing the block entirely.
Tests: `Notion Database to Obsidian/test_callouts.py` (TDD, 5 cases). Verified on a real export — all 13 callouts in a sample entry render flush (top-level) or consistently indented (nested in lists).

---

## 2026-06-16 — frontmatter keys: preserve original Notion property names

Decision: frontmatter keys are now the original Notion property name, verbatim and trimmed (`Created time`, `Tester(s)`, `Areas Under Test`) instead of lower_snake_case (`created_time`, `tester_s`, `areas_under_test`). `yamlify_key` → `property_key`. The tag property is matched case-insensitively, so a Notion "Tags" property still feeds Obsidian's tag system.
Why: lower_snake_case read poorly and broke Obsidian Bases built around the original property names — a hand-made base's columns no longer matched any note's keys. Obsidian property names and Bases columns tolerate spaces/punctuation; PyYAML quotes keys with special characters as needed.
Trade-off: keys now contain spaces/parens (quoted in YAML); some Dataview setups prefer snake_case, but Bases (this project's target) handles spaced names. `.obsidian/types.json` and the generated `.base` use the same original-name keys.
Tests: `Notion Database to Obsidian/test_property_keys.py` (TDD, 5 cases).

---

## 2026-06-16 — person properties: strip avatar initial

Decision: in `convert_property_value`, strip each `<span class="user">`'s avatar icon span before reading the name (applies to person / created_by / last_edited_by).
Why: Notion's person avatar carries the name's initial as text, so a naive `get_text()` glued it onto the name — a person cell came out with its leading character doubled (e.g. `Jane` → `JJane`).
Alt: regex-trim a leading duplicated character — rejected, it's a guess at the symptom and would corrupt names that legitimately start with a repeated letter. Chose to remove the icon node, the same idiom `parse_entry` already uses for property names.
Tests: `Notion Database to Obsidian/test_person_property.py` (TDD, 6 cases).

---

## 2026-06-16 — inplace mode: resolve cross-entry attachment links

Decision: in inplace attachment mode, `convert_body` prefixes every local href with the relpath from the output dir to the source-entries folder (new `inplace_link_prefix`), instead of rewriting only this entry's own attachment folder.
Why: Notion exports all sibling entries into one folder, so one entry can embed another's screenshots ("cross-entry" refs). The old code rewrote only the entry's own folder; cross-entry refs pointed at non-existent output paths and broke (one report resolved 2 of 91 images).
Also documented: symlink attachment mode does not render in Obsidian (Obsidian doesn't index files inside symlinked dirs) — inplace is the 0-GB mode that resolves to the real exported files. copy/symlink keep their existing same-entry-only behavior (cross-entry stays a known limitation there).
Verify: full export regenerated with `--inplace` — the cross-entry report went 2/91 → 91/91; a 60-entry sample resolved 536/536 on disk. Caveat: inplace points at the real export inside the vault, so output is not self-contained; Obsidian render should be spot-checked.
Tests: `Notion Database to Obsidian/test_cross_entry_images.py` (TDD, 5 cases).

---

## 2026-06-15 — tight Markdown lists

Decision: merge adjacent same-kind sibling `<ul>/<ol>` in the body tree before markdownify, via new `_merge_adjacent_lists()` in `convert_body`.
Why: Notion exports every bullet/number as its OWN single-item list element. markdownify renders each as a separate block → a blank line between every item (loose list). Output read as unrefined.
Alt: (a) regex-collapse blank lines in the Markdown — rejected, can't tell per-item gaps from intentional continuation paragraphs inside an item; (b) markdownify options — none fix one-`<ul>`-per-bullet. Chose tree merge: addresses the real HTML pathology; markdownify then emits tight lists natively.
Scope guard: "same kind" = same tag + identical class; any real content between lists ends a run. So bulleted/numbered/to-do/toggle never merge into each other and genuinely separate lists stay separate. Frontmatter, image embeds, and `.base` generation untouched (verified).
Tests: `Notion Database to Obsidian/test_list_merge.py` (TDD, 5 cases).

---

## 2026-06-02 — docs restructure

Decision: legacy script blurbs root README → `legacy/README.md`. Add Utility section: `fix_frontmatter_dates.py`. CLAUDE.md → lean orientation doc; user-facing bug notes → script README.
Why: root README + CLAUDE.md bloated. Split by audience.
Alt: keep verbose / dump all to READMEs. Chose route-by-audience: user stuff → READMEs, dev gotchas stay CLAUDE.md.
Tradeoff: knowledge spread across files. Root README points to `legacy/README.md`, no inline.

---

## 2026-06-02 — document known limitations

Decision: add Known limitations to script README.
- Nested-DB entry body → plain-text Notes cell. Img, link, format dropped. Top-level entries keep img/PDF embeds.
- Rich-text styling (color, indent) stripped by markdownify.
- External URLs left live.
- Strikethrough unstyled.
Why: behaviors known, lived only in internal notes. Set user expectations.
Caveat: strikethrough NOT verified vs current export. Flagged test.

---

## 2026-05-06 — PII scrub and repo prep for public push

**Decision:** Scrubbed personal identifiers from the repo before first public push. Removed the Obsidian vault, CSV trial outputs, and scratchpads from git history and future tracking (moved to `test-output/`, gitignored). Converted `legacy/merge_notion_db_html.py` from hardcoded paths to a proper argparse CLI. Genericized example paths in both READMEs. Removed `<!-- CAUTION -->` banners. Added `test-output/`, `scratchpads/`, and `session-report-*.html` to `.gitignore`.

**Context:** Generated output (vault, CSVs) contained personal identifiers in frontmatter and filenames. Scratchpads contained real names and database-specific paths. The legacy HTML script had hardcoded absolute paths to a specific database and its Notion UUID — converted to match the argparse pattern already used by the other two legacy scripts.

**Alternatives considered:**
- *Strip identifiers in place:* Keeps generated output as sample data but requires per-file passes and sets a precedent for maintaining scrubbed samples.
- *Gitignore by specific vault/folder names:* Exposes those names in a public file.
- *Leave scratchpads tracked:* Scratchpads are session notes with no value to contributors; excluding them is cleaner.

**Trade-offs:** `test-output/` is a convention, not enforced. README narrative references to old export paths remain for historical context; they are not runnable without a local copy. History rewrite attempt with `git filter-repo --force` caused data loss (see entry below); final clean history achieved via orphan branch instead.

---

## 2026-05-06 — filter-repo incident and orphan branch

**Decision:** Replaced full git history with a single clean commit via orphan branch after `git filter-repo --force` caused two data-loss incidents during the PII scrub.

**filter-repo Run 1 (remove vault):** Vault was moved to `test-output/` before the run. After the run, vault directory was found empty — only `.DS_Store` files remained. Assumed to be a consequence of Run 1, but contents were not verified after the move, and cause remains unknown. Vault contents still need Backblaze recovery.

**filter-repo Run 2 (remove scratchpads):** Ran against a dirty working tree with 6 uncommitted file edits. filter-repo hard-reset the working tree to the rewritten HEAD with no warning: 5 scratchpad files deleted from disk, 6 uncommitted edits clobbered. Reflog wiped. No git-native recovery path. Scratchpads recovered from Backblaze; edits re-applied from conversation context.

**Post-recovery audit** found PII across ~20 historical paths (CSV filenames, scratchpads in former locations, inline database name references in `notion_db_to_obsidian.py`). Too many paths for surgical filter-repo removal.

**Alternatives considered:**
- *filter-repo on a clone:* Preserves history but required inline reference rewriting beyond path removal; high complexity given prior incident.
- *git rm --cached + commit:* Simple but leaves PII visible in old commits — unsuitable for a public repo.

**Consequences:** ~14 commits lost, including feature work (nested DB conversion, date-parsing fixes). Working tree and all tracked file content preserved exactly. `git filter-repo` banned in CLAUDE.md. No force-push needed — no remote existed.

---

## 2026-05-06 — Nested databases → inline GFM tables

**Decision:** Databases nested at depth 2 from `src` (sub-databases inside a top-level entry's attachment folder) are rendered as inline GFM markdown tables appended to the parent entry's `.md` body. Depth ≥ 3 is a fatal error. Inline Notion snapshot tables are stripped from the parent HTML body before conversion to avoid duplicates.

**Context:** Notion does not embed nested DB content inline in the parent entry HTML for all entries — the sub-database rows live only in their own sub-folders. The old `discover_databases` treated every folder-of-entries as a top-level DB, producing a separate output folder per nested DB. This broke the vault structure: sub-databases that belonged to a single parent note became floating, unconnected DBs in the output.

**Alternatives considered:**
- *Separate output folder per nested DB (status quo):* Preserves full DB functionality (filtering, sorting in Bases) but severs the parent–child relationship; navigation between parent note and its sub-DB is lost.
- *Skip nested DBs entirely:* Simplest code change, but discards data.
- *Full recursive DB support (depth ≥ 3):* Would require a tree-traversal rewrite and ambiguous parent-assignment logic. Deferred; fatal error on depth ≥ 3 makes the edge case visible rather than silently wrong.

**Trade-offs:**
- Nested DB rows become static table rows — no Bases filtering/sorting on them.
- Table is always appended at end of parent body; Notion may have placed the inline embed mid-document. Position-preserving injection is a known future improvement (requires tracking DOM position of the stripped table and injecting a placeholder before `convert_body`).
- Entry body text of nested rows is captured as a "Notes" column (plain text). Markdown metacharacters in body text are escaped (`\`, `*`, `_`, `` ` ``, `[`, `]`).

---

## 2026-05-06 — Date parsing: `@`-prefix and MM/DD/YYYY format

**Decision:** `parse_notion_date` strips a leading `@` before format matching and handles `MM/DD/YYYY` (e.g. `@04/26/2023`). The fallback in `convert_property_value` also strips `@` if parsing fails.

**Context:** Notion renders date mentions in body text and some property cells as `@April 26, 2023` or `@04/26/2023`. The `get_text()` extraction preserved the `@`, and neither format was in the original format list, so dates fell back to the raw string with the `@` intact in YAML frontmatter.

**Trade-offs:** `MM/DD/YYYY` is ambiguous (US locale assumed). Dates in this format from non-US locales would be mis-parsed. Acceptable given the source data is a US-based team's Notion workspace.

---

## 2026-05-06 — Single vault-wide `.base` instead of one per database

**Decision:** Emit one `.base` file at the output root filtered on `file.ext == "md"` rather than one per database folder filtered on `file.inFolder()`.

**Context:** Obsidian Bases scopes are vault-wide by default; a per-folder `.base` with `inFolder()` filter duplicates scope logic Bases already handles via the file picker. Multiple `.base` files also meant opening any one of them showed only a subset of entries, which confused navigation.

**Alternatives considered:**
- *One `.base` per DB folder with `inFolder()` filter:* Natural mapping to Notion's per-DB view, but produced 8 separate `.base` files for one logical database due to how `discover_databases` grouped sub-folders.

**Trade-offs:** Single `.base` shows all `.md` files in the vault, not just the target DB. Acceptable because the output folder is typically a dedicated vault for one migration.

---

## 2026-05-05 — `_TAG_FACTORY` for BeautifulSoup tag creation

**Decision:** Module-level `_TAG_FACTORY = BeautifulSoup("", "html.parser")` used for all `new_tag()` calls instead of calling `soup_root.new_tag()`.

**Context:** `Tag.__getattr__` in BS4 intercepts unknown attribute lookups via `self.find(name)`. `new_tag` is only a real method on `BeautifulSoup` instances, not plain `Tag` objects. When `soup_root` was a `Tag` (not the root `BeautifulSoup`), `soup_root.new_tag` resolved to `self.find("new_tag")` → `None`, then `None(...)` raised `TypeError: 'NoneType' object is not callable`.

**Alternatives considered:**
- *Walk up to the root `BeautifulSoup` instance:* Brittle; relies on `.parent` chain terminating at the right object. Removed in favor of the factory.
- *Import and call `BeautifulSoup("", "html.parser").new_tag()` inline:* Creates a new parser instance per call; wasteful.

**Trade-offs:** Module-level singleton is effectively a global, but it's read-only (`new_tag` is stateless). No meaningful downside.

---

## 2026-05-05 — Direct HTML parse; no CSV

**Decision:** Read Notion's HTML export directly. Ignore CSV exports entirely.

**Context:** Notion's CSV export strips property type information — multi-selects become comma-separated strings, dates become human-readable text, checkboxes become "Yes"/"No" strings. The HTML export encodes each property's type in the `<tr class="property-row-{type}">` attribute, which allows faithful reconstruction of typed YAML frontmatter.

**Alternatives considered:**
- *CSV + HTML merge (legacy scripts):* Was the original approach. Preserved body content but lost types on import via Obsidian Importer plugin. Three legacy scripts remain in `legacy/` for reference.
- *Notion API:* Zero dependency on export format; would give structured JSON with full type info. Ruled out — requires API token, network access, and Notion account; contradicts the zero-network-access policy.

**Trade-offs:** Tied to Notion's HTML export format, which is undocumented and can change. The `property-row-{type}` class convention has been stable across the exports tested (2024–2026), but there's no guarantee. Unknown property types fall back to raw text with a warning in `_conversion_report.md`.
