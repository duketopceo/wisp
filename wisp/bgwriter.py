"""Background writer: trajectory and recall writes off the turn's hot path.

A turn must never wait on a disk or sqlite write that only feeds later
turns. Callers hand a callable to `submit`, which only appends to a
bounded in-memory queue under a lock held for microseconds and returns;
one daemon thread runs the callables in order.

Overflow policy: when the queue is full the OLDEST job is dropped and
`dropped` goes up by one, so a stuck disk can cost history but never a
turn and never unbounded memory. A job that raises is counted in
`failed` and otherwise ignored (the writes it carries were already
best-effort). The queue is flushed on shutdown: wispd calls `stop()`
from its finally block and `atexit` covers every other exit.

Tuning: [agents] writer_queue_max (default 256), applied by
`configure(cfg)`.
"""
import atexit
import collections
import threading

DEFAULT_MAX = 256

_cv = threading.Condition()
_q: "collections.deque" = collections.deque()
_max = DEFAULT_MAX
_thread = None
_busy = False
_closing = False
_stats = {"submitted": 0, "written": 0, "dropped": 0, "failed": 0}


def configure(cfg: dict | None) -> None:
    """Apply [agents] writer_queue_max. A bad value keeps the default."""
    global _max
    raw = ((cfg or {}).get("agents") or {}).get("writer_queue_max")
    try:
        n = int(raw) if raw not in (None, "") else DEFAULT_MAX
    except (TypeError, ValueError):
        n = DEFAULT_MAX
    with _cv:
        _max = max(1, min(n, 100000))


def submit(fn, *args, **kwargs) -> None:
    """Queue `fn(*args, **kwargs)` for the writer thread. Never blocks on
    I/O and never raises; drops the oldest queued job when full."""
    global _thread
    try:
        with _cv:
            if _closing:
                run_inline = True
            else:
                run_inline = False
                while len(_q) >= _max:
                    _q.popleft()
                    _stats["dropped"] += 1
                _q.append((fn, args, kwargs))
                _stats["submitted"] += 1
                if _thread is None or not _thread.is_alive():
                    _thread = threading.Thread(
                        target=_run, name="wisp-bgwriter", daemon=True)
                    _thread.start()
                _cv.notify_all()
        if run_inline:        # shutting down: write now, nothing queued
            _call(fn, args, kwargs)
    except Exception:         # noqa: BLE001 — a write must not hurt a turn
        pass


def _call(fn, args, kwargs) -> None:
    try:
        fn(*args, **kwargs)
        with _cv:
            _stats["written"] += 1
    except Exception:         # noqa: BLE001
        with _cv:
            _stats["failed"] += 1


def _run() -> None:
    global _busy
    while True:
        with _cv:
            while not _q:
                if _closing:
                    _cv.notify_all()
                    return
                _cv.wait()
            fn, args, kwargs = _q.popleft()
            _busy = True
        _call(fn, args, kwargs)
        with _cv:
            _busy = False
            _cv.notify_all()


def flush(timeout: float = 5.0) -> bool:
    """Wait until everything queued so far is written. True when the
    queue drained inside `timeout` seconds."""
    import time
    end = time.monotonic() + timeout
    with _cv:
        while _q or _busy:
            left = end - time.monotonic()
            if left <= 0:
                return False
            _cv.wait(left)
    return True


def stop(timeout: float = 5.0) -> bool:
    """Flush, then let the thread exit. Later submits run inline."""
    global _closing
    ok = flush(timeout)
    with _cv:
        _closing = True
        _cv.notify_all()
    return ok


def reopen() -> None:
    """Undo stop() (tests, and a daemon that restarts in-process)."""
    global _closing
    with _cv:
        _closing = False


def stats() -> dict:
    with _cv:
        return dict(_stats, queued=len(_q), max=_max)


atexit.register(stop, 2.0)
