"""Share a lesson, skill or helper as one file, and take one in safely (B27).

`wispd export lesson|skill|helper NAME` writes a JSON bundle: what it is,
its text, and a SHA-256 over exactly that content. It holds no secrets, no
home paths and no memory (a helper's notes, inbox and output stay home).
`wispd import FILE|URL` shows the whole text, what it asks for and the
hash, then waits for a yes. Imported text is untrusted data:

- it cannot add a tool, lower a tier or change the confirm policy: a skill
  that declares `tool:`, `tier: safe|mutating` or a policy key is rejected
  with the reason, and script files never come in;
- nothing runs on import, and a helper's routines arrive paused with no
  timer installed;
- it never overwrites what you have: a taken name gets an `-imported`
  suffix, and the same bundle (same hash) imported twice changes nothing.
"""
import hashlib
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import agent_home, config, lessons, report, skills, util

VERSION = 1
KINDS = ("lesson", "skill", "helper")
MAX_BUNDLE = 256 * 1024
MAX_FETCH = MAX_BUNDLE
TEXT_EXT = (".md", ".txt", ".json", ".csv", ".yaml", ".yml")
MAX_FILE = 20 * 1024
MAX_FILES = 8
MAX_STEPS = 40
MAX_ROUTINES = 5
# frontmatter keys that would add a tool or change what needs a confirm
POLICY_KEYS = ("tool", "confirm", "autonomy", "policy", "allow",
               "allow_shell", "deny", "kill", "risk")
IMPORTS = config.DATA_DIR / "imports.json"


class ShareError(Exception):
    """A user-facing reason, one sentence."""


# -- hashing ----------------------------------------------------------------

def digest(kind: str, name: str, payload: dict) -> str:
    raw = json.dumps({"kind": kind, "name": name, "payload": payload},
                     sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def make(kind: str, name: str, payload: dict, now=None) -> dict:
    return {"wisp_bundle": VERSION, "kind": kind, "name": name,
            "payload": payload, "hash": digest(kind, name, payload),
            "created": time.strftime("%Y-%m-%d", time.gmtime(now))}


# -- cleaning on the way out ------------------------------------------------

def _home_res():
    out = []
    home = os.path.expanduser("~").rstrip("/")
    if home and home not in ("", "~"):
        out.append(re.compile(re.escape(home)))
    out.append(re.compile(r"/(?:home|Users)/[^/\s\"':]+"))
    return out


def clean(text, where: str) -> str:
    """Text for a bundle: home paths become `~`; a key, token or secret
    value is refused, naming where it was found."""
    s = str(text or "")
    for r in report._TOKEN_RES:
        if r.search(s):
            raise ShareError(
                f"{where} contains something that looks like a key or "
                "token. Remove it and export again.")
    for name, val in os.environ.items():
        if len(val) >= 8 and report.SECRET_KEY.search(name) and val in s:
            raise ShareError(f"{where} contains the value of "
                             f"${name}. Remove it and export again.")
    for r in _home_res():
        s = r.sub("~", s)
    return s


# -- export -----------------------------------------------------------------

def export_lesson(name: str, root=None) -> dict:
    want = lessons.slug(name)
    rec = next((r for r in lessons.all_lessons(root)
                if lessons.slug(r.get("title", "")) == want), None)
    if rec is None:
        raise ShareError(f"No saved lesson called {name!r}.")
    steps = []
    for i, s in enumerate(rec["steps"][:MAX_STEPS], 1):
        step = {"text": clean(s.get("text"), f"lesson step {i}"),
                "label": clean(s.get("label"), f"lesson step {i} label")}
        pt = s.get("point")
        step["point"] = None
        if isinstance(pt, dict) and all(
                isinstance(pt.get(a), (int, float))
                and not isinstance(pt.get(a), bool) for a in ("x", "y")):
            step["point"] = {"x": pt["x"], "y": pt["y"],
                             "label": clean(pt.get("label", ""),
                                            f"lesson step {i} point")}
        steps.append(step)
    title = clean(rec.get("title"), "the lesson title")
    return make("lesson", lessons.slug(title) or want, {
        "title": title, "goal": clean(rec.get("goal") or title,
                                      "the lesson goal"),
        "steps": steps})


def _strip_keys(text: str, drop=("tool", "tier")) -> tuple:
    """(text without those frontmatter lines, names dropped)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return text, []
    kept, dropped = [], []
    for line in m.group(1).splitlines():
        k = line.partition(":")[0].strip()
        (dropped if k in drop else kept).append(k if k in drop else line)
    head = "---\n" + "\n".join(x for x in kept) + "\n---\n"
    return head + text[m.end():], dropped


def export_skill(name: str, base=None) -> tuple:
    """(bundle, notes). Notes say what was left out and why."""
    base = pathlib.Path(base) if base else skills.SKILLS_DIR
    d = base / skills._slug(name)
    f = d / "SKILL.md"
    if not f.is_file():
        raise ShareError(f"No skill called {name!r}.")
    notes = []
    body, dropped = _strip_keys(f.read_text(errors="replace"))
    if dropped:
        notes.append("left out " + ", ".join(f"`{k}:`" for k in dropped)
                     + " (an imported skill cannot add a tool or set a "
                     "tier)")
    files = {}
    for p in sorted(d.iterdir()):
        if p.name == "SKILL.md":
            continue
        if p.is_symlink() or not p.is_file():
            notes.append(f"left out {p.name} (not a plain file)")
        elif p.suffix.lower() not in TEXT_EXT:
            notes.append(f"left out {p.name} (only text files are shared)")
        elif p.stat().st_size > MAX_FILE or len(files) >= MAX_FILES:
            notes.append(f"left out {p.name} (too many or too large)")
        else:
            files[p.name] = clean(p.read_text(errors="replace"),
                                  f"skill file {p.name}")
    payload = {"skill": clean(body, "SKILL.md"), "files": files}
    return make("skill", skills._slug(name), payload), notes


def _helper_title(h) -> str:
    try:
        m = re.search(r"^# (.+)$", (h / "AGENTS.md").read_text(),
                      re.MULTILINE)
    except OSError:
        return ""
    return m.group(1).strip() if m else ""


def export_helper(name: str, routine_ids=(), root=None,
                  store=None) -> tuple:
    h = agent_home.home(name, root)
    ident = h / "AGENTS.md"
    if not ident.is_file():
        raise ShareError(f"No helper called {name!r}.")
    notes = ["left out its notes, inbox and output (what it remembers "
             "stays on your machine)"]
    rts = []
    if routine_ids:
        from . import routines
        st = store or routines.RoutineStore()
        for rid in list(routine_ids)[:MAX_ROUTINES]:
            r = st.get(rid)
            if r is None:
                raise ShareError(f"No routine {rid!r}.")
            rts.append({"name": clean(r.name, f"routine {rid} name"),
                        "task": clean(r.task, f"routine {rid} task"),
                        "schedule": clean(r.schedule,
                                          f"routine {rid} schedule")})
    title = _helper_title(h) or h.name
    payload = {"title": clean(title, "the helper name"),
               "identity": clean(ident.read_text(errors="replace"),
                                 "AGENTS.md"),
               "routines": rts}
    return make("helper", agent_home._slug(title), payload), notes


# -- reading and checking ---------------------------------------------------

def fetch(url: str, opener=None) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ShareError("Only https addresses can be imported.")

    class _Https(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlparse(newurl).scheme != "https":
                raise ShareError("The address redirected away from https.")
            return super().redirect_request(req, fp, code, msg, headers,
                                            newurl)

    op = opener or urllib.request.build_opener(_Https)
    req = urllib.request.Request(url, headers={"User-Agent": "wispd-import",
                                               "Accept": "application/json"})
    try:
        with op.open(req, timeout=10) as r:
            data = r.read(MAX_FETCH + 1)
    except ShareError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ShareError(f"Could not fetch {u.hostname}: "
                         f"{getattr(e, 'reason', e)}.")
    if len(data) > MAX_FETCH:
        raise ShareError("That file is larger than 256 KB.")
    return data.decode("utf-8", errors="strict") if data else ""


def load(source: str, opener=None) -> dict:
    """Parse a bundle from a file path or an https URL."""
    if re.match(r"^https?://", source or "", re.I):
        text = fetch(source, opener)
    else:
        p = pathlib.Path(source).expanduser()
        try:
            if p.stat().st_size > MAX_BUNDLE:
                raise ShareError("That file is larger than 256 KB.")
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise ShareError(f"Could not read {source}.")
    try:
        b = json.loads(text)
    except ValueError:
        raise ShareError("That is not a Wisp bundle (not valid JSON).")
    return check(b)


def _str(v, where: str, limit: int) -> str:
    if not isinstance(v, str):
        raise ShareError(f"{where} must be text.")
    if len(v) > limit:
        raise ShareError(f"{where} is longer than {limit} characters.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", v):
        raise ShareError(f"{where} has control characters.")
    return v


def _check_skill(p: dict) -> dict:
    body = _str(p.get("skill"), "SKILL.md", 32 * 1024)
    meta = skills._frontmatter(body)
    if not meta.get("name") and not meta.get("description"):
        raise ShareError("SKILL.md has no front matter.")
    for k in POLICY_KEYS:
        if k in meta:
            raise ShareError(
                f"The skill declares `{k}:`, which would "
                + ("add a tool" if k == "tool"
                   else "change what needs your confirmation")
                + ". Imported skills are text only; ask the author to "
                "share it without that line.")
    if meta.get("tier", "shell") in ("safe", "mutating"):
        raise ShareError(
            f"The skill declares `tier: {meta['tier']}`, which would "
            "lower its confirm tier. Imported skills keep the strictest "
            "tier.")
    files = p.get("files") or {}
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ShareError("The skill's files are not a short list.")
    out = {}
    for fn, text in files.items():
        if (not isinstance(fn, str) or "/" in fn or "\\" in fn
                or fn.startswith(".") or ".." in fn
                or not fn.lower().endswith(TEXT_EXT) or len(fn) > 60):
            raise ShareError(f"The skill ships {fn!r}: only plain text "
                             "files (.md, .txt, .json, .csv, .yaml) come "
                             "in, never scripts.")
        out[fn] = _str(text, f"file {fn}", MAX_FILE)
    return {"skill": body, "files": out}


def _check_lesson(p: dict) -> dict:
    steps = p.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        raise ShareError(f"A lesson has 1 to {MAX_STEPS} steps.")
    out = []
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            raise ShareError(f"Step {i} is not a step.")
        pt = s.get("point")
        if pt is not None:
            if not (isinstance(pt, dict) and all(
                    isinstance(pt.get(a), (int, float))
                    and not isinstance(pt.get(a), bool)
                    for a in ("x", "y"))):
                raise ShareError(f"Step {i} has a bad point.")
            pt = {"x": pt["x"], "y": pt["y"],
                  "label": _str(pt.get("label", ""),
                                f"step {i} point label", 160)}
        out.append({"text": _str(s.get("text"), f"step {i}", 600),
                    "label": _str(s.get("label", ""), f"step {i} label",
                                  160),
                    "point": pt})
        if not out[-1]["text"].strip():
            raise ShareError(f"Step {i} says nothing.")
    return {"title": _str(p.get("title"), "the title", 120),
            "goal": _str(p.get("goal") or p.get("title"), "the goal", 300),
            "steps": out}


def _check_helper(p: dict) -> dict:
    ident = _str(p.get("identity"), "the identity text", 4000)
    if not ident.strip():
        raise ShareError("The helper has no identity text.")
    rts = p.get("routines") or []
    if not isinstance(rts, list) or len(rts) > MAX_ROUTINES:
        raise ShareError(f"A helper bundle holds at most {MAX_ROUTINES} "
                         "routines.")
    out = []
    for i, r in enumerate(rts, 1):
        if not isinstance(r, dict):
            raise ShareError(f"Routine {i} is not a routine.")
        out.append({"name": _str(r.get("name"), f"routine {i} name", 80),
                    "task": _str(r.get("task"), f"routine {i} task", 600),
                    "schedule": _str(r.get("schedule", "daily"),
                                     f"routine {i} schedule", 60)})
    return {"title": _str(p.get("title"), "the helper name", 60),
            "identity": ident, "routines": out}


def check(b) -> dict:
    """The bundle, validated and with its hash proven, or ShareError."""
    if not isinstance(b, dict) or b.get("wisp_bundle") != VERSION:
        raise ShareError("That is not a Wisp bundle this version reads.")
    kind = b.get("kind")
    if kind not in KINDS:
        raise ShareError(f"Unknown bundle kind {kind!r}.")
    name = _str(b.get("name"), "the name", 80)
    if not util.slug(name, default=""):
        raise ShareError("The bundle has no usable name.")
    payload = b.get("payload")
    if not isinstance(payload, dict):
        raise ShareError("The bundle has no content.")
    payload = {"lesson": _check_lesson, "skill": _check_skill,
               "helper": _check_helper}[kind](payload)
    want = digest(kind, name, payload)
    if b.get("hash") != want:
        raise ShareError("The hash does not match the content: the file "
                         "was changed after it was exported.")
    return {"kind": kind, "name": name, "payload": payload, "hash": want}


# -- showing it -------------------------------------------------------------

def permissions(v: dict) -> list:
    k, p = v["kind"], v["payload"]
    keep = ["It runs nothing on import and adds no tool.",
            "It does not change your confirm settings or any tier."]
    if k == "lesson":
        return ["When you replay it, Wisp speaks each step and points at "
                "the labelled place on screen; it takes no action."] + keep
    if k == "skill":
        return ["Its text may be read by the assistant when a request "
                "matches it. It is data, not instructions you have "
                "approved."] + keep
    out = ["Its identity text becomes the opening of the prompt for a "
           "background agent whenever you ask for this helper by name; the "
           "usual contract and your confirm settings still apply."] + keep
    if p["routines"]:
        out.append(f"{len(p['routines'])} routine(s) arrive PAUSED, with no "
                   "timer installed. Nothing runs until you resume one "
                   "with `wispd routine resume`.")
    return out


def describe(v: dict) -> str:
    k, p = v["kind"], v["payload"]
    out = [f"{k}: {v['name']}", f"hash: {v['hash']}", "", "It asks for:"]
    out += [f"  - {x}" for x in permissions(v)] + ["", "Its full text:", ""]
    if k == "lesson":
        out += [f"title: {p['title']}", f"goal: {p['goal']}"]
        for i, s in enumerate(p["steps"], 1):
            lab = f"  [at: {s['label']}]" if s["label"] else ""
            out.append(f"{i}. {s['text']}{lab}")
    elif k == "skill":
        out += [p["skill"].rstrip()]
        for fn, text in p["files"].items():
            out += ["", f"--- file {fn} ---", text.rstrip()]
    else:
        out += [p["identity"].rstrip()]
        for r in p["routines"]:
            out += ["", f"routine (paused): {r['name']}  [{r['schedule']}]",
                    f"  task: {r['task']}"]
    return "\n".join(out)


# -- applying it ------------------------------------------------------------

def _manifest() -> dict:
    try:
        d = json.loads(IMPORTS.read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _remember(v: dict, stored: str, path=None) -> None:
    from . import private
    m = _manifest() if path is None else _manifest_at(path)
    m[v["hash"]] = {"kind": v["kind"], "name": v["name"],
                    "stored": stored,
                    "when": time.strftime("%Y-%m-%d")}
    with private.open_write(path or IMPORTS) as f:
        f.write(json.dumps(m, indent=1, sort_keys=True) + "\n")


def _manifest_at(path) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _marker(v: dict) -> str:
    return f"<!-- imported from a bundle, {v['hash']} -->"


def _free(base: pathlib.Path, stem: str, exists, ours) -> tuple:
    """(stem to use, already_there): the plain name when free, `-imported`
    when it is taken by something else, and already_there when the thing
    on disk is this very bundle."""
    for cand in (stem, stem + "-imported", stem + "-imported-2"):
        if not exists(cand):
            return cand, False
        if ours(cand):
            return cand, True
    raise ShareError(f"The names {stem!r} and {stem + '-imported'!r} are "
                     "both taken; rename one and import again.")


def apply(v: dict, *, lessons_dir=None, skills_dir=None, agents_root=None,
          store=None, manifest=None) -> dict:
    """Write the bundle. Returns {status: imported|unchanged, kind, name,
    stored, note}. Call only after the user said yes."""
    m = _manifest_at(manifest) if manifest is not None else _manifest()
    k, p = v["kind"], v["payload"]
    if k == "lesson":
        out = _apply_lesson(v, p, lessons_dir or lessons._dir())
    elif k == "skill":
        out = _apply_skill(v, p, pathlib.Path(skills_dir or
                                              skills.SKILLS_DIR))
    else:
        out = _apply_helper(v, p, agents_root, store)
    if out["status"] == "imported" or v["hash"] not in m:
        _remember(v, out["stored"], manifest)
    return out


def _apply_lesson(v, p, root) -> dict:
    root = pathlib.Path(root)
    stem = lessons.slug(p["title"]) or util.slug(v["name"], default="lesson")

    def ours(c):
        try:
            return json.loads((root / (c + ".json")).read_text()
                              ).get("imported") == v["hash"]
        except (OSError, ValueError):
            return False
    name, there = _free(root, stem, lambda c: (root / (c + ".json"))
                        .exists(), ours)
    if there:
        return {"status": "unchanged", "kind": "lesson", "name": name,
                "stored": str(root / (name + ".json")),
                "note": "this bundle is already imported"}
    rec = {"title": p["title"] if name == stem else p["title"] + " (imported)",
           "goal": p["goal"], "steps": p["steps"], "saved": time.time(),
           "imported": v["hash"]}
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (name + ".tmp")
    tmp.write_text(json.dumps(rec))
    os.replace(tmp, root / (name + ".json"))
    return {"status": "imported", "kind": "lesson", "name": name,
            "stored": str(root / (name + ".json")),
            "note": "" if name == stem else
            f"you already had {stem!r}; kept yours and saved this as "
            f"{name!r}"}


def _apply_skill(v, p, base: pathlib.Path) -> dict:
    stem = skills._slug(v["name"])

    def has(c):
        return (base / c / "SKILL.md").exists()

    def ours(c):
        try:
            return _marker(v) in (base / c / "SKILL.md").read_text()
        except OSError:
            return False
    name, there = _free(base, stem, has, ours)
    d = base / name
    if there:
        return {"status": "unchanged", "kind": "skill", "name": name,
                "stored": str(d), "note": "this bundle is already imported"}
    d.mkdir(parents=True, exist_ok=True)
    text = p["skill"].rstrip("\n") + "\n\n" + _marker(v) + "\n"
    (d / "SKILL.md").write_text(text)
    for fn, body in p["files"].items():
        (d / fn).write_text(body)
    return {"status": "imported", "kind": "skill", "name": name,
            "stored": str(d), "note": "" if name == stem else
            f"you already had {stem!r}; kept yours and saved this as "
            f"{name!r}"}


def _apply_helper(v, p, root, store) -> dict:
    from . import routines
    stem = agent_home._slug(p["title"] or v["name"])

    def has(c):
        return (agent_home.home(c, root) / "AGENTS.md").exists()

    def ours(c):
        try:
            return _marker(v) in (agent_home.home(c, root)
                                  / "AGENTS.md").read_text()
        except OSError:
            return False
    name, there = _free(None, stem, has, ours)
    h = agent_home.home(name, root)
    note = "" if name == stem else (
        f"you already had a helper {stem!r}; kept it and saved this as "
        f"{name!r}")
    if not there:
        for sub in ("notes", "output", "tmp"):
            (h / sub).mkdir(parents=True, exist_ok=True)
        ident = p["identity"].rstrip("\n")
        if name != stem:
            ident = re.sub(r"^# .+$", f"# {p['title']} (imported)", ident,
                           count=1, flags=re.M)
        (h / "AGENTS.md").write_text(ident + "\n\n" + _marker(v) + "\n")
    st = store or routines.RoutineStore()
    paused = []
    for r in p["routines"]:
        rid = util.slug(f"{name}-{r['name']}", max_len=36, default="routine")
        if st.get(rid) is not None:
            continue
        st.save(routines.Routine(id=rid, name=r["name"], task=r["task"],
                                 schedule=r["schedule"], enabled=False,
                                 paused=True, opt_in_confirmed=False,
                                 last_status="paused"))
        paused.append(rid)
    if there and not paused:
        return {"status": "unchanged", "kind": "helper", "name": name,
                "stored": str(h), "paused": [],
                "note": "this bundle is already imported"}
    if paused:
        note = (note + "; " if note else "") + (
            f"{len(paused)} routine(s) arrived paused: "
            + ", ".join(paused))
    return {"status": "imported", "kind": "helper", "name": name,
            "stored": str(h), "paused": paused, "note": note}
