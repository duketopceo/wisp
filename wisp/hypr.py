"""Hyprland over its own sockets: one module, no hyprctl forks.

Queries are `j/<name>` on the request socket, commands are Lua sent as
`eval <lua>` on the same socket (this build's Hyprland is Lua-configured;
the legacy `dispatch` syntax does not exist). Events stream from
.socket2.sock. Every request has a 300 ms deadline.

Lua generation rule: a value is only ever placed into generated code
through `lua_str()` (a quoted, single-line literal) or `int()`; builders
take typed arguments, never Lua fragments. Window classes, app names and
command lines come from a model and are hostile input.

Bind registry: binds are created into the Lua global table
`_G.wisp_binds` (handle -> chord) so they can be removed by handle, on
exit, and after a daemon crash (`clear_stale`). Only chords Wisp itself
registered are ever unbound. Every chord needs a modifier and must not
clash with an existing bind.
"""
from __future__ import annotations

import atexit
import dataclasses
import json
import os
import pathlib
import re
import shlex
import socket
import threading
import time
import uuid

TIMEOUT_S = 0.3
RETRY_S = 30.0          # re-probe cadence while Hyprland is marked down
HANDLE_PREFIX = "wisp:"

MODS = {"SUPER": 64, "MOD4": 64, "WIN": 64, "LOGO": 64,
        "SHIFT": 1, "CTRL": 4, "CONTROL": 4, "ALT": 8, "MOD1": 8}
_ORDER = (("SUPER", 64), ("CTRL", 4), ("ALT", 8), ("SHIFT", 1))
_KEY_RE = re.compile(r"[A-Za-z0-9_]+")


class HyprError(Exception):
    """code: unavailable | timeout | protocol | eval_failed | bind_clash"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ── transport ───────────────────────────────────────────────────────

def _sock_dir() -> pathlib.Path | None:
    rd = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    root = pathlib.Path(rd) / "hypr"
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and (root / sig / ".socket.sock").exists():
        return root / sig
    try:  # signature missing or stale (compositor restarted): newest wins
        live = [d for d in root.iterdir() if (d / ".socket.sock").exists()]
    except OSError:
        return None
    return max(live, key=lambda d: d.stat().st_mtime) if live else None


def _path(name: str) -> str:
    d = _sock_dir()
    if d is None:
        raise HyprError("unavailable", "no Hyprland instance socket")
    return str(d / name)


def request(msg: str, timeout: float = TIMEOUT_S) -> str:
    """One request, one reply (Hyprland closes after replying)."""
    deadline = time.monotonic() + timeout
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(_path(".socket.sock"))
        s.sendall(msg.encode("utf-8", "replace"))
        chunks = []
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise HyprError("timeout", msg[:40])
            s.settimeout(left)
            data = s.recv(65536)
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks).decode("utf-8", "replace")
    except socket.timeout:
        raise HyprError("timeout", msg[:40]) from None
    except OSError as e:
        raise HyprError("unavailable", str(e)) from None
    finally:
        s.close()


def query(name: str, timeout: float = TIMEOUT_S):
    """`j/<name>` parsed as JSON (activewindow, clients, monitors, binds)."""
    if not re.fullmatch(r"[a-z]+", name or ""):
        raise ValueError(f"bad query name {name!r}")
    reply = request("j/" + name, timeout)
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        raise HyprError("protocol", reply[:80]) from None


def eval_lua(lua: str, timeout: float = TIMEOUT_S) -> str:
    """Run Lua in the compositor. Returns the reply ('ok', or a
    'warning: ...' such as an unmatched window); raises on 'error: ...'."""
    if "\n" in lua or "\r" in lua:
        raise ValueError("eval takes a single line")
    reply = request("eval " + lua, timeout).strip()
    if reply.startswith("error"):
        raise HyprError("eval_failed", reply[:200])
    return reply


class LuaCmd(str):
    """Marks a command string as Lua for `platform._try` (vs an argv)."""


def run_lua(lua: str) -> bool:
    """True only on a clean 'ok'; never raises."""
    try:
        return eval_lua(lua) == "ok"
    except HyprError:
        return False


# ── availability / health ───────────────────────────────────────────

_state = {"ok": None, "at": 0.0}
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _state.update(ok=None, at=0.0)


def probe() -> bool:
    """Confirm both query and eval work; remembered for health()."""
    try:
        query("monitors")
        ok = eval_lua("return 1") == "ok"
    except HyprError:
        ok = False
    with _lock:
        _state.update(ok=ok, at=time.monotonic())
    return ok


def available() -> bool:
    with _lock:
        ok, at = _state["ok"], _state["at"]
    if ok is None or (not ok and time.monotonic() - at > RETRY_S):
        return probe()
    return bool(ok)


def health() -> dict:
    """Entry for the daemon's `health` object."""
    with _lock:
        ok = _state["ok"]
    return {"ok": bool(ok), "code": None if ok else "hypr_unavailable"}


# ── Lua generation ──────────────────────────────────────────────────

def lua_str(value) -> str:
    """Double-quoted single-line Lua literal. Escapes backslash, quote,
    and every control character (decimal escapes are always 3 digits so
    a following digit cannot extend them)."""
    out = ['"']
    for ch in str(value):
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif o < 32 or o == 127:
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _int(v, minimum=None) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise TypeError(f"expected an integer, got {v!r}")
    n = int(v)  # ValueError on junk strings
    if minimum is not None and n < minimum:
        raise ValueError(f"{n} < {minimum}")
    return n


def _cmd(cmd) -> str:
    return shlex.join([str(a) for a in cmd]) \
        if isinstance(cmd, (list, tuple)) else str(cmd)


def focus_class(cls: str) -> str:
    return f"hl.dispatch(hl.dsp.focus({{window = {lua_str('class:^' + cls)}}}))"


def close_window(cls: str = "") -> str:
    if not cls:
        return "hl.dispatch(hl.dsp.window.close())"
    return ("hl.dispatch(hl.dsp.window.close({window = "
            f"{lua_str('class:^' + cls)}}}))")


def focus_workspace(n) -> str:
    return f"hl.dispatch(hl.dsp.focus({{workspace = {_int(n, 1)}}}))"


def exec_cmd(cmd) -> str:
    """cmd: a command line, or an argv list (shell-quoted into one)."""
    return f"hl.dispatch(hl.dsp.exec_cmd({lua_str(_cmd(cmd))}))"


def cursor_move(x, y) -> str:
    return f"hl.dispatch(hl.dsp.cursor.move({{x = {_int(x)}, y = {_int(y)}}}))"


# ── bind registry ───────────────────────────────────────────────────

def parse_chord(chord: str) -> tuple[int, str, str]:
    """-> (modmask, KEY, canonical 'SUPER + SHIFT + X'). Raises
    ValueError for no modifier, no key, or anything that is not a plain
    modifier/key token."""
    toks = [t.strip(" ") for t in str(chord or "").split("+")]
    toks = [t for t in toks if t != ""]
    if not toks:
        raise ValueError("chord needs a modifier")
    for t in toks:
        if not _KEY_RE.fullmatch(t):
            raise ValueError(f"bad chord token {t!r}")
    *mods, key = toks
    if key.upper() in MODS:
        raise ValueError("chord has no key")
    if not mods:
        raise ValueError("chord needs a modifier")
    mask = 0
    for m in mods:
        if m.upper() not in MODS:
            raise ValueError(f"unknown modifier {m!r}")
        mask |= MODS[m.upper()]
    canon = [n for n, bit in _ORDER if mask & bit] + [key.upper()]
    return mask, key.upper(), " + ".join(canon)


def bind_lua(handle: str, chord: str, action) -> str:
    c, h = lua_str(chord), lua_str(handle)
    return ("_G.wisp_binds = _G.wisp_binds or {}; "
            f"hl.bind({c}, hl.dsp.exec_cmd({lua_str(_cmd(action))}), "
            f"{{description = {h}}}); _G.wisp_binds[{h}] = {c}")


def unbind_lua(handle: str) -> str:
    h = lua_str(handle)
    return (f"local c = _G.wisp_binds and _G.wisp_binds[{h}]; "
            f"if c then hl.unbind(c); _G.wisp_binds[{h}] = nil end")


def clear_stale_lua() -> str:
    return ("local t = _G.wisp_binds or {}; "
            "for h, c in pairs(t) do "
            f"if string.sub(h, 1, {len(HANDLE_PREFIX)}) == "
            f"{lua_str(HANDLE_PREFIX)} then hl.unbind(c); t[h] = nil end end")


_binds: dict[str, str] = {}
_exit_hooked = False


def active_binds() -> dict:
    return dict(_binds)


def reset_binds() -> None:
    global _exit_hooked
    _binds.clear()
    _submaps.clear()
    _entered.clear()
    _exit_hooked = False


def _clashes(mask: int, key: str) -> bool:
    for b in query("binds"):
        if (b.get("submap") or "") != "":
            continue  # a submap bind cannot fire in the global map
        if b.get("modmask") == mask and str(b.get("key", "")).upper() == key:
            return True
    return False


def bind(chord: str, action) -> str:
    """Register a transient bind running `action` (command line or argv).
    Returns the handle. Raises ValueError for a bad chord and
    HyprError('bind_clash') when the chord is already bound."""
    global _exit_hooked
    mask, key, canon = parse_chord(chord)
    if _clashes(mask, key):
        raise HyprError("bind_clash", canon)
    handle = HANDLE_PREFIX + uuid.uuid4().hex[:8]
    eval_lua(bind_lua(handle, canon, action))
    _binds[handle] = canon
    if not _exit_hooked:
        _exit_hooked = True
        atexit.register(shutdown)
    return handle


def unbind(handle: str) -> None:
    if handle not in _binds:
        return
    try:
        eval_lua(unbind_lua(handle))
    finally:
        _binds.pop(handle, None)


def clear_stale() -> None:
    """Remove every Wisp-prefixed bind (left by a crashed daemon)."""
    eval_lua(clear_stale_lua())


def shutdown() -> None:
    """Remove this process's binds. Never raises; gives up at the first
    dead-compositor error rather than waiting per bind."""
    try:
        leave_submap()
    except HyprError as e:
        if e.code in ("timeout", "unavailable"):
            _binds.clear()
            _submaps.clear()
            return
    for handle in list(_binds):
        try:
            unbind(handle)
        except HyprError as e:
            if e.code in ("timeout", "unavailable"):
                break
    _binds.clear()
    _submaps.clear()


# ── submaps (W24) ───────────────────────────────────────────────────
#
# A submap holds modifier-free keys (Esc, Enter, 1..9) that only exist
# while the compositor is IN the submap, so they never shadow a global
# bind or an app's typing outside it. The registry defines one under a
# Wisp-owned name, enters it, and always leaves it again (explicitly, on
# shutdown, and from the Esc bind itself). Every bind carries a
# `wisp:`-prefixed description, which is how our own leftovers are told
# apart from someone else's binds in the same submap.

@dataclasses.dataclass(frozen=True)
class SubmapBind:
    key: str                    # bare key name, e.g. "escape", "1"
    argv: list                  # command run on press
    then_reset: bool = False    # also leave the submap on press


_submaps: dict[str, str] = {}   # handle -> submap name
_entered: list = []             # [name] while inside a Wisp submap


def _submap_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", str(name or "")):
        raise ValueError(f"bad submap name {name!r}")
    return name


def _submap_key(key: str) -> str:
    if not _KEY_RE.fullmatch(str(key or "")) or key.upper() in MODS:
        raise ValueError(f"bad submap key {key!r}")
    return key


def define_submap_lua(name: str, binds) -> str:
    name = _submap_name(name)
    parts = []
    for b in binds:
        key = _submap_key(b.key)
        body = f"hl.dispatch(hl.dsp.exec_cmd({lua_str(_cmd(b.argv))}))"
        if b.then_reset:
            body += '; hl.dispatch(hl.dsp.submap("reset"))'
        desc = lua_str(f"{HANDLE_PREFIX}sub:{name}:{key}")
        parts.append(f"hl.bind({lua_str(key)}, function() {body} end, "
                     f"{{description = {desc}}})")
    return (f"hl.define_submap({lua_str(name)}, function() "
            + "; ".join(parts) + " end)")


def enter_submap_lua(name: str) -> str:
    return f"hl.dispatch(hl.dsp.submap({lua_str(_submap_name(name))}))"


def leave_submap_lua() -> str:
    return 'hl.dispatch(hl.dsp.submap("reset"))'


def submap_conflicts(name: str) -> list:
    """Binds already in submap `name` that Wisp did not create."""
    name = _submap_name(name)
    return [b for b in query("binds")
            if (b.get("submap") or "") == name
            and not str(b.get("description") or "").startswith(HANDLE_PREFIX)]


def define_submap(name: str, binds, check: bool = True) -> str:
    """Define a submap of Wisp binds. Raises HyprError('bind_clash') when
    the name is already used by binds that are not ours (reported, never
    clobbered). Returns a handle."""
    global _exit_hooked
    binds = list(binds)
    lua = define_submap_lua(name, binds)
    if check:
        clash = submap_conflicts(name)
        if clash:
            raise HyprError("bind_clash", ", ".join(
                str(b.get("key", "?")) for b in clash))
    eval_lua(lua)
    handle = f"{HANDLE_PREFIX}sub-{name}"
    _submaps[handle] = name
    if not _exit_hooked:
        _exit_hooked = True
        atexit.register(shutdown)
    return handle


def enter_submap(handle: str) -> None:
    name = _submaps.get(handle)
    if name is None:
        raise ValueError(f"unknown submap handle {handle!r}")
    eval_lua(enter_submap_lua(name))
    _entered[:] = [name]


def leave_submap(force: bool = False) -> None:
    """Back to the global map. A no-op unless we are inside a Wisp
    submap, or `force` (daemon start: clear what a crash left)."""
    if not (_entered or force):
        return
    try:
        eval_lua(leave_submap_lua())
    finally:
        _entered.clear()


def active_submaps() -> dict:
    return dict(_submaps)


# ── events ──────────────────────────────────────────────────────────

def parse_event(line: str):
    """'name>>data' -> (name, data); data may itself contain '>>'."""
    name, sep, data = line.partition(">>")
    if not sep or not name:
        return None
    return name, data


def events(stop: threading.Event | None = None, poll: float = 0.5):
    """Yield (name, data) from .socket2.sock until it closes or `stop`
    is set. Lines may arrive split across or batched within reads."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            s.settimeout(TIMEOUT_S)
            s.connect(_path(".socket2.sock"))
        except OSError as e:
            raise HyprError("unavailable", str(e)) from None
        s.settimeout(poll)
        buf = b""
        while not (stop and stop.is_set()):
            try:
                data = s.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            buf += data
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                ev = parse_event(raw.decode("utf-8", "replace"))
                if ev:
                    yield ev
                if stop and stop.is_set():
                    return
    finally:
        s.close()
