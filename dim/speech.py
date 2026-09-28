"""Spoken replies (TTS) with barge-in.

speak() spawns the TTS command and tracks its pid; a new listen (or
stop) calls stop() to kill in-flight speech fast — SIGTERM, no drain.
[voice] cmd overrides the binary: whitespace/shlex-split argv, `{text}`
placeholder replaced by the message (else it's appended as last arg).
"""

import shlex
import shutil
import subprocess
import threading

_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None


def _argv(msg: str, cfg: dict) -> list[str] | None:
    cmd = cfg.get("voice", {}).get("cmd", "")
    if cmd:
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return None
        if not parts:
            return None
        if "{text}" in parts:
            parts = [msg if p == "{text}" else p for p in parts]
        else:
            parts.append(msg)
        return parts
    bin_ = shutil.which("espeak-ng") or shutil.which("espeak")
    return [bin_, msg] if bin_ else None


def speak(msg: str, cfg: dict) -> subprocess.Popen | None:
    """Spawn the TTS command; returns the proc (None if voice off or no
    binary). Caller registers on_exit to observe natural completion."""
    global _PROC
    if not msg or cfg.get("voice", {}).get("enabled", "false") != "true":
        return None
    argv = _argv(msg, cfg)
    if argv is None:
        return None
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return None
    with _LOCK:
        old, _PROC = _PROC, proc
    _kill(old)
    return proc


def on_exit(proc: subprocess.Popen, cb) -> None:
    """Call cb() when proc exits; also clears the tracked pid."""
    def _watch():
        global _PROC
        proc.wait()
        with _LOCK:
            if _PROC is proc:
                _PROC = None
        cb()
    threading.Thread(target=_watch, daemon=True).start()


def _kill(proc: subprocess.Popen | None) -> None:
    """SIGTERM, then reap (unreaped children leak as zombies)."""
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def stop() -> None:
    global _PROC
    with _LOCK:
        proc, _PROC = _PROC, None
    _kill(proc)
