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
import filecmp
import functools
import json
import os
import re
import shutil
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
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

# Notion appends a 32-char hex ID to filenames and folder names. Notion
# sometimes leaves a trailing space after the hex on folder names ("Title <hex> "),
# so allow optional trailing whitespace inside the match — `re.sub` then strips
# both the hex and the trailing space, leaving a clean name.
NOTION_ID_RE = re.compile(r"\s+([0-9a-f]{32})\s*(?=\.html$|/$|$)", re.IGNORECASE)
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
    # A <h1 class="page-title"> can be present but EMPTY (an untitled Notion
    # page). Treat empty the same as missing: fall back to the filename with the
    # Notion id stripped, never "" — an empty title yields broken [[]] wikilinks.
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        title = strip_notion_id(html_path.stem).strip() or "Untitled"

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

    # B1 (attempted, blocked — see TODO.md): a landing/root page's own COVER
    # IMAGE lives outside <div class="page-body"> (typically a <div>/<img> or
    # <figure> near the top of <article>, before page-body, per Notion's
    # general "cover image sits above the title" convention). Its href would
    # need the same copy-path rewrite convert_body already applies to in-body
    # images, so a regular entry's images rewrite fine — only this outside-
    # page-body cover element does not. We did not extend parsing to pick it
    # up: there is no real Notion export sample accessible in this repo to
    # verify the actual cover-image markup shape (reading `test-output/` is
    # off-limits), and shipping a fix built only against invented markup
    # risks a change that "passes" its own synthetic test while doing nothing
    # — or the wrong thing — against a real export. The image-href rewrite
    # path this would need to reuse (see convert_body's `<img>` loop) is
    # itself verified working. Left as a known limitation; see TODO.md B1 and
    # README Known Issues.

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


def parse_notion_date_range_end(text: str) -> Optional[str]:
    """
    B9: a Notion date RANGE property renders as "Jan 2, 2024 → Jan 5, 2024".
    `parse_notion_date` (above) keeps only the start — Obsidian has no native
    date-range type, so per the recommended option (A) in TODO.md, the END
    date is emitted as a companion `<Prop> (end)` frontmatter property
    instead of being dropped. Returns the end date's ISO 8601 form (or the
    raw end text if unparseable), or None if `text` is not a range.
    """
    text = text.strip().lstrip("@")
    if " → " not in text:
        return None
    _start, end_text = text.split(" → ", 1)
    end_text = end_text.strip()
    if not end_text:
        return None
    return parse_notion_date(end_text) or end_text


def td_inner_markdown(td: Tag) -> str:
    """Convert a <td>'s inner HTML to Markdown (for rich text properties)."""
    return html_to_md(td.decode_contents(), heading_style="ATX").strip()


def _sole_anchor_href(td: Tag) -> Optional[str]:
    """
    If a property cell's only meaningful content is a single hyperlink, return
    its href; otherwise None.

    A Notion `text` property can hold one <a> (e.g. a Slack channel). Emitting
    that as a `[label](url)` Markdown link is noise inside a YAML frontmatter
    value — Obsidian doesn't render Markdown there — so we surface the bare URL.
    Detecting this on the HTML (rather than regexing markdownify's output)
    handles any URL, including ones containing ')'. Mixed content (text around
    the link, multiple links) yields None and is left as Markdown.
    """
    meaningful = [
        c for c in td.children
        if not (isinstance(c, NavigableString) and not c.strip())
    ]
    if len(meaningful) == 1 and isinstance(meaningful[0], Tag) and meaningful[0].name == "a":
        href = (meaningful[0].get("href") or "").strip()
        return href or None
    return None


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

    # Single select / status: one string.
    # NOTE (B8): when schema type-drift makes this entry's actual value carry
    # MULTIPLE selected-value spans (its own row was really multi_select, but
    # the dominant type across the database is select/status), grabbing only
    # the first span silently drops the rest — genuine data loss. Collect every
    # span and return a list when there's more than one, regardless of which
    # type name was passed in; a true single-select row only ever has one span,
    # so this is a no-op for the common case.
    if ptype in ("select", "status"):
        spans = td.find_all("span", class_="selected-value")
        if spans:
            values = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
            if not values:
                return None
            return values if len(values) > 1 else values[0]
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
    # is a single hyperlink, emit the bare URL instead (a `[label](url)` link
    # is not useful inside a YAML frontmatter value).
    if ptype in ("text", "title", "rich_text"):
        sole_href = _sole_anchor_href(td)
        if sole_href is not None:
            return sole_href
        md = td_inner_markdown(td)
        return md or None

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
        href_div = a.find("div", class_="bookmark-href")
        desc_div = a.find("div", class_="bookmark-description")
        # Notion often exports a bookmark-title div that is present but EMPTY
        # (no page title was fetched for a bare-URL bookmark). Fall back to the
        # visible URL (bookmark-href), then the raw href, then a literal — so a
        # title-less bookmark never collapses to an empty link and drops the URL.
        title = title_div.get_text(strip=True) if title_div else ""
        if not title:
            title = (href_div.get_text(strip=True) if href_div else "") or href or "Link"
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

        # The HTML bookmark card displays the URL as visible text in addition to
        # the title link. Mirror that (HTML render is the benchmark): emit the
        # URL as a visible autolink subtitle. Skip it when the title already IS
        # the URL (empty-title fallback) so the URL isn't duplicated.
        url_text = (href_div.get_text(strip=True) if href_div else "") or href
        if url_text and url_text != title:
            url_p = _TAG_FACTORY.new_tag("p")
            url_a = _TAG_FACTORY.new_tag("a", href=href)
            url_a.string = url_text
            url_p.append(url_a)
            replacement_nodes.append(url_p)

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
    foldable callout (expanded by default, still click-to-collapse):
        > [!note]+ Title
        > body
    Always expanded (`[!note]+`): Notion's HTML export marks every toggle as
    <details open>, so that attribute carries no usable collapsed/expanded
    state — we default to expanded so content is visible while staying
    collapsible.
    When the toggle is the sole item of its `<ul class="toggle">` wrapper, the
    wrapper (and its bullet) is dropped; otherwise only the <details> is
    replaced, preserving any sibling list items.
    """
    for details in body_tag.find_all("details"):
        if details.parent is None:
            continue
        summary = details.find("summary")
        # A "toggle heading" exports with a heading element inside its <summary>.
        # Obsidian folds real headings natively, so emit a genuine Markdown
        # heading (preserving the level) instead of a callout that would flatten
        # the level. A plain toggle (no heading) becomes an expanded foldable
        # callout as before.
        heading = summary.find(["h1", "h2", "h3", "h4", "h5", "h6"]) if summary else None
        title = (summary.get_text(strip=True) if summary else "") or "Toggle"
        if summary is not None:
            summary.extract()

        if heading is not None:
            node = _TAG_FACTORY.new_tag(heading.name)
            node.string = title
            replacement = [node]
            replacement.extend(child.extract() for child in list(details.contents))
        else:
            bq = _TAG_FACTORY.new_tag("blockquote")
            title_p = _TAG_FACTORY.new_tag("p")
            title_p.string = f"[!note]+ {title}".rstrip()
            bq.append(title_p)
            for child in list(details.contents):
                bq.append(child.extract())
            replacement = [bq]

        # Drop the `<ul class="toggle"><li>` wrapper when it holds only this
        # toggle, so we don't emit a stray bullet around the result.
        li = details.parent if details.parent.name == "li" else None
        ul = li.parent if li and li.parent and li.parent.name == "ul" \
            and any("toggle" in c for c in (li.parent.get("class") or [])) else None
        if ul is not None and len(ul.find_all("li", recursive=False)) == 1:
            ul.replace_with(*replacement)
        else:
            details.replace_with(*replacement)


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


_BLOCK_LEVEL_TAGS = {
    "p", "div", "ul", "ol", "li", "table", "figure", "details", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre",
}


def _convert_highlights(body_tag: Tag) -> None:
    """
    Convert Notion background-colored text into Obsidian highlights (==text==).

    Notion marks a highlighted block/run with a `block-color-*_background` class.
    markdownify has no highlight support (and strips <mark>), but literal `==`
    markers survive conversion — so wrap the element's inline content in `==`.
    Only elements whose content is purely inline are wrapped; a background on a
    container with block-level children is skipped, to avoid `==` spanning
    blocks. Notion's specific color is not preserved (Obsidian's `==` is one
    highlight style). Plain text COLORS (no background) are left as-is —
    Markdown/Obsidian has no native colored text. Callouts are converted earlier
    and excluded here.
    """
    for el in body_tag.find_all(
        lambda t: t.has_attr("class")
        and any(c.startswith("block-color-") and c.endswith("_background") for c in t["class"])
    ):
        if "callout" in el.get("class", []):
            continue
        if el.find(_BLOCK_LEVEL_TAGS):
            continue
        if not el.get_text(strip=True):
            continue
        el.insert(0, NavigableString("=="))
        el.append(NavigableString("=="))


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


def _code_language(pre_tag: Tag) -> str:
    """
    markdownify code-fence language callback: read Notion's
    `<pre><code class="language-XXX">` and return the language token (lowercased)
    so the fence opens with ```xxx. Returns "" (plain fence) when absent.
    """
    code = pre_tag.find("code")
    if code:
        for c in (code.get("class") or []):
            if c.startswith("language-"):
                return c[len("language-"):].strip().lower()
    return ""


def _convert_equations(body_tag: Tag) -> None:
    """
    Convert Notion equation blocks into fenced LaTeX Obsidian renders natively.

    Notion exports a BLOCK equation as
        <figure class="equation">…<annotation encoding="application/x-tex">E=mc^2</annotation>…</figure>
    which markdownify would otherwise drop entirely (no text-only fallback) —
    genuine data loss (B7). Obsidian's built-in LaTeX renderer (MathJax)
    typesets `$$...$$` (block) and `$...$` (inline) natively, no plugin
    required, so converting to that syntax is functional, not just
    source-preservation.

    Minimal viable per the investigation behind B7: preserve the LaTeX
    source as text. Block equations (the documented, confirmed export shape)
    become `$$tex$$` on their own line. Any remaining bare
    `<annotation encoding="application/x-tex">` NOT inside a block-equation
    figure (Notion's inline-equation shape isn't confirmed against a real
    export sample) is treated as inline and wrapped `$tex$` — a best-effort
    fallback so an inline equation is never silently dropped even if its
    exact wrapper markup differs from what's assumed here.
    """
    for fig in body_tag.find_all("figure", class_=lambda c: c and "equation" in c):
        annotation = fig.find("annotation", attrs={"encoding": "application/x-tex"})
        tex = (annotation.get_text(strip=True) if annotation else fig.get_text(strip=True))
        if not tex:
            fig.decompose()
            continue
        new_p = _TAG_FACTORY.new_tag("p")
        new_p.string = f"$${tex}$$"
        fig.replace_with(new_p)

    # Any TeX annotation not already consumed by the block-equation pass
    # above (i.e. not inside a <figure class="equation">) — best-effort
    # inline handling.
    for annotation in body_tag.find_all("annotation", attrs={"encoding": "application/x-tex"}):
        tex = annotation.get_text(strip=True)
        if not tex:
            annotation.decompose()
            continue
        wrapper = annotation.find_parent(["math", "span"]) or annotation
        wrapper.replace_with(NavigableString(f"${tex}$"))


def _convert_iframes(body_tag: Tag) -> None:
    """
    Notion embed blocks (YouTube, Maps, Figma, …) export as an <iframe>
    (sometimes wrapped in a <figure>). markdownify drops <iframe> entirely,
    losing the embedded URL. Replace each <iframe src=...> (and its wrapping
    <figure>, if any) with a plain link to that URL so the destination is
    preserved. An <iframe> with no usable src is removed (nothing to keep).
    """
    for iframe in body_tag.find_all("iframe"):
        if iframe.parent is None:
            continue
        target = iframe.find_parent("figure") or iframe
        src = (iframe.get("src") or "").strip()
        if not src:
            target.decompose()
            continue
        new_p = _TAG_FACTORY.new_tag("p")
        link = _TAG_FACTORY.new_tag("a", href=src)
        link.string = src
        new_p.append(link)
        target.replace_with(new_p)


def convert_body(
    body_tag: Optional[Tag],
    *,
    entry_attachment_dir_basename: Optional[str],
    new_attachment_dir_basename: Optional[str],
    wikilink_map: Dict[str, str],
    inplace_link_prefix: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> str:
    """
    Convert the <div class="page-body"> tag into Markdown.

    Pre-passes on the soup before markdownify:
      - Strip the leading properties table if any.
      - Replace bookmark <figure> blocks with clean title-link + description quote.
      - Replace local-file source <figure> blocks with [filename](path) links.
      - Rewrite <a href="OldFolder%20uuid/file.pdf"> → "NewFolder/file.pdf".
      - Rewrite <a href="OtherEntry%20uuid.html">Title</a> → [[Title]].
      - An in-page `#fragment` anchor, or an ".html" link that never resolves
        to a node in `wikilink_map` (B6: e.g. it targets a DIFFERENT export,
        or the target's filename diverged) is converted to plain visible
        text — never left as a raw, broken ".html"/"#fragment" href.

    `inplace_link_prefix` (inplace attachment mode only): every local href in a
    Notion export is relative to the shared source-entries folder — whether it
    targets this entry's own attachment dir or a SIBLING entry's (cross-entry
    references). When set, this relpath (output dir → source folder) is prefixed
    onto every local href, so same-entry AND cross-entry attachments resolve to
    the real files in the source export. When None, the copy/symlink behavior
    applies (only this entry's own folder is rewritten).

    `warnings`, if given, gets one line appended per unresolved link (fragment
    or cross-export ".html") converted to plain text.
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

    # Notion equations (<figure class="equation"> / inline TeX annotations) →
    # fenced LaTeX ($$...$$ / $...$) Obsidian renders natively (B7 — markdownify
    # otherwise drops them entirely).
    _convert_equations(body_tag)

    # Notion embed blocks (<iframe>) → a link to the embedded URL (markdownify
    # would otherwise drop the iframe and lose the URL entirely).
    _convert_iframes(body_tag)

    # Notion callouts (<figure class="callout">) → Obsidian `> [!type]` callouts.
    _convert_callouts(body_tag)

    # Notion toggles (<details>) → Obsidian foldable callouts `> [!note]-`.
    _convert_toggles(body_tag)

    # Notion to-do items → Obsidian task list items `- [ ]` / `- [x]`.
    _convert_checkboxes(body_tag)

    # Notion background-colored text → Obsidian highlights `==text==`.
    _convert_highlights(body_tag)

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

        # External links: leave alone (NEVER visited).
        if decoded.startswith(("http://", "https://", "mailto:")):
            continue

        # In-page "#fragment" heading links: this converter doesn't track
        # Notion's heading ids, so the anchor can never resolve in Obsidian —
        # it would render as a raw, permanently-broken `#fragment` href.
        # Drop the link, keep the visible text (B6).
        if decoded.startswith("#"):
            if warnings is not None:
                warnings.append(
                    f"unresolved in-page anchor link {href!r} converted to "
                    "plain text (heading ids are not tracked)."
                )
            a.replace_with(a.get_text())
            continue

        # Link to another node anywhere in the export -> [[wikilink]].
        # `wikilink_map` is keyed on each node's filename (basename). An entry
        # links to a sibling with a bare-basename href (direct match); an
        # index/landing page links DOWN into a subfolder, so its href carries a
        # folder prefix ("Resources abc/Aromatherapy def.html") — fall back to the
        # basename. Filenames are vault-unique (they keep the Notion hex), so the
        # basename resolves unambiguously. Checked before any attachment rewrite
        # so .html links never become paths.
        if decoded in wikilink_map:
            a.replace_with(f"[[{wikilink_map[decoded]}]]")
            continue
        decoded_base = decoded.rsplit("/", 1)[-1]
        if decoded_base != decoded and decoded_base in wikilink_map:
            a.replace_with(f"[[{wikilink_map[decoded_base]}]]")
            continue

        # An ".html" href that matched no node in this export at all (B6) —
        # it points into a DIFFERENT export, or the target's filename
        # diverged from this href. Left alone it would be a raw, dead
        # ".html" path in the output; there is nothing to resolve it to, so
        # convert to plain visible text rather than ship a broken link.
        if decoded_base.lower().endswith(".html"):
            if warnings is not None:
                warnings.append(
                    f"unresolved cross-export link {href!r} converted to "
                    "plain text (no matching node in this export)."
                )
            a.replace_with(a.get_text())
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
        code_language_callback=_code_language,
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
    folder_filter: Optional[str] = None,
    force: bool,
    overwrite_log: List[str],
    dry_run: bool = False,
) -> None:
    """
    Write a starter .base file: table view with one column per discovered
    property. Disposable — user can replace via Obsidian's UI
    (right-click → "New base").

    `folder_filter` (a vault-relative folder path, forward-slashed) scopes the
    base to files DIRECTLY in that folder via `file.folder == "<path>"`
    (non-recursive) — used for the per-database bases. When None, the base
    covers all `.md` files in the vault (the vault-wide base).

    Honors the safe-write contract: an existing `.base` file is preserved by
    default (new content lands in `<name>.base.new`); `force=True` overwrites.
    """
    order = ["file.name"] + [info["key"] for info in schema.values()]
    base_doc = OrderedDict()
    # Filter: .md only — excludes attachments (PDFs etc.) in entry subfolders.
    # A per-database base additionally scopes to its own folder (non-recursive).
    filters = ['file.ext == "md"']
    if folder_filter is not None:
        filters.append(f'file.folder == "{folder_filter}"')
    base_doc["filters"] = OrderedDict([("and", filters)])
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
        dominant_ptype = info["types"].most_common(1)[0][0]
        if key not in types_map:
            otype = obsidian_type_for(key, dominant_ptype)
            types_map[key] = otype
            added.append(f"{key}={otype}")
        # B9: a date-range property may emit a companion "<key> (end)" value
        # (see write_entry) on any entry whose raw value was a range. Register
        # it as datetime too, so Bases sorts/types it correctly wherever it
        # shows up — never clobbers an existing user choice for that key.
        if dominant_ptype in ("date", "created_time", "last_edited_time"):
            end_key = f"{key} (end)"
            if end_key not in types_map:
                types_map[end_key] = "datetime"
                added.append(f"{end_key}=datetime")

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
        # B10: this is an ADDITIVE schema merge (new property keys added,
        # nothing existing touched) — a different EVENT KIND from a file
        # collision/preservation (an existing .base/.md that got a `.new`
        # sibling, or was overwritten with --force). It used to share the
        # same overwrite_log list with no distinguishing prefix, so the run
        # summary's "any(w.startswith('OVERWROTE'))/else PRESERVED" heuristic
        # mislabeled a benign schema update as "PRESERVED N existing
        # file(s); new content written to .new siblings" — untrue; no .new
        # file was ever written for this. Tagging it "SCHEMA-MERGED" (its own
        # prefix, checked explicitly in _emit_conversion_report) keeps it out
        # of both the OVERWROTE and PRESERVED buckets.
        overwrite_log.append(
            f"{'WOULD SCHEMA-MERGE' if dry_run else 'SCHEMA-MERGED'} "
            f"`.obsidian/types.json` (added {len(added)}: {', '.join(added)})."
        )


# ---- Main pipeline ---------------------------------------------------------


def _attachment_copy_ignore(
    dir_path: str, names: List[str], warn_log: Optional[List[str]] = None
) -> Set[str]:
    """`shutil.copytree` ignore callback: keep genuine attachments, drop child nodes.

    On a nested export an entry's source folder ("<Title> <hex>/") holds both
    real attachments (images, PDFs) AND the entry's child nodes — each a
    "<Child> <hex>.html" file with an optional sibling "<Child> <hex>/" folder.
    Those child nodes are converted to their own .md notes elsewhere, so copying
    them here would duplicate every nested node (the reported "<name>.md" vs
    "<name> <hex>.html" dupes). Skip them; copy only true attachments.

    A name is child-node content iff it is one of:
      - a "<Title> <32-hex>.html" file (a node, converted to its own note) —
        matched by NOTION_ID_RE, NOT bare ".html". A saved web page or other
        genuine HTML attachment sitting alongside real node content (e.g.
        "some-page/index.html") has no Notion-id in its name and must survive
        (B2: a blanket ".html" filter here used to drop it);
      - a directory with a sibling "<name>.html" in the same listing (the node's
        attachment folder); or
      - a directory that itself contains "*.html" files (a nested database
        folder — its entries are "<Entry> <hex>.html" inside, with no
        "<name>.html" sibling at this level).
    All three are structural to Notion's export layout, not a heuristic guess.
    The DB-folder case is what kept nested databases sitting inside an attachment
    folder from being ghost-duplicated into the vault.

    Genuine attachment FILES are always kept (copied with their original name so
    the body href resolves) — even one whose name happens to end in a 32-hex id.
    Notion pages exported as a non-HTML file ("<Title> <hex>.pdf") are also kept
    with their original name; `copy_orphaned_files` only places the ones that no
    node's attachment copy reaches, and never with a renamed (hex-stripped) file.

    The sibling match is case-insensitive: the ".html" file test folds case, so
    a folder paired with an uppercase "<name>.HTML" (from a case-preserving tool)
    must be recognised too, or the node folder would leak while its html is
    filtered.

    B3 (known limitation, no clean structural fix): the two DIRECTORY-filtering
    rules below have no content-based check — a genuine user directory that
    happens to be named like a Notion node (sibling "<name>.html", or itself
    holding a hex-named ".html") is indistinguishable from a real node folder by
    name alone, and gets filtered along with everything inside it. Rather than
    fail silently, every directory filtered by either rule is reported via
    `warn_log` (when given — the caller threads in `overwrite_log` so it
    surfaces in `_conversion_report.md`) naming the path so a user can go check
    it by hand. See TODO.md B3.
    """
    lower_names = {n.lower() for n in names}
    ignored: Set[str] = set()
    for name in names:
        child = os.path.join(dir_path, name)
        if name.lower().endswith(".html") and extract_notion_id(name):
            ignored.add(name)
        elif (name.lower() + ".html") in lower_names and os.path.isdir(child):
            ignored.add(name)
            _warn_once(
                warn_log,
                f"WARN (B3, known limitation): directory `{child}` filtered "
                "from the attachment copy — a sibling `<name>.html` makes it "
                "look like that Notion node's own attachment folder. If this "
                "is actually unrelated user content that happens to share the "
                "name, its contents were NOT copied (no content-based check "
                "is possible; see TODO.md B3).",
            )
        elif os.path.isdir(child) and _dir_contains_node_html(child):
            ignored.add(name)
            _warn_once(
                warn_log,
                f"WARN (B3, known limitation): directory `{child}` filtered "
                "as a nested-database folder — it contains a Notion-node-"
                "shaped `.html` file. If this is actually unrelated user "
                "content, its contents were NOT copied (no content-based "
                "check is possible; see TODO.md B3).",
            )
    return ignored


def _symlink_filtered_attachments(
    src_dir: Path, dest_dir: Path, warn_log: List[str]
) -> None:
    """
    Populate `dest_dir` with PER-FILE/PER-ENTRY symlinks into `src_dir`,
    applying the same child-node filter used by copy mode
    (`_attachment_copy_ignore`) — only genuine attachments get a symlink; a
    Notion node's own ".html" and its hex-named folder are skipped.

    B5: the old implementation symlinked the WHOLE `src_dir` as one directory
    symlink, so Obsidian (or anything walking the output tree) saw straight
    through it to every child node's raw ".html" + hex folder — exactly the
    content the copy-mode filter exists to hide. Per-file symlinks close that
    gap without ever copying bytes: `dest_dir` is a real directory; each
    surviving entry inside it is a symlink to the corresponding entry in
    `src_dir`.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    names = os.listdir(src_dir)
    ignored = _attachment_copy_ignore(str(src_dir), names, warn_log=warn_log)
    for name in names:
        if name in ignored:
            continue
        (dest_dir / name).symlink_to((src_dir / name).resolve())


def _warn_once(warn_log: Optional[List[str]], message: str) -> None:
    """Append `message` to `warn_log` unless it's already the last entry.

    `_attachment_copy_ignore` can be invoked multiple times for the same
    directory (once as a pre-check, again by `shutil.copytree`'s own
    recursion), which would otherwise duplicate the same WARN line.
    """
    if warn_log is not None and message not in warn_log:
        warn_log.append(message)


def _dir_contains_node_html(dir_path: str) -> bool:
    """True if dir_path directly holds a Notion-node html ("<stem> <hex>.html").

    A nested database's entries-folder holds its entries as "<Entry> <hex>.html",
    so a directory containing a Notion-node html (one whose stem carries a 32-hex
    id) is that database's folder and must be skipped. Keying on the node-id
    pattern — not on any ".html" — is deliberate: a genuine user attachment
    subfolder can legitimately contain a non-node ".html" (a saved web page, an
    HTML export), and filtering on bare ".html" silently dropped such folders.
    """
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return False
    return any(
        e.lower().endswith(".html")
        and os.path.isfile(os.path.join(dir_path, e))
        and extract_notion_id(os.path.splitext(e)[0])
        for e in entries
    )


def write_entry(
    entry: Dict[str, Any],
    out_dir: Path,
    schema: "OrderedDict[str, Dict[str, Any]]",
    wikilink_map: Dict[str, str],
    used_filenames: Dict[str, int],
    *,
    out_name: Optional[str] = None,
    backlink_to: Optional[str] = None,
    owned_dbs: Optional[List[Dict[str, Any]]] = None,
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
      - "symlink": create a real directory in the output containing PER-FILE
        symlinks (via `_symlink_filtered_attachments`) into the source
        attachment dir — the same child-node filter used by copy mode is
        applied first, so a Notion node's own ".html"/hex-folder never gets a
        symlink (B5 fix: an earlier version symlinked the whole source dir,
        exposing child-node content straight through it). Zero extra disk
        usage for the attachment bytes themselves; new md hrefs reference
        `<NewDB>/<Entry>/file.pdf` and resolve through the per-file symlink.
        Breaks if the source is later moved/deleted. Filesystem-level tested
        2026-05-05; Obsidian render not yet verified.
      - "inplace": no output-side directory or symlink is created. Md hrefs
        are rewritten to point at the source attachment dir via a relative
        path from the new md file's parent directory. Zero extra disk usage.
        Breaks if the source is later moved/deleted. Filesystem-level tested
        2026-05-05; Obsidian render not yet verified.
    """
    warnings: List[str] = []

    # Output filename. Normally the caller pre-assigns a vault-unique `out_name`
    # (so name-based wikilinks resolve unambiguously). Without it, fall back to
    # per-folder collision disambiguation (append the short Notion ID).
    if out_name is not None:
        candidate = out_name
    else:
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
            # In copy mode, only materialize the dir if a genuine attachment
            # survives the child-node filter. Otherwise copytree would create an
            # empty folder: an entry's child nodes are written by the main loop
            # (each makes its own dir), not by this copy, so a folder holding
            # only child-node content has nothing to copy here.
            copy_has_attachments = True
            if attachment_mode == "copy":
                src_names = os.listdir(src_attach_dir)
                # Computed unconditionally (dry-run included) so B3's ambiguous-
                # directory WARN is always surfaced, not just on a real write.
                _ignored = _attachment_copy_ignore(
                    str(src_attach_dir), src_names, warn_log=overwrite_log
                )
                copy_has_attachments = any(nm not in _ignored for nm in src_names)
            # `is_symlink()` returns True for broken symlinks (where .exists()
            # is False), so check both to detect any existing target.
            target_exists = dest_attach.exists() or dest_attach.is_symlink()
            if target_exists:
                if force:
                    # Remove whatever is there (file, symlink, or directory)
                    # ONLY when we're about to recreate it. In copy mode with no
                    # genuine attachment surviving the filter there is nothing to
                    # recopy, so the existing output dir (which may hold
                    # hand-added files) is left untouched rather than deleted.
                    will_recreate = attachment_mode == "symlink" or copy_has_attachments
                    if not dry_run and will_recreate:
                        if dest_attach.is_symlink() or dest_attach.is_file():
                            dest_attach.unlink()
                        else:
                            shutil.rmtree(dest_attach)
                    if attachment_mode == "symlink":
                        if not dry_run:
                            _symlink_filtered_attachments(
                                src_attach_dir, dest_attach, overwrite_log
                            )
                        overwrite_log.append(
                            f"{'WOULD OVERWRITE' if dry_run else 'OVERWROTE'} "
                            f"existing target `{dest_attach.name}/` with "
                            f"per-file symlinks into `{src_attach_dir.resolve()}` "
                            f"(--force, --symlink-attachments; child-node "
                            f"HTML/folders skipped)."
                        )
                    elif copy_has_attachments:  # copy
                        if not dry_run:
                            shutil.copytree(
                                src_attach_dir, dest_attach,
                                ignore=functools.partial(
                                    _attachment_copy_ignore, warn_log=overwrite_log
                                ),
                            )
                        overwrite_log.append(
                            f"{'WOULD OVERWRITE' if dry_run else 'OVERWROTE'} "
                            f"existing attachment dir: `{dest_attach.name}/` (--force; "
                            f"child-node HTML/folders skipped)."
                        )
                    else:  # copy, nothing genuine survives the filter
                        overwrite_log.append(
                            f"{'WOULD KEEP' if dry_run else 'KEPT'} existing attachment "
                            f"dir `{dest_attach.name}/` (--force); source has only "
                            f"child-node content, nothing to recopy."
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
                        _symlink_filtered_attachments(
                            src_attach_dir, dest_attach, overwrite_log
                        )
                    if dry_run:
                        overwrite_log.append(
                            f"WOULD CREATE `{dest_attach.name}/` with per-file "
                            f"symlinks into `{src_attach_dir.resolve()}` "
                            f"(child-node HTML/folders skipped)."
                        )
                elif copy_has_attachments:  # copy
                    if not dry_run:
                        shutil.copytree(
                            src_attach_dir, dest_attach,
                            ignore=functools.partial(
                                _attachment_copy_ignore, warn_log=overwrite_log
                            ),
                        )
                    if dry_run:
                        overwrite_log.append(
                            f"WOULD COPY attachments from `{src_attach_basename}/` "
                            f"→ `{dest_attach.name}/` (child-node HTML/folders skipped)."
                        )
                elif dry_run:  # copy, nothing genuine survives the filter
                    overwrite_log.append(
                        f"WOULD SKIP attachment copy for `{src_attach_basename}/` "
                        f"(only child-node content; no genuine attachments)."
                    )

    # Build YAML frontmatter (insertion order = schema order).
    frontmatter: "OrderedDict[str, Any]" = OrderedDict()
    if entry["notion_uuid"]:
        frontmatter["notion_uuid"] = entry["notion_uuid"]
    # Build a quick lookup for this entry's properties.
    entry_props: Dict[str, Tuple[str, Tag]] = {p[0]: (p[1], p[2]) for p in entry["properties"]}
    for pname, info in schema.items():
        key = info["key"]
        # A property that is empty for THIS entry still appears in the YAML, as
        # null — so every note carries the database's full property set (Notion
        # shows the column for every row, and Bases stays consistent).
        if pname not in entry_props:
            frontmatter[key] = None
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
            frontmatter[key] = None
            continue
        # Special case: a "tags" property (matched case-insensitively, e.g.
        # Notion's "Tags") feeds Obsidian's tag system, which treats the values
        # as actual tags. Tag syntax disallows spaces, parens, etc., so
        # sanitize each value (e.g., "test plan" -> "test-plan").
        if key.lower() == "tags":
            if isinstance(value, list):
                value = [t for t in (sanitize_obsidian_tag(v) for v in value) if t]
                if not value:
                    frontmatter[key] = None
                    continue
            elif isinstance(value, str):
                sv = sanitize_obsidian_tag(value)
                if not sv:
                    frontmatter[key] = None
                    continue
                value = [sv]
        frontmatter[key] = value
        # B9: a date-range value ("Jan 2, 2024 → Jan 5, 2024") only carries
        # its START through `value` (parse_notion_date takes the first side
        # of the range). Obsidian has no native date-range type, so — per
        # the recommended option in TODO.md — emit the END date as a
        # companion `<Prop> (end)` property (also date-typed) rather than
        # dropping it. Only fires for date-like properties whose raw text is
        # actually a range; a plain single date is unaffected.
        if dominant_type in ("date", "created_time", "last_edited_time"):
            raw_text = td.get_text(strip=True)
            end_value = parse_notion_date_range_end(raw_text)
            if end_value is not None:
                frontmatter[f"{key} (end)"] = end_value

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
        warnings=warnings,
    )

    # Append inline tables for any nested databases owned by this entry.
    if extra_tables:
        for table in extra_tables:
            body_md = (body_md + "\n\n" + table) if body_md else table

    # Compose. The page title is emitted as a body H1: Notion renders the title
    # at the top of the page, but Obsidian only shows the filename, so without
    # this the title is absent from the note content, previews, and embeds.
    fm = yaml_dump_frontmatter(frontmatter)
    contents = fm
    if contents and not contents.endswith("\n"):
        contents += "\n"
    contents += "\n# " + entry["title"] + "\n"
    if backlink_to:
        contents += "\n↑ Part of [[" + backlink_to + "]]\n"
    if body_md:
        contents += "\n" + body_md + "\n"
    # If this note is the "home" of one or more child databases, embed each
    # child's .base and list its entries as wikilinks (drives the graph).
    # B11: when the owned DB's name is IDENTICAL to the page title (a common
    # shape — a database's own index/landing page named after the database),
    # the "## <DB>" section heading directly repeats the "# <title>" heading
    # already emitted above it. Omit the redundant section heading in that
    # case; the .base embed + entry list still follow directly under the
    # page's own H1.
    for od in (owned_dbs or []):
        if od["name"] != entry["title"]:
            contents += "\n## " + od["name"] + "\n"
        contents += "\n![[" + od["base_name"] + ".base]]\n"
        if od.get("children"):
            contents += "\n" + "\n".join(f"- [[{c}]]" for c in od["children"]) + "\n"

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


def discover_tree(src: Path) -> Dict[str, Any]:
    """
    Walk `src` and build the full nesting tree at ANY depth — no depth ceiling
    and no requirement that a database exist (supersedes the old
    depth-limited discovery).

    Returns:
        {
          "databases": [
            {entries_folder, entry_paths, name, hex, index_path, owner_hex, depth},
            ...
          ],
          "pages": [  # standalone (non-database) pages
            {path, name, hex, owner_hex, depth}, ...
          ],
        }

    A database is a folder of entry-HTMLs. Its owner is the node (entry or page)
    whose attachment folder — Notion names it "<Title> <32-hex>" — contains the
    database folder, resolved by that hex. `owner_hex` is None when the database
    or page sits directly under `src` (top level). Index/collection-content
    pages are attached to their database as `index_path`, not treated as
    standalone pages.
    """
    entries_by_folder: Dict[Path, List[Path]] = defaultdict(list)
    index_by_hex: Dict[str, Path] = {}
    page_paths: List[Path] = []
    for html in sorted(src.rglob("*.html")):
        kind = classify_html(html)
        if kind == "entry":
            entries_by_folder[html.parent].append(html)
        elif kind == "parent":
            h = extract_notion_id(html.name)
            if h:
                index_by_hex[h] = html
        elif kind == "page":
            page_paths.append(html)

    def owner_hex_of(path_obj: Path) -> Optional[str]:
        parent = path_obj.parent
        if parent == src:
            return None
        return extract_notion_id(parent.name)

    databases: List[Dict[str, Any]] = []
    for ef, paths in entries_by_folder.items():
        h = extract_notion_id(ef.name)
        databases.append({
            "entries_folder": ef,
            "entry_paths": sorted(paths),
            "name": strip_notion_id(ef.name).strip() or ef.name,
            "hex": h,
            "index_path": index_by_hex.get(h) if h else None,
            "owner_hex": owner_hex_of(ef),
            "depth": len(ef.relative_to(src).parts),
        })

    # A "parent" page (collection-content) is only a database's index when its
    # hex matches that database's entries-folder. A parent page whose hex matches
    # no entries-folder is a collection/landing page — typically the export root,
    # or any hub page that contains child *databases* rather than entry rows. It
    # still has a body and attachments and (by hex) owns the databases beneath it,
    # so it must become a note, not be dropped. Fold these into the page list.
    consumed_index_hexes = {db["hex"] for db in databases if db["index_path"] is not None}
    for h, idx_path in index_by_hex.items():
        if h not in consumed_index_hexes:
            page_paths.append(idx_path)

    pages: List[Dict[str, Any]] = []
    for p in page_paths:
        pages.append({
            "path": p,
            "name": strip_notion_id(p.stem).strip() or p.stem,
            "hex": extract_notion_id(p.name),
            "owner_hex": owner_hex_of(p),
            "depth": len(p.relative_to(src).parts) - 1,
        })

    return {"databases": databases, "pages": pages}


def assign_unique_names(nodes: List[Dict[str, Any]]) -> None:
    """
    Give every node a vault-unique `name` (the .md filename stem) so name-based
    wikilinks resolve unambiguously. Nodes are processed in the given order: the
    first claimant of a name keeps it; later collisions get the short Notion id
    appended (or a counter when there is no id).

    The name is derived from the node's **source stem** (its `<Title> <hex>.html`
    filename, hex stripped), NOT its H1 title. Notion sanitizes the on-disk
    file/folder name (e.g. dropping square brackets) while the title keeps the
    original characters; `mirror_output_dir` builds the folder tree from those
    sanitized stems, so the note must use the same basis or its note/attachment
    folder diverges from where its children mirror (duplicate sibling dirs). The
    title is still rendered verbatim as the note's body `# <title>` heading.
    """
    seen: Dict[str, int] = {}
    for node in nodes:
        stem = strip_notion_id(node["parsed"]["path"].stem).strip()
        base = sanitize_filename(stem) or sanitize_filename(node["parsed"]["title"]) or "Untitled"
        if base not in seen:
            seen[base] = 1
            node["name"] = base
        else:
            seen[base] += 1
            sid = (extract_notion_id(node["parsed"]["path"].name) or "")[-6:]
            node["name"] = f"{base} ({sid})" if sid else f"{base} ({seen[base]})"


def mirror_output_dir(src_folder: Path, src_root: Path, out_root: Path) -> Path:
    """
    Map a source folder to its mirrored output folder: replicate the path from
    `src_root` to `src_folder`, stripping the Notion hex id from every
    component. `mirror_output_dir(src_root, src_root, out)` returns `out`.
    """
    rel = src_folder.relative_to(src_root)
    parts = [sanitize_filename(strip_notion_id(p).strip() or p) for p in rel.parts]
    return out_root.joinpath(*parts)


def copy_orphaned_files(
    src: Path,
    out_root: Path,
    covered_dirs: Set[Path],
    *,
    overwrite_log: List[str],
    dry_run: bool = False,
) -> int:
    """Copy non-HTML source files that no node's attachment copy reaches.

    A Notion export can hold sections with NO entry HTML — a page exported as a
    PDF instead of HTML, or a folder of loose attachments. Those files belong to
    no node, so `write_entry` never copies them and they would be dropped
    silently. Walk every non-HTML source file and copy the ones that are not
    already covered by a node's attachment copy.

    `covered_dirs` is the set of resolved source attachment directories that a
    node owns (each node's "<Title> <hex>/"). Any file under one of them is the
    responsibility of that node's `write_entry` — copied to a possibly
    collision-renamed "<Title> (id)/" dir the orphan pass could not reproduce, or
    referenced in place under `--inplace`/`--symlink`. Either way the orphan pass
    skips it: an exact membership test, not a structural guess, so it can neither
    double-copy into the wrong folder nor fight the chosen attachment mode.

    The copied file keeps its ORIGINAL name; only the directory components are
    hex-stripped (via `mirror_output_dir`). Stripping the hex from the filename
    broke body hrefs that reference the original name. But two distinct source
    folders can still hex-strip to the SAME output dir ("Folder <hexA>/x.pdf" and
    "Folder <hexB>/x.pdf" both → "Folder/x.pdf"), so a destination clash is
    possible. We never silently drop: if the existing file is byte-identical it is
    the same content (an earlier run, or a node's copy) and is skipped; if it
    differs, the orphan is written under a disambiguated name and the clash is
    logged. Re-runs are stable because the disambiguated name is reused when it
    already holds an identical copy.

    Returns the count of files copied (or that would be copied, in dry-run).
    """
    src_resolved = src.resolve()
    claimed: Set[Path] = set()            # dests already taken this run (dry too)
    copied = 0
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".html":
            continue                      # a node → converted, not copied
        if path.name == ".DS_Store":
            continue                      # macOS cruft, never an attachment
        # Skip anything a node's attachment copy already handled.
        anc = path.parent.resolve()
        covered = False
        while True:
            if anc in covered_dirs:
                covered = True
                break
            if anc == src_resolved or anc.parent == anc:
                break
            anc = anc.parent
        if covered:
            continue
        # Resolve a non-clobbering destination. A slot is "taken by a different
        # file" if this run already claimed it, or it exists on disk with
        # different bytes. Two source folders can hex-strip to the same output
        # dir, so disambiguate rather than overwrite — never silently drop.
        base = mirror_output_dir(path.parent, src, out_root) / path.name
        dest, attempt, clashed = base, 1, False
        while dest in claimed or (dest.exists() and not filecmp.cmp(path, dest, shallow=False)):
            clashed = True
            attempt += 1
            dest = base.with_name(f"{base.stem} ({attempt}){base.suffix}")
        if dest not in claimed and dest.exists():
            continue                      # identical copy already on disk → done
        claimed.add(dest)
        copied += 1
        if clashed:
            overwrite_log.append(
                f"COLLISION: orphaned file `{path.name}` mapped to an existing "
                f"`{base.relative_to(out_root)}` holding different content; wrote "
                f"`{dest.relative_to(out_root)}` to avoid data loss."
            )
        if dry_run:
            overwrite_log.append(
                f"WOULD COPY orphaned file `{path.name}` → `{dest.relative_to(out_root)}`."
            )
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return copied


def run_conversion(
    src: Path,
    out_root: Path,
    *,
    db_name: Optional[str] = None,
    no_base: bool = False,
    no_types: bool = False,
    force: bool = False,
    attachment_mode: str = "copy",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Convert a Notion HTML export at `src` into a mirrored Obsidian vault at
    `out_root`. Every node — a database entry at ANY depth, a standalone page, or
    a database index/landing page — becomes a real .md note whose output path
    mirrors its source location (hex id stripped). No nesting-depth ceiling and
    no requirement that a database exist.

    Piece 3 wiring: every note gets a vault-unique filename; each database gets a
    same-level-scoped `.base` (alongside the vault-wide one); a database's "home"
    note embeds that base and lists `[[entry]]` links, and each entry carries an
    `↑ Part of [[home]]` backlink. The home is the owning entry/page for a nested
    database, or the index/landing page for a top-level database.

    Returns a summary dict (counts + paths) used for the conversion report and by
    callers/tests.
    """
    src = Path(src).expanduser().resolve()
    out_root = Path(out_root).expanduser().resolve()
    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("==== DRY RUN — no files will be written ====")
    print(f"Scanning {src} (recursive)...")
    tree = discover_tree(src)
    databases = tree["databases"]
    pages = tree["pages"]

    n_db_entries = sum(len(db["entry_paths"]) for db in databases)
    print(
        f"Found {n_db_entries} entr{'y' if n_db_entries == 1 else 'ies'} across "
        f"{len(databases)} database(s) at any depth; "
        f"{len(pages)} standalone page(s)."
    )
    if db_name and len(databases) > 1:
        print(
            f"WARNING: --db-name was given but {len(databases)} databases were "
            "found. Ignoring --db-name; each database's name comes from its folder."
        )
        db_name = None

    # Stable processing order → deterministic disambiguation below.
    databases.sort(key=lambda db: str(db["entries_folder"]))

    # Parse entries, build per-database schema, and resolve the mirrored folder.
    # B4: mirror_output_dir alone maps a DB folder to its output path by
    # hex-STRIPPING every path component, so two distinct sibling databases
    # that merely share a display name (their source folders are
    # "<Name> <hexA>/" and "<Name> <hexB>/", each with its own unique hex)
    # would both mirror to the SAME output dir and their entries would be
    # written into one shared folder. Disambiguate DB output dirs the same
    # way `assign_unique_names` disambiguates node filenames: the first
    # claimant of a (parent dir, name) pair keeps the plain name; a later
    # collision gets the short Notion id appended.
    db_out_dir_claims: Dict[Path, int] = {}
    for db in databases:
        db["_parsed"] = [e for p in db["entry_paths"] if (e := parse_entry(p)) is not None]
        db["schema"] = discover_schema(db["_parsed"])
        parent_out_dir = mirror_output_dir(db["entries_folder"].parent, src, out_root)
        base_name = sanitize_filename(db["name"]) or "Untitled"
        candidate_dir = parent_out_dir / base_name
        if candidate_dir in db_out_dir_claims:
            db_out_dir_claims[candidate_dir] += 1
            sid = (db["hex"] or "")[-6:]
            base_name = (
                f"{base_name} ({sid})" if sid
                else f"{base_name} ({db_out_dir_claims[candidate_dir]})"
            )
            candidate_dir = parent_out_dir / base_name
        else:
            db_out_dir_claims[candidate_dir] = 1
        db["out_dir"] = candidate_dir
        db["base_name"] = base_name

    # Node registry: every entry, index/landing page, and standalone page → a note.
    nodes: List[Dict[str, Any]] = []
    for db in databases:
        for parsed in db["_parsed"]:
            nodes.append({"parsed": parsed, "out_dir": db["out_dir"], "kind": "entry", "db": db})
    for db in databases:
        if db["index_path"] is not None:
            parsed = parse_entry(db["index_path"])
            if parsed is not None:
                nodes.append({
                    "parsed": parsed,
                    "out_dir": mirror_output_dir(db["index_path"].parent, src, out_root),
                    "kind": "index", "db": db,
                })
    for pg in pages:
        parsed = parse_entry(pg["path"])
        if parsed is None:
            continue
        nodes.append({
            "parsed": parsed,
            "out_dir": mirror_output_dir(pg["path"].parent, src, out_root),
            "kind": "page", "db": None,
        })

    # Stable order → deterministic vault-unique filenames.
    nodes.sort(key=lambda nd: str(nd["parsed"]["path"]))
    assign_unique_names(nodes)
    for nd in nodes:
        nd["backlink_to"] = None
        nd["owned_dbs"] = []

    # Name-based wikilink map: decoded source href filename → unique note name.
    wikilink_map = {unquote(nd["parsed"]["path"].name): nd["name"] for nd in nodes}
    # Resolve an owning node by the hex id in its source filename.
    node_by_hex: Dict[str, Dict[str, Any]] = {}
    for nd in nodes:
        h = extract_notion_id(nd["parsed"]["path"].name)
        if h:
            node_by_hex[h] = nd
    index_by_db: Dict[int, Dict[str, Any]] = {
        id(nd["db"]): nd for nd in nodes if nd["kind"] == "index"
    }

    # Strip the inline collection-snapshot table Notion embeds in an owner's body
    # (the child DB is rendered as its own notes / embedded base instead).
    nested_hexes_by_owner_uuid: Dict[str, Set[str]] = defaultdict(set)
    for db in databases:
        if db["owner_hex"] and db["hex"]:
            nested_hexes_by_owner_uuid[hex_to_uuid(db["owner_hex"])].add(db["hex"])

    total_warnings: List[str] = []
    overwrite_log: List[str] = []

    # Assign each database a "home" note that embeds its base + lists its entries;
    # give every entry an `↑ Part of [[home]]` backlink.
    for db in databases:
        entry_nodes = [nd for nd in nodes if nd["kind"] == "entry" and nd["db"] is db]
        child_names = [nd["name"] for nd in entry_nodes]
        # Nesting that can't be mapped (owner folder renamed / missing its hex id)
        # is reported, not silently mis-nested.
        if db["owner_hex"] is None and db["entries_folder"].parent != src:
            total_warnings.append(
                f"database {db['name']!r}: nesting could not be mapped — its owner "
                "folder is missing a Notion id (renamed?); treated as top-level."
            )
        home = node_by_hex.get(db["owner_hex"]) if db["owner_hex"] else index_by_db.get(id(db))
        if home is None:
            total_warnings.append(
                f"database {db['name']!r}: no home note found; its .base is written "
                "but not embedded (a top-level database needs an index page)."
            )
            continue
        home["owned_dbs"].append({
            "name": db["name"], "base_name": db["base_name"], "children": child_names,
        })
        for en in entry_nodes:
            en["backlink_to"] = home["name"]

    # Write every node.
    entries_written = 0
    pages_written = 0
    for nd in nodes:
        parsed = nd["parsed"]
        db = nd["db"]
        schema = db["schema"] if nd["kind"] == "entry" else OrderedDict()
        if not dry_run:
            nd["out_dir"].mkdir(parents=True, exist_ok=True)
        folder_hexes = nested_hexes_by_owner_uuid.get(parsed["notion_uuid"]) or None
        _p, warns = write_entry(
            parsed, nd["out_dir"], schema, wikilink_map, {},
            out_name=nd["name"], backlink_to=nd["backlink_to"], owned_dbs=nd["owned_dbs"],
            nested_db_folder_hexes=folder_hexes,
            force=force, overwrite_log=overwrite_log,
            attachment_mode=attachment_mode, dry_run=dry_run,
        )
        total_warnings.extend(warns)
        if nd["kind"] == "entry":
            entries_written += 1
        elif nd["kind"] == "page":
            pages_written += 1

    for db in databases:
        print(f"  → {db['name']}: {len(db['_parsed'])} entries → {db['out_dir']}")
        for w in warn_schema_drift(db["schema"]):
            print(f"    drift {w.strip()}")
    if pages:
        print(f"  → {pages_written} standalone page(s) written as notes")

    # Copy non-HTML files that belong to no node — PDF-only export sections and
    # loose attachments that write_entry never reaches. Without this they vanish.
    # Files under a node's own attachment dir are already copied by write_entry
    # (possibly into a collision-renamed dir), so exclude those dirs by exact path.
    covered_dirs: Set[Path] = set()
    for nd in nodes:
        attach_dir = nd["parsed"]["path"].with_suffix("")
        if attach_dir.is_dir():
            covered_dirs.add(attach_dir.resolve())
    n_orphaned = copy_orphaned_files(
        src, out_root, covered_dirs, overwrite_log=overwrite_log, dry_run=dry_run
    )
    if n_orphaned:
        print(
            f"  → {n_orphaned} orphaned file(s) "
            f"{'would be ' if dry_run else ''}copied (no entry HTML; preserved as attachments)"
        )

    # Aggregate schema across all databases for the vault-wide artifacts.
    aggregate_schema: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for db in databases:
        for pname, info in db["schema"].items():
            if pname in aggregate_schema:
                aggregate_schema[pname]["types"].update(info["types"])
            else:
                aggregate_schema[pname] = {"types": Counter(info["types"]), "key": info["key"]}

    # Per-database same-level-scoped .base files + the vault-wide base.
    if not no_base:
        for db in databases:
            folder_filter = db["out_dir"].relative_to(out_root).as_posix()
            emit_base_file(
                db["out_dir"] / f"{db['base_name']}.base",
                db["schema"],
                folder_filter=folder_filter,
                force=force, overwrite_log=overwrite_log, dry_run=dry_run,
            )
        vault_base_name = strip_notion_id(src.name).strip() or src.name
        emit_base_file(
            out_root / f"{vault_base_name}.base",
            aggregate_schema,
            force=force, overwrite_log=overwrite_log, dry_run=dry_run,
        )

    if not no_types:
        emit_types_json(
            out_root, aggregate_schema,
            force=force, overwrite_log=overwrite_log, dry_run=dry_run,
        )

    summary = {
        "src": src,
        "out_root": out_root,
        "databases": databases,
        "pages": pages,
        "total_entries": entries_written,
        "pages_written": pages_written,
        "orphaned_files": n_orphaned,
        "attachment_mode": attachment_mode,
        "dry_run": dry_run,
        "warnings": total_warnings,
        "overwrite_log": overwrite_log,
    }
    _emit_conversion_report(summary, src, out_root)
    return summary


def _emit_conversion_report(
    summary: Dict[str, Any], src: Path, out_root: Path
) -> None:
    """Write `_conversion_report.md` at the output root (or print in dry-run)."""
    databases = summary["databases"]
    pages = summary["pages"]
    total_entries = summary["total_entries"]
    attachment_mode = summary["attachment_mode"]
    dry_run = summary["dry_run"]
    total_warnings = summary["warnings"]
    overwrite_log = summary["overwrite_log"]

    lines = ["# Conversion report" + (" (DRY RUN)" if dry_run else ""), ""]
    lines.append(f"- Source: `{src}`")
    lines.append(f"- Output: `{out_root}`")
    lines.append(f"- Databases found (any depth): {len(databases)}")
    lines.append(f"- Database entries written: {total_entries}")
    lines.append(f"- Standalone pages written: {summary['pages_written']}")
    if summary.get("orphaned_files"):
        lines.append(
            f"- Orphaned files {'would be ' if dry_run else ''}copied "
            f"(non-HTML, no entry; preserved as attachments): {summary['orphaned_files']}"
        )
    n_index = sum(1 for db in databases if db.get("index_path"))
    if n_index:
        lines.append(
            f"- Database index/landing pages discovered: {n_index} "
            "(written as notes — each is its database's home note: it embeds the "
            "`.base` and lists the entries)"
        )
    lines.append(f"- Attachment mode: `{attachment_mode}`")
    if attachment_mode in ("symlink", "inplace"):
        lines.append(
            "  - **NOTE:** This mode is filesystem-level tested but its "
            "Obsidian rendering is not yet verified. New md hrefs depend on the "
            "source attachment dirs staying put; if you later move or delete the "
            "source export, embedded files will break."
        )
    for db in databases:
        # Use the already-resolved (possibly disambiguated, B4) out_dir rather
        # than recomputing a bare mirror_output_dir — the latter would report
        # the wrong (collided) path for a same-named sibling database.
        rel = db["out_dir"].relative_to(out_root)
        lines.append(
            f"  - **{db['name']}** ({len(db['entry_paths'])} entries) "
            f"→ `{rel}/` (depth {db['depth']})"
        )
    if pages:
        lines.append(f"- Standalone pages: {len(pages)}")
        for pg in pages[:20]:
            lines.append(f"  - `{pg['name']}`")
        if len(pages) > 20:
            lines.append(f"  - …and {len(pages) - 20} more")
    if total_warnings:
        lines.append("")
        lines.append("## Per-entry warnings")
        for w in total_warnings:
            lines.append(f"- {w}")
    # B10: classify overwrite_log entries by EVENT KIND before deciding what
    # header/summary to print. A run that only added new schema keys to
    # types.json (SCHEMA-MERGED) or only flagged an ambiguous directory
    # filter (WARN, B3) has neither overwritten nor preserved any file — the
    # old logic ("any OVERWROTE? else assume PRESERVED") mislabeled those
    # runs as "PRESERVED N existing file(s); new content written to .new
    # siblings", which was simply untrue (no .new file was ever written).
    overwrite_events = [w for w in overwrite_log if w.startswith(("OVERWROTE", "WOULD OVERWRITE"))]
    schema_merge_events = [w for w in overwrite_log if w.startswith(("SCHEMA-MERGED", "WOULD SCHEMA-MERGE"))]
    warn_events = [w for w in overwrite_log if w.startswith("WARN")]
    preserve_events = [
        w for w in overwrite_log
        if w not in overwrite_events and w not in schema_merge_events and w not in warn_events
    ]

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
        elif overwrite_events:
            lines.append("## Overwrites (--force)")
        elif preserve_events:
            lines.append("## Skipped overwrites (existing files preserved)")
            lines.append("")
            lines.append(
                "The output folder already contained one or more `.base` or "
                "`.md` files. To preserve any hand-edits, the new content was "
                "written next to the existing files with a `.new` suffix. Diff "
                "and merge by hand, or re-run with `--force` to overwrite."
            )
            lines.append("")
        else:
            lines.append("## Notes")
            lines.append("")
            lines.append(
                "No file was overwritten or preserved-as-`.new` this run. "
                "Entries below are additive schema updates and/or WARNs "
                "flagging a known limitation — see TODO.md for context."
            )
            lines.append("")
        for w in overwrite_log:
            lines.append(f"- {w}")

    if dry_run:
        print("")
        print("\n".join(lines))
        print("")
        print(f"DRY RUN complete. Planned output: {out_root}")
        print(
            f"  {total_entries} entries across {len(databases)} database(s) "
            f"and {summary['pages_written']} page(s) would be written."
        )
        print(f"  Attachment mode: {attachment_mode}")
        print("  No files were written; --dry-run was set.")
    else:
        report = out_root / "_conversion_report.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote report: {report}")
        print(f"Output: {out_root}")
        # B10: report each EVENT KIND with its own line — an additive schema
        # merge and a WARN are neither an overwrite nor a preserved file, and
        # must not be folded into the "PRESERVED N existing file(s)" count.
        if overwrite_events:
            print(f"  Overwrote {len(overwrite_events)} existing file(s) (--force).")
        if preserve_events:
            print(
                f"  PRESERVED {len(preserve_events)} existing file(s); new content "
                f"written to .new siblings. See _conversion_report.md."
            )
        if schema_merge_events:
            print(
                f"  SCHEMA-MERGED {len(schema_merge_events)} additive update(s) into "
                f"`.obsidian/types.json` (no existing keys touched). "
                f"See _conversion_report.md."
            )
        if warn_events:
            print(
                f"  {len(warn_events)} WARN(s) — known limitations flagged, not "
                f"necessarily errors. See _conversion_report.md."
            )
    print("Done.")


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
            "output, create a real directory containing PER-FILE symlinks "
            "into the source attachment dir (only genuine attachments — the "
            "same child-node filter copy mode uses is applied, so a Notion "
            "node's own HTML/hex-folder is never symlinked). Avoids "
            "duplicating attachment files on disk. New md hrefs reference "
            "`<NewDB>/<Entry>/file.pdf` and resolve through the per-file "
            "symlink. If you later move or delete the source export, the "
            "symlinks (and any md links into them) break. Filesystem-level "
            "tested 2026-05-05; Obsidian render not yet verified — "
            "spot-check one entry in Obsidian before relying on it. "
            "Mutually exclusive with --inplace-attachments."
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

    src = Path(args.input_path).expanduser().resolve()
    if not src.is_dir():
        sys.exit(f"ERROR: {src} is not a directory.")

    out_root = (
        Path(args.output).expanduser().resolve()
        if args.output
        else src.parent / f"{src.name} (Obsidian)"
    )

    run_conversion(
        src,
        out_root,
        db_name=args.db_name,
        no_base=args.no_base,
        no_types=args.no_types,
        force=args.force,
        attachment_mode=attachment_mode,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
