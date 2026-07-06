# Changelog

Decision log for this project. Each entry records what changed, why, what was considered, and what was traded away. Git history has the exact diffs.

---

## 2026-07-06 — README/CHANGELOG/ROADMAP consolidation for the packaged tool

Decision: root `README.md` now documents `pip install`, both console scripts (`notion2obsidian`, `notion2obsidian-fix-dates`), and a `from notion_to_obsidian import run_conversion` library example, up top — before the per-tool detail sections. `src/notion_to_obsidian/README.md`'s "Known limitations" section is renamed in substance to a full Known Issues list reflecting the B1–B12 triage outcome (fixed items removed/corrected, B1/B3/B5's residual scope stated precisely, by-design non-bugs listed explicitly so they aren't re-raised as bugs), plus a "personal tool, no SLA" maintenance note. New root `ROADMAP.md` holds the generic multi-source-converter idea (sized L) as its own document rather than a README aside.
Context: the packaging work (src-layout, pyproject.toml, console scripts) made the old README's `python3 notion_db_to_obsidian.py` instructions stale, and the B1–B12 bug pass left the "Known limitations" section partly inaccurate (claims about strikethrough, date ranges, and equations no longer held). Rolling doc fixes into the code-change commits would have buried them; this is its own pass so the "why" for each doc decision is traceable.
Trade-off: the generic-converter idea explicitly documents WHY it's an architecture project and not a config flag — the 32-hex Notion-id convention and Notion's specific HTML class names are load-bearing for node identity and link resolution, not just property parsing — so a future session doesn't underestimate the scope and reach for a quick flag-based hack.

---

## 2026-07-06 — CI: GitHub Actions matrix build

Decision: `.github/workflows/ci.yml` runs on `ubuntu-latest` across a Python 3.9–3.12 matrix (the full range `requires-python = ">=3.9"` allows and `actions/setup-python` supports), installing via `pip install -e .` and running the test suite via `unittest discover` against `src/notion_to_obsidian/tests`.
Context: no CI existed; packaging work made "does this actually install and run on a clean machine/Python version" a real question, not just "do the local `/usr/bin/python3` tests pass."
Trade-off: matrix stops at 3.12 rather than including inevitable future versions — deliberately bounded to versions confirmed available in `actions/setup-python` at write time rather than guessing forward.

---

## 2026-07-06 — Package as pip-installable `notion-to-obsidian` (src-layout)

Decision: `Notion Database to Obsidian/` renamed to `src/notion_to_obsidian/` (src-layout); `notion_db_to_obsidian.py`, `synthetic_export.py`, `fix_frontmatter_dates.py`, and all `test_*.py` moved under it (tests into `src/notion_to_obsidian/tests/`). New `pyproject.toml` at repo root (`build-backend = "setuptools.build_meta"` — a prior packaging spec draft had `"setuptools.backends.legacy:build"`, which is invalid and fails to build; corrected here). Two console scripts: `notion2obsidian` (the converter) and `notion2obsidian-fix-dates` (the existing frontmatter-date migration utility, which already had a clean argparse `main()` — reused as-is, no rewrite). `legacy/` stays outside `src/`, deliberately not packaged/importable.
Context: the tool was two flat directories of scripts with no way to `pip install` it, get console-script entry points, or `import` it as a library. `requires-python = ">=3.9"` was set only after grepping both modules for `match`/`case` statements and bare `X | Y` type-hint unions outside `from __future__ import annotations` — neither module used either, and both already import `annotations` from `__future__`, so 3.9 is a genuinely clean floor, not a guess. Dependency floors (`beautifulsoup4>=4.11`, `markdownify>=1.0`, `pyyaml>=6.0`) are floors, not exact pins — checked against installed-and-tested versions (4.14.3 / 1.2.2 / 6.0.3) via `pip show`, then relaxed to a sane minimum rather than pinning exactly.
Fix (test migration): 11 `test_*.py` files loaded `notion_db_to_obsidian.py` via `importlib.util.spec_from_file_location` using a same-directory path (`Path(__file__).with_name(...)` / `Path(__file__).parent`); these were updated to `.parent.parent` now that the module lives one directory above `tests/`. Every other test file kept its existing BARE imports (`import notion_db_to_obsidian as n`, `from synthetic_export import build, folder`) completely unchanged — a new `tests/__init__.py` inserts the package directory onto `sys.path` once per test session (it runs before `unittest discover`/`pytest` collect any `test_*.py` inside it), which was the smallest import-shim that kept 30+ pre-existing test files working with zero per-file changes to their import style.
Alternatives considered: rewriting every test to package-relative imports (`from notion_to_obsidian import notion_db_to_obsidian as n`) — more "correct" long-term, but a much larger diff for zero behavior change, and the packaging spec explicitly asked for whichever layout "needs the least import-shim hackery."
Verification: `pip install -e .` succeeds in a fresh venv; both console scripts run `--help`; `from notion_to_obsidian import run_conversion` imports cleanly from a throwaway script; full suite (183/183) passes under both the venv's Python and the repo's own `/usr/bin/python3` (via `PYTHONPATH=src`) — re-checked against a scratch clone of the committed tree, not just the worktree's on-disk state, after an initial `git add -A` with a bad multi-pathspec silently dropped several files from the first attempt at this commit.

---

## 2026-07-06 — Bug triage pass: B1–B12 (from a prior investigation's TODO)

Fixed, with a dedicated test each: **B8** (schema type-drift no longer collapses a multi-value select/status to its first value — `convert_property_value` now returns a list whenever more than one `selected-value` span is present, regardless of the dominant type passed in); **B2** (`_attachment_copy_ignore` rule 1 narrowed to hex-named Notion node HTML via `extract_notion_id`, so a genuine non-node `.html` attachment — e.g. a saved web page — survives the copy); **B4** (sibling databases that merely share a display name no longer merge into one output directory — DB output dirs disambiguated the same way node filenames already are, via a short-hex/counter suffix on collision); **B5** (`--symlink-attachments` now creates a real directory of PER-FILE symlinks, reusing the copy-mode child-node filter, instead of one directory symlink that exposed child-node HTML/hex-folders straight through it); **B6** (an unresolved cross-export `.html` link, or an in-page `#fragment` anchor this converter doesn't track, now converts to plain visible text instead of shipping a dead href — logged via a new optional `warnings` param threaded through `convert_body`); **B7** (Notion equations — `<figure class="equation"><annotation encoding="application/x-tex">` — converted to fenced LaTeX `$$...$$`/`$...$` Obsidian's built-in MathJax renders natively, instead of being silently dropped by markdownify); **B10** (an additive `.obsidian/types.json` schema merge now gets its own `SCHEMA-MERGED` log prefix, so `_emit_conversion_report`'s summary no longer mislabels it as a "PRESERVED existing file" event); **B11** (a top-level DB home note's owned-DB section heading is omitted when it's identical to the page's own title, instead of printing the same text twice); **B9** (a date-RANGE property keeps its start value in place and additionally emits a companion `<Prop> (end)` frontmatter property, both registered as `datetime` in `types.json` — option (A) from the prior investigation's decision doc).

Partially fixed (safe partial, not a full fix — documented as a known limitation): **B3** — `_attachment_copy_ignore`'s two directory-filtering rules (sibling `<name>.html`, or a folder containing a hex-named `.html`) have no content-based way to tell a genuine Notion node folder from a same-shaped coincidence; per the prior investigation, that's inherent, not a bug to close. Every such filtered directory now emits an explicit `WARN (B3, known limitation): ...` line (naming the path) into the run's `overwrite_log`/`_conversion_report.md`, so the potential loss is surfaced rather than silent — the ambiguity itself is not eliminated.

Attempted and blocked, documented rather than shipped unverified: **B1** (a landing/root page's own cover image isn't rewritten to its copied vault path). `parse_entry` only reads `<div class="page-body">`; a cover image plausibly lives outside it. There is no real Notion export sample accessible in this repo to confirm the actual cover-image markup shape (`test-output/` is off-limits per repo policy), so a parser change built only against invented markup risks passing its own synthetic test while doing nothing — or the wrong thing — against a real export. Left as a documented comment at `parse_entry` plus a TODO.md/README note, rather than shipping a fix nobody could verify.

Reclassified as not-a-bug (doc-only, TODO.md-only edit — TODO.md is gitignored/local, so this has no separate commit): **B12** (strikethrough). The pinned `markdownify` (1.2.2+) already aliases both `<s>` and `<del>` to `~~text~~` — verified directly (`markdownify('<s>x</s>')` and `markdownify('<del>x</del>')` both → `'~~x~~'`), disproving the old row's "html_to_md is markdownify with no strikethrough config" claim. If a real-world "unstyled strikethrough" bug persists, the more likely cause is Notion emitting `<span style="text-decoration:line-through">` rather than `<s>`/`<del>` — unverifiable here without a real export sample.

Each fix's test file is named for its bug in the commit history (`test_schema_drift_multivalue.py`, `test_non_node_html_survives_copy.py`, `test_ambiguous_dir_filter_warns.py`, `test_sibling_db_name_collision.py`, `test_symlink_filters_node_content.py`, `test_unresolved_link_fallback.py`, `test_equations.py`, `test_schema_merge_not_preserved.py`, `test_owned_db_heading_dedup.py`, `test_date_range_end.py`); full suite grew from a 143-test baseline to 183, green throughout.

---

## 2026-06-23 — preserve orphaned non-HTML files (PDF-only sections, loose attachments)

Decision: a new post-pass `copy_orphaned_files` copies every non-HTML source file that no node's attachment copy reaches, so a Notion page exported as a PDF — or any loose attachment in a section with no entry HTML — lands in the vault instead of being dropped.
Context: `discover_tree` finds entries only via `*.html`. A PDF-only export section produces no node, so `write_entry` never runs and `shutil.copytree` never fires — the files vanished with no warning. On real exports this dropped whole PDF-exported pages.
Fix: after all nodes are written, walk every non-HTML source file and copy the ones not already handled. "Handled" is an EXACT test, not a guess: the file lives under some node's own attachment dir (`<Title> <hex>/`, collected into `covered_dirs`), which `write_entry` already copied/symlinked. Copied files keep their ORIGINAL name; only directory components are hex-stripped (via `mirror_output_dir`) — the dirs, not the filename, carry the vault's "no hex dirs" invariant.
Collision safety: two distinct source folders can hex-strip to the same output dir (`Folder <hexA>/x.pdf` and `Folder <hexB>/x.pdf` → `Folder/x.pdf`). Rather than overwrite, the pass byte-compares — identical content is the same file (a re-run or a node's copy) and is skipped; different content is written under a disambiguated `x (2).pdf` name and the clash is logged. Re-runs are stable.
Attachment modes: respects the chosen mode — under `--inplace`/`--symlink`, attachments are referenced in the source, so files under a node's dir are skipped in every mode (no stray real copies); true orphans, which no note references, are always copied as real files so they are not lost.
Two adversarial reviews drove the design. An earlier attempt stripped the hex from filenames (broke body hrefs that reference the original name; collapsed two same-title PDF exports onto one path, losing one) and skipped hex-named files during the node copy (dropped genuine attachments whose names end in a 32-hex); both were reverted for the original-name + covered-dirs design. Known limitations left as-is (pre-existing or by design): a stray non-node `.html` *inside* an attachment tree is still dropped by the child-node filter; a user file coincidentally named `<x> <32hex>.html` is treated as a node; `--inplace` deliberately does not copy covered attachments into the vault.
Tests: `Notion Database to Obsidian/test_orphaned_pdf_copy.py` (15 — root-level + nested orphans keep their original names; a loose PDF beside DB entries; covered files not duplicated; two same-stem orphans both survive; a genuine hex-named attachment keeps a resolvable href; two folders colliding after the hex-strip both survive with a stable re-run). Full suite green (143).

---

## 2026-06-23 — narrow the nested-DB filter to node HTML (avoid dropping real attachment folders)

Decision: the rule that filters a nested database folder out of the attachment copy now fires only when the folder directly contains a Notion-NODE html (`<Entry> <hex>.html`), not any `*.html` (helper renamed `_dir_contains_html` → `_dir_contains_node_html`).
Context: adversarial review of the earlier "filter nested database folders" fix found a data-loss false positive. That rule dropped any directory directly holding an `.html` file — including a GENUINE attachment subfolder that happens to contain a non-node html (a saved web page or HTML export the user attached). `gallery/index.html` + `gallery/photo.jpg` made the whole `gallery/` folder, `photo.jpg` and all, vanish silently. The earlier "structural, not a heuristic" claim did not hold for that rule.
Fix: key the rule on the Notion node-id pattern. A database's entries are `<Entry> <hex>.html`, so requiring a 32-hex id in the html's stem distinguishes a real DB folder from a user attachment folder whose html carries no id — restoring the structural property and stopping the data loss. A residual ambiguity remains only for a user file coincidentally named `<x> <32hex>.html` (inherent to filename heuristics, and far rarer than the bare-`.html` surface it replaces).
Tests: `Notion Database to Obsidian/test_copy_filters_node_content.py` — the DB-folder case now uses realistic 32-hex ids; new `test_attachment_subdir_with_non_node_html_is_kept` guards the false positive (12 cases). Full suite green.

---

## 2026-06-23 — filter nested database folders during attachment copy (ghost-dupe fix)

Decision: `_attachment_copy_ignore` now also ignores a directory that itself contains `*.html` files (a nested database folder).
Context: the copy-mode attachment filter skipped `*.html` files and any directory paired with a sibling `<name>.html` (a node's attachment folder), but a nested *database* folder has neither marker at its parent level: `"<DB> <hex>/"` holds its entries as `"<Entry> <hex>.html"` *inside* it, with no `"<DB> <hex>.html"` sibling next to it. So when such a DB folder sat inside another entry's source folder, `copytree` copied it wholesale — ghost-duplicating every DB entry as a raw `"<Entry> <hex>.html"` (and hex dir) beside the clean `"<Entry>.md"`. Same class of dupe the 2026-06-22 copy-filter fix addressed, for the one structural case it missed. Latent in the original filter; exposed by deeper nesting.
Fix: add a third rule keyed on a new helper `_dir_contains_html(dir)` — a directory holding any `*.html` file directly is child-node content and is skipped. Structural to Notion's export layout, not a heuristic. `copy_has_attachments` (which decides whether to materialize the dir at all) inherits the rule, so a folder of only DB content still leaves no empty dir.
Tests: `Notion Database to Obsidian/test_copy_filters_node_content.py` gains `test_db_folder_containing_html_entries_is_filtered` (DB folder filtered; genuine sibling attachment kept) — 11 cases total. Full suite green.

---

## 2026-06-23 — strip trailing space after the Notion hex id (ghost-dir fix)

Decision: `NOTION_ID_RE` now allows optional trailing whitespace after the 32-char hex (`\s*` before the end-anchored lookahead).
Context: Notion sometimes exports a folder name with a trailing space after the hex — `"<Title> <hex> "`. The old pattern `\s+([0-9a-f]{32})(?=\.html$|/$|$)` anchored the hex to end-of-string (or `.html`/`/`), so a trailing space made the lookahead fail: `strip_notion_id` returned the name with the hex still attached, and `mirror_output_dir` emitted a ghost `"<name> <hex>"` directory — the clean nested path under it was effectively dropped. Latent since the regex was introduced; exposed by the arbitrary-depth nesting feature, which mirrors every such folder into the vault.
Fix: `r"\s+([0-9a-f]{32})\s*(?=\.html$|/$|$)"` — the `\s*` is consumed by `re.sub`, so the hex and its trailing space are removed together. Fixes both `strip_notion_id` and `extract_notion_id`.
Tests: `Notion Database to Obsidian/test_trailing_space_hex.py` (6 — strip/extract with and without the trailing space; an integration run asserting a trailing-space container folder produces no hex dir and the entry note lands at the clean path). Full suite green.

---

## 2026-06-22 — red-team fixes: index/landing link resolution, force-delete safety, report wording

Three fixes from an adversarial review of the landing-page + stem-naming work:
- **Index & landing page body links now resolve.** `wikilink_map` is keyed on each node's filename (basename). An entry links to a sibling with a bare basename (direct hit), but an index/landing page links DOWN into a subfolder, so its hrefs carried a folder prefix and missed the map — leaving raw `.html` links (broken in Obsidian) in those notes. Added a basename fallback (filenames are vault-unique, so it resolves unambiguously). Entry links are unaffected.
- **`--force` no longer deletes an output attachment dir it won't refill.** In copy mode, when an entry's source folder holds only child-node content (nothing survives the attachment filter), a `--force` run used to `rmtree` the existing output dir and copy nothing back — silently destroying any hand-added files. It now removes only when it will recreate; otherwise the existing dir is kept.
- **Report wording:** the "index/landing pages … not yet written … in a later step" line was stale; they are written as each database's home note.
Tests: `Notion Database to Obsidian/test_wikilink_rewrite.py` (3 — bare/folder-prefixed link resolution; non-node basename stays a non-link); `test_copy_filters_node_content.py` gains a force-keep case. Full suite green.
Known remaining (backlogged, pre-existing — see `TODO.md`): a landing page's own linked cover image is not rewritten to its copied location (broken image link on the note). (An earlier note here about cross-database `../` links was withdrawn — that link does end in `.html` and resolves in a real export; it only appeared broken in the redacted test copy, where the redaction rendered the link text and the filename differently for the same Notion id.)

---

## 2026-06-22 — note names come from the source stem, not the H1 title (dupe-dir fix)

Decision: `assign_unique_names` now derives each note's filename from its source stem (the `<Title> <hex>` file/folder name, hex stripped) instead of its H1 title.
Context: Notion sanitizes the on-disk file/folder name — e.g. dropping square brackets — while the page title keeps them. `mirror_output_dir` builds the folder tree from those sanitized stems, but the note + its attachment folder were named from the title via `sanitize_filename`. When the two differed, a node split into **two sibling directories**: its children mirrored under the stem name while its attachments landed in a title-named dir. A real export with a bracketed title (e.g. title `Group [Co] Hub`, on-disk folder `Group Co Hub`) produced two top-level dirs — one with the children, one with the landing page's images. (Surfaced once the landing/root page became a note and carried both children and attachments; latent for any such node before that.)
Fix: name nodes from `sanitize_filename(strip_notion_id(stem))` — the exact basis `mirror_output_dir` uses — so the note, its attachment dir, and its children all share one folder. The H1 title is still rendered verbatim as the body `# <title>` heading; only the filename/wikilink name changes, and only when Notion's filename sanitization differs from the title.
Verified on a real export: one top-level dir instead of two, no sibling near-duplicate dirs, the landing note's filename matching its children's folder; still 0 raw `.html`, 0 hex dirs, 0 empty dirs (35 notes, 17 attachments).
Known latent edge (pre-existing, not introduced here): two sibling nodes with the *same* stripped stem still split (one note gets a ` (id)` suffix while both children mirror to the same base dir — a collision `mirror_output_dir` already merges). Logged for a later pass.
Tests: `Notion Database to Obsidian/test_title_vs_folder_naming.py` (4 cases — note named from stem; no title-named split dir; attachment + children share one dir; title preserved as the body heading). Full suite green.

---

## 2026-06-22 — collection/landing pages (incl. the export root) become notes

Decision: a "parent" page (one with a `collection-content` table) whose hex matches no database's entries-folder is now written as a note instead of being dropped.
Context: `classify_html` labels any `collection-content` page `parent`, and `discover_tree` only kept a parent page if it was some database's index (its hex == that database's entries-folder hex). A page that *contains* child databases rather than entry rows — most importantly the export's own root/landing page — matched nothing, so it was silently orphaned: no note, its inline images lost, and every database it owned reported "no home note found" (the owner node didn't exist). On a real export this dropped the root page and orphaned 2 images.
Fix: `discover_tree` now folds every unconsumed `parent` page into the page list, so it becomes a `kind="page"` node. Because these pages own the databases beneath them (by hex), the existing owner→home wiring then makes each one the home for its databases — embedding their `.base`, listing `[[entry]]` links, and giving entries an `↑ Part of [[home]]` backlink. The owner's inline collection-snapshot table is already stripped before body conversion, so no duplication. Composes with the copy-attachment filter: the landing page's genuine images are copied; the child-DB HTML/folders in its folder are not.
Verified on a real export: the root page is now a note (`.md` 34 → 35), both previously-orphaned images are recovered (attachments 15 → 17), and the two "no home note found" warnings are gone; still 0 raw `.html`, 0 hex dirs, 0 empty dirs.
Docs: refreshed both READMEs (intro, output tree, the rewritten "Nesting (any depth)" section, removed two now-false "Known limitations") and the project `CLAUDE.md` invariants (no depth limit; per-database `.base` + vault-wide), all of which still described the superseded "nested DBs → inline tables, depth ≥ 3 fatal" model.
Tests: `Notion Database to Obsidian/test_landing_page_notes.py` (5 cases — landing page written; its attachment copied; owned-DB entries written; landing page embeds the child base + lists entries; entries backlink to it). Full suite green.

---

## 2026-06-22 — copy attachment mode filters child-node content (dupe fix)

Decision: in `copy` mode, copy only genuine attachments from an entry's source folder; skip the child-node tree it also contains.
Context: on a nested export an entry's folder (`<Title> <hex>/`) holds both real attachments (images, PDFs) AND the entry's child nodes (`<Child> <hex>.html` + `<Child> <hex>/`). The default `copy` mode `shutil.copytree`'d the whole folder, so every nested node landed in the vault twice — once as the clean `<Child>.md` note, once as the raw `<Child> <hex>.html` (+ hex folder). On a real export this turned 34 source `.html` into 59 copies plus 27 stray hex-named dirs. The Piece-4 warning flagged this but the behavior shipped anyway.
Fix: a `shutil.copytree(ignore=...)` callback (`_attachment_copy_ignore`) drops any `*.html` and any directory that has a (case-insensitive) sibling `<name>.html` (a node folder), copying only true attachments. The rule is structural to Notion's export layout, not a heuristic. The depth-duplication warning now fires for `symlink` mode only (which still exposes child nodes through the symlinked source dir); `copy` no longer warns.
Hardened after an adversarial review: (a) the sibling-html match is case-folded, so an uppercase `<name>.HTML` from a case-preserving tool no longer leaks the node folder while filtering its html; (b) copy mode now skips `copytree` entirely when nothing survives the filter, so an entry whose folder holds only child-node content no longer leaves an empty directory in the vault (children make their own dirs in the main write loop); the force-overwrite copytree branch carries the same filter and a matching dry-run log.
Alternatives: auto-switch nested exports to `inplace` (rejected — leaves genuine image attachments pointing back at the source export instead of copied into the vault); document `--inplace-attachments` as required (rejected — silent dupes by default). Trade-off: a stray non-node `.html` attachment (rare in Notion exports) would also be skipped; acceptable.
Verified on a real export: output `.html` 59 → 0, hex dirs 27 → 0, empty dirs 1 → 0, `.md` count unchanged (34), all 15 genuine attachments preserved.
Separately flagged (NOT fixed here — distinct concern, backlogged): the whole-export root/landing page is not written as a note, so its inline images (2 in this export) are orphaned. Pre-existing; present before this change too. The README intro's pre-PR description of nested DBs (inline tables, depth-3 fatal) is also stale and should be rewritten before the nesting PR merges.
Tests: `Notion Database to Obsidian/test_copy_filters_node_content.py` (9 cases — attachment copied; no `.html`/hex-dir leak; child notes intact; uppercase-`.HTML` sibling filtered; non-node attachment dir kept; no empty dirs; force-recopy invariants). Full suite green.

---

## 2026-06-18 — arbitrary-depth nesting, Piece 4: edge cases + regression

Decision: round out the nested-directory feature with edge-case coverage and two best-effort warnings.
- Edge tests (`test_edge_cases.py`): page-only export (no "database required" fatal), single-entry DB, a node owning multiple child DBs (multiple base embeds + link groups), folder-missing-hex (no crash + warning), copy attachment mode on a nested export (no crash).
- Warning: copy/symlink attachment mode on a NESTED export duplicates child-node content under deep paths → recommends `--inplace-attachments`.
- Warning: a nested DB whose owner folder lacks a Notion id (renamed) can't be mapped → reported and treated as top-level, never silently mis-nested.
Context: spec acceptance criteria 9/10 + "Edge cases".
Note: broad regression is covered by the existing per-feature suite (callouts / toggles / checkboxes / highlights / code-langs / tight lists / frontmatter / attachments / url / person / property keys), all green after the Piece 2–4 refactor. Known limitation: copy/symlink modes still *duplicate* child-node content on nested exports (use `--inplace`); a copy-time content filter is a possible follow-up.
Tests: `Notion Database to Obsidian/test_edge_cases.py` (5 cases). Full suite 98 green.

---

## 2026-06-18 — arbitrary-depth nesting, Piece 3: per-level bases, home notes, links & backlinks

Decision: complete the nested-directory feature's linking/graph layer.
- **Vault-unique filenames:** every note's filename is now unique across the whole vault (not just within a folder), so name-based `[[wikilinks]]` resolve unambiguously. Names are assigned deterministically (sorted by source path); a collision gets the short Notion id suffix.
- **Per-database `.base`:** each database now gets its own same-level-scoped `.base` (`file.folder == "<mirrored path>"`) at its folder, ALONGSIDE the vault-wide base at the output root.
- **Database "home" notes:** each database has one home note that embeds its `.base` (`![[Name.base]]`) and lists its entries as `[[links]]`; each entry carries an `↑ Part of [[home]]` backlink. The home is the owning entry/page for a nested database, or the index/landing page for a top-level database — which also means DB index/landing pages are now written as notes (audit item 68).
- **Refactor:** `run_conversion` builds a node registry (entries + index pages + standalone pages), assigns unique names, wires homes/links/backlinks, then writes. Removed the now-superseded `process_database` and `build_wikilink_map`.
Context: spec acceptance criteria 5/6/7 (`docs/superpowers/specs/2026-06-17-nested-directory-support-design.md`).
Alternatives: path-qualified wikilinks (rejected — brittle on move; name-based + unique filenames is move-proof); a static child summary table instead of a base embed (rejected — embedding is documented Obsidian behavior and drives the graph). Trade-offs: a top-level database with no index page has no home (its base is written but not embedded; warned). `.base`/embeds need Obsidian 1.9+; the `.md` notes and `[[links]]` work without it. One `.base` per nested DB (proliferation — acceptable, documented).
Tests (one feature per file): `Notion Database to Obsidian/test_per_level_bases.py`, `test_home_notes_and_backlinks.py`, `test_unique_filenames.py` (9 cases). Full suite green.

---

## 2026-06-18 — toggle headings keep their heading level

Decision: when a Notion toggle's `<summary>` contains a heading element, convert it to a real Markdown heading (preserving the level) instead of a foldable callout. Obsidian folds real headings natively, so this keeps both the level and the fold. Plain toggles (no heading in the summary) still become expanded `> [!note]+` callouts.
Context: divergence-audit item 5. A toggle heading previously flattened to `> [!note]+`, losing the heading level.
Caveat: no toggle-heading sample exists in the current test library, so this targets the plausible structure (a heading element inside `<summary>`). It is a safe no-op for toggles without a heading and should be re-confirmed against a real toggle-heading export.
Tests: `Notion Database to Obsidian/test_toggles.py::test_toggle_heading_becomes_real_markdown_heading`.

---

## 2026-06-18 — verified: body tables convert to GFM (audit item 21)

Audit item 21 flagged body-table conversion as uncertain. Verified: an ordinary content `<table>` in a note body converts to a GFM Markdown table via markdownify. GFM has no `colspan`/`rowspan`, so merged cells are flattened (the value lands in the first column, the rest blank) — but no cell text is lost. No code change — added regression tests.
Limitation: merged-cell *layout* is not preserved (a GFM constraint, not a data loss).
Tests: `Notion Database to Obsidian/test_tables.py`.

---

## 2026-06-18 — verified: nested to-do conversion is faithful (audit item 8)

Audit item 8 questioned whether the `to-do-children` wrapper span around to-do text leaves artifacts. Verified it does not: a nested to-do converts to indented `- [x]` / `- [ ]` task items with the span dropped cleanly (markdownify treats the inline span transparently). No code change — added a regression test that locks the nested-to-do output and asserts no `to-do-children` leakage.
Tests: `Notion Database to Obsidian/test_checkboxes.py::test_nested_todo_indents_under_parent`.

---

## 2026-06-18 — keep embedded URLs (iframes)

Decision: convert Notion embed blocks (`<iframe>` — YouTube, Maps, Figma, etc., sometimes wrapped in a `<figure>`) into a plain link to the embedded URL (`_convert_iframes`, pre-pass). markdownify drops `<iframe>` entirely, so the URL was lost; an iframe with no `src` is removed.
Context: divergence-audit item 32. The HTML render shows the embed; Markdown has no interactive-iframe equivalent, but the destination URL must survive.
Alternatives: try to reconstruct a provider-specific embed (rejected — out of scope, and Obsidian has no native embed for most providers). Trade-off: a live embed becomes a link, not an inline player. Latent in the current test library (0 iframes); built against the general `<iframe>` case with synthetic tests.
Tests: `Notion Database to Obsidian/test_embeds.py` (3 cases).

---

## 2026-06-18 — include empty properties as null

Decision: every property in a database's schema now appears in each note's YAML; a property that is empty for a given entry is emitted as `null` (previously the key was omitted entirely). The same applies to a property whose value converts to nothing (e.g. an emptied tags list).
Context: divergence-audit item 64. Notion shows the column for every row, so omitting empty properties made the property panel inconsistent across notes and could hide a property from Bases on notes where it happens to be blank.
Alternatives: emit empty as `""` (rejected — `null` is the natural "no value" and reads better in Bases); keep omitting (rejected — the flagged divergence). Trade-off: noisier frontmatter (a `null` line per unset property).
Tests: `Notion Database to Obsidian/test_empty_values.py` (`EmptyProperties`).

---

## 2026-06-18 — show the page title as a body heading

Decision: write the Notion page title as an `# H1` at the top of each note's body (in `write_entry`, after the YAML frontmatter). Notion renders the page title at the top of the page; Obsidian shows only the filename, so without this the title was absent from the note's content, previews, exported Markdown, and transclusions/embeds.
Context: divergence-audit item 65 (`test-output/divergence-audit-2026-06-18.md`). The HTML render is the fidelity benchmark, and it shows the title prominently.
Alternatives: rely on Obsidian's "Show inline title" (which displays the filename) only — rejected: the title then never appears in exported Markdown or in embeds of the note.
Trade-off: with "Show inline title" enabled, the title shows twice (the inline title plus the body H1).
Tests: `Notion Database to Obsidian/test_mirrored_processing.py::test_note_body_starts_with_title_heading`.

---

## 2026-06-18 — bookmarks: never drop the URL

Decision: a Notion link bookmark (`<figure><a class="bookmark source">`) now always keeps its URL. Two parts: (1) when the bookmark title is present-but-EMPTY (Notion fetched no page title), fall back to the visible URL → raw href → "Link", instead of emitting an empty link that markdownify dropped — which silently produced a note with no body; (2) for a titled bookmark, also emit the URL as a visible autolink subtitle (`<url>`), matching the HTML bookmark card which shows the URL in addition to the title.
Context: found while testing a real export — a title-less bookmark's URL vanished entirely (7 of 253 entries affected). The HTML render is the fidelity benchmark; the card shows title + description + URL, so hiding the URL behind the title link was a regression.
Alternatives: default the link text to the URL (rejected — a fetched title is more readable; would regress ~246 titled bookmarks to raw-URL text). Trade-offs: the favicon/preview image is still dropped (decorative); the URL subtitle adds one line per titled bookmark.
Tests: `Notion Database to Obsidian/test_bookmark_figures.py` (TDD, 6 cases).

---

## 2026-06-18 — present-but-empty hardening (page title, toggle summary)

Decision: elements that EXIST but are empty now fall back instead of yielding an empty string (`X.get_text() if X else fallback` treated an empty `X` as truthy). (1) An empty `<h1 class="page-title">` falls back to the filename with the Notion id stripped (e.g. `Untitled`), never `""` — an empty title produced broken `[[]]` wikilinks; this also improves the title-absent case (was using the raw filename including the hex id). (2) An empty toggle `<summary>` falls back to `Toggle`.
Context: surfaced by an audit prompted by the bookmark bug ("are there other present-vs-empty checks?"). One real untitled empty page in the test library hit the title case.
Alternatives: none meaningful — these are guard fixes. Trade-offs: none; toggle content was never lost (cosmetic title only). Benign present-but-empty cases left as-is (callout emoji → `[!note]` fallback; `.get(href,"")` guarded by `if not href`).
Tests: `Notion Database to Obsidian/test_empty_values.py` (TDD, 3 cases).

---

## 2026-06-17 — arbitrary-depth nesting, Piece 2: recursive mirrored notes

Decision: replace the depth-limited pipeline (`discover_databases` + inline-table nested DBs) with a recursive, mirrored one. `main()` is now a thin argparse wrapper around a new `run_conversion(src, out_root, ...)` orchestration function; `run_conversion` walks `discover_tree` and writes one real `.md` note per node — every database entry at ANY depth and every standalone page — into an output folder that mirrors its source location, with the Notion hex id stripped from each path component (`mirror_output_dir`). Database index/landing pages are discovered (and counted in the report) but not yet written — they become each database's home note in Piece 3. `process_database` now writes into a caller-supplied mirrored folder and takes the vault-wide wikilink map. A standalone page is just an entry with no properties, so the same writer handles both (no separate page code path). Removed the now-superseded `discover_databases`, `render_nested_db_as_markdown_table`, and `_body_to_cell`.
Context: the old ceiling aborted on databases nested deeper than depth 2 and required a top-level database to exist; nested DBs were flattened into inline GFM tables instead of becoming real notes.
Alternatives: (a) keep DB-name-only output folders (`out/<db>/`) — rejected: loses the nesting structure and can't host per-level `.base` scoping; (b) flatten everything to one folder with path-encoded names — rejected: not graph-friendly, ugly filenames. Chose mirrored layout so the entry-note and its children-folder sit side by side (Obsidian's note+folder pattern).
Trade-offs: copy/symlink attachment modes would `copytree` an owner's source subfolder (which now also holds child-node HTML) and duplicate the subtree — so this piece is verified with `--inplace` (rewrites hrefs, copies nothing); copy/symlink child-vs-attachment separation is deferred to Piece 4 edge work. Per-level `.base`, parent↔child wikilinks/backlinks, and vault-unique filenames are Piece 3 (not yet wired). Because output filenames are de-duplicated per database (not yet vault-wide), two entries with the same title in different mirrored folders that resolve to the same output directory can collide — the safe-write contract writes the second to a `.md.new` sibling (and would overwrite under `--force`); vault-wide unique filenames land in Piece 3. Cosmetic, pre-existing (from `main`): the `types.json` "Updated …" log line lands in the same `overwrite_log` as file-preservation events, so the summary can mislabel an additive types.json merge as "PRESERVED 1 … .new siblings" when nothing was preserved — separate fix.
Tests: `Notion Database to Obsidian/test_mirrored_processing.py` (TDD, 8 cases: note-per-node at every depth incl. beyond the old limit, standalone pages, page-owned DB, note+folder coexistence, body-`<table>` stays a Markdown table, total count). Full suite 65 green. CLI smoke-tested (`--dry-run` writes nothing; `--inplace` produces the 10-note mirrored tree + vault-wide `.base` + `types.json`).

---

## 2026-06-17 — revive Notion highlights (background color → ==)

Decision: wrap inline-content `block-color-*_background` elements in `==` so they become Obsidian highlights (`_convert_highlights`, pre-pass). markdownify has no highlight/`<mark>` support, but literal `==` survives. Block-container backgrounds are skipped (avoid `==` spanning blocks); callouts are excluded (converted earlier).
Why: Notion highlighted text was flattened to plain text.
Limitation: Obsidian's `==` is one highlight style, so Notion's specific colors collapse to a single highlight. Plain text COLORS (no background) are left as-is — Markdown has no native colored text.
Verify: full export regenerated — 730 highlights, no empty/malformed markers.
Tests: `Notion Database to Obsidian/test_highlights.py` (TDD, 6 cases).

---

## 2026-06-17 — preserve code-block languages

Decision: pass a markdownify `code_language_callback` that reads Notion's `<pre><code class="language-XXX">` and opens the fence with that language (```xxx, lowercased), replacing the fixed `code_language=""` that dropped it.
Why: language-less fences lose syntax highlighting in Obsidian.
Tests: `Notion Database to Obsidian/test_code_blocks.py` (TDD, 3 cases).

---

## 2026-06-17 — code-review hardening (callouts, person)

Decision: address red-team findings on the polish branch.
- Callouts: drop the icon, then move ALL remaining figure content into the callout body — a degenerate single-`<div>` callout (icon + content together) no longer loses its body. Standard two-div exports are unchanged.
- Person properties: when a cell has avatar chips but no readable name, return None instead of the raw text (which still carried the doubled avatar initial).
- Dropped redundant `.strip()` in the two tag-property checks (`property_key` already trims).
Tests: added cases to `test_callouts.py` and `test_person_property.py` (43 tests total, all green).

---

## 2026-06-16 — text properties: bare URL instead of a Markdown link

Decision: when a Notion `text` property's value is exactly one hyperlink, emit the bare URL in frontmatter instead of a `[label](url)` Markdown link (`_sole_anchor_href` — detected on the HTML `<td>`, so any URL works, including ones containing `)`). Mixed content (text around a link, multiple links) is left as Markdown.
Why: Obsidian doesn't render Markdown inside YAML frontmatter, so a single-link property came out as the literal string `[label](url)`. The bare URL is clean and usable. (HTML-level detection replaced an earlier regex that missed URLs with parentheses.)
Tests: `Notion Database to Obsidian/test_url_property.py` (TDD, 7 cases).

---

## 2026-06-16 — revive Notion to-do items as Obsidian task lists

Decision: convert Notion to-do items (`<li>` with `<div class="checkbox checkbox-on|off">`) into Markdown task syntax (`_convert_checkboxes`, pre-pass) — `- [x] text` (checked) / `- [ ] text` (unchecked). Adjacent to-do lists merge into one tight task list.
Why: markdownify dropped the checkbox and rendered a plain bullet, losing the checked/unchecked state.
Tests: `Notion Database to Obsidian/test_checkboxes.py` (TDD, 4 cases). Verified on a real export (13 task items in a sample entry).

---

## 2026-06-16 — revive Notion toggles as Obsidian foldable callouts

Decision: convert Notion toggles (`<details>`, exported wrapped in `<ul class="toggle">`) into expanded Obsidian foldable callouts (`_convert_toggles`, pre-pass) — `> [!note]+ Title` (still click-to-collapse). The `<ul class="toggle"><li>` wrapper is dropped when it holds only the toggle, so no stray bullet remains. Always expanded: Notion's export marks every toggle `<details open>`, so the attribute carries no real state; expanded keeps content visible while staying collapsible.
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
