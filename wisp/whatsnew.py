"""What's new: the changelog, and the one-time card after an update.

`CHANGELOG.md` is the source. Its first three lines under a version are
that version's headline. After `wispd update` (or any install) records a
different version than the one you last saw, the Panel shows a card with
the headline and a link; closing the panel marks the version seen, so it
shows once. The first install shows nothing: there is nothing "new" to a
person who has just arrived. Nothing is fetched; the text is the
installed file.
"""
import json
import pathlib
import re

from . import config, private

STATE = config.DATA_DIR / "whatsnew.json"
HEADLINES = 3
URL = "https://github.com/duketopceo/wisp/blob/master/CHANGELOG.md"

_HEAD = re.compile(r"^##\s+(Unreleased|v?\d+\.\d+\.\d+\S*)"
                   r"(?:\s+-\s+(\d{4}-\d{2}-\d{2}))?\s*$", re.I)
_THANKS = re.compile(r"\s*\(thanks (@[A-Za-z0-9][A-Za-z0-9-]{0,38})\)\s*$")
# a claim about how many people, with no source next to it
_COUNT = re.compile(
    r"(?<![\w-])\d+(?:,\d{3})*(?:\.\d+)?\s*[km]?\s+(?:users|downloads|"
    r"installs|stars|"
    r"people|contributors|customers|developers)\b", re.I)
_SOURCE = re.compile(r"\(source: https?://\S+\)")


def changelog_path() -> pathlib.Path:
    """The installed copy, else the one next to the source tree."""
    for p in (config.HOME / ".local" / "opt" / "wisp" / "CHANGELOG.md",
              pathlib.Path(__file__).resolve().parent.parent
              / "CHANGELOG.md"):
        if p.is_file():
            return p
    return p


def parse(text: str) -> list:
    """[{version, date, lines: [{text, who}]}], newest first as written."""
    out, cur = [], None
    for raw in text.splitlines():
        m = _HEAD.match(raw.strip())
        if m:
            v = m.group(1)
            cur = {"version": "Unreleased" if v.lower() == "unreleased"
                   else v if v.startswith("v") else "v" + v,
                   "date": m.group(2) or "", "lines": []}
            out.append(cur)
            continue
        if cur is not None and raw.startswith("- "):
            body = raw[2:].strip()
            t = _THANKS.search(body)
            cur["lines"].append({"text": _THANKS.sub("", body).strip(),
                                 "who": t.group(1) if t else ""})
        elif raw.startswith("## "):
            cur = None
    return out


def lint(text: str) -> list:
    """Problems with the changelog's own rules."""
    bad = []
    secs = parse(text)
    if not secs:
        bad.append("no version sections")
    for s in secs:
        for ln in s["lines"]:
            full = ln["text"]
            if _COUNT.search(full) and not _SOURCE.search(full):
                bad.append(f"{s['version']}: a count with no source: "
                           f"{full[:60]!r}")
            if len(full) > 400:
                bad.append(f"{s['version']}: a line over 400 characters")
    return bad


def find(sections: list, version: str) -> dict | None:
    """The section for an installed version. A release tag matches its own
    heading; a commit install (no tag) is the Unreleased section."""
    v = str(version or "").strip()
    if not v or v == "unknown":
        return None
    want = v if v.startswith("v") else "v" + v
    for s in sections:
        if s["version"].lower() == want.lower():
            return s
    if not re.match(r"^v?\d+\.\d+", v):
        return next((s for s in sections if s["version"] == "Unreleased"),
                    None)
    return None


def _load(path) -> dict | None:
    try:
        d = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _save(d: dict, path) -> None:
    try:
        with private.open_write(path) as f:
            f.write(json.dumps(d) + "\n")
    except OSError:
        pass


def card(version: str | None = None, text: str | None = None,
         path=None) -> dict | None:
    """The card to show, or None. Records the version on a first install
    (nothing is shown) and when the version has no changelog section."""
    from . import update
    path = path or STATE
    v = version if version is not None else update.installed_version()
    st = _load(path)
    if st is None:
        _save({"seen": v}, path)        # first install: nothing is new
        return None
    if st.get("seen") == v:
        return None
    if text is None:
        try:
            text = changelog_path().read_text()
        except OSError:
            text = ""
    sec = find(parse(text), v)
    if not sec or not sec["lines"]:
        _save({"seen": v}, path)
        return None
    head = sec["lines"][:HEADLINES]
    return {"version": v, "title": sec["version"], "date": sec["date"],
            "lines": [h["text"] for h in head],
            "credits": sorted({h["who"] for h in head if h["who"]}),
            "more": len(sec["lines"]) - len(head), "url": URL}


def mark_seen(version: str | None = None, path=None) -> str:
    from . import update
    v = version if version is not None else update.installed_version()
    _save({"seen": v}, path or STATE)
    return v
