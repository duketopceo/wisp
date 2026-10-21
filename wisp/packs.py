"""Capture packs: the durable per-turn evidence artifact (U4, R6/R10/R11).

At turn end the act loop calls `write()`, which folds the transient
`~/.local/share/wisp/rec/<turn>/` recording into a durable
`~/.local/share/wisp/packs/<turn>/` directory:

    manifest.json   schema "wisp-capture-pack/v1" — turn id, session,
                    transcript lines with timestamps, actions with
                    verdicts + turn_dir refs, frame index
    turn-NNNNN/     frame PNGs (before/after/click-annotated/terminal),
                    the redacted action.json, evidence.json, AT-SPI
                    state dumps
    contact.png     montage of the turn's frames (PIL grid first,
                    ImageMagick `montage` fallback, omitted otherwise —
                    a missing backend never fails the pack)

Invariants (plan stop conditions):

- packs/ and rec/ are mode 0700; manifest.json and the salt file 0600.
- Keyboard-bearing args (type_text/key text) never persist as
  plaintext in a pack — pack copies carry length + an HMAC-SHA256
  salted hash. The salt is a per-install random file
  (~/.local/share/wisp/pack.salt, 0600): repeats correlate within a
  store but cannot be dictionary-reversed, and the salt never leaves
  the install (unlike cua_safety's per-process salt, pack copies are
  durable — a fixed source salt would make typed-text hashes
  dictionary-attackable at rest).
- Privacy: the pack-write re-checks deny-surface visibility
  (verify.visible_deny). A visible deny-listed surface — or an
  unreadable window list — suppresses the whole turn: every frame PNG
  is deleted via verify.suppress (quarantine is deletion, not
  retention) and the suppression is recorded in the manifest. Turn
  dirs already flagged privacy_suppressed by the mid-loop re-check
  get a second pass — the driver's after.png can land after the
  suppress that removed its siblings. No deny-interval frame
  survives the turn.
- Retention: [packs] keep (count) AND keep_days (age) bound packs/;
  an evicted pack's rec/<turn> intermediates go with it. rec/ is
  transient — after a pack write the turn's own dir is removed and
  siblings are swept too (act runs serialize on the daemon's busy
  lock, so no sibling can be mid-turn; the daemon-start orphan sweep
  in record.sweep_orphans covers crashes anyway).
- shots/ (the screenshot tool's working dir, tools/system.py) has an
  explicit pruning owner: THIS module, on the same count+age policy
  via [packs] shots_keep / shots_keep_days. The policy is declared in
  config and the settings schema — shots are never deleted outside
  those keys.
- Manifest text is untrusted data: control characters are stripped at
  write (KTD4); consumers that feed pack text to a model must keep it
  quoted, never interpolated as instructions.

`wispd captures` serves packs over the peer-cred'd IPC socket —
metadata + frame paths by default; transcript lines and AT-SPI state
dumps only behind --full (they can hold utterances and window text).
"""
import hashlib
import hmac
import json
import os
import pathlib
import re
import shutil
import time
from datetime import datetime, timezone

from . import config, record, verify

SCHEMA = "wisp-capture-pack/v1"
PACKS_DIR = config.DATA_DIR / "packs"
SALT_FILE = config.DATA_DIR / "pack.salt"
SHOTS_DIR = config.DATA_DIR / "shots"

_TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# control chars must never reach durable pack text (KTD4 — pack text
# is untrusted input to later judge/review passes)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_MAX_TEXT = 1000
# tools whose arg is typed keyboard input — the wisp toolbelt names and
# the driver-side names a recorded action.json can carry
_KEYBOARD_TOOLS = {
    "type_text", "type", "input_text", "send_text", "send_keys",
    "key", "keys", "hotkey", "press",
}
# arg fields that stay cleartext even on a keyboard action (routing
# metadata, never typed content)
_BENIGN_ARGS = {"session", "scope", "x", "y", "ms", "ts", "epoch"}
_CONTACT_MAX = 24          # frames in one montage


def _f(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _num(v, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def settings(cfg: dict | None) -> dict:
    """[packs] retention. keep/keep_days bound packs/; shots_keep/
    shots_keep_days are the shots/ policy this module owns. A 0 on an
    axis disables it."""
    p = (cfg or {}).get("packs", {}) or {}
    return {
        "keep": _num(p.get("keep"), 200),
        "keep_days": _num(p.get("keep_days"), 30),
        "shots_keep": _num(p.get("shots_keep"), 100),
        "shots_keep_days": _num(p.get("shots_keep_days"), 30),
    }


# -------------------------------------------------------------- text

def _clean(s) -> str:
    """Strip control characters and cap length — pack text is untrusted
    data (KTD4)."""
    return _CTRL_RE.sub(" ", str(s))[:_MAX_TEXT]


def _deep_clean(obj):
    if isinstance(obj, str):
        return _clean(obj)
    if isinstance(obj, dict):
        return {k: _deep_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_clean(v) for v in obj]
    return obj


def _json(path) -> dict | None:
    try:
        d = json.loads(pathlib.Path(path).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _mk_0700(path: pathlib.Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


# ---------------------------------------------------------- redaction

def _salt() -> bytes:
    """Per-install HMAC salt for typed-text redaction — created once at
    ~/.local/share/wisp/pack.salt (0600). Falls back to a throwaway
    salt rather than ever writing plaintext."""
    p = pathlib.Path(SALT_FILE)
    try:
        data = p.read_bytes()
        if len(data) >= 16:
            return data
    except OSError:
        pass
    data = os.urandom(32)
    try:
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(p, 0o600)
    except OSError:
        pass
    return data


def _redacted(text: str, salt: bytes) -> dict:
    """Length + salted HMAC-SHA256 in place of typed text — the
    cua_safety audit convention, durable."""
    return {"redacted": True, "len": len(text),
            "sha256": hmac.new(salt, text.encode("utf-8", "replace"),
                               hashlib.sha256).hexdigest()}


def _redact_args(tool: str, args, salt: bytes):
    """Redact a recorded action's args dict for the pack copy. Only
    keyboard-bearing tools carry typed text; everything else passes
    through cleaned but intact (coords, options)."""
    if tool not in _KEYBOARD_TOOLS or not isinstance(args, dict):
        return args
    out = {}
    for k, v in args.items():
        if k in _BENIGN_ARGS or not isinstance(v, str) or not v:
            out[k] = v
        else:
            out[k] = _redacted(v, salt)
    return out


def _manifest_arg(tool: str, arg, salt: bytes):
    """The step record's `arg` for the manifest action list — keyboard
    tools get the salted-hash form, everything else the cleaned text."""
    text = "" if arg is None else str(arg)
    if tool in _KEYBOARD_TOOLS and text:
        return _redacted(text, salt)
    return _clean(text)


def _redacted_action(src: pathlib.Path, salt: bytes) -> dict:
    """The pack's copy of action.json — identical to the driver's
    except keyboard args are the redacted form."""
    d = _json(src)
    if not isinstance(d, dict):
        return {"unparseable": True}
    tool = str(d.get("tool") or "")
    if tool in _KEYBOARD_TOOLS:
        d = dict(d)
        d["args"] = _redact_args(tool, d.get("args"), salt)
        # a keyboard action may also carry the text at top level
        for k in ("arg", "text", "keys"):
            if isinstance(d.get(k), str) and d[k]:
                d[k] = _redacted(d[k], salt)
    return d


# ------------------------------------------------------------ frames

def _turn_dirs(rec_dir) -> list:
    d = pathlib.Path(rec_dir) if rec_dir else None
    if d is None or not d.is_dir():
        return []
    try:
        return sorted(p for p in d.iterdir()
                      if p.is_dir() and record._TURN_RE.match(p.name))
    except OSError:
        return []


def _link_or_copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Prefer a hardlink (same volume, zero extra bytes — the rec/ copy
    is deleted after write, so the pack owns the inode); copy on
    cross-device or any link failure."""
    try:
        dst.unlink(missing_ok=True)
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _frame_kind(name: str) -> str:
    if name.startswith("observe") and name.endswith(
            (".png", ".jpg", ".jpeg")):
        return "observe"    # U5 observe-frame provenance
    if name.endswith(".png"):
        return "frame"
    if name.endswith("_state.json"):
        return "state"      # AT-SPI dumps can hold window text (--full)
    return "meta"


def _collect_frames(pack: pathlib.Path, dirs: list,
                    salt: bytes) -> tuple:
    """Copy each turn dir's evidence into the pack; returns the frame
    index and the ordered PNG list for the contact sheet."""
    index, pngs = [], []
    for d in dirs:
        dst = pack / d.name
        dst.mkdir(mode=0o700, exist_ok=True)
        entry = {"dir": d.name, "bytes": 0, "files": []}
        try:
            files = sorted(d.iterdir())
        except OSError:
            files = []
        for src in files:
            if src.is_dir():
                continue
            kind = _frame_kind(src.name)
            if kind == "meta" and src.name != "action.json" \
                    and src.suffix not in (".json", ".jsonl"):
                continue    # non-JSON strays stay transient
            out = dst / src.name
            try:
                if src.name == "action.json":
                    # never link the driver's copy: it holds cleartext
                    out.write_text(json.dumps(
                        _redacted_action(src, salt),
                        separators=(",", ":")))
                    os.chmod(out, 0o600)
                elif kind == "meta" and src.suffix == ".json":
                    # evidence.json-style docs may also embed a
                    # keyboard action's args — run the same pass
                    red = _redacted_action(src, salt)
                    if "unparseable" in red:
                        _link_or_copy(src, out)
                    else:
                        out.write_text(json.dumps(
                            red, separators=(",", ":")))
                        os.chmod(out, 0o600)
                else:
                    _link_or_copy(src, out)
                sz = out.stat().st_size
            except OSError:
                continue
            entry["bytes"] += sz
            entry["files"].append(
                {"name": src.name, "kind": kind, "bytes": sz})
            if kind in ("frame", "observe"):
                pngs.append(out)
        index.append(entry)
    return index, pngs


# ------------------------------------------------------- contact sheet

try:
    from PIL import Image as _Image
    _PIL = True
except ImportError:
    _PIL = False


def _montage_bin() -> list | None:
    """argv prefix for ImageMagick montage, or None."""
    m = shutil.which("montage")
    if m:
        return [m]
    if shutil.which("magick"):
        return ["magick", "montage"]
    return None


def _contact_pil(pngs: list, out: pathlib.Path) -> bool:
    """4-column thumbnail grid via PIL."""
    thumb_w, thumb_h, gap, cols = 320, 240, 4, 4
    imgs = []
    for p in pngs[:_CONTACT_MAX]:
        try:
            with _Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((thumb_w, thumb_h))
                imgs.append(im.copy())
        except Exception:
            continue
    if not imgs:
        return False
    rows = (len(imgs) + cols - 1) // cols
    sheet = _Image.new("RGB",
                       (cols * thumb_w + (cols + 1) * gap,
                        rows * thumb_h + (rows + 1) * gap),
                       (24, 24, 24))
    for i, im in enumerate(imgs):
        x = gap + (i % cols) * (thumb_w + gap)
        y = gap + (i // cols) * (thumb_h + gap)
        sheet.paste(im, (x, y))
    try:
        sheet.save(out)
        return True
    except Exception:
        return False


def _contact_magick(pngs: list, out: pathlib.Path,
                    montage: list) -> bool:
    from . import cancel as _cancel
    cmd = montage + ["-tile", "4x", "-geometry", "320x240+4+4+2"] \
        + [str(p) for p in pngs[:_CONTACT_MAX]] + [str(out)]
    try:
        r = _cancel.run(cmd, capture_output=True, timeout=60)
        return r.returncode == 0 and out.exists()
    except Exception:
        return False


def _contact_sheet(pngs: list, out: pathlib.Path,
                   montage=None) -> dict:
    """contact.png manifest entry; never fails the pack."""
    if not pngs:
        return {"file": None, "note": "no frames", "frames": 0}
    if _PIL and _contact_pil(pngs, out):
        return {"file": out.name, "backend": "pil",
                "frames": min(len(pngs), _CONTACT_MAX)}
    mb = montage if montage is not None else _montage_bin()
    if mb and _contact_magick(pngs, out, mb):
        return {"file": out.name, "backend": "montage",
                "frames": min(len(pngs), _CONTACT_MAX)}
    return {"file": None,
            "note": "no contact backend (no PIL, no ImageMagick)",
            "frames": 0}


# --------------------------------------------------------------- write

def _action_ts(action: dict):
    return record._action_ts(action)


def _actions_index(pack: pathlib.Path, steps: list,
                   salt: bytes) -> tuple:
    """Manifest action list from the step records: verdict, evidence
    ref rebased into the pack, ts pulled from the copied action.json.
    Read-only steps (no verdict, no turn_dir) are not action records."""
    actions, stamps = [], []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        tdir = s.get("turn_dir")
        if not tdir and "verdict" not in s and "verify" not in s:
            continue
        a = {"tool": s.get("tool"),
             "arg": _manifest_arg(s.get("tool") or "", s.get("arg"),
                                  salt),
             "turn_dir": pathlib.Path(str(tdir)).name if tdir else None,
             "verdict": s.get("verdict")}
        v = s.get("verify")
        if isinstance(v, dict):
            v = dict(v)
            if v.get("evidence"):
                # rebase the absolute rec path onto the pack dir name
                v["evidence"] = pathlib.Path(str(v["evidence"])).name
            a["verify"] = v
            a["verdict"] = v.get("verdict", a["verdict"])
        for k in ("route", "transport", "delivery"):
            if s.get(k):
                a[k] = s[k]
        if s.get("result"):
            a["result"] = _clean(s["result"])[:300]
        if tdir:
            aj = _json(pack / a["turn_dir"] / "action.json") or {}
            ts = _action_ts(aj)
            if ts is not None:
                a["ts"] = ts
                stamps.append(ts)
        actions.append(a)
    verdicts = {}
    for a in actions:
        v = a.get("verdict") or "none"
        verdicts[v] = verdicts.get(v, 0) + 1
    return actions, verdicts, stamps


def _transcript(lines, now: float, t0) -> list:
    """Sanitized transcript entries; a missing ts anchors the user line
    at the turn's first action, the rest at pack time."""
    out = []
    for e in lines or []:
        if not isinstance(e, dict):
            continue
        text = _clean(e.get("text") or "")
        if not text:
            continue
        ts = e.get("ts")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            ts = t0 if e.get("role") == "user" and t0 else now
        out.append({"ts": round(float(ts), 3),
                    "role": _clean(e.get("role") or "note")[:16],
                    "text": text})
    return out


def _privacy_recheck(dirs: list, cfg: dict, clients, monitors) -> tuple:
    """KTD6 pack-write pass. Returns (suppressed, events)."""
    off, readable = verify.visible_deny(cfg, clients=clients,
                                        monitors=monitors)
    if not readable:
        why = "compositor window list unreadable"
        stage = "pack"
    elif off is not None:
        why = ("deny-listed surface visible: "
               + str(off.get("class") or off.get("title") or "?"))
        stage = "pack"
    else:
        why, stage = "", ""
    events = []
    if why:
        for d in dirs:
            ev = verify.suppress(d, why)
            events.append({"dir": d.name, "stage": stage, **ev})
        return True, events
    # loop-stage suppressions: evidence.json carries the flag — delete
    # stragglers (a lagging after.png can land after the suppress that
    # removed its siblings) and record them again here
    for d in dirs:
        evj = _json(d / "evidence.json") or {}
        sup = evj.get("suppression")
        if evj.get("privacy_suppressed"):
            ev = verify.suppress(
                d, (sup or {}).get("reason")
                or "deny interval (loop-stage)")
            ev = dict(ev, stage="loop")
            events.append({"dir": d.name, **ev})
    return bool(events), events


def write(turn: str, steps: list, cfg: dict | None = None, *,
          rec_dir=None, recorded: bool = False, transcript=None,
          session: str = "wisp", clients=None, monitors=None,
          root=None, rec_root=None, clean_rec: bool = True,
          contact=None) -> pathlib.Path | None:
    """Fold the turn's recording into packs/<turn>/; returns the dir.

    None when the turn has nothing durable — no recording (daemon
    down / guide mode), no turn dirs, no recorded steps: a bare
    transcript already lives in session.jsonl, an empty pack is noise.
    Never raises; the act loop's finally must not learn a failure mode
    from the artifact path."""
    try:
        return _write(turn, steps, cfg, rec_dir=rec_dir,
                      recorded=recorded, transcript=transcript,
                      session=session, clients=clients,
                      monitors=monitors, root=root, rec_root=rec_root,
                      clean_rec=clean_rec, contact=contact)
    except Exception:
        return None


def _write(turn, steps, cfg, *, rec_dir, recorded, transcript, session,
           clients, monitors, root, rec_root, clean_rec, contact):
    turn = str(turn or "")
    if not turn or turn == "sys" or not _TURN_ID_RE.match(turn):
        return None
    cfg = cfg or {}
    dirs = _turn_dirs(rec_dir)
    if not dirs and not recorded \
            and not any(isinstance(s, dict) and s.get("turn_dir")
                        for s in (steps or [])):
        return None
    now = time.time()
    salt = _salt()

    # R9/KTD6 — before any frame is copied, re-run the deny check over
    # the live window list; a visible deny surface quarantines the turn
    suppressed, events = _privacy_recheck(dirs, cfg, clients, monitors)

    root = pathlib.Path(root) if root else pathlib.Path(PACKS_DIR)
    _mk_0700(root)
    pack = root / turn
    _mk_0700(pack)

    index, pngs = _collect_frames(pack, dirs, salt)
    actions, verdicts, stamps = _actions_index(pack, steps or [], salt)
    t0 = min(stamps) if stamps else None
    lines = _transcript(transcript, now, t0)
    contact = contact if contact is not None else \
        _contact_sheet(pngs, pack / "contact.png")

    manifest = {
        "schema": SCHEMA,
        "turn": turn,
        "session": session or "wisp",
        "ts": round(now, 3),
        "created": datetime.now(timezone.utc).isoformat(),
        "transcript": lines,
        "actions": actions,
        "frames": index,
        "frame_count": sum(
            1 for e in index for f in e["files"]
            if f["kind"] in ("frame", "observe")),
        "verdicts": verdicts,
        "privacy_suppressed": bool(suppressed),
        "privacy": {"suppressed": bool(suppressed), "events": events},
        "contact": contact,
    }
    manifest = _deep_clean(manifest)
    tmp = pack / ".manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False,
                              separators=(",", ":")))
    os.chmod(tmp, 0o600)
    os.replace(tmp, pack / "manifest.json")
    _emit_pack(turn, manifest)
    # link the pack back onto the step records for the trajectory fold
    for s in steps or []:
        if isinstance(s, dict) and "verdict" in s:
            s["pack"] = f"packs/{turn}"

    if clean_rec:
        # rec/ is transient and in-flight-only: the just-packed turn's
        # intermediates are in the pack now, and the busy lock means no
        # sibling act run can be mid-turn — sweep them all
        rr = pathlib.Path(rec_root) if rec_root \
            else pathlib.Path(record.REC_DIR)
        _clean_rec(rr)
    maintenance(cfg, rec_root=rec_root)
    return pack


def _clean_rec(rec_root: pathlib.Path) -> list:
    """Remove every leftover rec/<turn>/ dir — stale intermediates,
    never promoted."""
    gone = []
    try:
        kids = sorted(rec_root.iterdir())
    except OSError:
        return gone
    for p in kids:
        if not p.is_dir() or p.is_symlink():
            continue
        try:
            shutil.rmtree(p)
            gone.append(p.name)
        except OSError:
            pass
    return gone


def _emit_pack(turn: str, manifest: dict) -> None:
    try:
        from . import trace as _trace
        _trace.emit(turn or _trace.current(), "pack", "rec", {
            "dir": f"packs/{turn}",
            "frames": manifest.get("frame_count", 0),
            "actions": len(manifest.get("actions") or []),
            "verdicts": manifest.get("verdicts"),
            "suppressed": manifest.get("privacy_suppressed")})
    except Exception:
        pass


# ------------------------------------------------------------ retention

def _entry_ts(path: pathlib.Path) -> float:
    """Sort key for retention: a pack's manifest ts, else mtime."""
    if path.is_dir():
        m = _json(path / "manifest.json")
        if m:
            ts = m.get("ts")
            if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                return float(ts)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _evict(root, keep: int, keep_days: int, now: float,
           rec_root=None) -> dict:
    """Age + count pruning over one store dir. `keep`/`keep_days` <= 0
    disables that axis. Pack evictions also drop the matching
    rec/<turn> intermediates."""
    root = pathlib.Path(root)
    out = {"removed": [], "rec_removed": []}
    try:
        kids = [p for p in root.iterdir()
                if not p.name.startswith(".")]
    except OSError:
        return out
    if keep_days > 0 or keep > 0:
        entries = sorted(((p, _entry_ts(p)) for p in kids),
                         key=lambda kv: kv[1], reverse=True)
        drop = set()
        if keep_days > 0:
            cutoff = now - keep_days * 86400
            for p, ts in entries:
                if ts < cutoff:
                    drop.add(p)
        if keep > 0:
            alive = [(p, ts) for p, ts in entries if p not in drop]
            for p, _ts in alive[keep:]:
                drop.add(p)
        for p in sorted(drop):
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                out["removed"].append(p.name)
            except OSError:
                continue
            if rec_root is not None:
                rec = pathlib.Path(rec_root) / p.name
                try:
                    if rec.is_dir():
                        shutil.rmtree(rec)
                        out["rec_removed"].append(p.name)
                except OSError:
                    pass
    return out


def prune(cfg: dict | None = None, *, now: float | None = None,
          root=None, rec_root=None) -> dict:
    """Enforce [packs] keep + keep_days on packs/."""
    st = settings(cfg)
    rr = rec_root if rec_root is not None else record.REC_DIR
    return _evict(root or PACKS_DIR, st["keep"], st["keep_days"],
                  now or time.time(), rec_root=rr)


def prune_shots(cfg: dict | None = None, *, now: float | None = None,
                root=None) -> dict:
    """shots/ retention — this module is the declared owner (see module
    docstring): the same count+age policy as packs, on its own keys."""
    st = settings(cfg)
    return _evict(root or SHOTS_DIR, st["shots_keep"],
                  st["shots_keep_days"], now or time.time())


def maintenance(cfg: dict | None = None, *, now: float | None = None,
                rec_root=None) -> dict:
    """One retention pass over every store this module owns — called
    after each pack write and once at daemon start."""
    st = settings(cfg)
    rr = rec_root if rec_root is not None else record.REC_DIR
    return {
        "packs": _evict(PACKS_DIR, st["keep"], st["keep_days"],
                        now or time.time(), rec_root=rr),
        "shots": _evict(SHOTS_DIR, st["shots_keep"],
                        st["shots_keep_days"], now or time.time()),
    }


# -------------------------------------------------------------- serves

def list_packs(root=None) -> list:
    """captures rows, newest first: turn, ts, action count, verdict
    histogram, frame count, path — metadata only, never transcript."""
    root = pathlib.Path(root) if root else pathlib.Path(PACKS_DIR)
    try:
        kids = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return []
    rows = []
    for p in kids:
        m = _json(p / "manifest.json")
        if not m:
            continue
        contact = m.get("contact") or {}
        rows.append({
            "turn": m.get("turn") or p.name,
            "ts": m.get("ts") or _entry_ts(p),
            "actions": len(m.get("actions") or []),
            "verdicts": m.get("verdicts") or {},
            "frames": m.get("frame_count") or 0,
            "suppressed": bool(m.get("privacy_suppressed")),
            "contact": contact.get("file"),
            "path": str(p)})
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows


def manifest(turn: str, *, full: bool = False, root=None) -> dict | None:
    """One pack's manifest for IPC. Without `full` the transcript lines
    and the *_state.json file entries (AT-SPI dumps — same sensitivity
    class as transcript text) are stripped; the files stay on disk."""
    root = pathlib.Path(root) if root else pathlib.Path(PACKS_DIR)
    m = _json(root / str(turn) / "manifest.json")
    if m is None:
        return None
    m = dict(m)
    m["path"] = str(root / str(turn))
    if full:
        return m
    lines = m.get("transcript") or []
    m["transcript"] = []
    m["transcript_lines"] = len(lines)
    if lines:
        m["transcript_gated"] = "--full"
    states = 0
    for e in m.get("frames") or []:
        keep = [f for f in e.get("files", [])
                if f.get("kind") != "state"]
        states += len(e.get("files", [])) - len(keep)
        e["files"] = keep
    if states:
        m["state_dumps_gated"] = "--full"
    return m


def captures_response(cmd: dict, root=None) -> dict:
    """The IPC `captures` handler's payload. `{"cmd":"captures"}` lists
    packs; `{"turn": "<id>"}` serves one manifest; `"full": true` opens
    the gated fields. Same-UID socket trust — the gate exists because
    transcript/state text is the sensitive class."""
    turn = str(cmd.get("turn") or "").strip()
    if turn:
        if not _TURN_ID_RE.match(turn):
            return {"ok": False, "error": "bad_turn"}
        m = manifest(turn, full=bool(cmd.get("full")), root=root)
        if m is None:
            return {"ok": False, "error": "no_such_pack"}
        return {"ok": True, "manifest": m}
    return {"ok": True, "packs": list_packs(root=root)}
