"""Turn-scoped action recording via cua-driver (U1).

`Recorder` wraps one act-loop run: it mints the stable `wisp` session
label (`start_session` is idempotent — an idle-expired label is simply
re-minted) and starts a session-filtered `start_recording` into
`~/.local/share/wisp/rec/<turn-id>/` (mode 0700). The driver writes one
`turn-NNNNN/` per dispatched action tool — `action.json` carrying the
tool, args, `action_truth` and monotonic/epoch stamps — read-only calls
are never recorded. Because *every* dispatched tool earns a dir
(`move_cursor` included), a step is attributed to its dir by matching
tool + args + timestamp, never by "newest dir" (an interleaved move
would steal the next click's attribution).

The session label idle-expires at ~300 s (docs/research/
cua-sessions-cursor.md). Each cua call refreshes the TTL, so the label
only risks lapsing when a run goes 5 min without dispatching (a parked
confirm card, a slow model reply) — `ensure()` re-mints it before a
dispatch once it's older than RENEW_AFTER_S, and re-arms the recording
in case the dead session took it down.

A driver outage degrades to `record_unavailable` trace events — the
turn proceeds unrecorded; nothing here raises into the act loop.
"""
import json
import os
import pathlib
import re
import shutil
import time

from . import cancel as _cancel
from . import config, cua
from . import trace as _trace

SESSION = cua.SESSION
REC_DIR = config.DATA_DIR / "rec"

CTRL_TIMEOUT_S = 5.0      # start/stop/status round-trips
SESSION_TTL_S = 300.0     # documented idle expiry
RENEW_AFTER_S = 240.0     # re-mint with this much idle time elapsed
MATCH_WAIT_S = 1.5        # the turn dir can lag the dispatch reply
MATCH_POLL_S = 0.05
_TS_SKEW_S = 2.0          # tolerate a couple seconds of clock skew
_TURN_RE = re.compile(r"^turn-\d{5}$")
# epoch-second keys the driver is known to write in action.json
_TS_KEYS = ("ts", "epoch")
_MS_KEYS = ("ms", "mono_ms", "mono")   # driver-side monotonic millis


def _client(client=None, timeout_s: float = CTRL_TIMEOUT_S) -> cua.Cua:
    if client is not None:
        return client
    from .pipeline import hypr_env
    return cua.Cua(timeout_s=timeout_s, env=hypr_env())


def mint(client=None) -> dict:
    """`start_session{session:"wisp"}` — idempotent; revives an
    expired/ended label. The label is daemon-global, so one-shot
    `cua-driver call` transports all share it."""
    return _client(client).call("start_session", {"session": SESSION},
                                strict=False, timeout=CTRL_TIMEOUT_S)


def status(client=None) -> dict:
    """`get_recording_state{session:"wisp"}` — {recording: bool, ...}."""
    return _client(client).call("get_recording_state",
                                {"session": SESSION},
                                timeout=CTRL_TIMEOUT_S)


def begin(turn: str, client=None) -> "Recorder":
    """Create + start the run's Recorder. Always returns — on failure
    the recorder is inert (`active` False) and the run goes unrecorded."""
    rec = Recorder(turn, client=client)
    rec.start()
    return rec


def _action_ts(action: dict) -> float | None:
    """Epoch seconds for the recorded action, from whichever stamp the
    driver wrote (seconds or milliseconds)."""
    for k in _TS_KEYS:
        v = action.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v / 1000.0 if v > 1e11 else float(v)
    return None


def _action_ms(action: dict) -> float | None:
    """Driver-side monotonic milliseconds — same host, same monotonic
    clock as `time.monotonic()` in this process, so it is the honest
    this-dispatch watermark _scan compares `since_mono` against."""
    for k in _MS_KEYS:
        v = action.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _read_action(path: pathlib.Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _coord_ok(recorded, want) -> bool:
    """args.x/y filter: only a parseable mismatch disqualifies the dir —
    a driver that doesn't echo coords still matches on tool+ts."""
    if want is None or recorded is None:
        return True
    try:
        return int(recorded) == int(want)
    except (TypeError, ValueError):
        return True


class Recorder:
    """One act run's recording lifecycle: start → per-dispatch keepalive
    (`ensure`) + attribution (`match_turn`) → `stop` on any exit."""

    def __init__(self, turn: str, client=None, output_dir=None):
        self.turn = turn
        self._client = client      # None -> built lazily, inside a try
        self.dir = pathlib.Path(output_dir) if output_dir \
            else pathlib.Path(REC_DIR) / turn
        self.session = SESSION
        self.started = False
        self._dead = False
        self._touched = 0.0
        self._claimed: set = set()

    @property
    def client(self) -> cua.Cua:
        if self._client is None:
            self._client = _client()
        return self._client

    # -- lifecycle -----------------------------------------------------
    @property
    def active(self) -> bool:
        return self.started and not self._dead

    def start(self) -> bool:
        try:
            root = pathlib.Path(REC_DIR)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(root, 0o700)
            self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.dir, 0o700)
        except OSError as e:
            self._unavailable("mkdir", e)
            return False
        try:
            self._mint()
            self.client.call(
                "start_recording",
                {"session": self.session, "output_dir": str(self.dir)},
                strict=False, timeout=CTRL_TIMEOUT_S)
        # Exception, not CuaError: a cancelled turn raises Cancelled out
        # of cancel.run — recording is never worth breaking the run for
        except Exception as e:
            self._unavailable("start", e)
            return False
        self.started = True
        self._emit("record", {"state": "start", "dir": str(self.dir)})
        return True

    def _mint(self) -> dict:
        r = self.client.call("start_session",
                             {"session": self.session},
                             strict=False, timeout=CTRL_TIMEOUT_S)
        self._touched = time.monotonic()
        return r

    def touch(self) -> None:
        """A session-labeled dispatch just went out — it slides the
        driver-side idle TTL, so the local keepalive stamp follows."""
        self._touched = time.monotonic()

    def ensure(self) -> None:
        """Re-mint the session label before a dispatch when it's about
        to idle-expire; the mint revives an ended/expired label, and the
        re-issued start_recording re-arms a recording the dead session
        took down (the re-issue is harmless when one is already live —
        REFUSED just means keep going). Never raises. The mint gets one
        bounded retry (F19): a transient transport hiccup must not mark
        the recorder dead for the rest of the turn; a real outage still
        does."""
        if not self.active:
            return
        if time.monotonic() - self._touched < RENEW_AFTER_S:
            return
        err = None
        for attempt in range(2):            # mint + one bounded retry
            try:
                self._mint()
                err = None
                break
            except _cancel.Cancelled:
                raise                       # user interrupt: never retry
            except Exception as e:
                err = e
                if attempt == 0:
                    time.sleep(0.2)
        if err is not None:
            self._dead = True
            self._unavailable("keepalive", err)
            return
        try:
            self.client.call(
                "start_recording",
                {"session": self.session, "output_dir": str(self.dir)},
                strict=False, timeout=CTRL_TIMEOUT_S)
        except Exception:
            pass   # already recording / re-arm is best-effort

    def stop(self) -> None:
        """stop_recording on run end — all exits (normal, interrupt,
        error) land here from the act loop's finally. Runs UNBOUND from
        the turn's cancel token — teardown must still reach the daemon
        when the turn was cancelled. Never raises."""
        if not self.started:
            return
        self.started = False
        try:
            with _cancel.bind(None):
                self.client.call("stop_recording",
                                 {"session": self.session},
                                 strict=False, timeout=CTRL_TIMEOUT_S)
        except Exception as e:
            self._unavailable("stop", e)
        self._emit("record", {"state": "stop", "dir": str(self.dir)})

    # -- attribution ---------------------------------------------------
    def match_turn(self, cua_tool: str, x=None, y=None,
                   since: float = 0.0, wait_s: float = MATCH_WAIT_S,
                   poll_s: float = MATCH_POLL_S, since_mono=None):
        """(dir, action.json dict) for the action this step dispatched.

        The dir can lag the dispatch reply, so poll briefly. A dir
        matches on tool name + x/y (when both sides carry them) + an
        epoch ts no older than `since`; each dir is claimed at most
        once so a repeated identical call can't re-attribute it.
        `since_mono` (dispatch-time time.monotonic()) is the F11
        watermark: a dir whose driver-side monotonic `ms` predates
        this dispatch was written for an EARLIER action — tool+coords
        matching must never attribute it to this one (e.g. a dir that
        landed too late for its own step's bounded wait).
        """
        if not self.active:
            return None
        deadline = time.monotonic() + wait_s
        while True:
            hit = self._scan(cua_tool, x, y, since, since_mono)
            if hit is not None:
                self._claimed.add(str(hit[0]))
                return hit
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_s)

    def _scan(self, cua_tool, x, y, since, since_mono=None):
        try:
            dirs = sorted(d for d in self.dir.iterdir()
                          if d.is_dir() and _TURN_RE.match(d.name))
        except OSError:
            return None
        for d in dirs:
            if str(d) in self._claimed:
                continue
            a = _read_action(d / "action.json")
            if a is None or a.get("tool") != cua_tool:
                continue
            args = a.get("args") or {}
            if not _coord_ok(args.get("x"), x) \
                    or not _coord_ok(args.get("y"), y):
                continue
            ts = _action_ts(a)
            if ts is not None and ts < since - _TS_SKEW_S:
                continue
            if since_mono is not None:
                ms = _action_ms(a)
                if ms is not None \
                        and ms < since_mono * 1000.0 - _TS_SKEW_S * 1000.0:
                    continue    # F11: written for an earlier dispatch
            return d, a
        return None

    # -- trace ---------------------------------------------------------
    def _emit(self, step: str, data: dict) -> None:
        try:
            _trace.emit(self.turn, step, "rec", data)
        except Exception:
            pass

    def _unavailable(self, why: str, e) -> None:
        self._emit("record_unavailable",
                   {"why": why, "detail": str(e)[:200]})


def sweep_orphans(root=None) -> list:
    """Discard every `rec/<turn>/` left by a dead run at daemon start —
    an orphan never reached pack-write, so it is never promoted.
    Returns the dropped entry names; emits a trace event per drop."""
    root = pathlib.Path(root if root is not None else REC_DIR)
    dropped = []
    try:
        kids = sorted(root.iterdir())
    except OSError:
        return dropped
    for p in kids:
        # orphan DIRECTORIES only — a stray file here isn't a turn
        # record and may be a future pack marker; leave it alone
        if not p.is_dir() or p.is_symlink():
            continue
        try:
            shutil.rmtree(p)
        except OSError:
            continue
        dropped.append(p.name)
        try:
            _trace.emit("sys", "record", "rec",
                        {"state": "orphan_discarded", "dir": p.name})
        except Exception:
            pass
    return dropped


def probe(cfg: dict | None = None) -> dict:
    """`wispd doctor` capability row: can this box record cua turns?
    -> {ok, skipped, detail}. An absent driver reports `skipped`
    (nothing to record), not a failure."""
    from . import probes_cua
    try:
        st = probes_cua.CuaProbe(cfg).check(version=False)
    except Exception as e:
        return {"ok": False, "skipped": False, "detail": f"probe: {e}"}
    state = st.get("state") or "absent"
    if state == "absent":
        return {"ok": False, "skipped": True,
                "detail": "cua-driver not installed — nothing to record"}
    if state != "running":
        return {"ok": False, "skipped": False,
                "detail": f"cua daemon {state} — recording unavailable"}
    try:
        mint()
        rs = status()
    except cua.CuaError as e:
        return {"ok": False, "skipped": False,
                "detail": f"{e.cua_code}: {e}"}
    return {"ok": True, "skipped": False,
            "detail": "recording" if rs.get("recording") else "idle"}
