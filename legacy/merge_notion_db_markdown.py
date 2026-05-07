"""
Merge Notion database CSV with HTML page body content (as simplified Markdown).

Notion exports databases as:
  - A CSV file with properties (columns) but no page body content
  - Separate HTML files per entry, named: "Title HexID.html"

This script matches each CSV row to its HTML file, extracts the body content,
converts it from HTML to simplified Markdown, and adds it as a "Body" column
in a new merged CSV.

Requirements:
  pip install markdownify
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from html.parser import HTMLParser

try:
    from markdownify import markdownify as md
except ImportError:
    print("ERROR: markdownify is required. Install it with:", file=sys.stderr)
    print("  pip install markdownify", file=sys.stderr)
    sys.exit(1)


class BodyExtractor(HTMLParser):
    """Extract everything inside <body> from Notion HTML export,
    skipping the property table that Notion puts at the top."""

    def __init__(self):
        super().__init__()
        self.capture = False
        self.in_property_table = False
        self.table_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.capture = True
            return

        if not self.capture:
            return

        # Notion renders properties in a <table class="properties"> at the top
        attr_dict = dict(attrs)
        if tag == "table" and "properties" in attr_dict.get("class", ""):
            self.in_property_table = True
            self.table_depth = 1
            return

        if self.in_property_table:
            if tag == "table":
                self.table_depth += 1
            return

        # Rebuild the tag as raw HTML
        attr_str = ""
        for k, v in attrs:
            if v is None:
                attr_str += " " + k
            else:
                attr_str += ' %s="%s"' % (k, v)
        self.parts.append("<%s%s>" % (tag, attr_str))

    def handle_endtag(self, tag):
        if tag == "body":
            self.capture = False
            return

        if not self.capture:
            return

        if self.in_property_table:
            if tag == "table":
                self.table_depth -= 1
                if self.table_depth == 0:
                    self.in_property_table = False
            return

        self.parts.append("</%s>" % tag)

    def handle_data(self, data):
        if self.capture and not self.in_property_table:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.capture and not self.in_property_table:
            self.parts.append("&%s;" % name)

    def handle_charref(self, name):
        if self.capture and not self.in_property_table:
            self.parts.append("&#%s;" % name)

    def get_body(self):
        return "".join(self.parts).strip()


def extract_html_body(filepath):
    """Read an HTML file and return the body content minus the properties table."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        parser = BodyExtractor()
        parser.feed(content)
        return parser.get_body()
    except Exception as e:
        print("  WARNING: Could not parse %s: %s" % (filepath, e), file=sys.stderr)
        return ""


def html_to_markdown(html_body):
    """Convert HTML body content to simplified Markdown."""
    if not html_body.strip():
        return ""
    body_md = md(html_body, heading_style="ATX", strip=["style", "script"])
    # Clean up excessive blank lines
    body_md = re.sub(r"\n{3,}", "\n\n", body_md)
    return body_md.strip()


def sanitize_for_match(text):
    """Normalize text the same way Notion sanitizes filenames.

    Notion strips punctuation like colons, question marks, quotes, pipes,
    angle brackets, asterisks, periods, ellipses, slashes, and smart
    punctuation. It also normalizes Unicode accents and collapses whitespace.
    """
    # Replace newlines/tabs with spaces
    text = re.sub(r"[\r\n\t]+", " ", text)
    # Replace ellipsis character and triple dots
    text = text.replace("…", " ").replace("...", " ")
    # Replace em/en dashes with hyphen
    text = text.replace("—", "-").replace("–", "-")
    # Normalize Unicode accents (NFD decomposition, strip combining marks)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Remove all punctuation that Notion strips from filenames
    strip_chars = '.:"\'?|<>*()/""'''
    chars_to_strip = set(strip_chars)
    text = "".join(c if c not in chars_to_strip else " " for c in text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def build_filename_index(html_dir):
    """Build a lookup from sanitized title -> filepath for all HTML files.

    Notion filenames follow: "Title HexID.html" where titles may be truncated
    at ~50 characters.
    """
    index = {}
    pattern = re.compile(r"^(.+?)\s+([a-f0-9]{32})\.html$")

    for fname in os.listdir(html_dir):
        if not fname.endswith(".html"):
            continue
        match = pattern.match(fname)
        if match:
            title = match.group(1).strip()
        else:
            title = fname[:-5].strip()

        sanitized = sanitize_for_match(title)
        index[sanitized] = os.path.join(html_dir, fname)

    return index


def find_html_file(csv_name, index):
    """Match a CSV Name value to an HTML file, handling Notion's title
    truncation and filename sanitization.

    Strategy:
    1. Exact sanitized match
    2. Prefix match (longest matching prefix wins)
    """
    if not csv_name.strip():
        return None

    normalized = sanitize_for_match(csv_name)

    # 1. Exact match
    if normalized in index:
        return index[normalized]

    # 2. Prefix matching (handles Notion's ~50 char truncation)
    best_match = None
    best_len = 0
    for title, filepath in index.items():
        if normalized.startswith(title) or title.startswith(normalized):
            match_len = min(len(title), len(normalized))
            if match_len > best_len:
                best_match = filepath
                best_len = match_len

    # Accept prefix matches of reasonable length
    if best_match and (best_len >= 10 or best_len >= len(normalized) * 0.8):
        return best_match

    return None


def find_csv_for_html_dir(html_dir):
    """Auto-discover the Notion CSV file for a given HTML export folder.

    In a standard Notion export, the CSV sits next to the HTML folder with
    the same name (e.g. "My Database abc123.csv" beside "My Database abc123/").
    Also checks inside the folder as a fallback.
    """
    folder_name = os.path.basename(html_dir.rstrip(os.sep))
    parent_dir = os.path.dirname(html_dir.rstrip(os.sep))

    # 1. Look for exact match next to the folder: "FolderName.csv"
    candidate = os.path.join(parent_dir, folder_name + ".csv")
    if os.path.isfile(candidate):
        return candidate

    # 2. Look inside the folder
    candidate = os.path.join(html_dir, folder_name + ".csv")
    if os.path.isfile(candidate):
        return candidate

    # 3. Look for any CSV next to the folder that shares the hex ID
    hex_match = re.search(r"[a-f0-9]{32}$", folder_name)
    if hex_match:
        hex_id = hex_match.group()
        for fname in os.listdir(parent_dir):
            if fname.endswith(".csv") and hex_id in fname:
                return os.path.join(parent_dir, fname)

    # 4. Recursively search nearby for a CSV with the matching hex ID
    if hex_match:
        for root, dirs, files in os.walk(parent_dir):
            for fname in files:
                if fname.endswith(".csv") and hex_id in fname:
                    return os.path.join(root, fname)

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Merge a Notion database CSV with its HTML page body content, "
                    "converting body to simplified Markdown.",
        epilog="Examples:\n"
               "  # Auto-discover CSV (standard Notion export layout):\n"
               '  python3 merge_notion_db_markdown.py "My Database abc123/"\n'
               "\n"
               "  # Specify CSV manually if it's in a different location:\n"
               '  python3 merge_notion_db_markdown.py "My Database abc123/" \\\n'
               '    --csv "/other/path/My Database abc123.csv"\n'
               "\n"
               "  # Custom output path:\n"
               '  python3 merge_notion_db_markdown.py "My Database abc123/" \\\n'
               '    -o "merged-output.csv"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "html_dir",
        help="Path to the folder containing the Notion HTML exports",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to the Notion database CSV file (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for the merged output CSV (default: <html_folder> - merged-markdown.csv)",
    )

    args = parser.parse_args()

    html_dir = os.path.abspath(args.html_dir)

    if args.csv:
        csv_path = os.path.abspath(args.csv)
    else:
        csv_path = find_csv_for_html_dir(html_dir)
        if csv_path:
            print("Auto-discovered CSV: %s" % csv_path)
        else:
            print("ERROR: Could not find a CSV file for '%s'." % html_dir, file=sys.stderr)
            print("  Use --csv to specify the path manually.", file=sys.stderr)
            sys.exit(1)

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        # Default: put "- merged-markdown.csv" based on the HTML folder name
        folder_name = os.path.basename(html_dir.rstrip(os.sep))
        parent_dir = os.path.dirname(html_dir.rstrip(os.sep))
        output_path = os.path.join(parent_dir, folder_name + " - merged-markdown.csv")

    # Validate paths
    if not os.path.exists(csv_path):
        print("ERROR: CSV not found at %s" % csv_path, file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(html_dir):
        print("ERROR: HTML directory not found at %s" % html_dir, file=sys.stderr)
        sys.exit(1)

    # Build index of HTML files
    print("Indexing HTML files in: %s" % html_dir)
    index = build_filename_index(html_dir)
    print("  Found %d HTML files" % len(index))

    # Read CSV and merge
    print("Reading CSV: %s" % csv_path)
    rows = []
    matched = 0
    unmatched = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ["Body"]

        for row in reader:
            name = row.get("Name", "").strip()
            html_file = find_html_file(name, index)

            if html_file:
                body_html = extract_html_body(html_file)
                row["Body"] = html_to_markdown(body_html)
                matched += 1
            else:
                row["Body"] = ""
                unmatched.append(name)

            rows.append(row)

    # Write merged CSV
    print("\nWriting merged CSV: %s" % output_path)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Report
    total = len(rows)
    print("\n" + "=" * 60)
    print("RESULTS:")
    print("  Total CSV rows:    %d" % total)
    print("  Matched to HTML:   %d (%.1f%%)" % (matched, matched / total * 100))
    print("  Unmatched:         %d (%.1f%%)" % (len(unmatched), len(unmatched) / total * 100))

    if unmatched:
        print("\nUnmatched entries:")
        for name in sorted(unmatched):
            print("  - %s" % name)

    print("\nOutput saved to: %s" % output_path)


if __name__ == "__main__":
    main()
