#!/usr/bin/env python3
"""
Non-HTML files (PDFs, CSVs, images) in PDF-only export sections — where Notion
exported a page as a PDF instead of HTML — must be copied to the mirrored output
path even though no .md note is created for them. Without a corresponding HTML
entry the files are "orphaned": write_entry never runs, so shutil.copytree never
fires, and they silently disappear.

The orphan pass copies each such file with its ORIGINAL name (only the directory
components are hex-stripped, by mirror_output_dir). It does NOT rename the file:
renaming broke body hrefs that reference the original name and collapsed two
distinct pages ("Report <hexA>.pdf", "Report <hexB>.pdf") onto one destination,
silently dropping one. Files already under a node's own attachment folder are
copied by write_entry and skipped here.

Run: /usr/bin/python3 test_orphaned_pdf_copy.py
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from synthetic_export import build, folder, hex_id
import notion_db_to_obsidian as n


def _page_html(title: str, hex_str: str, body: str = "") -> str:
    """A standalone page: an article with NO properties table."""
    uuid = n.hex_to_uuid(hex_str)
    return (
        f'<html><body><article id="{uuid}" class="page sans">'
        f'<h1 class="page-title">{title}</h1>'
        f'<div class="page-body">{body}</div></article></body></html>'
    )


class OrphanedPdfAtRootLevel(unittest.TestCase):
    """
    A section folder with only a PDF and no HTML at the top level must still
    have the PDF copied to the output vault — with its original filename.

    Source layout:
        src/
          Section/
            Page <hex>.pdf          ← orphaned PDF (no sibling .html)
            Page <hex>/             ← attachment folder (no parent .html)
              nested-file.pdf
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        self.h = hex_id("Page")
        section = self.src / "Section"
        section.mkdir(parents=True)
        (section / f"Page {self.h}.pdf").write_bytes(b"%PDF-1.4 fake")
        attach = section / f"Page {self.h}"
        attach.mkdir()
        (attach / "nested-file.pdf").write_bytes(b"%PDF-1.4 nested fake")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_top_level_pdf_copied(self):
        # Original filename is preserved (no hex stripping on the file itself).
        expected = self.out / "Section" / f"Page {self.h}.pdf"
        self.assertTrue(expected.is_file(), f"top-level orphaned PDF missing: {expected}")

    def test_nested_pdf_in_attachment_folder_copied(self):
        # Files inside an orphaned attachment folder are copied too; the FOLDER
        # name is hex-stripped (mirror_output_dir), the file name is not.
        expected = self.out / "Section" / "Page" / "nested-file.pdf"
        self.assertTrue(expected.is_file(), f"nested orphaned PDF missing: {expected}")


class OrphanedPdfAlongsideHtmlEntry(unittest.TestCase):
    """
    When a section contains both HTML entries (covered by write_entry) and a
    loose PDF in the database's entries folder, the PDF is preserved and the
    HTML entries convert normally — neither is lost.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        build(self.src)  # provides the Animals/Breeds/etc. structure

        # Add a loose PDF inside the Animals entries folder. That folder is the
        # Animals index node's attachment dir, so write_entry copies the PDF
        # (original name); the orphan pass sees it covered and skips it.
        animals_dir = self.src / folder("Animals")
        self.h = hex_id("Report")
        (animals_dir / f"Report {self.h}.pdf").write_bytes(b"%PDF-1.4 report")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_loose_pdf_preserved_with_original_name(self):
        expected = self.out / "Animals" / f"Report {self.h}.pdf"
        self.assertTrue(expected.is_file(), f"loose PDF missing: {expected}")

    def test_no_hex_stripped_duplicate(self):
        # It must NOT also appear hex-stripped — that would be a ghost duplicate.
        ghost = self.out / "Animals" / "Report.pdf"
        self.assertFalse(ghost.exists(), f"ghost hex-stripped duplicate present: {ghost}")

    def test_html_entries_still_converted(self):
        self.assertTrue((self.out / "Animals" / "Cat.md").is_file())
        self.assertTrue((self.out / "Animals" / "Dog.md").is_file())


class CoveredFilesNotDuplicated(unittest.TestCase):
    """
    Files already inside an entry's attachment folder (copied by write_entry)
    must not be double-copied by the orphaned-file pass.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        build(self.src)
        # Put a PDF inside Cat's attachment folder (Cat has a sibling .html).
        cat_dir = self.src / folder("Animals") / folder("Cat")
        (cat_dir / "attachment.pdf").write_bytes(b"%PDF-1.4 cat attach")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_covered_attachment_still_copied_once(self):
        expected = self.out / "Animals" / "Cat" / "attachment.pdf"
        self.assertTrue(expected.is_file(), "covered attachment PDF missing")

    def test_no_duplicate_copy_at_wrong_location(self):
        wrong = self.out / "Animals" / "attachment.pdf"
        self.assertFalse(wrong.exists(), f"covered PDF duplicated at wrong path: {wrong}")


class SameStemHexOrphansBothSurvive(unittest.TestCase):
    """
    Regression (data-loss): two distinct orphan PDFs whose names share a stem
    but differ only in the Notion hex ("Report <hexA>.pdf", "Report <hexB>.pdf")
    must BOTH reach the vault. Stripping the hex collapsed them to one
    destination and silently dropped one. Keeping the original name keeps the
    destinations distinct.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        self.ha = hex_id("ReportA")
        self.hb = hex_id("ReportB")
        self.assertNotEqual(self.ha, self.hb)
        self.src.mkdir(parents=True)
        (self.src / f"Report {self.ha}.pdf").write_bytes(b"CONTENT_A")
        (self.src / f"Report {self.hb}.pdf").write_bytes(b"CONTENT_B")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_both_files_present(self):
        a = self.out / f"Report {self.ha}.pdf"
        b = self.out / f"Report {self.hb}.pdf"
        self.assertTrue(a.is_file(), f"first orphan dropped: {a}")
        self.assertTrue(b.is_file(), f"second orphan dropped: {b}")

    def test_both_contents_preserved(self):
        contents = sorted(p.read_bytes() for p in self.out.rglob("*.pdf"))
        self.assertEqual(contents, [b"CONTENT_A", b"CONTENT_B"],
                         "distinct orphan contents were not both preserved")


class GenuineAttachmentWithHexLikeName(unittest.TestCase):
    """
    Regression (broken href): a genuine attachment whose filename ends in a
    space + 32-hex id (e.g. "scan <hex>.png") is referenced by its note's body.
    It must be copied with its ORIGINAL name so the href resolves — it must not
    be reclassified as a page export and renamed.

    Source layout:
        src/
          Pic <hex>.html                  ← standalone page, body <img> → the png
          Pic <hex>/
            scan <imghex>.png             ← genuine attachment, hex-like name
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        self.page_h = hex_id("Pic")
        self.img_h = hex_id("scan")
        self.src.mkdir(parents=True)
        img_rel = f"Pic%20{self.page_h}/scan%20{self.img_h}.png"
        (self.src / f"Pic {self.page_h}.html").write_text(
            _page_html("Pic", self.page_h, f'<figure><img src="{img_rel}"/></figure>'),
            encoding="utf-8",
        )
        attach = self.src / f"Pic {self.page_h}"
        attach.mkdir()
        (attach / f"scan {self.img_h}.png").write_bytes(b"\x89PNG real image")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_attachment_copied_with_original_name(self):
        expected = self.out / "Pic" / f"scan {self.img_h}.png"
        self.assertTrue(expected.is_file(),
                        f"genuine hex-named attachment missing (original name): {expected}")

    def test_no_hex_stripped_variant(self):
        ghost = self.out / "Pic" / "scan.png"
        self.assertFalse(ghost.exists(), f"attachment was wrongly renamed to: {ghost}")

    def test_body_href_resolves_on_disk(self):
        md = self.out / "Pic.md"
        self.assertTrue(md.is_file(), "Pic.md not written")
        text = md.read_text(encoding="utf-8")
        hrefs = re.findall(r"\]\(([^)]*\.png)\)", text) + re.findall(r'src="([^"]*\.png)"', text)
        self.assertTrue(hrefs, f"no png href found in note body:\n{text}")
        for h in hrefs:
            target = (md.parent / unquote(h)).resolve()
            self.assertTrue(target.exists(),
                            f"note links to a file that is not on disk: {h} → {target}")


class CollidingOrphanDirsBothSurvive(unittest.TestCase):
    """
    Regression (data-loss): two orphan files with the SAME filename live in two
    source folders that hex-strip to the SAME output dir
    ("Folder <hexA>/report.pdf" and "Folder <hexB>/report.pdf" → "Folder/...").
    Both must survive — the second is written under a disambiguated name, never
    silently overwritten or dropped. Re-running stays stable (no new copies).
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"

        self.ha = "a" * 32
        self.hb = "b" * 32
        (self.src / f"Folder {self.ha}").mkdir(parents=True)
        (self.src / f"Folder {self.hb}").mkdir(parents=True)
        (self.src / f"Folder {self.ha}" / "report.pdf").write_bytes(b"CONTENT_A")
        (self.src / f"Folder {self.hb}" / "report.pdf").write_bytes(b"CONTENT_B")

        n.run_conversion(self.src, self.out)

    def tearDown(self):
        self._td.cleanup()

    def test_both_contents_preserved(self):
        contents = sorted(p.read_bytes() for p in self.out.rglob("*.pdf"))
        self.assertEqual(contents, [b"CONTENT_A", b"CONTENT_B"],
                         "a colliding orphan was silently dropped")

    def test_two_distinct_files_written(self):
        pdfs = sorted(p.name for p in (self.out / "Folder").glob("*.pdf"))
        self.assertEqual(len(pdfs), 2, f"expected two disambiguated PDFs, got {pdfs}")

    def test_rerun_is_stable(self):
        # A second conversion must not add more copies (idempotent).
        before = sorted(p.name for p in (self.out / "Folder").glob("*.pdf"))
        n.run_conversion(self.src, self.out)
        after = sorted(p.name for p in (self.out / "Folder").glob("*.pdf"))
        self.assertEqual(before, after, f"re-run changed the output: {before} → {after}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
