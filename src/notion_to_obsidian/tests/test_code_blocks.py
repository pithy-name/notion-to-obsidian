#!/usr/bin/env python3
"""
Tests for code-block language preservation.

Notion exports a code block as `<pre><code class="language-XXX">…</code></pre>`.
The fence should open with the language (```xxx) so Obsidian highlights it.

Run: PYTHONPATH=src /usr/bin/python3 -m unittest discover -t src/notion_to_obsidian -s src/notion_to_obsidian/tests -p "test_*.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).parent.parent / "notion_db_to_obsidian.py"
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def conv(html: str) -> str:
    soup = BeautifulSoup(f'<div class="page-body">{html}</div>', "html.parser")
    return ndo.convert_body(
        soup.find("div", class_="page-body"),
        entry_attachment_dir_basename=None,
        new_attachment_dir_basename=None,
        wikilink_map={},
    )


class CodeBlocks(unittest.TestCase):
    def test_language_preserved_lowercased(self):
        md = conv('<pre class="code"><code class="language-JavaScript">const x = 1;</code></pre>')
        self.assertIn("```javascript", md)
        self.assertIn("const x = 1;", md)

    def test_no_language_plain_fence(self):
        md = conv('<pre class="code"><code>plain code</code></pre>')
        self.assertIn("```", md)
        self.assertNotIn("```language", md)

    def test_multiword_language_takes_first_token(self):
        # Notion "Plain Text" -> class="language-Plain Text" -> two classes;
        # we take the language- token -> "plain".
        md = conv('<pre class="code"><code class="language-Plain Text">log line</code></pre>')
        self.assertIn("```plain", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
