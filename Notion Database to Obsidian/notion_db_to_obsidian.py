#!/usr/bin/env python3
"""
notion_db_to_obsidian.py — Convert a Notion database HTML export
into an Obsidian-compatible folder of .md files with type-aware YAML
frontmatter, plus a starter .base file.

No CSV is required (or used). Property names, types, and values are
extracted from each entry's HTML <table class="properties"> block,
where Notion encodes the property type in the <tr> class name as
`property-row-{type}` (e.g., property-row-multi_select).

ZERO NETWORK ACCESS. All processing is local string/file manipulation.
URLs in the source export are preserved verbatim or rewritten as text;
they are never visited.

Usage:
    python3 notion_db_to_obsidian.py <entries-folder> [-o OUT] [--db-name NAME]

Where <entries-folder> is the folder Notion creates next to the parent
page HTML, containing one .html per database entry plus per-entry
attachment subfolders. Example:
    My Notion Export/My Database abc123/

Dependencies (pip install):
    beautifulsoup4
    markdownify
    pyyaml
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote, unquote

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

try:
    from markdownify import markdownify as html_to_md
except ImportError:
    sys.exit("ERROR: markdownify not installed. Run: pip install markdownify")

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pyyaml not installed. Run: pip install pyyaml")


# Module-level BS4 instance used as a tag factory (Tag.__getattr__ returns
# self.find(name) for unknown attrs, so new_tag must come from BeautifulSoup,
# not a plain Tag, to avoid TypeError: 'NoneType' object is not callable).
_TAG_FACTORY = BeautifulSoup("", "html.parser")

# ---- Notion ID handling ----------------------------------------------------

# Notion appends a 32-char hex ID to filenames and folder names.
NOTION_ID_RE = re.compile(r"\s+([0-9a-f]{32})(?=\.html$|/$|$)", re.IGNORECASE)
# UUID form (used in <article id="..."> attributes).
UUID_DASHED_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def strip_notion_id(name: str) -> str:
    """Remove the trailing 32-char Notion ID from a filename or folder name."""
    return NOTION_ID_RE.sub("", name)


def hex_to_uuid(h: str) -> str:
    """Convert a 32-char hex Notion ID to dashed UUID form."""
    h = h.lower()
    if len(h) != 32:
        return h
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def extract_notion_id(filename: str) -> Optional[str]:
    """Pull the 32-char hex ID out of a Notion-exported filename."""
    m = NOTION_ID_RE.search(filename)
    return m.group(1).lower() if m else None


# ---- Filesystem-safe filenames ---------------------------------------------

# Notion already strips most punctuation, but defend against the residue.
UNSAFE_FS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 200) -> str:
    name = UNSAFE_FS_RE.sub("", name).strip().strip(".")
    return name[:max_len] if name else "Untitled"


# ---- HTML parsing ----------------------------------------------------------


def parse_entry(html_path: Path) -> Optional[Dict[str, Any]]:
    """
    Parse a Notion-exported entry HTML file.

    Returns a dict with: title, notion_uuid, properties (list of (name, type, td_tag)),
    body_tag (a BeautifulSoup Tag for <div class="page-body">, or None).
    Returns None if the file doesn't look like a Notion page.
    """
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")

    article = soup.find("article", class_="page")
    if not article:
        return None

    # Title
    title_tag = article.find("h1", class_="page-title")
    title = title_tag.get_text(strip=True) if title_tag else html_path.stem

    # UUID (article id attribute)
    article_id = article.get("id", "")
    uuid = article_id if UUID_DASHED_RE.match(article_id) else None

    # Properties (in <header><table class="properties">)
    properties: List[Tuple[str, str, Tag]] = []
    props_table = article.find("table", class_="properties")
    if props_table:
        for row in props_table.find_all("tr", class_="property-row"):
            classes = row.get("class", [])
            type_class = next((c for c in classes if c.startswith("property-row-")), None)
            if not type_class:
                continue
            ptype = type_class[len("property-row-"):]
            th = row.find("th")
            td = row.find("td")
            if th is None or td is None:
                continue
            # Strip the icon span from <th> before reading the name.
            for icon in th.find_all("span", class_="icon"):
                icon.decompose()
            pname = th.get_text(strip=True)
            properties.append((pname, ptype, td))

    body = article.find("div", class_="page-body")

    return {
        "path": html_path,
        "title": title,
        "notion_uuid": uuid,
        "properties": properties,
        "body": body,
    }


# ---- Property value conversion --------------------------------------------


def parse_notion_date(text: str) -> Optional[str]:
    """
    Try to parse a Notion-rendered date string into ISO 8601.
    Returns None if no known format matches; caller should fall back to raw text.
    """
    text = text.strip().lstrip("@")
    if not text:
        return None
    # Notion ranges look like "January 2, 2024 → January 5, 2024". Take the first.
    if " → " in text:
        text = text.split(" → ", 1)[0].strip()
    fmts = [
        "%B %d, %Y %I:%M %p",   # April 12, 2022 11:26 AM
        "%B %d, %Y %H:%M",      # April 12, 2022 14:30
        "%B %d, %Y",            # April 12, 2022
        "%m/%d/%Y",             # 04/26/2023 (Notion @-mention date format)
        "%Y-%m-%dT%H:%M",       # already-ISO
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.isoformat() if "%H" in fmt or "%I" in fmt else dt.date().isoformat()
        except ValueError:
            continue
    return None


def td_inner_markdown(td: Tag) -> str:
    """Convert a <td>'s inner HTML to Markdown (for rich text properties)."""
    return html_to_md(td.decode_contents(), heading_style="ATX").strip()


# A property value that is exactly one Markdown link, e.g. "[#chan](https://…)".
_SOLE_MD_LINK_RE = re.compile(r"^\[[^\]]*\]\((https?://[^)\s]+)\)$")


def _unwrap_sole_markdown_link(md: str) -> str:
    """
    If a text-property value is exactly one Markdown link, return the bare URL.

    A Notion `text` property can hold a single hyperlink (e.g. a Slack channel),
    which markdownify renders as `[label](url)`. Inside a YAML frontmatter value
    that link syntax is just noise — Obsidian doesn't render Markdown there — so
    collapse it to the bare URL. Mixed content (text around a link, multiple
    links) is left as-is.
    """
    m = _SOLE_MD_LINK_RE.match(md.strip())
    return m.group(1) if m else md


def convert_property_value(ptype: str, td: Tag) -> Any:
    """
    Convert the value of a Notion property (given its <td> and Notion type)
    into a Python value suitable for YAML frontmatter.

    Returns None for empty cells (so they're omitted from frontmatter).
    """
    raw_text = td.get_text(strip=True)

    # Multi-select: list of tag strings
    if ptype == "multi_select":
        values = [s.get_text(strip=True) for s in td.find_all("span", class_="selected-value")]
        return values or None

    # Single select / status: one string
    if ptype in ("select", "status"):
        span = td.find("span", class_="selected-value")
        if span:
            return span.get_text(strip=True) or None
        return raw_text or None

    # Checkbox: bool
    if ptype == "checkbox":
        # Notion renders checked as ✓ (or sometimes <span class="checkbox checkbox-on">).
        if td.find(class_="checkbox-on"):
            return True
        if td.find(class_="checkbox-off"):
            return False
        return raw_text in ("✓", "Yes", "true", "True", "x", "X")

    # Number
    if ptype == "number":
        if not raw_text:
            return None
        # Strip thousands separators and currency symbols best-effort.
        cleaned = raw_text.replace(",", "").lstrip("$€£¥")
        try:
            n = int(cleaned)
            return n
        except ValueError:
            try:
                return float(cleaned)
            except ValueError:
                return raw_text

    # Date / created_time / last_edited_time
    if ptype in ("date", "created_time", "last_edited_time"):
        if not raw_text:
            return None
        return parse_notion_date(raw_text) or raw_text.lstrip("@")

    # Person-like: created_by, last_edited_by, person.
    # NOTE: mutates `td` (strips avatar icon spans). Safe — each td is converted
    # once. Each <span class="user"> holds an avatar icon whose text is the
    # name's initial, then the name itself — so a naive get_text() yields the
    # initial doubled ("JJane Doe"). Strip the icon span first (same as
    # parse_entry does for property names) before reading each user's name.
    if ptype in ("created_by", "last_edited_by", "person"):
        user_spans = td.find_all(class_="user")
        if user_spans:
            users = []
            for u in user_spans:
                for icon in u.find_all("span", class_="icon"):
                    icon.decompose()
                name = u.get_text(strip=True)
                if name:
                    users.append(name)
            # Had user chips but no readable names: return None, NOT raw_text —
            # raw_text still carries the doubled avatar initial.
            if not users:
                return None
            return users[0] if len(users) == 1 else users
        return raw_text or None

    # File property: list of relative or external URLs
    if ptype == "file":
        hrefs = [unquote(a.get("href", "")) for a in td.find_all("a") if a.get("href")]
        return hrefs or None

    # URL / email / phone: string
    if ptype in ("url", "email", "phone_number"):
        return raw_text or None

    # Relation: list of titles of linked pages (network is NEVER accessed)
    if ptype == "relation":
        titles = [a.get_text(strip=True) for a in td.find_all("a") if a.get_text(strip=True)]
        if titles:
            return titles
        return raw_text or None

    # Formula / rollup: just the rendered display value
    if ptype in ("formula", "rollup"):
        return raw_text or None

    # Rich text / title: preserve formatting via Markdown. If the whole value
    # is a single hyperlink, emit the bare URL (a `[label](url)` Markdown link
    # is not useful inside a YAML frontmatter value).
    if ptype in ("text", "title", "rich_text"):
        md = td_inner_markdown(td)
        if not md:
            return None
        return _unwrap_sole_markdown_link(md)

    # Unknown type: preserve raw text and let the user inspect.
    return raw_text or None


# ---- YAML frontmatter ------------------------------------------------------


class _IndentedDumper(yaml.SafeDumper):
    """
    YAML dumper that indents list items under their parent key, e.g.:
        tags:
          - foo
          - bar
    rather than the unindented default. Some YAML parsers (and Obsidian's
    frontmatter handling, anecdotally) are happier with the indented form.
    """
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def _ordered_dict_representer(dumper, d):
    return dumper.represent_mapping("tag:yaml.org,2002:map", d.items())


_IndentedDumper.add_representer(OrderedDict, _ordered_dict_representer)


def yaml_dump_frontmatter(data: "OrderedDict[str, Any]") -> str:
    """
    Serialize a dict to YAML suitable for use as Markdown frontmatter.
    - Preserves insertion order.
    - Uses block style for lists (one item per line, indented).
    - Avoids unnecessary quoting.
    """
    if not data:
        return ""
    body = yaml.dump(
        data,
        Dumper=_IndentedDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10**9,  # don't line-wrap long strings
        indent=2,
    )
    return f"---\n{body}---\n"


def property_key(name: str) -> str:
    """
    The frontmatter key for a Notion property: the original property name,
    preserved verbatim (only surrounding whitespace trimmed).

    Earlier versions lower_snake_cased this ("Created time" -> created_time,
    "Tester(s)" -> tester_s), which read poorly and — more importantly — broke
    Obsidian Bases built around the original Notion property names. Obsidian
    property names and Bases columns tolerate spaces and punctuation, and YAML
    quotes keys with special characters as needed, so the original name is both
    safe and what users expect. The tag property is matched case-insensitively
    by callers, so case is preserved here.
    """
    return name.strip() or "property"


def sanitize_obsidian_tag(s: str) -> str:
    """
    Make a string a valid Obsidian tag value.
    Obsidian tags allow letters, digits, _, -, / (for nested tags).
    Whitespace is replaced with hyphens; other characters (parens,
    commas, dots, etc.) are stripped. Case is preserved.
    Returns "" if nothing valid remains.
    """
    s = (s or "").strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^A-Za-z0-9_/\-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


# ---- Body HTML → Markdown --------------------------------------------------


def _clean_bookmark_figures(body_tag: Tag) -> None:
    """
    Notion's link-bookmark blocks export as <figure><a class="bookmark source">…</a></figure>
    with title, description, favicon, and og:image nested inside the <a>. Markdownify
    turns this into an unreadable mess. Replace each with a clean
        <p><strong><a href="URL">Title</a></strong></p>
        <blockquote><p>Description</p></blockquote>
    so markdownify produces tidy output.
    """
    for fig in body_tag.find_all("figure"):
        a = fig.find("a", class_=lambda c: c and "bookmark" in c)
        if not a:
            continue
        href = a.get("href", "")
        title_div = a.find("div", class_="bookmark-title")
        desc_div = a.find("div", class_="bookmark-description")
        title = title_div.get_text(strip=True) if title_div else (href or "Link")
        desc = desc_div.get_text(strip=True) if desc_div else ""

        new_p = _TAG_FACTORY.new_tag("p")
        strong = _TAG_FACTORY.new_tag("strong")
        link = _TAG_FACTORY.new_tag("a", href=href)
        link.string = title
        strong.append(link)
        new_p.append(strong)

        replacement_nodes = [new_p]
        if desc:
            bq = _TAG_FACTORY.new_tag("blockquote")
            bq_p = _TAG_FACTORY.new_tag("p")
            bq_p.string = desc
            bq.append(bq_p)
            replacement_nodes.append(bq)

        # Replace the figure with the new nodes.
        fig.replace_with(*replacement_nodes)


# File extensions Obsidian renders inline when used with the ![alt](path)
# Markdown embed syntax. PDFs render as an inline PDF viewer; images, audio,
# and video render in their respective players. Anything else falls back to a
# plain link.
EMBEDDABLE_EXTS = {
    # Images
    "png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "avif",
    # Audio
    "mp3", "wav", "m4a", "ogg", "flac", "3gp",
    # Video
    "mp4", "webm", "ogv", "mov", "mkv",
    # PDF
    "pdf",
}


def _clean_source_figures(body_tag: Tag) -> None:
    """
    Local-file figures export as <figure><div class="source"><a href="local/path.pdf">
    https://s3-…/file.pdf</a></div></figure> — the visible text is the original S3 URL,
    not the filename.

    Replace with an Obsidian-style INLINE EMBED for media types Obsidian can
    render in place (PDFs, images, audio, video) — i.e., produce an <img> tag
    so markdownify emits `![filename](path)`. For non-embeddable types,
    fall back to a plain `<a>` link.
    """
    for fig in body_tag.find_all("figure"):
        if fig.parent is None:
            continue
        src_div = fig.find("div", class_="source")
        if not src_div:
            continue
        a = src_div.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        decoded = unquote(href)
        # Only rewrite for local-relative paths (no scheme).
        if decoded.startswith(("http://", "https://", "mailto:", "#")):
            continue
        filename = decoded.rsplit("/", 1)[-1] or decoded
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        new_p = _TAG_FACTORY.new_tag("p")

        if ext in EMBEDDABLE_EXTS:
            # <img> ⇒ markdownify emits ![alt](src), which Obsidian inlines.
            new_img = _TAG_FACTORY.new_tag("img")
            new_img["src"] = href
            new_img["alt"] = filename
            new_p.append(new_img)
        else:
            new_a = _TAG_FACTORY.new_tag("a", href=href)
            new_a.string = filename
            new_p.append(new_a)

        fig.replace_with(new_p)


# Notion callout icons (emoji) → Obsidian callout types. Unmapped icons fall
# back to [!note]; the emoji is always kept in the callout title so nothing is
# lost.
_CALLOUT_EMOJI_TYPE = {
    "💡": "tip", "🔥": "tip",
    "⚠️": "warning", "⚠": "warning", "❗": "warning", "❕": "warning", "🚨": "warning",
    "ℹ️": "info", "ℹ": "info",
    "✅": "success", "✔️": "success", "☑️": "success",
    "❌": "failure", "🚫": "failure",
    "🐛": "bug",
    "❓": "question", "❔": "question",
    "📝": "note", "📌": "note", "📍": "note",
}


def _convert_callouts(body_tag: Tag) -> None:
    """
    Convert Notion callout blocks into Obsidian callouts.

    Notion exports a callout as
        <figure class="… callout"><div>[emoji icon]</div><div>[content]</div></figure>
    which markdownify would otherwise flatten to a stray emoji line plus loose
    content. Turn each into a <blockquote> whose first line is `[!type] emoji`,
    so markdownify emits an Obsidian callout:
        > [!tip] 💡
        > content
    The emoji maps to a callout type where recognized (else `note`) and is
    always preserved in the title.
    """
    for fig in body_tag.find_all("figure", class_=lambda c: c and "callout" in c):
        if fig.parent is None:
            continue
        icon_span = fig.find("span", class_="icon")
        emoji = icon_span.get_text(strip=True) if icon_span else ""
        ctype = _CALLOUT_EMOJI_TYPE.get(emoji, "note")

        # Drop the icon (and its now-empty wrapper div), then move everything
        # that remains into the callout body. This handles the standard
        # two-div layout AND the degenerate single-div case (icon and content
        # in one div) without losing content.
        if icon_span is not None:
            wrapper = icon_span.parent
            icon_span.decompose()
            if (
                wrapper is not None
                and wrapper is not fig
                and not wrapper.find(True)
                and not wrapper.get_text(strip=True)
            ):
                wrapper.decompose()

        bq = _TAG_FACTORY.new_tag("blockquote")
        title = _TAG_FACTORY.new_tag("p")
        title.string = f"[!{ctype}]" + (f" {emoji}" if emoji else "")
        bq.append(title)
        for child in list(fig.contents):
            bq.append(child.extract())
        fig.replace_with(bq)


def _convert_toggles(body_tag: Tag) -> None:
    """
    Convert Notion toggles into Obsidian foldable callouts.

    Notion exports a toggle as
        <ul class="toggle"><li><details [open]><summary>Title</summary>…body…</details></li></ul>
    (toggle headings export as a bare <details>). markdownify drops the
    collapse and flattens it to a plain bullet. Turn each <details> into a
    foldable callout that stays click-to-expand:
        > [!note]- Title
        > body
    Always collapsed (`[!note]-`): Notion's HTML export marks every toggle as
    <details open>, so that attribute carries no usable collapsed/expanded
    state — defaulting to collapsed matches a toggle's click-to-expand purpose.
    When the toggle is the sole item of its `<ul class="toggle">` wrapper, the
    wrapper (and its bullet) is dropped; otherwise only the <details> is
    replaced, preserving any sibling list items.
    """
    for details in body_tag.find_all("details"):
        if details.parent is None:
            continue
        summary = details.find("summary")
        title = summary.get_text(strip=True) if summary else "Toggle"
        if summary is not None:
            summary.extract()
        bq = _TAG_FACTORY.new_tag("blockquote")
        title_p = _TAG_FACTORY.new_tag("p")
        title_p.string = f"[!note]- {title}".rstrip()
        bq.append(title_p)
        for child in list(details.contents):
            bq.append(child.extract())

        # Drop the `<ul class="toggle"><li>` wrapper when it holds only this
        # toggle, so we don't emit a stray bullet around the callout.
        li = details.parent if details.parent.name == "li" else None
        ul = li.parent if li and li.parent and li.parent.name == "ul" \
            and any("toggle" in c for c in (li.parent.get("class") or [])) else None
        if ul is not None and len(ul.find_all("li", recursive=False)) == 1:
            ul.replace_with(bq)
        else:
            details.replace_with(bq)


def _convert_checkboxes(body_tag: Tag) -> None:
    """
    Convert Notion to-do items into Obsidian task-list items.

    Notion exports a to-do as
        <ul class="to-do-list"><li><div class="checkbox checkbox-on|off"></div>
            <span class="to-do-children-…">text</span></li></ul>
    markdownify drops the checkbox and renders a plain bullet. Replace the
    checkbox marker with Markdown task syntax so the item becomes `- [x] text`
    (checked) or `- [ ] text` (unchecked). Adjacent to-do lists are then merged
    into one tight task list by _merge_adjacent_lists.
    """
    for li in body_tag.find_all("li"):
        # Only this item's own checkbox (direct child) — nested to-dos are their
        # own <li>s and get handled on their own iteration.
        cb = li.find("div", class_=lambda c: c and "checkbox" in c, recursive=False)
        if cb is None:
            continue
        checked = any("checkbox-on" in c for c in (cb.get("class") or []))
        cb.decompose()
        li.insert(0, NavigableString("[x] " if checked else "[ ] "))


_LIST_TAGS = ("ul", "ol")


def _merge_adjacent_lists(root: Tag) -> None:
    """
    Merge runs of adjacent same-kind sibling <ul>/<ol> into a single list.

    Notion exports every bullet and every numbered item as its OWN
    single-item list element (e.g. a run of `<ul class="bulleted-list">`s,
    one per bullet; numbered items as `<ol class="numbered-list" start="N">`).
    markdownify renders each list element as a separate block, so consecutive
    single-item lists come out as a "loose" list — a blank line between every
    item. Collapsing them into one list element makes markdownify emit a tight
    list instead.

    "Same kind" = same tag name AND identical class attribute, so bulleted,
    numbered, to-do, and toggle lists never merge into one another. A run is
    only joined when the lists are *immediately* adjacent (only inter-element
    whitespace between them); any real content (text, <p>, a heading) ends the
    run, preserving genuinely separate lists. Runs nested inside <li>s are
    handled too, since every list in the tree is visited.
    """
    for lst in root.find_all(_LIST_TAGS):
        if lst.parent is None:
            continue  # already absorbed into an earlier sibling this pass
        kind = (lst.name, tuple(lst.get("class") or []))
        sib = lst.next_sibling
        while sib is not None:
            nxt = sib.next_sibling
            if isinstance(sib, NavigableString):
                if sib.strip() == "":
                    sib = nxt  # skip whitespace between sibling lists
                    continue
                break  # real text between the lists — leave them separate
            if not isinstance(sib, Tag):
                break
            if (sib.name, tuple(sib.get("class") or [])) != kind:
                break  # a different kind of list (or any other element)
            # Same-kind adjacent list: move its <li>s in, then drop the husk.
            for li in sib.find_all("li", recursive=False):
                lst.append(li.extract())
            sib.decompose()
            sib = nxt


def convert_body(
    body_tag: Optional[Tag],
    *,
    entry_attachment_dir_basename: Optional[str],
    new_attachment_dir_basename: Optional[str],
    wikilink_map: Dict[str, str],
    inplace_link_prefix: Optional[str] = None,
) -> str:
    """
    Convert the <div class="page-body"> tag into Markdown.

    Pre-passes on the soup before markdownify:
      - Strip the leading properties table if any.
      - Replace bookmark <figure> blocks with clean title-link + description quote.
      - Replace local-file source <figure> blocks with [filename](path) links.
      - Rewrite <a href="OldFolder%20uuid/file.pdf"> → "NewFolder/file.pdf".
      - Rewrite <a href="OtherEntry%20uuid.html">Title</a> → [[Title]].

    `inplace_link_prefix` (inplace attachment mode only): every local href in a
    Notion export is relative to the shared source-entries folder — whether it
    targets this entry's own attachment dir or a SIBLING entry's (cross-entry
    references). When set, this relpath (output dir → source folder) is prefixed
    onto every local href, so same-entry AND cross-entry attachments resolve to
    the real files in the source export. When None, the copy/symlink behavior
    applies (only this entry's own folder is rewritten).
    """
    if body_tag is None:
        return ""

    # Drop any nested properties table (defensive — usually in <header>, not body).
    for t in body_tag.find_all("table", class_="properties"):
        t.decompose()

    # Clean Notion's special figure blocks BEFORE generic link rewrites,
    # so we don't have to deal with their nested mess later.
    _clean_bookmark_figures(body_tag)
    _clean_source_figures(body_tag)

    # Notion callouts (<figure class="callout">) → Obsidian `> [!type]` callouts.
    _convert_callouts(body_tag)

    # Notion toggles (<details>) → Obsidian foldable callouts `> [!note]-`.
    _convert_toggles(body_tag)

    # Notion to-do items → Obsidian task list items `- [ ]` / `- [x]`.
    _convert_checkboxes(body_tag)

    # Notion emits one <ul>/<ol> per bullet/number; merge adjacent same-kind
    # lists so markdownify renders tight lists, not blank-line-separated ones.
    _merge_adjacent_lists(body_tag)

    # Rewrite attachment paths and resolve in-export wikilinks.
    # IMPORTANT: paths in markdown ![](path) and [](path) syntax must be
    # URL-encoded; literal spaces break parsing (Obsidian truncates the
    # URL at the first whitespace and tries to treat the leading word as
    # a wikilink target). Use quote(..., safe="/") to keep path separators
    # readable while encoding spaces and other special characters.
    for a in body_tag.find_all("a"):
        href = a.get("href", "")
        if not href:
            continue
        decoded = unquote(href)

        # External or anchor links: leave alone (NEVER visited).
        if decoded.startswith(("http://", "https://", "mailto:", "#")):
            continue

        # Link to another entry in the same database? -> [[wikilink]].
        # Keys in wikilink_map are decoded relative paths like "Some Title uuid.html".
        # Checked before any attachment rewrite so .html links never become paths.
        if decoded in wikilink_map:
            a.replace_with(f"[[{wikilink_map[decoded]}]]")
            continue

        # Inplace mode: prefix the relpath to the source export onto every local
        # href, so this entry's own AND sibling entries' attachments resolve.
        if inplace_link_prefix is not None:
            a["href"] = quote(f"{inplace_link_prefix}/{decoded}", safe="/")
            continue

        # copy/symlink: rewrite only this entry's own attachment folder.
        if (
            entry_attachment_dir_basename
            and new_attachment_dir_basename
            and decoded.startswith(entry_attachment_dir_basename + "/")
        ):
            tail = decoded[len(entry_attachment_dir_basename) + 1:]
            new_rel = f"{new_attachment_dir_basename}/{tail}"
            a["href"] = quote(new_rel, safe="/")
            continue

    # Rewrite <img src=...> the same way for local files.
    for img in body_tag.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        decoded = unquote(src)
        if decoded.startswith(("http://", "https://", "data:")):
            continue
        # Inplace mode: prefix the relpath to the source export (same- and
        # cross-entry images both resolve to the real exported files).
        if inplace_link_prefix is not None:
            img["src"] = quote(f"{inplace_link_prefix}/{decoded}", safe="/")
            continue
        if (
            entry_attachment_dir_basename
            and new_attachment_dir_basename
            and decoded.startswith(entry_attachment_dir_basename + "/")
        ):
            tail = decoded[len(entry_attachment_dir_basename) + 1:]
            img["src"] = quote(f"{new_attachment_dir_basename}/{tail}", safe="/")

    md = html_to_md(
        body_tag.decode_contents(),
        heading_style="ATX",
        bullets="-",
        code_language="",
    )
    # Clean up extra blank lines markdownify can leave behind.
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


# ---- Schema discovery ------------------------------------------------------


def discover_schema(entries: List[Dict[str, Any]]) -> "OrderedDict[str, Dict[str, Any]]":
    """
    Walk all parsed entries, build a schema:
      {pname: {"types": Counter(), "first_seen_order": int}}
    Property order is the order of first appearance across entries.
    """
    schema: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for entry in entries:
        for pname, ptype, _td in entry["properties"]:
            if pname not in schema:
                schema[pname] = {"types": Counter(), "key": property_key(pname)}
            schema[pname]["types"][ptype] += 1
    return schema


def warn_schema_drift(schema: "OrderedDict[str, Dict[str, Any]]") -> List[str]:
    """Return a list of warning strings for properties with multiple types."""
    warnings = []
    for pname, info in schema.items():
        if len(info["types"]) > 1:
            breakdown = ", ".join(f"{t}={c}" for t, c in info["types"].most_common())
            warnings.append(f"  - {pname!r}: types vary across entries ({breakdown})")
    return warnings


# ---- Safe write (collision-aware) ------------------------------------------


def safe_write_text(
    path: Path,
    content: str,
    *,
    force: bool,
    overwrite_log: List[str],
    kind: str,
    dry_run: bool = False,
) -> Path:
    """
    Write `content` to `path`, but never silently clobber an existing file.

    Behavior:
      - If `path` does not exist: write normally; nothing logged.
      - If `path` exists and force=False (default): write to a sibling whose
        name has `.new` appended (e.g. `MyDB.base` → `MyDB.base.new`,
        `Entry.md` → `Entry.md.new`) so the existing file is preserved.
        The collision is recorded in `overwrite_log`.
      - If `path` exists and force=True: overwrite the existing file. The
        overwrite is recorded in `overwrite_log`.

    `kind` is a short label (e.g. ".base", ".md") used in log messages.

    Returns the path that was actually written to.
    """
    if path.exists():
        if force:
            if not dry_run:
                path.write_text(content, encoding="utf-8")
            overwrite_log.append(
                f"{'WOULD OVERWRITE' if dry_run else 'OVERWROTE'} existing "
                f"{kind}: `{path.name}` (--force)."
            )
            # Clean up the corresponding stale `.new` sibling from a prior
            # safe-mode run. Only clean up the exact `<path>.new` that pairs
            # with this file — never touch unrelated `.new` files.
            stale_new = path.with_name(path.name + ".new")
            if stale_new.exists() and stale_new.is_file():
                if not dry_run:
                    stale_new.unlink()
                overwrite_log.append(
                    f"{'WOULD REMOVE' if dry_run else 'REMOVED'} stale "
                    f"`{stale_new.name}` from prior safe-mode run (--force cleanup)."
                )
            return path
        # Safe mode: preserve original, write new content to <name>.new.
        new_path = path.with_name(path.name + ".new")
        if not dry_run:
            new_path.write_text(content, encoding="utf-8")
        overwrite_log.append(
            f"{'WOULD SKIP' if dry_run else 'SKIPPED'} overwrite of {kind} "
            f"`{path.name}`; new content "
            f"{'would be written' if dry_run else 'written'} to "
            f"`{new_path.name}` (re-run with --force to overwrite, or diff and "
            f"merge by hand)."
        )
        return new_path
    if not dry_run:
        path.write_text(content, encoding="utf-8")
    return path


# ---- .base file generation -------------------------------------------------


def emit_base_file(
    out_path: Path,
    schema: "OrderedDict[str, Dict[str, Any]]",
    *,
    force: bool,
    overwrite_log: List[str],
    dry_run: bool = False,
) -> None:
    """
    Write a starter .base file: table view with one column per discovered
    property. Covers all .md files in the vault (no folder scope).
    Disposable — user can replace via Obsidian's UI (right-click → "New base").

    Honors the safe-write contract: an existing `.base` file is preserved by
    default (new content lands in `<name>.base.new`); `force=True` overwrites.
    """
    order = ["file.name"] + [info["key"] for info in schema.values()]
    base_doc = OrderedDict()
    # Filter: .md only — excludes attachments (PDFs etc.) in entry subfolders.
    base_doc["filters"] = OrderedDict([
        ("and", [
            'file.ext == "md"',
        ])
    ])
    base_doc["views"] = [
        OrderedDict([
            ("type", "table"),
            ("name", "All entries"),
            ("order", order),
        ])
    ]
    content = yaml.dump(
        base_doc,
        Dumper=_IndentedDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10**9,
        indent=2,
    )
    safe_write_text(
        out_path, content,
        force=force, overwrite_log=overwrite_log, kind=".base", dry_run=dry_run,
    )


# ---- .obsidian/types.json generation ---------------------------------------

# Map Notion property types to Obsidian property types
# (https://help.obsidian.md/properties#Property+types).
# Obsidian's Bases respects types declared in `.obsidian/types.json` and
# does NOT reliably auto-detect ISO 8601 datetime values from raw YAML, so
# explicit declaration is required for date/datetime columns to behave as
# date/datetime rather than text in Bases. Lesson learned from testing.
NOTION_TO_OBSIDIAN_TYPE = {
    "date":             "datetime",
    "created_time":     "datetime",
    "last_edited_time": "datetime",
    "multi_select":     "multitext",
    "select":           "text",
    "status":           "text",
    "checkbox":         "checkbox",
    "number":           "number",
    "text":             "text",
    "title":            "text",
    "rich_text":        "text",
    "url":              "text",
    "email":            "text",
    "phone_number":     "text",
    "person":           "multitext",
    "created_by":       "text",
    "last_edited_by":   "text",
    "file":             "multitext",
    "relation":         "multitext",
    "formula":          "text",
    "rollup":           "text",
}


def obsidian_type_for(key: str, ptype: str) -> str:
    """
    Map a Notion property (property-name key + Notion type) to an Obsidian
    property type. A "tags" property (matched case-insensitively, e.g. Notion's
    "Tags") is special-cased to Obsidian's `tags` type (which feeds the global
    #tag system) when the source is a multi-select; otherwise it falls back to
    the type-table.
    """
    if key.lower() == "tags" and ptype == "multi_select":
        return "tags"
    return NOTION_TO_OBSIDIAN_TYPE.get(ptype, "text")


def emit_types_json(
    out_root: Path,
    schema: "OrderedDict[str, Dict[str, Any]]",
    *,
    force: bool,
    overwrite_log: List[str],
    dry_run: bool = False,
) -> None:
    """
    Emit (or merge into) `<vault>/.obsidian/types.json` so Obsidian Bases
    types each property correctly instead of falling back to text.

    Behavior:
      - If the file doesn't exist: write a fresh one.
      - If the file exists: load it, add ONLY keys we don't have. Never
        clobber existing entries (those are user choices). Re-write only
        if we'd add new keys; otherwise leave the file alone.
      - `force=True` is honored only for collisions on keys we'd be
        adding from scratch — we still don't overwrite existing keys.
    """
    if not schema:
        return
    types_path = out_root / ".obsidian" / "types.json"
    if not dry_run:
        types_path.parent.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Any] = {}
    if types_path.exists():
        try:
            existing = json.loads(types_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable — preserve original by writing to .new
            existing = {}
            corrupt = True
        else:
            corrupt = False
    else:
        corrupt = False

    types_map = existing.get("types", {}) if isinstance(existing, dict) else {}
    if not isinstance(types_map, dict):
        types_map = {}

    added: List[str] = []
    for pname, info in schema.items():
        key = info["key"]
        if key in types_map:
            continue  # never clobber user choices
        dominant_ptype = info["types"].most_common(1)[0][0]
        otype = obsidian_type_for(key, dominant_ptype)
        types_map[key] = otype
        added.append(f"{key}={otype}")

    if not added and not corrupt:
        # Nothing to add and existing file is fine.
        return

    new_doc = existing if isinstance(existing, dict) else {}
    new_doc["types"] = types_map
    content = json.dumps(new_doc, indent=2) + "\n"

    if corrupt:
        # Preserve the original (unreadable) file by writing alongside.
        safe_write_text(
            types_path, content, force=force, overwrite_log=overwrite_log,
            kind=".obsidian/types.json", dry_run=dry_run,
        )
        return

    # Surgical append — write back even if file existed; we've already
    # verified we're only adding keys, not changing existing ones.
    if not dry_run:
        types_path.write_text(content, encoding="utf-8")
    if added:
        overwrite_log.append(
            f"{'WOULD UPDATE' if dry_run else 'Updated'} `.obsidian/types.json` "
            f"(added {len(added)}: {', '.join(added)})."
        )


# ---- Main pipeline ---------------------------------------------------------


def build_wikilink_map(entries: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Build {decoded relative href → Obsidian title} so links between entries
    in the same export resolve to [[wikilinks]] in the output.
    """
    m: Dict[str, str] = {}
    for entry in entries:
        rel = entry["path"].name  # e.g., "Title abc123…html"
        m[unquote(rel)] = entry["title"]
    return m


def _body_to_cell(body_tag) -> str:
    """Extract plain text from a page-body tag for use in a table cell."""
    if body_tag is None:
        return ""
    text = body_tag.get_text(separator=" ", strip=True)
    # Escape backslash first, then GFM metacharacters that render inside cells.
    for ch in ("\\", "|", "*", "_", "`", "[", "]"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", " ").replace("\r", "")


def render_nested_db_as_markdown_table(
    entries: List[Dict[str, Any]],
    schema: "OrderedDict[str, Dict[str, Any]]",
    db_name: str,
) -> str:
    """
    Render a nested DB's entries as a GFM markdown table under a heading.
    Columns: entry title, all Notion property columns, then Notes (body text).
    Pipe chars in cell values are escaped so the table stays valid.
    """
    if not entries or not schema:
        return ""
    prop_headers = list(schema.keys())
    headers = ["Topic"] + prop_headers + ["Notes"]
    lines: List[str] = [f"### {db_name}", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for entry in entries:
        entry_props: Dict[str, Tuple[str, Tag]] = {
            p[0]: (p[1], p[2]) for p in entry["properties"]
        }
        title_cell = (entry.get("title") or "").replace("|", "\\|").replace("\n", " ")
        row: List[str] = [title_cell]
        for pname, info in schema.items():
            if pname not in entry_props:
                row.append("")
                continue
            _, td = entry_props[pname]
            dominant_type = info["types"].most_common(1)[0][0]
            value = convert_property_value(dominant_type, td)
            if value is None:
                cell = ""
            elif isinstance(value, list):
                cell = ", ".join(str(v) for v in value)
            else:
                cell = str(value)
            cell = cell.replace("|", "\\|").replace("\n", " ").replace("\r", "")
            row.append(cell)
        row.append(_body_to_cell(entry.get("body")))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def write_entry(
    entry: Dict[str, Any],
    out_dir: Path,
    schema: "OrderedDict[str, Dict[str, Any]]",
    wikilink_map: Dict[str, str],
    used_filenames: Dict[str, int],
    *,
    extra_tables: Optional[List[str]] = None,
    nested_db_folder_hexes: Optional[Set[str]] = None,
    force: bool,
    overwrite_log: List[str],
    attachment_mode: str = "copy",
    dry_run: bool = False,
) -> Tuple[Path, List[str]]:
    """
    Write one entry's .md file and copy its attachments. Returns (md_path, warnings).

    Honors the safe-write contract for the .md file: an existing .md is
    preserved by default (new content lands in `<name>.md.new`); `force=True`
    overwrites. Attachment-directory collisions retain the existing
    behavior (preserve existing, warn).

    `attachment_mode` controls how each entry's attachment dir is materialized
    in the output:
      - "copy" (default): full copy via shutil.copytree. Doubles disk usage.
      - "symlink": create a symlink in the output that points at the source
        attachment dir's absolute path. Zero extra disk usage; new md hrefs
        reference `<NewDB>/<Entry>/file.pdf` and resolve through the symlink.
        Breaks if the source is later moved/deleted. Filesystem-level tested
        2026-05-05; Obsidian render not yet verified.
      - "inplace": no output-side directory or symlink is created. Md hrefs
        are rewritten to point at the source attachment dir via a relative
        path from the new md file's parent directory. Zero extra disk usage.
        Breaks if the source is later moved/deleted. Filesystem-level tested
        2026-05-05; Obsidian render not yet verified.
    """
    warnings: List[str] = []

    # Choose the output filename. Disambiguate collisions by appending the
    # short Notion ID (last 6 hex chars) if needed.
    base_name = sanitize_filename(entry["title"])
    candidate = base_name
    if base_name in used_filenames:
        used_filenames[base_name] += 1
        suffix = (extract_notion_id(entry["path"].name) or "")[-6:]
        if suffix:
            candidate = f"{base_name} ({suffix})"
        else:
            candidate = f"{base_name} ({used_filenames[base_name]})"
        warnings.append(f"Filename collision on {base_name!r}, wrote as {candidate!r}")
    else:
        used_filenames[base_name] = 1

    md_path = out_dir / f"{candidate}.md"

    # Attachment folder handling depends on attachment_mode.
    #   "copy"    — full copy of the source dir into the output (default,
    #               doubles disk usage).
    #   "symlink" — symlink in the output pointing at the source dir's
    #               absolute path. Zero extra disk; breaks if source moves.
    #   "inplace" — no output-side dir or symlink at all; md hrefs are
    #               rewritten to point at the source via a relative path
    #               from the new md file's parent dir. Zero extra disk;
    #               breaks if source moves.
    src_attach_dir = entry["path"].with_suffix("")  # strip .html
    new_attach_basename: Optional[str] = None
    src_attach_basename: Optional[str] = None
    if src_attach_dir.is_dir():
        src_attach_basename = src_attach_dir.name  # original "Title abc123" (encoded form used in hrefs is URL-quoted)

        if attachment_mode == "inplace":
            # No dest dir or symlink. Compute the relative path from the
            # new md file's parent (out_dir) up/over to the source attachment
            # dir, and pass it through as the "new basename" for href rewrite.
            # The existing rewrite path uses quote(..., safe="/") which
            # URL-encodes spaces while preserving the path separators.
            new_attach_basename = os.path.relpath(
                src_attach_dir.resolve(), out_dir.resolve()
            )
            if dry_run:
                overwrite_log.append(
                    f"WOULD REWRITE hrefs in `{candidate}.md` to point at "
                    f"`{new_attach_basename}/...` (inplace mode; no output-side "
                    f"attachment dir created)."
                )
        else:
            # copy or symlink: clean title becomes the new basename.
            new_attach_basename = candidate
            dest_attach = out_dir / candidate
            # `is_symlink()` returns True for broken symlinks (where .exists()
            # is False), so check both to detect any existing target.
            target_exists = dest_attach.exists() or dest_attach.is_symlink()
            if target_exists:
                if force:
                    # Remove whatever is there (file, symlink, or directory)
                    # before recreating in the requested mode.
                    if not dry_run:
                        if dest_attach.is_symlink() or dest_attach.is_file():
                            dest_attach.unlink()
                        else:
                            shutil.rmtree(dest_attach)
                    if attachment_mode == "symlink":
                        if not dry_run:
                            dest_attach.symlink_to(src_attach_dir.resolve())
                        overwrite_log.append(
                            f"{'WOULD OVERWRITE' if dry_run else 'OVERWROTE'} "
                            f"existing target with symlink: `{dest_attach.name}` "
                            f"→ `{src_attach_dir.resolve()}` "
                            f"(--force, --symlink-attachments)."
                        )
                    else:  # copy
                        if not dry_run:
                            shutil.copytree(src_attach_dir, dest_attach)
                        overwrite_log.append(
                            f"{'WOULD OVERWRITE' if dry_run else 'OVERWROTE'} "
                            f"existing attachment dir: `{dest_attach.name}/` (--force)."
                        )
                else:
                    label = "symlink" if attachment_mode == "symlink" else "dir"
                    overwrite_log.append(
                        f"{'WOULD SKIP' if dry_run else 'SKIPPED'} refresh of "
                        f"attachment {label} `{dest_attach.name}`; existing "
                        f"target preserved (re-run with --force to refresh; "
                        f"any hand-added contents would be lost)."
                    )
            else:
                if attachment_mode == "symlink":
                    if not dry_run:
                        dest_attach.symlink_to(src_attach_dir.resolve())
                    if dry_run:
                        overwrite_log.append(
                            f"WOULD CREATE symlink `{dest_attach.name}` → "
                            f"`{src_attach_dir.resolve()}`."
                        )
                else:  # copy
                    if not dry_run:
                        shutil.copytree(src_attach_dir, dest_attach)
                    if dry_run:
                        overwrite_log.append(
                            f"WOULD COPY attachment dir `{src_attach_basename}/` "
                            f"→ `{dest_attach.name}/`."
                        )

    # Build YAML frontmatter (insertion order = schema order).
    frontmatter: "OrderedDict[str, Any]" = OrderedDict()
    if entry["notion_uuid"]:
        frontmatter["notion_uuid"] = entry["notion_uuid"]
    # Build a quick lookup for this entry's properties.
    entry_props: Dict[str, Tuple[str, Tag]] = {p[0]: (p[1], p[2]) for p in entry["properties"]}
    for pname, info in schema.items():
        if pname not in entry_props:
            continue
        ptype, td = entry_props[pname]
        # Use the dominant type from the schema for conversion (handles drift).
        dominant_type = info["types"].most_common(1)[0][0]
        if ptype != dominant_type:
            warnings.append(
                f"{entry['title']!r}: property {pname!r} is {ptype} on this page "
                f"but {dominant_type} elsewhere; converted as {dominant_type}."
            )
        value = convert_property_value(dominant_type, td)
        if value is None:
            continue
        # Special case: a "tags" property (matched case-insensitively, e.g.
        # Notion's "Tags") feeds Obsidian's tag system, which treats the values
        # as actual tags. Tag syntax disallows spaces, parens, etc., so
        # sanitize each value (e.g., "test plan" -> "test-plan").
        if info["key"].lower() == "tags":
            if isinstance(value, list):
                value = [t for t in (sanitize_obsidian_tag(v) for v in value) if t]
                if not value:
                    continue
            elif isinstance(value, str):
                sv = sanitize_obsidian_tag(value)
                if not sv:
                    continue
                value = [sv]
        frontmatter[info["key"]] = value

    # Strip inline snapshot tables Notion embeds for nested databases.
    if nested_db_folder_hexes and entry.get("body"):
        for tbl in list(entry["body"].find_all("table")):
            hrefs = [a.get("href", "") for a in tbl.find_all("a")]
            if any(hx in href for hx in nested_db_folder_hexes for href in hrefs):
                tbl.decompose()

    # Body. In inplace mode, every local href is relative to the source-entries
    # folder; pass the relpath (md's dir → source folder) so same- and
    # cross-entry attachments both resolve to the real exported files.
    inplace_link_prefix = (
        os.path.relpath(entry["path"].parent.resolve(), out_dir.resolve())
        if attachment_mode == "inplace"
        else None
    )
    body_md = convert_body(
        entry["body"],
        entry_attachment_dir_basename=src_attach_basename,
        new_attachment_dir_basename=new_attach_basename,
        wikilink_map=wikilink_map,
        inplace_link_prefix=inplace_link_prefix,
    )

    # Append inline tables for any nested databases owned by this entry.
    if extra_tables:
        for table in extra_tables:
            body_md = (body_md + "\n\n" + table) if body_md else table

    # Compose
    fm = yaml_dump_frontmatter(frontmatter)
    contents = fm
    if body_md:
        if contents and not contents.endswith("\n"):
            contents += "\n"
        contents += "\n" + body_md + "\n"

    actual_path = safe_write_text(
        md_path, contents,
        force=force, overwrite_log=overwrite_log, kind=".md", dry_run=dry_run,
    )
    return actual_path, warnings


def classify_html(html_path: Path) -> str:
    """
    Quick string-level classification (avoids parsing every file twice):
      - 'entry'   = has a properties table (a Notion DB row)
      - 'parent'  = has a collection-content table but no properties (a DB parent page)
      - 'page'    = has neither (a standalone page; out of scope for v1)
      - 'unknown' = couldn't read it
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "unknown"
    has_props = 'class="properties"' in text
    has_collection = 'class="collection-content"' in text
    if has_props:
        return "entry"
    if has_collection:
        return "parent"
    return "page"


def discover_databases(
    src: Path,
) -> Tuple[Dict[Path, List[Path]], Dict[Path, List[Path]], List[Path], List[Path]]:
    """
    Walk src recursively, classify every .html file, and group entries by
    their immediate parent folder (= one database per folder of entries).

    Databases are split by depth relative to src:
      depth 0 → top-level DB (entries live directly in src)
      depth 2 → nested DB (entries live in src/<attach-folder>/<nested-db-folder>)
      depth 1, ≥3 → fatal: list all offenders and abort

    Returns (top_level_dbs, nested_dbs, parent_pages, standalone_pages):
      top_level_dbs  — {entries_folder: [entry html paths]}  (depth 0)
      nested_dbs     — {entries_folder: [entry html paths]}  (depth 2)
      parent_pages   — list of parent-page html paths (skipped in v1)
      standalone_pages — list of non-DB-row html paths (skipped in v1)
    """
    all_dbs: Dict[Path, List[Path]] = defaultdict(list)
    parents: List[Path] = []
    standalones: List[Path] = []
    for html_path in sorted(src.rglob("*.html")):
        kind = classify_html(html_path)
        if kind == "entry":
            all_dbs[html_path.parent].append(html_path)
        elif kind == "parent":
            parents.append(html_path)
        elif kind == "page":
            standalones.append(html_path)

    top_level_dbs: Dict[Path, List[Path]] = {}
    nested_dbs: Dict[Path, List[Path]] = {}
    too_deep: List[Tuple[Path, int]] = []

    for ef, paths in all_dbs.items():
        depth = len(ef.relative_to(src).parts)
        if depth == 0:
            top_level_dbs[ef] = paths
        elif depth == 2:
            nested_dbs[ef] = paths
        else:
            too_deep.append((ef, depth))

    if too_deep:
        msg = (
            "ERROR: databases nested too deeply — only one level of nesting "
            "(depth 2 from src) is supported. Offending folders:\n"
        )
        for ef, d in too_deep:
            msg += f"  depth {d}: {ef}\n"
        sys.exit(msg)

    return top_level_dbs, nested_dbs, parents, standalones


def process_database(
    entries_folder: Path,
    entry_paths: List[Path],
    out_root: Path,
    db_name_override: Optional[str],
    *,
    nested_tables_by_uuid: Optional[Dict[str, List[str]]] = None,
    nested_folder_hexes_by_uuid: Optional[Dict[str, Set[str]]] = None,
    force: bool,
    overwrite_log: List[str],
    attachment_mode: str = "copy",
    dry_run: bool = False,
) -> Tuple[int, List[str], "OrderedDict[str, Dict[str, Any]]"]:
    """
    Process one database: parse all entries, write .md files into a
    folder named after the database under out_root, copy attachments.

    nested_tables_by_uuid maps entry notion_uuid → list of pre-rendered
    GFM table strings (one per nested DB owned by that entry). Passed
    through to write_entry so tables are appended after the body.

    Returns (num_entries_written, warnings, schema). The schema is
    returned so the caller can aggregate across databases for
    vault-wide artifacts like `.obsidian/types.json`.
    """
    db_name = db_name_override or strip_notion_id(entries_folder.name).strip() or entries_folder.name

    # Parse entries
    parsed_entries: List[Dict[str, Any]] = []
    for path in entry_paths:
        parsed = parse_entry(path)
        if parsed is None:
            continue
        parsed_entries.append(parsed)
    if not parsed_entries:
        return 0, [f"No parseable entries found in {entries_folder}"], OrderedDict()

    # Schema
    schema = discover_schema(parsed_entries)
    drift = warn_schema_drift(schema)

    # Output paths
    db_out_dir = out_root / db_name
    if not dry_run:
        db_out_dir.mkdir(parents=True, exist_ok=True)

    # Wikilinks within this DB
    wikilink_map = build_wikilink_map(parsed_entries)

    # Write each entry
    used_filenames: Dict[str, int] = {}
    warnings: List[str] = []
    _nested = nested_tables_by_uuid or {}
    _hexes = nested_folder_hexes_by_uuid or {}
    for entry in parsed_entries:
        tables = _nested.get(entry["notion_uuid"]) or None
        folder_hexes = _hexes.get(entry["notion_uuid"]) or None
        _md_path, warns = write_entry(
            entry,
            db_out_dir,
            schema,
            wikilink_map,
            used_filenames,
            extra_tables=tables,
            nested_db_folder_hexes=folder_hexes,
            force=force,
            overwrite_log=overwrite_log,
            attachment_mode=attachment_mode,
            dry_run=dry_run,
        )
        warnings.extend(warns)

    print(f"  → {db_name}: {len(parsed_entries)} entries written to {db_out_dir.name}/")
    for w in drift:
        print(f"    drift {w.strip()}")
    return len(parsed_entries), warnings, schema


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Convert a Notion database HTML export into an Obsidian-ready folder of "
            ".md files with type-aware YAML frontmatter and a starter .base file. "
            "Accepts either the export root or an entries folder; finds databases recursively."
        )
    )
    p.add_argument(
        "input_path",
        help="Path to the Notion export. Can be the export root, the entries folder, "
             "or any folder containing entry .html files at any depth.",
    )
    p.add_argument(
        "-o", "--output",
        help="Output folder. Default: '<input> (Obsidian)' as a sibling of the input.",
    )
    p.add_argument(
        "--db-name",
        help="Override the database display name (used in folder names and the .base "
             "folder filter). Only sensible when the input contains exactly one database.",
    )
    p.add_argument(
        "--no-base",
        action="store_true",
        help="Skip generating .base stub files.",
    )
    p.add_argument(
        "--no-types",
        action="store_true",
        help=(
            "Skip generating/updating `<output>/.obsidian/types.json`. By default "
            "the script writes Obsidian property-type declarations for every "
            "discovered Notion property so date/datetime/multitext columns "
            "behave correctly in Bases. Existing entries in types.json are "
            "never overwritten — only missing keys are added."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing .base and .md files in the output folder. "
            "Default behavior preserves existing files and writes new content "
            "to a sibling file named `<original>.new` (so a hand-customized "
            ".base is never silently clobbered). Either way, every collision "
            "is logged in _conversion_report.md."
        ),
    )

    # Mutually exclusive attachment-mode flags. Default = "copy".
    attach_mode_group = p.add_mutually_exclusive_group()
    attach_mode_group.add_argument(
        "--symlink-attachments",
        action="store_true",
        help=(
            "Instead of copying each entry's attachment directory into the "
            "output, create a symlink in the output that points at the "
            "source attachment dir. Avoids duplicating attachment files on "
            "disk. New md hrefs reference `<NewDB>/<Entry>/file.pdf` and "
            "resolve through the symlink. If you later move or delete the "
            "source export, the symlinks (and any md links into them) "
            "break. Filesystem-level tested 2026-05-05; Obsidian render "
            "not yet verified — spot-check one entry in Obsidian before "
            "relying on it. Mutually exclusive with --inplace-attachments."
        ),
    )
    attach_mode_group.add_argument(
        "--inplace-attachments",
        action="store_true",
        help=(
            "Don't create attachment dirs or symlinks in the output at "
            "all. Md hrefs are rewritten to point at the source attachment "
            "dir via a relative path from the new md file's parent "
            "directory. Avoids duplicating attachment files on disk AND "
            "avoids creating any output-side filesystem objects for "
            "attachments. If you later move the source export, every md "
            "link breaks. Filesystem-level tested 2026-05-05; Obsidian "
            "render not yet verified — spot-check one entry in Obsidian "
            "before relying on it. Mutually exclusive with "
            "--symlink-attachments."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't write anything to disk. Walk the source, parse every "
            "entry, build the schema, plan all output paths and attachment "
            "operations, and print what *would* happen — counts of "
            "discovered databases/entries/skipped pages, schema with drift "
            "warnings, planned filenames (including any collision suffixes), "
            "planned attachment operations under the chosen attachment mode, "
            "and types.json key additions. The output folder is not "
            "created. Useful for sanity-checking a big run before "
            "committing to it."
        ),
    )
    args = p.parse_args()

    # Resolve attachment mode from the mutually exclusive flag group.
    if args.symlink_attachments:
        attachment_mode = "symlink"
    elif args.inplace_attachments:
        attachment_mode = "inplace"
    else:
        attachment_mode = "copy"

    dry_run = args.dry_run

    src = Path(args.input_path).expanduser().resolve()
    if not src.is_dir():
        sys.exit(f"ERROR: {src} is not a directory.")

    out_root = (
        Path(args.output).expanduser().resolve()
        if args.output
        else src.parent / f"{src.name} (Obsidian)"
    )
    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("==== DRY RUN — no files will be written ====")
    print(f"Scanning {src} (recursive)...")
    top_level_dbs, nested_dbs, parents, standalones = discover_databases(src)

    n_top_entries = sum(len(v) for v in top_level_dbs.values())
    n_nested_entries = sum(len(v) for v in nested_dbs.values())
    print(
        f"Found {n_top_entries} entries across "
        f"{len(top_level_dbs)} top-level database(s)"
        + (
            f"; {n_nested_entries} entries across "
            f"{len(nested_dbs)} nested database(s) will become inline tables"
            if nested_dbs else ""
        )
        + f"; {len(parents)} parent page(s) "
        f"and {len(standalones)} non-DB page(s) skipped (out of scope for v1)."
    )

    if not top_level_dbs:
        sys.exit(
            "ERROR: no top-level database entries found. An entry HTML must contain "
            '<table class="properties"> in its <header>. Did you point at the '
            "right folder? It can be the export root, an entries folder, or "
            "anything in between."
        )

    if args.db_name and len(top_level_dbs) > 1:
        print(
            f"WARNING: --db-name was given but {len(top_level_dbs)} top-level databases "
            "were found. Ignoring --db-name; will derive each database's name from its folder."
        )
        args.db_name = None

    # Pre-process nested databases: parse entries, build per-DB schema,
    # render as GFM tables, key by the parent top-level entry's notion_uuid.
    # Also collect the nested folder hex IDs so write_entry can strip the
    # inline snapshot tables that Notion embeds in the parent body HTML.
    nested_tables_by_uuid: Dict[str, List[str]] = defaultdict(list)
    nested_folder_hexes_by_parent_uuid: Dict[str, Set[str]] = defaultdict(set)
    for nested_folder, nested_paths in nested_dbs.items():
        attach_folder = nested_folder.parent
        parent_hex = extract_notion_id(attach_folder.name)
        if parent_hex is None:
            print(
                f"  WARNING: no Notion ID in folder name {attach_folder.name!r}; "
                f"skipping nested DB {nested_folder.name!r}"
            )
            continue
        parent_uuid = hex_to_uuid(parent_hex)
        nested_hex = extract_notion_id(nested_folder.name)
        if nested_hex is None:
            print(
                f"  WARNING: no Notion ID in nested folder name {nested_folder.name!r}; "
                f"skipping (cannot strip body snapshot table without hex ID)"
            )
            continue
        nested_folder_hexes_by_parent_uuid[parent_uuid].add(nested_hex)
        nested_entries = [e for p in nested_paths if (e := parse_entry(p)) is not None]
        if not nested_entries:
            continue
        nested_schema = discover_schema(nested_entries)
        db_display = strip_notion_id(nested_folder.name).strip() or nested_folder.name
        table_md = render_nested_db_as_markdown_table(nested_entries, nested_schema, db_display)
        if table_md:
            nested_tables_by_uuid[parent_uuid].append(table_md)

    total_entries = 0
    total_warnings: List[str] = []
    overwrite_log: List[str] = []
    # Aggregate schema across all top-level databases so a single vault-wide
    # types.json captures every property the user might Bases-filter on.
    aggregate_schema: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for entries_folder, entry_paths in top_level_dbs.items():
        n, warns, db_schema = process_database(
            entries_folder,
            entry_paths,
            out_root,
            args.db_name if len(top_level_dbs) == 1 else None,
            nested_tables_by_uuid=nested_tables_by_uuid,
            nested_folder_hexes_by_uuid=nested_folder_hexes_by_parent_uuid,
            force=args.force,
            overwrite_log=overwrite_log,
            attachment_mode=attachment_mode,
            dry_run=dry_run,
        )
        total_entries += n
        total_warnings.extend(warns)
        # Merge: first-seen properties keep their position; conflicting
        # types accumulate into the per-property Counter so dominant-type
        # logic still applies vault-wide.
        for pname, info in db_schema.items():
            if pname in aggregate_schema:
                aggregate_schema[pname]["types"].update(info["types"])
            else:
                aggregate_schema[pname] = {
                    "types": Counter(info["types"]),
                    "key": info["key"],
                }

    # Single vault-wide .base covering all entries across all databases.
    if not args.no_base:
        vault_base_name = strip_notion_id(src.name).strip() or src.name
        emit_base_file(
            out_root / f"{vault_base_name}.base",
            aggregate_schema,
            force=args.force, overwrite_log=overwrite_log, dry_run=dry_run,
        )

    # Emit/merge .obsidian/types.json so Obsidian Bases types each
    # property correctly (especially date/datetime, which Bases will
    # otherwise read as plain text).
    if not args.no_types:
        emit_types_json(
            out_root, aggregate_schema,
            force=args.force, overwrite_log=overwrite_log, dry_run=dry_run,
        )

    # Conversion report at the output root (or printed to stdout in dry-run).
    report = out_root / "_conversion_report.md"
    lines = [
        "# Conversion report" + (" (DRY RUN)" if dry_run else ""),
        "",
    ]
    lines.append(f"- Source: `{src}`")
    lines.append(f"- Output: `{out_root}`")
    lines.append(f"- Total entries written: {total_entries}")
    lines.append(f"- Top-level databases found: {len(top_level_dbs)}")
    lines.append(f"- Nested databases (inlined as tables): {len(nested_dbs)}")
    lines.append(f"- Attachment mode: `{attachment_mode}`")
    if attachment_mode in ("symlink", "inplace"):
        lines.append(
            "  - **NOTE:** This mode is filesystem-level tested but its "
            "Obsidian rendering is not yet verified. The new md hrefs "
            "depend on the source attachment dirs staying at their current "
            "absolute path (symlink) or relative path from the output "
            "(inplace). If you later move or delete the source export, "
            "embedded PDFs and images will break. Spot-check one entry "
            "in Obsidian before relying on this mode at scale."
        )
    for entries_folder in top_level_dbs:
        db_name = strip_notion_id(entries_folder.name).strip() or entries_folder.name
        lines.append(f"  - **{db_name}** ({len(top_level_dbs[entries_folder])} entries) — `{entries_folder}`")
    if parents:
        lines.append(f"- Parent pages skipped: {len(parents)}")
        for p_path in parents[:20]:
            lines.append(f"  - `{p_path.name}`")
        if len(parents) > 20:
            lines.append(f"  - …and {len(parents) - 20} more")
    if standalones:
        lines.append(f"- Standalone (non-DB) pages skipped: {len(standalones)}")
        for sp in standalones[:20]:
            lines.append(f"  - `{sp.name}`")
        if len(standalones) > 20:
            lines.append(f"  - …and {len(standalones) - 20} more")
    if total_warnings:
        lines.append("")
        lines.append("## Per-entry warnings")
        for w in total_warnings:
            lines.append(f"- {w}")
    if overwrite_log:
        lines.append("")
        if dry_run:
            lines.append("## Planned operations")
            lines.append("")
            lines.append(
                "All filesystem operations the script would perform if you "
                "re-ran without `--dry-run`. Nothing has been written."
            )
            lines.append("")
        elif args.force:
            lines.append("## Overwrites (--force)")
        else:
            lines.append("## Skipped overwrites (existing files preserved)")
            lines.append("")
            lines.append(
                "The output folder already contained one or more `.base` or "
                "`.md` files. To preserve any hand-edits, the new content was "
                "written next to the existing files with a `.new` suffix. "
                "Diff and merge by hand, or re-run with `--force` to overwrite."
            )
            lines.append("")
        for w in overwrite_log:
            lines.append(f"- {w}")
    if dry_run:
        # Dump the planned report to stdout instead of writing to disk.
        print("")
        print("\n".join(lines))
        print("")
        print(f"DRY RUN complete. Planned output: {out_root}")
        print(f"  {total_entries} entries would be written across {len(top_level_dbs)} top-level database(s), {len(nested_dbs)} nested DB(s) inlined as tables.")
        print(f"  Attachment mode: {attachment_mode}")
        print("  No files were written; --dry-run was set.")
    else:
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote report: {report}")
        print(f"Output: {out_root}")
        if overwrite_log:
            if args.force:
                print(f"  Overwrote {len(overwrite_log)} existing file(s) (--force).")
            else:
                print(
                    f"  PRESERVED {len(overwrite_log)} existing file(s); new content "
                    f"written to .new siblings. See _conversion_report.md."
                )
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
