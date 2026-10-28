"""B9: answer about the whole document, not just what is on screen."""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import docread, stage_speak  # noqa: E402


def make_pdf(path, pages):
    """A plain text PDF, one string per page (no libraries)."""
    objs = []

    def add(body):
        objs.append(body)
        return len(objs)
    cat = add(None)
    tree = add(None)
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"
        c = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        p = add(f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 612 792] "
                f"/Contents {c} 0 R /Resources << /Font << /F1 {font} 0 R "
                ">> >> >>")
        kids.append(f"{p} 0 R")
    objs[cat - 1] = f"<< /Type /Catalog /Pages {tree} 0 R >>"
    objs[tree - 1] = (f"<< /Type /Pages /Count {len(pages)} "
                      f"/Kids [{' '.join(kids)}] >>")
    out, offs = ["%PDF-1.4\n"], []
    pos = len(out[0])
    for i, o in enumerate(objs, 1):
        s = f"{i} 0 obj\n{o}\nendobj\n"
        offs.append(pos)
        out.append(s)
        pos += len(s)
    xref = f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(
        f"{o:010d} 00000 n \n" for o in offs)
    out.append(xref + f"trailer\n<< /Size {len(objs) + 1} /Root {cat} 0 R "
               f">>\nstartxref\n{pos}\n%%EOF\n")
    pathlib.Path(path).write_bytes("".join(out).encode("latin-1"))


PAGES = [f"Page {i} of the handbook. Filler text for section {i}."
         for i in range(1, 41)]
PAGES[29] = "The warranty period is seven years. Page 30 secret clause."


class Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        p = mock.patch.object(docread, "_home", lambda: self.dir)
        p.start()
        self.addCleanup(p.stop)


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class RealPdf(Tmp):
    def test_a_40_page_pdf_answers_about_page_30(self):
        f = self.dir / "Documents"
        f.mkdir()
        make_pdf(f / "handbook.pdf", PAGES)
        win = {"class": "zathura", "title": "handbook.pdf", "pid": None}
        text = docread.context_for("what does page 30 say about the "
                                   "warranty", win, {}, fd_listing=[])
        self.assertIn("seven years", text)
        self.assertIn("[page 30 of 40]", text)
        self.assertLess(len(text), docread.BLOCK_CHARS + 600)

    def test_keywords_find_a_page_that_is_not_named(self):
        f = self.dir / "Documents"
        f.mkdir()
        make_pdf(f / "handbook.pdf", PAGES)
        win = {"class": "zathura", "title": "handbook.pdf", "pid": None}
        text = docread.context_for("how long is the warranty in this "
                                   "document", win, {}, fd_listing=[])
        self.assertIn("seven years", text)


class Pages(unittest.TestCase):
    def test_a_named_page_always_makes_the_cut(self):
        pages = [f"filler {i} " * 200 for i in range(1, 41)]
        pages[29] = "the answer is forty-two"
        out = docread.relevant(pages, "what is on page 30", budget=1000)
        self.assertIn("forty-two", out)
        self.assertIn("[page 30 of 40]", out)
        self.assertLessEqual(len(out), 1200)

    def test_keyword_match_beats_page_order(self):
        pages = ["intro text"] * 10 + ["the penalty clause applies"] \
            + ["more"] * 5
        out = docread.relevant(pages, "tell me about the penalty", 400)
        self.assertIn("penalty clause", out)

    def test_generic_question_gets_the_first_pages(self):
        pages = ["start of the paper", "middle", "end"]
        out = docread.relevant(pages, "summarize this", 5000)
        self.assertTrue(out.startswith("[page 1 of 3]\nstart of the paper"))

    def test_out_of_range_page_is_ignored(self):
        self.assertIn("[page 1 of 2]",
                      docread.relevant(["a one", "b two"], "page 99"))

    def test_empty(self):
        self.assertEqual(docread.relevant([], "x"), "")


class Formats(Tmp):
    def test_docx_text_is_read_from_its_xml(self):
        f = self.dir / "memo.docx"
        xml = ('<w:document><w:body><w:p><w:r><w:t>Hello </w:t></w:r>'
               '<w:r><w:t>world</w:t></w:r></w:p><w:p><w:r><w:t>Second'
               '</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", xml)
        self.assertEqual(docread.extract(f), ["Hello world\nSecond"])

    def test_xlsx_cells_resolve_shared_strings(self):
        f = self.dir / "t.xlsx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("xl/sharedStrings.xml",
                       "<sst><si><t>Name</t></si><si><t>Ada</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData><row><c r="A1" t="s"><v>0</v>'
                       '</c><c r="B1" t="s"><v>1</v></c><c r="A2"><v>42</v>'
                       "</c></row></sheetData></worksheet>")
        out = docread.extract(f)[0]
        self.assertEqual(out.splitlines(), ["A1: Name", "B1: Ada", "A2: 42"])

    def test_plain_text_and_markdown(self):
        f = self.dir / "n.md"
        f.write_text("# notes\nbody")
        self.assertEqual(docread.extract(f), ["# notes\nbody"])

    def test_oversized_files_are_not_read(self):
        f = self.dir / "big.txt"
        f.write_text("x")
        with mock.patch.object(docread, "MAX_BYTES", 0):
            self.assertEqual(docread.extract(f), [])

    def test_a_scanned_pdf_falls_back_to_ocr(self):
        f = self.dir / "scan.pdf"
        f.write_bytes(b"%PDF")
        with mock.patch.object(docread, "_pdftotext",
                               return_value="\f\f\f\f\f"), \
                mock.patch.object(docread, "_ocr_page",
                                  side_effect=lambda p, n: f"ocr {n}"):
            pages = docread.extract(f, want=[3])
        self.assertEqual(pages[:3], ["ocr 1", "ocr 2", "ocr 3"])


class Finding(Tmp):
    def test_the_open_file_of_the_window_wins(self):
        f = self.dir / "Documents"
        f.mkdir()
        doc = f / "a.pdf"
        doc.write_bytes(b"x")
        found = docread.find_path({"pid": 1, "title": "whatever"},
                                  fd_listing=[str(doc), "/dev/null"])
        self.assertEqual(found, doc)

    def test_the_title_names_a_file_under_documents(self):
        d = self.dir / "Downloads" / "sub"
        d.mkdir(parents=True)
        (d / "Report.PDF").write_bytes(b"x")
        found = docread.find_path({"pid": None,
                                   "title": "report.pdf — Evince"},
                                  fd_listing=[])
        self.assertEqual(found.name, "Report.PDF")

    def test_protected_folders_are_refused(self):
        ssh = self.dir / ".ssh"
        ssh.mkdir()
        (ssh / "notes.txt").write_text("secret")
        self.assertTrue(docread.protected(ssh / "notes.txt"))
        self.assertIsNone(docread.find_path(
            {"pid": 1, "title": ""},
            fd_listing=[str(ssh / "notes.txt")]))
        self.assertTrue(docread.protected("/etc/passwd"))
        self.assertFalse(docread.protected(self.dir / "Documents" / "a.pdf"))

    def test_no_file_means_no_context(self):
        self.assertEqual(docread.context_for(
            "summarize this document",
            {"class": "foot", "title": "zsh", "pid": None}, {},
            fd_listing=[]), "")


class Triggers(unittest.TestCase):
    def test_document_questions(self):
        for q in ("what does page 3 say", "summarize this pdf",
                  "who wrote this paper"):
            self.assertTrue(docread.wants_doc(q, {}), q)
        self.assertTrue(docread.wants_doc("what is the main point here",
                                          {"class": "org.pwmt.zathura"}))
        self.assertFalse(docread.wants_doc("what time is it",
                                           {"class": "foot"}))

    def test_can_be_turned_off(self):
        self.assertEqual(docread.context_for(
            "summarize this document", {"title": "a.pdf"},
            {"docs": {"enabled": "false"}}), "")


class IntoTheAnswer(unittest.TestCase):
    def test_excerpts_reach_the_model_as_a_system_message(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": "seven years"}
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False), \
                mock.patch("wisp.memory.context_block", return_value=""):
            out = stage_speak.ask_chat("how long is the warranty", {},
                                       doc_text="EXCERPT: seven years")
        self.assertEqual(out, "seven years")
        sys_msgs = [m["content"] for m in seen["m"] if m["role"] == "system"]
        self.assertIn("EXCERPT: seven years", sys_msgs)

    def test_no_excerpts_no_extra_message(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": "x"}
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False), \
                mock.patch("wisp.memory.context_block", return_value=""):
            stage_speak.ask_chat("hi", {})
        self.assertEqual(len([m for m in seen["m"]
                              if m["role"] == "system"]), 1)


if __name__ == "__main__":
    unittest.main()
