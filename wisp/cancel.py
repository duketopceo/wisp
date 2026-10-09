"""Cancellable turns and prompt ids (backend U9).

A `CancelToken` is created per turn. Everything a turn starts that can
block registers with it:

- subprocesses (whisper-cli, tool shells, the TTS child) by pid — cancel
  SIGTERMs the process group, then SIGKILLs a straggler;
- HTTP calls by socket — cancel shuts the connection down so a blocked
  read returns at once and the late reply is never read;
- loops (act steps, the brain stream reader) poll `token.cancelled`.

`bind(token)` makes it the *current* token so deep helpers (`run`,
`urlopen`) need no extra parameter; a turn runs one at a time. With no
current token both helpers are exactly `subprocess.run` /
`urllib.request.urlopen`.

`PromptBroker` is the single-slot pending-prompt registry behind the
`choice` command: every offered prompt has an id, a pick for another id
is `stale_prompt`, a pick that was not offered is `not_offered`, and a
1-based `index` selects the nth offered option.
"""
import contextlib
import http.client
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
import urllib.request

from . import errors_codes

_ORIG_URLOPEN = urllib.request.urlopen
_CURRENT = None


class Cancelled(errors_codes.WispError):
    """The user stopped the turn. Never retried, never falls back."""

    def __init__(self, detail: str = "turn cancelled"):
        super().__init__("cancelled", detail)


def _signal_proc(proc, sig) -> None:
    try:
        # a child we started in its own session leads its group: take
        # the whole tree (sh -c "a | b") with it
        if os.getpgid(proc.pid) == proc.pid != os.getpgrp():
            os.killpg(proc.pid, sig)
        else:
            proc.send_signal(sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _kill(proc) -> None:
    """SIGTERM now; SIGKILL and reap in the background if it lingers."""
    _signal_proc(proc, signal.SIGTERM)

    def reap():
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            _signal_proc(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass
    threading.Thread(target=reap, daemon=True).start()


def _hard_close(sock) -> None:
    for fn in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
        try:
            fn()
        except OSError:
            pass


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()
        self._lock = threading.Lock()
        self._pids: list = []
        self._closers: dict = {}
        self._next = 0

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def is_set(self) -> bool:  # Event-compatible, for `interrupted=`
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled (True) or the timeout passes (False)."""
        return self._ev.wait(timeout)

    def register_pid(self, proc) -> None:
        with self._lock:
            if not self._ev.is_set():
                self._pids.append(proc)
                return
        _kill(proc)

    def unregister_pid(self, proc) -> None:
        with self._lock:
            if proc in self._pids:
                self._pids.remove(proc)

    def register_close(self, fn) -> int:
        with self._lock:
            if not self._ev.is_set():
                self._next += 1
                self._closers[self._next] = fn
                return self._next
        _safe(fn)
        return 0

    def unregister_close(self, handle: int) -> None:
        with self._lock:
            self._closers.pop(handle, None)

    def cancel(self) -> None:
        with self._lock:
            if self._ev.is_set():
                return
            self._ev.set()
            pids, self._pids = self._pids, []
            closers, self._closers = list(self._closers.values()), {}
        for proc in pids:
            _kill(proc)
        for fn in closers:
            _safe(fn)


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        pass


def current():
    return _CURRENT


def is_cancelled() -> bool:
    return _CURRENT is not None and _CURRENT.cancelled


def check() -> None:
    if _CURRENT is not None:
        _CURRENT.check()


@contextlib.contextmanager
def bind(token):
    global _CURRENT
    prev, _CURRENT = _CURRENT, token
    try:
        yield token
    finally:
        _CURRENT = prev


# -- subprocesses --------------------------------------------------------

def run(argv, *, input=None, capture_output=False, timeout=None,
        check=False, **kw):
    """`subprocess.run` that the current turn can kill. Raises
    `Cancelled` if the turn was cancelled while the child ran."""
    tok = _CURRENT
    if tok is None:
        return subprocess.run(argv, input=input,
                              capture_output=capture_output,
                              timeout=timeout, check=check, **kw)
    tok.check()
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    kw.setdefault("start_new_session", True)
    proc = subprocess.Popen(argv, **kw)
    tok.register_pid(proc)
    try:
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            _signal_proc(proc, signal.SIGKILL)
            proc.communicate()
            raise subprocess.TimeoutExpired(argv, timeout, e.output,
                                            e.stderr) from None
    finally:
        tok.unregister_pid(proc)
    if tok.cancelled:
        raise Cancelled()
    cp = subprocess.CompletedProcess(argv, proc.returncode, out, err)
    if check:
        cp.check_returncode()
    return cp


# -- HTTP ----------------------------------------------------------------

class _Tracked(http.client.HTTPConnection):
    token = None

    def connect(self):
        super().connect()
        sock = self.sock
        self.token.register_close(lambda: _hard_close(sock))


class _TrackedS(http.client.HTTPSConnection):
    token = None

    def connect(self):
        super().connect()
        sock = self.sock
        self.token.register_close(lambda: _hard_close(sock))


def _tracked(base, tok):
    return type("Tracked" + base.__name__, (base,), {"token": tok})


class _HTTP(urllib.request.HTTPHandler):
    def __init__(self, tok):
        super().__init__()
        self._cls = _tracked(_Tracked, tok)

    def http_open(self, req):
        return self.do_open(self._cls, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def __init__(self, tok):
        super().__init__()
        self._cls = _tracked(_TrackedS, tok)

    def https_open(self, req):
        return self.do_open(self._cls, req, context=self._context)


def urlopen(req, *a, **kw):
    """`urllib.request.urlopen` whose connection the current turn can
    close. Cancel shuts the socket down (a blocked read returns at once,
    a late reply is never read) and the call raises `Cancelled`."""
    tok = _CURRENT
    if tok is None or urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, *a, **kw)
    tok.check()
    opener = urllib.request.build_opener(_HTTP(tok), _HTTPS(tok))
    try:
        return opener.open(req, *a, **kw)
    except Exception as e:
        if tok.cancelled:
            raise Cancelled() from e
        raise


# -- prompts -------------------------------------------------------------

def new_prompt_id() -> str:
    return "p" + secrets.token_hex(4)


_UNSET = object()


class PromptBroker:
    """One pending prompt at a time (a turn offers one, waits, moves on).
    The turn calls `waiter(token)(timeout, prompt_id=, options=)`; the
    daemon's `choice` handler calls `offer(...)` from another thread."""

    def __init__(self, clock=time.monotonic):
        # `clock` is injectable so tests drive the deadline without sleeping
        self._clock = clock
        self._cv = threading.Condition()
        self._pending = None
        self._pick = _UNSET

    @property
    def pending_id(self) -> str:
        with self._cv:
            return self._pending["id"] if self._pending else ""

    def pending(self) -> dict | None:
        """The live prompt {"id", "options"} or None — a voice-answer
        path needs the offered options to map an utterance onto."""
        with self._cv:
            if self._pending is None:
                return None
            return {"id": self._pending["id"],
                    "options": list(self._pending["options"] or [])}

    def waiter(self, token=None):
        def wait(timeout, prompt_id=None, options=None):
            pid = prompt_id or new_prompt_id()
            with self._cv:
                self._pending = {"id": pid,
                                 "options": None if options is None
                                 else list(options)}
                self._pick = _UNSET
                end = self._clock() + timeout
                try:
                    while self._pick is _UNSET:
                        if token is not None and token.cancelled:
                            return None
                        left = end - self._clock()
                        if left <= 0:
                            return None
                        self._cv.wait(min(left, 0.02))
                    return self._pick or None
                finally:
                    self._pending = None
        return wait

    def offer(self, pick=None, prompt_id=None, index=None) -> dict:
        def no(code):
            return {"ok": False, "error": code}
        with self._cv:
            p = self._pending
            if p is None:
                return no("stale_prompt")
            if prompt_id and prompt_id != p["id"]:
                return no("stale_prompt")
            opts = p["options"]
            if index is not None:
                if opts is None or not 1 <= index <= len(opts):
                    return no("bad_index")
                pick = opts[index - 1]
            elif not pick:
                pick = ""           # dismiss: same as no answer
            elif opts is not None and pick not in opts:
                return no("not_offered")
            self._pick = pick
            self._cv.notify_all()
            return {"ok": True}
