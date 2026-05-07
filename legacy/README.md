# Legacy CSV-merge scripts (reference only)

All three live here since 2026-05-04. They do the same shape of job: take a Notion DB CSV, match each row to its per-page body file, and emit a fatter CSV with a `Body` column. They were intended for use with Obsidian's Importer plugin, which throws away property *types* on the way in. Use `notion_db_to_obsidian.py` instead unless you have a specific reason to stay in CSV-land.

## `merge_notion_db_html.py`

The original script. Outputs **raw HTML** in the Body column. Accepts any folder via CLI, auto-discovers the CSV (same strategy as `merge_notion_db_markdown.py`). Kept as the historical starting point; use `merge_notion_db_markdown.py` for new work since it converts the body to Markdown.

## `merge_notion_db_markdown.py`

Generalized version of the above. Same CSV+HTML inputs, but accepts any folder via CLI, auto-discovers the CSV, handles Notion's filename truncation/punctuation-stripping with prefix matching, and runs the body through `markdownify` so the Body column is **simplified Markdown** instead of raw HTML. Requires `markdownify`.

## `merge_notion_db_from_md.py`

For the case where the Notion export gave you `.md` files instead of `.html`. No conversion needed, no external dependencies. Strips YAML frontmatter from each `.md` by default (since the same fields are already in the CSV); pass `--keep-frontmatter` to retain it. Handles both Notion-style filenames (`Title abc123.md`) and clean ones (`Title.md`).
