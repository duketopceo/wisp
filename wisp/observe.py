"""`observe` — the U5 model-facing frame capture.

One call captures one frame for the model to look at:

- the focused app's control channel `ui.screenshot` when the app ships
  a channel (U3) — the app writes the PNG itself into our evidence
  dir;
- else a cua `zoom` on the focused window — a window-cropped JPEG in
  the run's own "wisp" session. Snapshot-first: a
  get_window_state{include_screenshot} primes the session's screenshot
  context (and carries the window dims the crop needs) before zoom
  cuts the region; screenshot_context_missing gets one re-prime retry.

Privacy (R9/KTD6): verify.visible_deny runs BEFORE any capture — the
same visible deny-surface gate the verify path applies. A deny-listed
surface on a visible workspace, or an unreadable window list, returns
SUPPRESSED: no frame, no rec/ dir, no pack entry. A denied surface is
never captured for the model.

Pack linkage (U4): a captured frame lands in a `turn-9NNNN/` dir
minted under the turn's rec/ root, with a driver-shaped action.json +
evidence.json carrying kind:"observe" provenance — packs.write then
indexes it in manifest["frames"] like any recorded evidence. The
9NNNN range sits far above the driver's sequential mint (turn-00001
upward), so an observe dir can never collide with an action dir the
driver numbers later, and sorted order keeps observe dirs last in the
frame index. Without a turn context the frame falls back to shots/
like the screenshot tool — inspectable, just not pack-linked.
"""
import base64
import json
import os
import pathlib
import re
import stat
import time
from datetime import datetime

from . import config, control, cua, record, verify
from . import trace as _trace

SHOTS_DIR = config.DATA_DIR / "shots"

# turn-9NNNN — far above the driver's sequential mint (turn-00001
# up): an observe dir can't collide with an action dir the driver
# numbers later, and the pack's sorted frame index keeps observes last.
OBSERVE_BASE = 90000
OBSERVE_MAX = 32              # observe dirs per turn — a bound, not a knob
IMG_CAP = 8 * 1024 * 1024     # an untrusted reply's image can't be huge

_LIST_TIMEOUT_S = 3.0
_STATE_TIMEOUT_S = 8.0
_ZOOM_TIMEOUT_S = 5.0

# 'x1,y1,x2,y2' — a window-local crop region for the zoom lane; any
# other non-empty arg is a panel name for the channel lane
_REGION_RE = re.compile(
    r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")

# payload keys an inline image can hide under, and path keys a
# file-referenced frame rides on — channel + driver reply shapes are
# untrusted input, scan rather than assert
_B64_KEYS = ("image", "screenshot", "jpeg", "png", "data",
             "image_data", "bytes", "b64", "base64", "content")
_PATH_KEYS = ("file", "path", "file_path", "screenshot_file_path",
              "screenshot_path", "out", "output")


# ------------------------------------------------------------- entry

def observe(arg: str, cfg: dict | None = None) -> str:
    """The toolbelt executor (REGISTRY): one call, one result line.
    Never raises — a broken observe reads SKIP, not a crashed loop."""
    try:
        return capture(arg, cfg, rec_dir=_rec_dir())["result"]
    except Exception as e:
        return f"SKIP (observe failed: {str(e)[:160]})"


def capture(arg: str, cfg: dict | None = None, *, rec_dir=None,
            win=None, active=None, clients=None, monitors=None,
            cua_client=None) -> dict:
    """One observe call -> {"result", "path", "turn_dir", "source",
    "suppressed"}.

    Compositor/driver seams are injectable for tests: `win` is a
    pre-resolved focused window (control.focused_window shape),
    `active`/`clients`/`monitors` are the raw compositor payloads,
    `cua_client` swaps the driver boundary for a fake `call()`."""
    cfg = cfg or {}
    arg = (arg or "").strip()
    # R9: the verify path's deny gate BEFORE any capture attempt —
    # fail-safe on an unreadable window list, refuse a visible
    # deny-listed surface. Neither produces a frame nor a pack entry.
    off, readable = verify.visible_deny(cfg, clients=clients,
                                        monitors=monitors)
    if not readable:
        return _denied("compositor window list unreadable")
    if off is not None:
        cls = off.get("class") or off.get("title") or "?"
        return _denied(f"deny-listed surface visible: {cls}")

    if win is None:
        win = control.focused_window(clients=clients, active=active,
                                     cua=cua_client)
    panel, region = arg, None
    m = _REGION_RE.match(arg)
    if m:
        panel, region = "", [int(v) for v in m.groups()]

    # the dst dir mints lazily — only a lane that can actually produce
    # a frame leaves a turn-9NNNN behind
    dst_dir, base = None, None

    # lane 1: the focused app's own control channel (U3)
    ch = control.channel(cfg, win)
    if ch is not None:
        win = ch[1]          # channel() may have resolved it for us
        dst_dir, base = _dst(rec_dir)
        frame = _via_channel(ch[0], panel, dst_dir, base)
        if frame is not None:
            return _frame_ok(frame, dst_dir, "control", arg)

    # lane 2: cua zoom on the focused window — the recording session's
    # snapshot context is what zoom crops
    c = cua_client if cua_client is not None else _cua_client()
    if c is not None and win is not None:
        if dst_dir is None:
            dst_dir, base = _dst(rec_dir)
        frame = _via_zoom(c, win, region, dst_dir, base)
        if frame is not None:
            return _frame_ok(frame, dst_dir, "zoom", arg)

    _drop_if_empty(dst_dir)
    why = ("no focused window — nothing to observe" if win is None
           else "channel and cua zoom both produced no frame")
    return {"result": f"SKIP (observe: {why})", "path": None,
            "turn_dir": None, "source": None, "suppressed": False}


# ------------------------------------------------------------- lanes

def _via_channel(ep, panel: str, dst_dir, base: str):
    """`ui.screenshot` on the app's channel: the app writes the PNG
    itself to the given path; an inline-image reply is written by us.
    Channel errors abstain (the zoom lane gets its try) — ControlError
    is closed-vocabulary, never an exception type that escapes."""
    try:
        client = control.ControlClient(ep.host, ep.port)
    except (ValueError, OSError):
        return None
    try:
        try:
            res = client.screenshot(
                panel=panel, path=str(dst_dir / f"{base}.png"))
        finally:
            client.close()
    except control.ControlError:
        return None
    p = dst_dir / f"{base}.png"
    # the app wrote into our evidence dir but its bytes stay untrusted:
    # a regular, in-cap file with image magic only — anything else is
    # deleted outright so a hostile channel can't leave non-image
    # content where the pack will pick it up (F3/F4)
    if _valid_frame_file(p):
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return p
    try:
        p.unlink()
    except OSError:
        pass
    data = _image_bytes(res, dst_dir)
    return _write_frame(dst_dir, base, data) if data else None


def _valid_frame_file(p: pathlib.Path) -> bool:
    """A channel-written frame: an existing regular file (never a
    symlink — the channel could point it anywhere), non-empty, at most
    IMG_CAP bytes, and real image magic."""
    try:
        st = p.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):   # lstat: symlinks fail here too
        return False
    if st.st_size <= 0 or st.st_size > IMG_CAP:
        return False
    try:
        with p.open("rb") as f:
            return _looks_image(f.read(16))
    except OSError:
        return False


def _via_zoom(c, win, region, dst_dir, base: str):
    """cua zoom on the focused window. `list_windows` picks the window
    (pid, then title/class, then identical frame geometry — never a
    blind first entry), `get_window_state` primes the session snapshot
    and yields the dims the region needs, `zoom` cuts the crop."""
    ent = _pick_window(c, win)
    if ent is None:
        return None
    wid = _int(ent.get("window_id"))
    pid = _int(ent.get("pid"))
    if pid is None:
        pid = _int((win or {}).get("pid"))
    if wid is None:
        return None
    st = _snapshot(c, pid, wid)
    if region is None:
        dims = _state_dims(st) or _win_dims(ent)
        if dims is None:
            b = (win or {}).get("bounds")
            if b:
                dims = (int(b[2]), int(b[3]))
        if not dims or dims[0] <= 0 or dims[1] <= 0:
            return None
        region = [0, 0, int(dims[0]), int(dims[1])]
    args = {"window_id": wid, "x1": int(region[0]),
            "y1": int(region[1]), "x2": int(region[2]),
            "y2": int(region[3])}
    if pid is not None:
        args["pid"] = pid
    res = None
    try:
        res = c.call("zoom", args, timeout=_ZOOM_TIMEOUT_S,
                     session=record.SESSION)
    except Exception as e:
        if "screenshot_context_missing" in str(e).lower():
            _snapshot(c, pid, wid)      # re-prime, then one retry
            try:
                res = c.call("zoom", args, timeout=_ZOOM_TIMEOUT_S,
                             session=record.SESSION)
            except Exception:
                res = None
    data = _image_bytes(res, dst_dir)
    return _write_frame(dst_dir, base, data) if data else None


def _snapshot(c, pid, wid) -> dict:
    """get_window_state{include_screenshot:true,
    include_accessibility_tree:false} — primes the session's screenshot
    context (what zoom crops) without paying for the AT-SPI walk; the
    reply also carries the dims the region needs. Best-effort: {} when
    it fails — an earlier snapshot may still serve zoom."""
    args = {"window_id": int(wid),
            "include_accessibility_tree": False,
            "include_screenshot": True}
    if pid is not None:
        args["pid"] = int(pid)
    try:
        r = c.call("get_window_state", args, timeout=_STATE_TIMEOUT_S,
                   session=record.SESSION)
        return r if isinstance(r, dict) else {}
    except Exception:
        return {}


def _pick_window(c, win) -> dict | None:
    """The list_windows entry for the focused window — pid match, then
    class/title, then identical frame geometry. A blind first-window
    pick would crop the wrong surface, and no focused window means
    there is nothing to match — don't even probe the driver."""
    if not isinstance(win, dict) or not win:
        return None
    try:
        res = c.call("list_windows", {}, timeout=_LIST_TIMEOUT_S,
                     session=record.SESSION)
    except Exception:
        return None
    wins = res.get("windows") if isinstance(res, dict) else res
    if not isinstance(wins, list):
        return None
    wins = [w for w in wins if isinstance(w, dict)]
    pid = _int((win or {}).get("pid"))
    if pid is not None:
        for w in wins:
            if _int(w.get("pid")) == pid:
                return w
    want = control._norm((win or {}).get("class") or "") \
        or control._norm((win or {}).get("title") or "")
    if want:
        for w in wins:
            have = (control._norm(w.get("class") or "") + " "
                    + control._norm(w.get("title") or "")).strip()
            if want in have or (have and have in want):
                return w
    b = (win or {}).get("bounds")
    if b:
        for w in wins:
            f = _win_frame(w)
            if f and all(abs(f[i] - b[i]) < 1.5 for i in range(4)):
                return w
    return None


# ------------------------------------------------------------- frame

def _frame_ok(frame, dst_dir, source: str, arg: str) -> dict:
    """Success envelope; the driver-shaped metadata pair is written
    when the frame landed in a minted turn dir (pack linkage)."""
    is_turn = dst_dir is not None \
        and bool(record._TURN_RE.match(dst_dir.name))
    if is_turn:
        _write_meta(dst_dir, source, arg)
    return {"result": f"SHOT {frame}", "path": frame,
            "turn_dir": dst_dir if is_turn else None,
            "source": source, "suppressed": False}


def _denied(why: str) -> dict:
    return {"result": (f"SUPPRESSED ({why} — observation declined; "
                       "no frame captured)"),
            "path": None, "turn_dir": None, "source": None,
            "suppressed": True}


def _write_meta(d, source: str, arg: str) -> None:
    """Driver-shaped action.json + evidence.json so the dir indexes
    and reads like recorded evidence: action_truth names the observe
    route, evidence carries the kind:"observe" provenance."""
    now = time.time()
    try:
        (d / "action.json").write_text(json.dumps({
            "tool": "observe",
            "args": {"session": record.SESSION,
                     **({"arg": arg} if arg else {})},
            "action_truth": {"effect": "delivered",
                             "route": f"observe:{source}",
                             "transport": source, "refusal": None},
            "ts": round(now, 3),
            "ms": int(time.monotonic() * 1000)},
            separators=(",", ":")))
        (d / "evidence.json").write_text(json.dumps({
            "kind": "observe", "source": source,
            "arg": arg[:200], "ts": round(now, 3)},
            separators=(",", ":")))
        for n in ("action.json", "evidence.json"):
            try:
                os.chmod(d / n, 0o600)
            except OSError:
                pass
    except OSError:
        pass


# ------------------------------------------------------------- files

def _dst(rec_dir):
    """(dir, base): a minted turn-9NNNN under the turn's rec/ root
    when a turn context exists; shots/ + a timestamped base for a
    context-less capture."""
    if rec_dir is not None:
        d = _turn_dir(rec_dir)
        if d is not None:
            return d, "observe"
    out = pathlib.Path(SHOTS_DIR)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = f"observe-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    return out, base


def _turn_dir(rec_dir) -> pathlib.Path | None:
    """Mint the next free turn-9NNNN dir under rec/<turn>/."""
    root = pathlib.Path(rec_dir)
    for i in range(OBSERVE_BASE, OBSERVE_BASE + OBSERVE_MAX):
        d = root / f"turn-{i:05d}"
        try:
            d.mkdir(mode=0o700, parents=True)
        except FileExistsError:
            continue            # a racing lane minted it first
        except OSError:
            return None
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        return d
    return None


def _drop_if_empty(d) -> None:
    """A minted-but-unused turn dir must not leave an empty artifact
    in the pack — drop it, and the rec/<turn>/ parent when it also
    went empty; a dir the app half-wrote keeps its files."""
    try:
        if d is not None and record._TURN_RE.match(d.name) \
                and not any(d.iterdir()):
            d.rmdir()
            try:
                d.parent.rmdir()
            except OSError:
                pass
    except OSError:
        pass


def _img_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    return ".png"     # unknown bytes still get a frame-shaped name


def _write_frame(dst_dir, base: str, data: bytes):
    if not data:
        return None
    p = dst_dir / f"{base}{_img_ext(data)}"
    try:
        p.write_bytes(data)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return p
    except OSError:
        return None


def _rec_dir():
    """The in-flight act turn's rec/<turn>/ root, or None without a
    turn context (a Jev-routed call, a CLI one-shot). Recorder.begin
    mints REC_DIR/trace.current() — deriving the same path lets an
    observe frame land beside the recorded actions."""
    try:
        turn = str(_trace.current() or "")
    except Exception:
        return None
    if not turn or turn == "sys":
        return None
    return pathlib.Path(record.REC_DIR) / turn


def _cua_client():
    try:
        return record._client(timeout_s=_STATE_TIMEOUT_S)
    except Exception:
        return None


# --------------------------------------------------------- reply data

_IMG_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff",
              b"GIF8", b"BM", b"RIFF")


def _looks_image(data: bytes) -> bool:
    """Untrusted-reply payload must actually BE an image — a hostile
    or broken channel naming ~/.ssh/id_rsa must not smuggle file
    bytes into the model conversation (or the pack)."""
    return data.startswith(_IMG_MAGIC)


def _image_bytes(res, root=None) -> bytes | None:
    """A base64/inline or file-referenced image out of an untrusted
    reply dict — capped at IMG_CAP bytes, image magic required. A
    file-referenced image is only honored when `root` is given AND the
    resolved real path sits inside it: a reply key must never become
    a read of an arbitrary host path (F4)."""
    if not isinstance(res, dict):
        return None
    for k in _B64_KEYS:
        v = res.get(k)
        if isinstance(v, dict):
            data = _image_bytes(v, root)
            if data:
                return data
        elif isinstance(v, str) and v:
            if v.startswith("data:"):
                v = v.split(",", 1)[-1]
            if len(v) > IMG_CAP * 2:   # b64 ~1.4x the bytes — over cap
                continue
            try:
                data = base64.b64decode(v, validate=True)
            except (ValueError, TypeError):
                continue
            if 0 < len(data) <= IMG_CAP and _looks_image(data):
                return data
    if root is None:
        return None
    try:
        root_r = pathlib.Path(root).resolve()
    except OSError:
        return None
    for k in _PATH_KEYS:
        v = res.get(k)
        if not (isinstance(v, str) and v):
            continue
        try:
            rp = pathlib.Path(v).resolve()
        except (OSError, RuntimeError):
            continue
        if not rp.is_relative_to(root_r):
            continue            # outside the evidence dir: refuse
        if not _valid_frame_file(rp):
            continue
        try:
            data = rp.read_bytes()
        except OSError:
            continue
        if 0 < len(data) <= IMG_CAP and _looks_image(data):
            return data
    return None


def _state_dims(res) -> tuple | None:
    """(w,h) of the snapshot image a get_window_state reply carried —
    screenshot dims first (that's the pixel space zoom crops), then
    the window's own bounds."""
    if not isinstance(res, dict):
        return None
    for k in ("screenshot", "image", "capture", "shot"):
        v = res.get(k)
        if isinstance(v, dict):
            d = _wh(v)
            if d:
                return d
    d = _wh(res)
    if d:
        return d
    return _wh(res.get("window_bounds"))


def _wh(d) -> tuple | None:
    if not isinstance(d, dict):
        return None
    for kw, kh in (("width", "height"), ("w", "h")):
        w, h = _int(d.get(kw)), _int(d.get(kh))
        if w and h and w > 0 and h > 0:
            return w, h
    return None


def _win_frame(w: dict) -> tuple | None:
    """(x,y,w,h) out of a list_windows entry's frame/bounds dict."""
    f = w.get("frame") or w.get("bounds") or {}
    if not isinstance(f, dict):
        return None
    x, y = _int(f.get("x")), _int(f.get("y"))
    wd = _int(f.get("w")) or _int(f.get("width"))
    ht = _int(f.get("h")) or _int(f.get("height"))
    if x is None or y is None or not wd or not ht:
        return None
    return x, y, wd, ht


def _win_dims(w: dict) -> tuple | None:
    f = _win_frame(w)
    return (f[2], f[3]) if f else None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
