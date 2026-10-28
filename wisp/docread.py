"""Answer about the whole document (B9): read the focused window's file.

When the question is about a document ("what does page 30 say", "summarize
this paper") and the focused window is showing a file whose path can be
found, the file's text goes to the answer model as excerpts: the pages the
question names or matches, bounded to a few thousand characters. Nothing
here uploads the file; it is read locally, with a size bound, and only
from folders that are not protected (keys, config, keyrings, browser
profiles, system dirs).

Path: an open file of the window's process (`/proc/<pid>/fd`), else a file
name in the window title found under the usual document folders.
Text: PDF through `pdftotext` (OCR through `pdftoppm` + `tesseract` when a
page has no text layer), DOCX and XLSX straight from their XML, plain text.
"""
import os
import pathlib
import re
import shutil
import subprocess
import zipfile

DOC_EXT = (".pdf", ".docx", ".xlsx", ".txt", ".md")
MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 400
BLOCK_CHARS = 6000
OCR_PAGES = 5
PROTECTED = (".ssh", ".gnupg", ".aws", ".config", ".local/share/keyrings",
             ".password-store", ".mozilla", ".cache", ".kube", ".docker",
             ".local/share/wisp", ".config/wisp")
PROTECTED_ABS = ("/etc", "/proc", "/sys", "/dev", "/root", "/boot", "/var")
VIEWERS = ("zathura", "evince", "okular", "atril", "mupdf", "xreader",
           "foxit", "qpdfview", "libreoffice", "onlyoffice", "calibre")
_WORDS = ("document", "doc", "pdf", "file", "page", "paper", "article",
          "chapter", "section", "spreadsheet", "sheet", "report",
          "contract", "essay", "manual", "slide", "resume", "invoice")
_TITLE_FILE = re.compile(r"([^\s/\\][^/\\]*?\.(?:pdf|docx|xlsx|txt|md))",
                         re.IGNORECASE)
_PAGE = re.compile(r"\bpage\s+(\d{1,4})\b", re.IGNORECASE)


def _home():
    return pathlib.Path(os.path.expanduser("~"))


def protected(path) -> bool:
    """True for a path in a folder Wisp must never read from."""
    try:
        p = pathlib.Path(path).resolve()
    except (OSError, RuntimeError):
        return True
    s = str(p)
    if any(s == a or s.startswith(a + "/") for a in PROTECTED_ABS):
        return True
    home = _home().resolve()
    for sub in PROTECTED:
        pr = home / sub
        if p == pr or pr in p.parents:
            return True
    return False


def wants_doc(question: str, window: dict) -> bool:
    """Is the user asking about the document in front of them?"""
    q = " " + (question or "").lower() + " "
    if any(re.search(rf"\b{w}s?\b", q) for w in _WORDS):
        return True
    cls = str((window or {}).get("class") or "").lower()
    return any(v in cls for v in VIEWERS) and len(q.split()) > 2


# -- finding the file ------------------------------------------------------

def _open_files(pid, listing=None) -> list:
    """Document files the window's process has open."""
    out = []
    try:
        names = listing if listing is not None else [
            os.readlink(f"/proc/{int(pid)}/fd/{fd}")
            for fd in os.listdir(f"/proc/{int(pid)}/fd")]
    except (OSError, TypeError, ValueError):
        return out
    for n in names:
        if str(n).lower().endswith(DOC_EXT) and os.path.isfile(n):
            out.append(str(n))
    return out


def _by_title(title: str, roots=None, limit: int = 3000) -> list:
    m = _TITLE_FILE.search(title or "")
    if not m:
        return []
    name = m.group(1).strip().lower()
    roots = roots if roots is not None else [
        _home() / d for d in ("Documents", "Downloads", "Desktop")] + [_home()]
    seen, found = 0, []
    for root in roots:
        for depth_dir in _walk(pathlib.Path(root), 2):
            try:
                for e in os.scandir(depth_dir):
                    seen += 1
                    if seen > limit:
                        return found
                    if e.is_file() and e.name.lower() == name:
                        found.append(e.path)
            except OSError:
                continue
        if found:
            break
    return found


def _walk(root, depth):
    yield root
    if depth <= 0:
        return
    try:
        subs = [e.path for e in os.scandir(root)
                if e.is_dir(follow_symlinks=False)
                and not e.name.startswith(".")]
    except OSError:
        return
    for s in subs:
        yield from _walk(pathlib.Path(s), depth - 1)


def _active_pid():
    try:
        from . import hypr
        w = hypr.query("activewindow")
        return w.get("pid") if isinstance(w, dict) else None
    except Exception:
        return None


def find_path(window: dict, fd_listing=None, roots=None):
    """The file the focused window is showing, or None."""
    w = window or {}
    pid = w.get("pid") if "pid" in w else _active_pid()
    cands = _open_files(pid, fd_listing) \
        + _by_title(str(w.get("title") or ""), roots)
    for c in cands:
        if not protected(c):
            try:
                if os.path.getsize(c) <= MAX_BYTES:
                    return pathlib.Path(c)
            except OSError:
                continue
    return None


# -- reading it ------------------------------------------------------------

def _run(cmd, timeout=30, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, **kw)


def _pdftotext(path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    try:
        r = _run([exe, "-layout", "-l", str(MAX_PAGES), str(path), "-"])
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def _ocr_page(path, n: int) -> str:
    pdftoppm, tess = shutil.which("pdftoppm"), shutil.which("tesseract")
    if not (pdftoppm and tess):
        return ""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "p")
        try:
            _run([pdftoppm, "-r", "150", "-f", str(n), "-l", str(n),
                  "-png", str(path), base], timeout=60)
            png = next(pathlib.Path(td).glob("p*.png"), None)
            if not png:
                return ""
            r = _run([tess, str(png), "-"], timeout=60)
        except (OSError, subprocess.SubprocessError):
            return ""
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def _pdf_pages(path, want=()) -> list:
    pages = _pdftotext(path).split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    pages = [p.strip() for p in pages[:MAX_PAGES]]
    if not any(pages):                        # scanned: no text layer
        n_pages = len(pages) or max([*want, OCR_PAGES])
        pages = pages or [""] * n_pages
        for n in sorted({*want, 1, 2, 3})[:OCR_PAGES]:
            if 1 <= n <= len(pages):
                pages[n - 1] = _ocr_page(path, n).strip()
    return pages


def _xml_text(raw: bytes, tag: str) -> list:
    s = raw.decode("utf-8", "replace")
    return [re.sub(r"<[^>]+>", "", m).strip()
            for m in re.findall(rf"<{tag}[ >].*?</{tag}>", s, re.S)]


def _chunks(text: str, size: int = 3000) -> list:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _docx_pages(path) -> list:
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return []
    paras = _xml_text(raw, "w:p")
    return _chunks("\n".join(p for p in paras if p))


def _xlsx_pages(path) -> list:
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                shared = _xml_text(z.read("xl/sharedStrings.xml"), "si")
            sheets = sorted(n for n in z.namelist()
                            if n.startswith("xl/worksheets/sheet"))
            pages = []
            for n in sheets:
                s = z.read(n).decode("utf-8", "replace")
                rows = []
                for ref, attrs, body in re.findall(
                        r'<c r="([A-Z]+\d+)"([^>]*)>(.*?)</c>', s, re.S):
                    v = re.search(r"<v>(.*?)</v>", body, re.S)
                    if not v:
                        continue
                    val = v.group(1)
                    if 't="s"' in attrs and val.isdigit() \
                            and int(val) < len(shared):
                        val = shared[int(val)]
                    rows.append(f"{ref}: {val}")
                pages += _chunks("\n".join(rows))
            return pages
    except (OSError, KeyError, zipfile.BadZipFile):
        return []


def extract(path, want=()) -> list:
    """The file's text as a list of pages (1-based in speech)."""
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    try:
        if p.stat().st_size > MAX_BYTES:
            return []
    except OSError:
        return []
    if ext == ".pdf":
        return _pdf_pages(p, want)
    if ext == ".docx":
        return _docx_pages(p)
    if ext == ".xlsx":
        return _xlsx_pages(p)
    try:
        return _chunks(p.read_text(errors="replace")[:2_000_000])
    except OSError:
        return []


# -- choosing what to send ---------------------------------------------------

def _terms(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 4 and w not in _WORDS}


def relevant(pages: list, question: str, budget: int = BLOCK_CHARS) -> str:
    """Excerpts: the pages the question names ("page 30"), then the best
    keyword matches, then the first pages; in page order, bounded."""
    if not pages:
        return ""
    named = [int(n) for n in _PAGE.findall(question or "")
             if 1 <= int(n) <= len(pages)]
    q = _terms(question)
    scored = sorted(
        ((len(q & _terms(p)), i + 1) for i, p in enumerate(pages) if p),
        key=lambda t: (-t[0], t[1]))
    order = named + [n for sc, n in scored if sc > 0 and n not in named]
    order += [n for n in range(1, len(pages) + 1) if n not in order]
    chosen, used = [], 0
    for n in order:
        text = pages[n - 1].strip()
        if not text:
            continue
        room = budget - used
        if room <= 80:
            break
        piece = text[:room]
        chosen.append((n, piece))
        used += len(piece) + 12
    chosen.sort()
    label = "page" if len(pages) > 1 else "text"
    return "\n\n".join(f"[{label} {n} of {len(pages)}]\n{t}"
                       for n, t in chosen)


def context_for(question: str, window: dict, cfg: dict | None = None,
                **seams) -> str:
    """The system-message text to add for this question, or ""."""
    d = (cfg or {}).get("docs") or {}
    if str(d.get("enabled", "true")).lower() == "false":
        return ""
    if not wants_doc(question, window):
        return ""
    path = find_path(window, seams.get("fd_listing"), seams.get("roots"))
    if path is None:
        return ""
    want = [int(n) for n in _PAGE.findall(question or "")]
    body = relevant(extract(path, want), question)
    if not body:
        return ""
    return (f"The user's focused window shows the file {path.name}. "
            "Relevant excerpts from the file (not necessarily what is "
            f"visible right now):\n{body}")
