"""Closed set of typed error codes (backend U7, KTD8).

Every failure that ends a turn maps to one of CODES. The shell renders
copy from the code; `human()` is the safe fallback string that goes in
state.json `error`. The raw exception text never leaves the machine in
`error` — it rides in `error_detail` and trace.jsonl only.
"""
import json
import socket
import urllib.error

CODES = ("jev_down", "brain_down", "stt_down", "ground_down",
         "ground_failed", "timeout", "cancelled", "busy", "stale_prompt",
         "restarted", "tool_failed", "budget_exceeded", "internal")

_HUMAN = {
    "jev_down": "The router is offline",
    "brain_down": "The local brain is offline",
    "stt_down": "Speech recognition is offline",
    "ground_down": "Screen grounding is offline",
    "ground_failed": "Could not find that on screen",
    "timeout": "That took too long",
    "cancelled": "Cancelled",
    "busy": "Busy with another request",
    "stale_prompt": "That prompt expired",
    "restarted": "Wisp restarted",
    "tool_failed": "A step failed",
    "budget_exceeded": "Daily model budget reached",
    "internal": "Something went wrong",
}


def human(code: str) -> str:
    return _HUMAN.get(code, _HUMAN["internal"])


class WispError(RuntimeError):
    """A failure with a closed-set `code`. `public` is safe to show;
    `detail` is raw text kept local. str(e) is the detail when present
    so existing log lines and messages stay informative."""

    def __init__(self, code: str, detail: str = "",
                 public: str | None = None):
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}")
        self.code = code
        self.detail = detail
        self.public = public or human(code)
        super().__init__(detail or self.public)


def _unwrap(exc):
    return exc.reason if isinstance(exc, urllib.error.URLError) \
        and not isinstance(exc, urllib.error.HTTPError) \
        and isinstance(exc.reason, BaseException) else exc


def is_timeout(exc) -> bool:
    return isinstance(_unwrap(exc), (socket.timeout, TimeoutError))


def is_connection_failure(exc) -> bool:
    """Refused or reset — the only failures worth one fast retry."""
    return isinstance(_unwrap(exc),
                      (ConnectionRefusedError, ConnectionResetError,
                       ConnectionAbortedError, BrokenPipeError)) \
        or type(_unwrap(exc)).__name__ in ("RemoteDisconnected",
                                           "IncompleteRead")


def classify(exc: BaseException, endpoint_code: str) -> WispError:
    """Map any exception to a WispError. `endpoint_code` is the code of
    the endpoint being called (jev_down, brain_down, ...): connection
    errors, HTTP errors and unparseable replies all mean that endpoint
    is not usable; timeouts are `timeout`; anything else is `internal`."""
    if isinstance(exc, WispError):
        return exc
    detail = str(exc) or type(exc).__name__
    if is_timeout(exc):
        return WispError("timeout", detail)
    if isinstance(exc, (urllib.error.URLError, OSError,
                        json.JSONDecodeError, UnicodeDecodeError)) \
            or is_connection_failure(exc):
        return WispError(endpoint_code, detail)
    return WispError("internal", f"{type(exc).__name__}: {detail}")
