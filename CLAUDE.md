# CLAUDE.md — Recover Notion Databases

Instructions for Claude Code working in this repo.

---

## Memory

Project memory (user preferences, conventions, the git-rewriting procedure, prior decisions) lives in `~/.claude/projects/<this-project>/memory/`. **Read `MEMORY.md` at session start and pay close attention to recalled memories** — they carry context not duplicated here.

## No PII or personal data in tracked files

- No real names, email addresses, database names, Notion UUIDs, or absolute paths in any tracked file.
- Use placeholders: `<vault-folder>`, `<database-name>`, `<entry-name>`, `<your-path>`, etc.
- This repo is public. Treat every tracked file as visible to anyone.
- To audit all paths ever committed (not just currently tracked): `git log --all --full-history --name-only | sort -u`

## Directory layout

```
pyproject.toml                        # pip package: notion-to-obsidian (src-layout)
src/notion_to_obsidian/
  __init__.py                         # exports run_conversion
  notion_db_to_obsidian.py            # main script — library entry point + CLI (console script: notion2obsidian)
  fix_frontmatter_dates.py            # maintenance utility (console script: notion2obsidian-fix-dates)
  README.md
  tests/                              # all test_*.py (+ tests/__init__.py sys.path shim)
    synthetic_export.py                # builds synthetic HTML export fixtures for tests; lives here (not the package root) so it's excluded from the wheel
legacy/                               # older CSV-merge scripts + README — NOT packaged/importable
```

## Git history rewriting

- **Never run `git filter-repo`.** It hard-resets the working tree with no warning (deletes tracked *and* uncommitted files), wipes the reflog, and prunes unreachable objects — no git-native recovery. If history rewriting is genuinely needed, stop and ask the user first.
- Safe alternative (orphan-branch procedure): see project memory.

## Commit workflow

- Commit between each logical fix — not per-file, per logical change.
- **Always prompt the user before committing.** Ask "Want me to commit this before we continue?" and wait for confirmation.
- Separate commits for separate concerns. A date-parsing fix and a structural refactor go in different commits even if they touch the same file.

## Documentation

- **`CHANGELOG.md`** (repo root) — update with every significant decision. Each entry needs: decision, context, alternatives considered, trade-offs. Dates come from git; don't guess.
- **`README.md`** (repo root) and **`src/notion_to_obsidian/README.md`** — update only when CLI flags, output structure, or user-visible behavior changes. Do not append update chains; those live in CHANGELOG.md. Do not embed session IDs, "maintenance note for Claude" blocks, or any Claude-internal metadata in READMEs — those belong in CLAUDE.md.

## Python environment

- Working runtime: `/usr/bin/python3` (Python 3.9, has `beautifulsoup4` installed at `~/Library/Python/3.9/`).
- `python3` in PATH resolves to Homebrew Python 3.14, which does **not** have `beautifulsoup4`. Do not use it.
- **Packaged (pip-installable) since the src-layout move.** For a fresh dev/test venv against the console scripts: `/usr/bin/python3 -m venv .venv-dev && .venv-dev/bin/pip install --upgrade pip && .venv-dev/bin/pip install -e .` (the `--upgrade pip` step matters: Python 3.9's bundled pip is 21.2.4, which predates PEP 660 and fails `-e .` on this pyproject-only, setuptools-based layout with no `setup.py` — needs pip >= 21.3; a plain `pip install .`, no `-e`, works on any pip version). This gets you `notion2obsidian` / `notion2obsidian-fix-dates` on `.venv-dev/bin/` and `import notion_to_obsidian` working. Any `.venv*` dir is gitignored — never commit one.
- Dependencies: `beautifulsoup4`, `markdownify`, `pyyaml` (floors pinned in `pyproject.toml`; installed-and-tested-against versions are 4.14.3 / 1.2.2 / 6.0.3 — check with `/usr/bin/python3 -m pip show <name>` before assuming a floor is still accurate).

## Project invariants

- **Zero network access.** The script never fetches URLs. Any change that introduces network calls is a breaking policy change — call it out explicitly.
- **No CSV.** HTML export only. Notion's HTML encodes property types; CSV does not.
- **`.base` files:** one folder-scoped `.base` per database (`file.folder == "<path>"`) **plus** a vault-wide `.base` at the output root.
- **No depth limit, no database required.** Every node (database entry at any depth, standalone page, and database index/landing page — including the export root) becomes its own note in a folder layout that mirrors the export. A node that owns a database is that database's "home" (embeds its `.base`, lists `[[entry]]` links; entries backlink `↑ Part of [[home]]`).

## Before committing script changes

1. Run the test suite from repo root:
   ```bash
   PYTHONPATH=src /usr/bin/python3 -m unittest discover \
     -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
   ```
2. Run `--dry-run` against a local HTML export and confirm entry/DB counts look right:
   ```bash
   /usr/bin/python3 src/notion_to_obsidian/notion_db_to_obsidian.py \
     "<path-to-html-export>" --dry-run
   ```
3. If the change touches nested DB rendering or body conversion, spot-check a nested-DB entry in the test output.
4. Update `CHANGELOG.md` if the change involves a non-obvious decision.

## Key architecture notes

- `_TAG_FACTORY = BeautifulSoup("", "html.parser")` — module-level singleton for all `new_tag()` calls. Never call `soup_root.new_tag()` directly; `Tag.__getattr__` intercepts it and returns `None`.
- `parse_entry` returns `{title, notion_uuid, properties, body}`. `body` is the BS4 `<div class="page-body">` tag or `None`.
- Nested DB body-table stripping happens in `write_entry` before `convert_body`, keyed on hex IDs in `nested_db_folder_hexes`. Must strip before conversion or Notion's inline snapshot table duplicates the generated table.
- `parse_notion_date` strips leading `@` before format matching. Fallback in `convert_property_value` also strips `@`.
