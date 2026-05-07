"""
Merge Notion database CSV with Markdown page body content.

Notion exports databases as:
  - A CSV file with properties (columns) but no page body content
  - Separate files per entry (HTML or Markdown)

This script handles the Markdown export case. It matches each CSV row to its
.md file, strips any YAML frontmatter (which duplicates the CSV properties),
and adds the remaining content as a "Body" column in a new merged CSV.

Supports two filename patterns:
  - Notion export style: "Title HexID.md" (with 32-char hex suffix)
  - Clean names: "Title.md" (e.g. after Obsidian import)

No external dependencies required (stdlib only).
"""

import argparse
import csv
import os
import re
import sys
import unicodedata


def strip_frontmatter(text):
    """Remove YAML frontmatter (--- delimited block at the start of a file)."""
    if text.startswith("---"):
        # Find the closing ---
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]
    return text.strip()


def read_md_body(filepath):
    """Read a Markdown file and return the body content (frontmatter stripped)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return strip_frontmatter(content)
    except Exception as e:
        print("  WARNING: Could not read %s: %s" % (filepath, e), file=sys.stderr)
        return ""


def sanitize_for_match(text):
    """Normalize text for fuzzy filename matching.

    Handles Notion's filename sanitization (stripping colons, question marks,
    etc.) as well as Obsidian/other tools that replace colons with dashes.
    Normalizes all separator-like punctuation to spaces so both styles match.
    """
    # Replace newlines/tabs with spaces
    text = re.sub(r"[\r\n\t]+", " ", text)
    # Strip URLs (filenames mangle these differently across tools)
    text = re.sub(r"https?://[^\s]+", "", text)
    # Replace ellipsis character and triple dots
    text = text.replace("…", " ").replace("...", " ")
    # Normalize ALL dashes, colons, hyphens to spaces
    # (Notion strips colons; Obsidian replaces them with dashes)
    text = text.replace("—", " ").replace("–", " ").replace("-", " ").replace(":", " ")
    # Normalize Unicode accents (NFD decomposition, strip combining marks)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Remove remaining punctuation
    chars_to_strip = set('.\"\'?|<>*()/""''')
    text = "".join(c if c not in chars_to_strip else " " for c in text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def build_filename_index(md_dir):
    """Build a lookup from sanitized title -> filepath for all Markdown files.

    Handles two patterns:
      - "Title HexID.md" (standard Notion export, may be truncated at ~50 chars)
      - "Title.md" (clean names, e.g. after Obsidian import)
    """
    index = {}
    hex_pattern = re.compile(r"^(.+?)\s+([a-f0-9]{32})\.md$")

    for fname in os.listdir(md_dir):
        if not fname.endswith(".md"):
            continue

        match = hex_pattern.match(fname)
        if match:
            title = match.group(1).strip()
        else:
            title = fname[:-3].strip()  # remove .md

        sanitized = sanitize_for_match(title)
        index[sanitized] = os.path.join(md_dir, fname)

    return index


def find_md_file(csv_name, index):
    """Match a CSV Name value to a Markdown file, handling Notion's title
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


def find_csv_for_md_dir(md_dir):
    """Auto-discover the Notion CSV file for a given Markdown export folder.

    Checks (in order):
    1. Sibling CSV with the same name as the folder
    2. CSV inside the folder with the same name
    3. Any sibling CSV sharing the folder's hex ID
    4. Recursive search for a CSV with the matching hex ID
    """
    folder_name = os.path.basename(md_dir.rstrip(os.sep))
    parent_dir = os.path.dirname(md_dir.rstrip(os.sep))

    # 1. Sibling with same name
    candidate = os.path.join(parent_dir, folder_name + ".csv")
    if os.path.isfile(candidate):
        return candidate

    # 2. Inside the folder
    candidate = os.path.join(md_dir, folder_name + ".csv")
    if os.path.isfile(candidate):
        return candidate

    # 3. Sibling CSV sharing hex ID
    hex_match = re.search(r"[a-f0-9]{32}$", folder_name)
    if hex_match:
        hex_id = hex_match.group()
        for fname in os.listdir(parent_dir):
            if fname.endswith(".csv") and hex_id in fname:
                return os.path.join(parent_dir, fname)

    # 4. Recursive search
    if hex_match:
        for root, dirs, files in os.walk(parent_dir):
            for fname in files:
                if fname.endswith(".csv") and hex_id in fname:
                    return os.path.join(root, fname)

    # 5. If no hex ID in folder name, look for any CSV in the folder
    for fname in os.listdir(md_dir):
        if fname.endswith(".csv"):
            return os.path.join(md_dir, fname)

    # 6. Look for any CSV next to the folder
    for fname in os.listdir(parent_dir):
        if fname.endswith(".csv"):
            return os.path.join(parent_dir, fname)

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Merge a Notion database CSV with its Markdown page body content.",
        epilog="Examples:\n"
               "  # Auto-discover CSV (standard Notion export layout):\n"
               '  python3 merge_notion_db_from_md.py "My Database abc123/"\n'
               "\n"
               "  # Clean folder names (no hex ID), CSV auto-discovered:\n"
               '  python3 merge_notion_db_from_md.py "My Notes/"\n'
               "\n"
               "  # Specify CSV manually:\n"
               '  python3 merge_notion_db_from_md.py "My Database abc123/" \\\n'
               '    --csv "/other/path/database.csv"\n'
               "\n"
               "  # Custom output path:\n"
               '  python3 merge_notion_db_from_md.py "My Database abc123/" \\\n'
               '    -o "merged-output.csv"\n'
               "\n"
               "  # Keep YAML frontmatter in the Body column:\n"
               '  python3 merge_notion_db_from_md.py "My Database abc123/" --keep-frontmatter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "md_dir",
        help="Path to the folder containing the Notion Markdown exports",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to the Notion database CSV file (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for the merged output CSV (default: <folder> - merged.csv)",
    )
    parser.add_argument(
        "--keep-frontmatter",
        action="store_true",
        default=False,
        help="Keep YAML frontmatter in the Body column (stripped by default)",
    )

    args = parser.parse_args()

    md_dir = os.path.abspath(args.md_dir)

    if args.csv:
        csv_path = os.path.abspath(args.csv)
    else:
        csv_path = find_csv_for_md_dir(md_dir)
        if csv_path:
            print("Auto-discovered CSV: %s" % csv_path)
        else:
            print("ERROR: Could not find a CSV file for '%s'." % md_dir, file=sys.stderr)
            print("  Use --csv to specify the path manually.", file=sys.stderr)
            sys.exit(1)

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        folder_name = os.path.basename(md_dir.rstrip(os.sep))
        parent_dir = os.path.dirname(md_dir.rstrip(os.sep))
        output_path = os.path.join(parent_dir, folder_name + " - merged.csv")

    # Validate paths
    if not os.path.exists(csv_path):
        print("ERROR: CSV not found at %s" % csv_path, file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(md_dir):
        print("ERROR: Markdown directory not found at %s" % md_dir, file=sys.stderr)
        sys.exit(1)

    # Build index of Markdown files
    print("Indexing Markdown files in: %s" % md_dir)
    index = build_filename_index(md_dir)
    print("  Found %d .md files" % len(index))

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
            md_file = find_md_file(name, index)

            if md_file:
                content = read_md_body(md_file) if not args.keep_frontmatter else ""
                if args.keep_frontmatter:
                    try:
                        with open(md_file, "r", encoding="utf-8") as mf:
                            content = mf.read().strip()
                    except Exception as e:
                        print("  WARNING: Could not read %s: %s" % (md_file, e),
                              file=sys.stderr)
                        content = ""
                row["Body"] = content
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
    print("  Matched to .md:    %d (%.1f%%)" % (matched, matched / total * 100))
    print("  Unmatched:         %d (%.1f%%)" % (len(unmatched), len(unmatched) / total * 100))

    if unmatched:
        print("\nUnmatched entries:")
        for name in sorted(unmatched):
            print("  - %s" % name)

    print("\nOutput saved to: %s" % output_path)


if __name__ == "__main__":
    main()
