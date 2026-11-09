"""The focused window's own text, read once and prefetched at key press.

`collect()` tries, in order: AT-SPI Text-interface content, the cua
driver's tree text, then OCR of the focused-window crop when `tesseract`
is installed (detected, never installed). Otherwise the source is `none`
and the caller keeps the screenshot path.

The text is untrusted reference data: this module returns it raw and
never logs it. A sensitive window (the capture/input deny policy or the
sensitive surfaces list) yields `none` before anything is read. A text
read past 0.3 s or an OCR past 0.7 s is `none`; the clock and every
reader are injectable.
"""
import dataclasses
import os
import shutil
import subprocess
import tempfile
import time

TEXT_BUDGET_S = 0.3
OCR_BUDGET_S = 0.7
MAX_CHARS = 6000
LINE_CAP = 1000

ATSPI, CUA, OCR, NONE = "atspi", "cua", "ocr", "none"


@dataclasses.dataclass(frozen=True)
class Result:
    text: str
    source: str
    elapsed: float


def tidy(parts, cap: int = MAX_CHARS) -> str:
    """Whitespace-normalised, de-duplicated lines, capped at `cap`."""
    seen, lines = set(), []
    for p in parts:
        for line in str(p).splitlines():
            line = " ".join(line.split())
            if not line or line in seen:
                continue
            seen.add(line)
            lines.append(line[:LINE_CAP])
    return "\n".join(lines)[:cap]


def _sensitive(cfg, win) -> bool:
    from . import cua_safety
    win = dict(win or {})
    win["app"] = str(win.get("app") or win.get("class") or "").lower()
    try:
        return bool(cua_safety.capture_blocked(cfg, window=win)
                    or cua_safety.sensitive_surface(cfg, window=win))
    except Exception:
        return True          # cannot tell: treat as sensitive


def _default_tree():
    from . import elementtree
    return elementtree.default_tree()


def _default_cua(win) -> str:
    from . import blank
    return blank.window_text(win)


def _default_capture(win):
    """A private crop of the focused window, or None."""
    from . import platform
    geo = platform.active_geometry()
    fd, path = tempfile.mkstemp(prefix="wisp-wt-", suffix=".png")
    os.close(fd)
    cmd = platform.window_screenshot_cmd(path, geo)
    if cmd:
        try:
            r = subprocess.run(cmd, capture_output=True,
                               timeout=OCR_BUDGET_S)
            if r.returncode == 0 and os.path.getsize(path) > 0:
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    _remove(path)
    return None


def _remove(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _tesseract(path) -> str:
    try:
        r = subprocess.run(["tesseract", str(path), "stdout"],
                           capture_output=True, text=True,
                           timeout=OCR_BUDGET_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _read_tree(tree_factory) -> str:
    try:
        tree = tree_factory()
        if tree.state()[0] != "ok":      # UNAVAILABLE / UNBOUND
            return ""
        return tidy(tree.texts())
    except Exception:
        return ""


def collect(cfg=None, *, window=None, tree=None, cua=None, capture=None,
            ocr=None, which=shutil.which, clock=time.monotonic) -> Result:
    cfg = cfg or {}
    t0 = clock()

    def done(text="", source=NONE) -> Result:
        return Result(text, source if text else NONE, clock() - t0)

    if window is None:
        try:
            from . import platform
            window = platform.active_window() or {}
        except Exception:
            window = {}
    if _sensitive(cfg, window):
        return done()

    text = _read_tree(tree or _default_tree)
    if clock() - t0 > TEXT_BUDGET_S:
        return done()
    if text:
        return done(text, ATSPI)

    try:
        text = tidy([(cua or _default_cua)(window)])
    except Exception:
        text = ""
    if clock() - t0 > TEXT_BUDGET_S:
        return done()
    if text:
        return done(text, CUA)

    if ocr is None:
        if not which("tesseract"):
            return done()
        ocr = _tesseract
    cap = capture or (lambda: _default_capture(window))
    t1 = clock()
    path = None
    try:
        path = cap()
        text = tidy([ocr(path)]) if path else ""
    except Exception:
        text = ""
    finally:
        if path and capture is None:
            _remove(path)
    if clock() - t1 > OCR_BUDGET_S:
        return done()
    return done(text, OCR)
