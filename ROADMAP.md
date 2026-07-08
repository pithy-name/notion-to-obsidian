# Roadmap

Larger, not-yet-started ideas. Day-to-day bugs and small enhancements are
tracked in the maintainer's private issue backlog (not part of this repo);
this file is for bigger swings worth recording durably.

## Generic multi-source converter (size: L)

**Idea:** support export sources other than Notion — Roam Research, Craft,
Coda, and similar tools that also export a folder of per-page HTML/Markdown
with rich metadata.

**Why this is an architecture project, not a config flag:** the 32-hex
Notion-id convention (`NOTION_ID_RE`, `strip_notion_id`, `extract_notion_id`)
and Notion's specific HTML export class names (`page`, `page-title`,
`properties`, `page-body`, `collection-content`) aren't just parsing
details — they're **load-bearing for node identity and link resolution**,
not only for reading property values:

- **Node identity.** `assign_unique_names` and the wikilink map key off the
  Notion hex id to guarantee vault-unique filenames and unambiguous
  `[[wikilink]]` resolution across an arbitrarily nested export. Another
  export source won't have this exact id shape (Roam uses its own UID
  format; Craft and Coda have their own conventions), so the uniqueness/
  resolution strategy itself needs to be pluggable, not just the regex.
- **Structural discovery.** `discover_tree`'s classification of an HTML
  file into `entry` / `parent` / `page` is keyed on Notion's specific class
  names (`property-row-{type}`, `collection-content`). A different export
  shape needs its own discovery pass, not a find-and-replace of class
  names — the DB-vs-page-vs-standalone-page distinction itself may not
  map cleanly onto another tool's export model.
- **Property typing.** `convert_property_value`'s type table
  (`property-row-{type}` → Python value) is Notion's own type vocabulary
  (`select`, `multi_select`, `relation`, `rollup`, …). Another source has
  a different property-type vocabulary entirely, not just different class
  names for the same types.

**Recommended shape when this gets picked up:** extract an adapter
interface — something like `discover_tree(src) -> tree`,
`parse_entry(path) -> {title, uuid, properties, body}`,
`extract_node_id(name) -> Optional[str]` — with the current
`notion_db_to_obsidian.py` logic becoming the first (`notion`) adapter
implementation, and `run_conversion` taking an adapter parameter. This is
a genuine refactor of the parsing/identity layer, not a bolt-on flag, and
should get its own design pass (and its own test fixtures per source)
before implementation starts.

## Smaller ideas (not yet sized)

- Resolve `relation` properties to `[[wikilinks]]` when the linked page is
  in the same export (currently emitted as plain title strings).
- Capture page-level icons (emoji/image in the Notion page header) — not
  currently read at all.
- `--flat` output-layout flag, and Windows `MAX_PATH` (260-char) handling
  for very deeply mirrored paths.
- Defang/break live URLs in converted bodies as an opt-in flag (currently
  converted links stay clickable).
