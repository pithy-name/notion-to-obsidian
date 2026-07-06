#!/usr/bin/env python3
"""
B2: a non-node `.html` file inside an attachment subtree must survive copy.

`_attachment_copy_ignore` rule 1 used to ignore ANY "*.html" name, on the
assumption every html file at that level is a Notion node (converted to its
own note elsewhere). But a genuine attachment can itself be an HTML file — a
saved web page, an offline copy, an HTML export a user dropped into their
Notion attachment folder. Its name carries no Notion 32-hex id, so it must be
kept, not silently dropped.

Run: /usr/bin/python3 test_non_node_html_survives_copy.py
"""
import os
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder
import notion_db_to_obsidian as n


class NonNodeHtmlSurvivesIgnoreCallback(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_non_hex_html_is_kept(self):
        # A saved web page sitting directly in the attachment folder, no
        # Notion id in its name.
        (self.d / "saved-page.html").write_text("<html>saved</html>", encoding="utf-8")
        (self.d / "photo.png").write_text("x", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertNotIn("saved-page.html", ignored)
        self.assertNotIn("photo.png", ignored)

    def test_hex_named_html_is_still_filtered(self):
        # A real Notion node html (hex id in the name) must still be filtered
        # — this is a converted node, not a genuine attachment.
        node_name = "Child fedcba9876543210fedcba9876543210.html"
        (self.d / node_name).write_text("<html></html>", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertIn(node_name, ignored)


class NonNodeHtmlSurvivesFullConversion(unittest.TestCase):
    def test_saved_web_page_in_attachment_folder_is_copied(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        # Drop a saved-webpage-style HTML file (no Notion id) inside Cat's own
        # attachment folder, alongside the nested "Breeds" DB.
        cat_dir = src / folder("Animals") / folder("Cat")
        page_dir = cat_dir / "some-page"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text("<html>clipped page</html>", encoding="utf-8")
        n.run_conversion(src, out)
        self.assertTrue(
            (out / "Animals" / "Cat" / "some-page" / "index.html").is_file(),
            "non-node html attachment was dropped by the copy filter",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
