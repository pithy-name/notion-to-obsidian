#!/usr/bin/env python3
"""
Copy attachment mode must NOT duplicate child-node content.

On a nested export, an entry's source folder ("<Title> <hex>/") holds that
entry's child nodes (their "<Child> <hex>.html" + "<Child> <hex>/" folders) as
well as any genuine attachments (images, PDFs). The default `copy` mode used to
`shutil.copytree` the whole folder, so every nested node landed twice: once as a
clean "<Child>.md" note and again as the raw "<Child> <hex>.html" (+ hex folder).

Copy mode must copy only genuine attachments and skip the child-node tree:
  - no "*.html" should appear in the output (node HTML is converted, not copied),
  - no hex-named directory should appear in the output,
  - but a real attachment file (image) must still be copied into the vault.

Run: /usr/bin/python3 test_copy_filters_node_content.py
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

from synthetic_export import build, folder
import notion_db_to_obsidian as n

HEX_DIR_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)


class CopyFiltersNodeContent(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        build(self.src)
        # Drop a genuine attachment into Cat's own folder (which also holds the
        # nested "Breeds" database). It must survive the copy; the node tree
        # alongside it must not.
        cat_dir = self.src / folder("Animals") / folder("Cat")
        (cat_dir / "cat-photo.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
        # Default attachment mode is "copy".
        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_genuine_attachment_is_copied(self):
        self.assertTrue(
            (self.out / "Animals" / "Cat" / "cat-photo.png").is_file(),
            "genuine attachment image should be copied into the vault",
        )

    def test_no_raw_html_leaks_into_output(self):
        leaked = sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*.html"))
        self.assertEqual(leaked, [], f"raw node HTML leaked into output: {leaked}")

    def test_no_hex_named_dirs_leak_into_output(self):
        leaked = sorted(
            str(p.relative_to(self.out))
            for p in self.out.rglob("*")
            if p.is_dir() and HEX_DIR_RE.search(p.name)
        )
        self.assertEqual(leaked, [], f"hex-named node folders leaked into output: {leaked}")

    def test_child_notes_still_written(self):
        # Sanity: the children are still converted to clean notes.
        self.assertTrue((self.out / "Animals" / "Cat" / "Breeds" / "Tabby.md").is_file())


class IgnoreCallbackEdges(unittest.TestCase):
    """Unit tests for the _attachment_copy_ignore callback's matching rules."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_uppercase_html_sibling_dir_is_filtered(self):
        # Notion emits lowercase ".html", but a case-preserving tool could yield
        # "<X>.HTML". The node folder "<X>/" must still be recognised and skipped,
        # not leaked into the vault. The file filter is case-insensitive, so the
        # sibling-dir match must be too.
        (self.d / "Memo abc.HTML").write_text("x", encoding="utf-8")
        (self.d / "Memo abc").mkdir()
        (self.d / "photo.png").write_text("x", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertIn("Memo abc.HTML", ignored)
        self.assertIn("Memo abc", ignored)        # the node folder
        self.assertNotIn("photo.png", ignored)    # genuine attachment kept

    def test_attachment_dir_without_html_sibling_is_kept(self):
        # A real attachment sub-folder (e.g. "diagrams/") has no sibling html;
        # it must be copied, not mistaken for a node folder.
        (self.d / "diagrams").mkdir()
        (self.d / "report.pdf").write_text("x", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertEqual(ignored, set())

    def test_db_folder_containing_html_entries_is_filtered(self):
        # A nested database folder (e.g. "Bug Catalog <hex>/") sits inside an
        # outer attachment folder. It has NO sibling ".html" at the outer level
        # but DOES contain Notion-node ".html" files inside it (its entries, each
        # named "<Entry> <hex>.html"). It must be filtered out — copying it would
        # ghost-duplicate all DB entries.
        db_dir = self.d / "Bug Catalog 0123456789abcdef0123456789abcdef"
        db_dir.mkdir()
        (db_dir / "Entry One fedcba9876543210fedcba9876543210.html").write_text(
            "<html></html>", encoding="utf-8")
        (self.d / "real-attachment.png").write_text("x", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertIn("Bug Catalog 0123456789abcdef0123456789abcdef", ignored,
                      "DB folder should be filtered")
        self.assertNotIn("real-attachment.png", ignored, "real attachment must be kept")

    def test_attachment_subdir_with_non_node_html_is_kept(self):
        # A user's own attachment subfolder may contain a NON-node ".html" — a
        # saved web page or HTML export — whose name carries no Notion id. It is
        # not a database folder and must be kept; filtering on bare ".html"
        # silently dropped such folders (data loss). Keyed on the node-id pattern.
        gallery = self.d / "gallery"
        gallery.mkdir()
        (gallery / "index.html").write_text("<html>saved page</html>", encoding="utf-8")
        (gallery / "photo.jpg").write_text("x", encoding="utf-8")
        ignored = n._attachment_copy_ignore(str(self.d), os.listdir(self.d))
        self.assertNotIn("gallery", ignored,
                         "genuine attachment subdir with a non-node .html must be kept")


class CopyModeNoEmptyDirs(unittest.TestCase):
    def test_only_node_content_leaves_no_empty_dir(self):
        # An entry whose source folder holds only filtered content (here a stray
        # ".html" with no children to repopulate the folder) must not leave an
        # empty directory behind in the vault.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        # Give the childless "Dog" entry a folder containing only a stray .html
        # attachment (filtered) — nothing genuine survives the copy.
        dog_dir = src / folder("Animals") / folder("Dog")
        dog_dir.mkdir(parents=True, exist_ok=True)
        (dog_dir / "loose-doc.html").write_text("<html><body>doc</body></html>", encoding="utf-8")
        n.run_conversion(src, out)  # default copy
        dog_out = out / "Animals" / "Dog"
        self.assertFalse(
            dog_out.is_dir() and not any(dog_out.iterdir()),
            "copy mode left an empty attachment directory in the vault",
        )

    def test_no_empty_dirs_anywhere(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        dog_dir = src / folder("Animals") / folder("Dog")
        dog_dir.mkdir(parents=True, exist_ok=True)
        (dog_dir / "loose-doc.html").write_text("<html><body>doc</body></html>", encoding="utf-8")
        n.run_conversion(src, out)
        empties = sorted(
            str(p.relative_to(out)) for p in out.rglob("*")
            if p.is_dir() and not any(p.iterdir())
        )
        self.assertEqual(empties, [], f"empty dirs left in vault: {empties}")


class CopyModeForcePath(unittest.TestCase):
    def test_force_recopy_keeps_invariants(self):
        # The force-overwrite copytree branch (rmtree + recopy) must apply the
        # same child-node filter as the fresh-copy branch.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        cat_dir = src / folder("Animals") / folder("Cat")
        (cat_dir / "cat-photo.png").write_bytes(b"\x89PNG fake")
        n.run_conversion(src, out)                # first pass populates the vault
        n.run_conversion(src, out, force=True)    # second pass hits the force branch
        html = sorted(str(p.relative_to(out)) for p in out.rglob("*.html"))
        hexd = sorted(
            str(p.relative_to(out)) for p in out.rglob("*")
            if p.is_dir() and HEX_DIR_RE.search(p.name)
        )
        self.assertEqual(html, [], f"force recopy leaked node HTML: {html}")
        self.assertEqual(hexd, [], f"force recopy leaked hex dirs: {hexd}")
        self.assertTrue((out / "Animals" / "Cat" / "cat-photo.png").is_file())

    def test_force_does_not_delete_existing_dir_when_nothing_to_recopy(self):
        # When an entry's source folder has only filtered (child-node) content,
        # a --force run has nothing to recopy and must NOT delete a pre-existing
        # output dir (which may hold hand-added files).
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name)
        src, out = tmp / "src", tmp / "out"
        build(src)
        # Childless "Dog" with only a stray .html (filtered → no genuine attachment).
        dog_dir = src / folder("Animals") / folder("Dog")
        dog_dir.mkdir(parents=True, exist_ok=True)
        (dog_dir / "loose-doc.html").write_text("<html><body>doc</body></html>", encoding="utf-8")
        n.run_conversion(src, out)
        # Simulate a hand-curated output dir for Dog.
        out_dog = out / "Animals" / "Dog"
        out_dog.mkdir(parents=True, exist_ok=True)
        (out_dog / "my-notes.txt").write_text("keep me", encoding="utf-8")
        n.run_conversion(src, out, force=True)
        self.assertTrue((out_dog / "my-notes.txt").is_file(),
                        "force run deleted a hand-added file when there was nothing to recopy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
