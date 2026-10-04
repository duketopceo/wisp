"""Typed client for the cua-driver daemon (W8).

Transport: the `cua-driver call <tool> '<json>'` CLI, argv only (no
shell, JSON args as one element). The daemon's own unix-socket framing
(`~/.cache/cua-driver/cua-driver.sock`) is an internal session protocol
the CLI documents no contract for, so wisp does not speak it; the CLI is
the supported surface and also honours `--socket`. See docs/LINUX.md.

Errors are `CuaError`, a `WispError` (closed U7 code set) that also
carries the driver-level `cua_code`:

    E_CUA_DOWN      daemon unreachable / binary missing   -> tool_failed
    E_CUA_TIMEOUT   no reply within the call timeout      -> timeout
    E_CUA_REFUSED   the driver returned a tool error      -> tool_failed
    E_CUA_PROTOCOL  success reply that is not JSON        -> tool_failed

A cancelled turn raises `cancel.Cancelled` (never a CuaError) so callers
never treat a user stop as a failure to fall back from.
"""
import json
import os
import re
import shutil
import subprocess

from . import cancel as _cancel
from . import errors_codes

BIN = "cua-driver"
CLICK_TIMEOUT_S = 0.8

DOWN = "E_CUA_DOWN"
TIMEOUT = "E_CUA_TIMEOUT"
REFUSED = "E_CUA_REFUSED"
PROTOCOL = "E_CUA_PROTOCOL"

# driver code -> closed U7 code
U7 = {DOWN: "tool_failed", TIMEOUT: "timeout", REFUSED: "tool_failed",
      PROTOCOL: "tool_failed"}

_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,63}$")
_DOWN_HINTS = ("e_cua_down", "not running", "cannot reach",
               "no such file", "connection refused", "incompatible")


class CuaError(errors_codes.WispError):
    def __init__(self, cua_code: str, detail: str = ""):
        self.cua_code = cua_code
        super().__init__(U7[cua_code], detail or cua_code)


def socket_path() -> str:
    return os.path.expanduser("~/.cache/cua-driver/cua-driver.sock")


def _text(b) -> str:
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    return b or ""


class Cua:
    def __init__(self, binary: str = BIN, timeout_s: float = CLICK_TIMEOUT_S,
                 env: dict | None = None):
        self.binary = binary
        self.timeout_s = float(timeout_s)
        self.env = env

    # -- availability (same contract as platform._cua_live) ------------
    def available(self) -> bool:
        return shutil.which(self.binary) is not None \
            and os.path.exists(socket_path())

    # -- generic call --------------------------------------------------
    def call(self, tool: str, args: dict | None = None, *,
             timeout: float | None = None, strict: bool = True) -> dict:
        """Invoke one driver tool. `strict` demands a JSON-object reply
        on success (E_CUA_PROTOCOL otherwise); non-strict trusts the
        exit code (action tools may print plain text)."""
        if not isinstance(tool, str) or not _TOOL.match(tool):
            raise ValueError(f"bad cua tool name {tool!r}")
        argv = [self.binary, "call", tool, json.dumps(args or {})]
        try:
            r = _cancel.run(argv, capture_output=True, env=self.env,
                            timeout=self.timeout_s if timeout is None
                            else timeout)
        except subprocess.TimeoutExpired:
            raise CuaError(TIMEOUT, f"{tool} timed out") from None
        except OSError as e:
            raise CuaError(DOWN, f"{self.binary}: {e}") from None
        out, err = _text(r.stdout).strip(), _text(r.stderr).strip()
        if r.returncode != 0:
            msg = err or out or f"exit {r.returncode}"
            low = msg.lower()
            if any(h in low for h in _DOWN_HINTS):
                raise CuaError(DOWN, msg)
            raise CuaError(REFUSED, msg)
        if not out:
            return {}
        try:
            val = json.loads(out)
        except ValueError:
            if strict:
                raise CuaError(PROTOCOL, f"{tool}: reply is not JSON") \
                    from None
            return {}
        if not isinstance(val, dict):
            if strict:
                raise CuaError(PROTOCOL, f"{tool}: reply is not an object")
            return {}
        return val

    # -- typed actions -------------------------------------------------
    def click(self, x, y) -> dict:
        return self.call("click", {
            "x": int(x), "y": int(y), "coordinate_frame": "desktop",
            "scope": "desktop"}, strict=False)

    def move_cursor(self, x, y) -> dict:
        return self.call("move_cursor", {
            "x": int(x), "y": int(y), "scope": "desktop"}, strict=False)

    # -- read-only window tools (spike: present in cua-driver 0.33) ----
    def list_windows(self, timeout: float = 3.0) -> dict:
        return self.call("list_windows", {}, timeout=timeout)

    def window_state(self, pid: int, window_id: int,
                     timeout: float = 5.0) -> dict:
        return self.call("get_window_state", {
            "pid": int(pid), "window_id": int(window_id)},
            timeout=timeout)
