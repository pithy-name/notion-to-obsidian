# CLAUDE.md — Recover Notion Databases

Instructions for Claude Code working in this repo.

---

## No PII or personal data in tracked files

- No real names, email addresses, database names, Notion UUIDs, or absolute paths in any tracked file.
- Use placeholders: `<vault-folder>`, `<database-name>`, `<entry-name>`, `<your-path>`, etc.
- This repo is public. Treat every tracked file as visible to anyone.
- To audit all paths ever committed (not just currently tracked): `git log --all --full-history --name-only | sort -u`

## Directory layout

```
Notion Database to Obsidian/   # main script + README
legacy/                        # older merge scripts (kept for reference)
scratchpads/                   # session design notes (gitignored, not tracked)
test-output/                   # gitignored; vault + csv trial outputs live here
```

## Git history rewriting

- **Do not use `git filter-repo`** under any circumstances. It resets the working tree to the rewritten HEAD with no warning, deleting tracked files and discarding all uncommitted changes. It also wipes the reflog and prunes all unreachable objects, leaving no git-native recovery path. If history rewriting is genuinely needed, stop and discuss with the user first.
- **Approved alternative:** orphan branch. `git checkout --orphan <new>` preserves working tree; `git rm --cached -r <path>` unstages what you don't want; `git add -A` + commit = single clean root commit. Delete old branch after. See CHANGELOG for full sequence.

## Commit workflow

- Commit between each logical fix — not per-file, per logical change.
- **Always prompt the user before committing.** Ask "Want me to commit this before we continue?" and wait for confirmation.
- Separate commits for separate concerns. A date-parsing fix and a structural refactor go in different commits even if they touch the same file.
- Git identity is already set in local config: `pithy-name <pithy.name@fastmail.com>`. Do not change it.

## Documentation

- **`CHANGELOG.md`** (repo root) — update with every significant decision. Each entry needs: decision, context, alternatives considered, trade-offs. Dates come from git; don't guess.
- **`README.md`** (repo root) and **`Notion Database to Obsidian/README.md`** — update only when CLI flags, output structure, or user-visible behavior changes. Do not append update chains; those live in CHANGELOG.md. Do not embed session IDs, "maintenance note for Claude" blocks, or any Claude-internal metadata in READMEs — those belong in CLAUDE.md.
- **Scratchpads** — design plans, session notes, post-mortems, or any misc doc worth capturing. Create in `scratchpads/` with naming convention `SCRATCHPAD-YYYY-MM-DD-topic.md`. Directory is gitignored; files are local only, never committed.

## Python environment

- Working runtime: `/usr/bin/python3` (Python 3.9, has `beautifulsoup4` installed at `~/Library/Python/3.9/`).
- `python3` in PATH resolves to Homebrew Python 3.14, which does **not** have `beautifulsoup4`. Do not use it.
- No venv currently. If adding one, use `/usr/bin/python3 -m venv .venv`.
- Dependencies: `beautifulsoup4`, `markdownify`, `pyyaml`.

## Project invariants

- **Zero network access.** The script never fetches URLs. Any change that introduces network calls is a breaking policy change — call it out explicitly.
- **No CSV.** HTML export only. Notion's HTML encodes property types; CSV does not.
- **Single vault-wide `.base`** at the output root. Not one per database.
- **Depth rule:** depth-0 folders → top-level DBs; depth-2 → nested DBs (inline tables); depth ≥ 3 → `sys.exit` with offender list.

## Before committing script changes

1. Run `--dry-run` against a local HTML export and confirm entry/DB counts look right:
   ```bash
   /usr/bin/python3 "Notion Database to Obsidian/notion_db_to_obsidian.py" \
     "test-output/<export-folder>" --dry-run
   ```
2. If the change touches nested DB rendering or body conversion, spot-check a nested-DB entry in the test output.
3. Update `CHANGELOG.md` if the change involves a non-obvious decision.

## Known issues and improvements

**Bugs (unresolved):**
- Image attachments inside embedded DB/table entry bodies don't appear in output.
- Nested tables render at bottom of file, not at original inline position. Puts them out of context when Notion placed the embed mid-document.
- Strikethrough text (`~~text~~`) not converting correctly — appears unstyled in output.
- Rich text styling (indentation, colorized text) largely stripped by `markdownify`. No current workaround.

**Improvements (deferred):**
- Break/defang URLs in output so they don't resolve on accidental click.

**README cleanup (deferred):**
- Add `legacy/README.md` with script descriptions; move legacy script blurbs from root `README.md` there to simplify it.
- Add `fix_frontmatter_dates.py` description to `Notion Database to Obsidian/README.md` (currently only in root README).

## Key architecture notes

- `_TAG_FACTORY = BeautifulSoup("", "html.parser")` — module-level singleton for all `new_tag()` calls. Never call `soup_root.new_tag()` directly; `Tag.__getattr__` intercepts it and returns `None`.
- `parse_entry` returns `{title, notion_uuid, properties, body}`. `body` is the BS4 `<div class="page-body">` tag or `None`.
- Nested DB body-table stripping happens in `write_entry` before `convert_body`, keyed on hex IDs in `nested_db_folder_hexes`. Must strip before conversion or Notion's inline snapshot table duplicates the generated table.
- `parse_notion_date` strips leading `@` before format matching. Fallback in `convert_property_value` also strips `@`.
