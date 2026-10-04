"""CLI error copy: `E_CODE: sentence` plus a `Try:` line.

TODO(W17): move this table into wisp/copy.py (generated copy table) once
the lint test there can cover CLI strings. Until then the rules are the
same: sentence case, plain verbs, no emoji, no em dashes, every sentence
ends with a period.
"""
from .. import errors_codes

# code -> (sentence, try-line). The sentence is the default; a call site
# may pass a more specific one (it must follow the same rules).
ERRORS = {
    "E_USAGE": ("The command line is not valid.", "wispd --help"),
    "E_FAILED": ("The command did not succeed.", "wispd doctor"),
    "E_NOT_FOUND": ("That item does not exist.", "wispd --help"),
    "E_BAD_CONFIG": ("That config change was rejected.",
                     "wispd config show"),
    "E_DAEMON_DOWN": ("The wisp daemon is not running.",
                      "systemctl --user start wispd"),
    "E_UNHEALTHY": ("A dependency is down or unreachable.", "wispd doctor"),
    "E_CUA_DOWN": ("The cua driver is not reachable.", "wispd cua status"),
    "E_NO_NOTIFIER": ("No notification tool is available.",
                      "wispd doctor"),
    "E_NOT_READY": ("Setup is not finished.", "wispd onboard"),
}

_DOWN_TRY = "wispd health"
for _code in errors_codes.CODES:
    ERRORS["E_" + _code.upper()] = (
        errors_codes.human(_code)[:1].upper()
        + errors_codes.human(_code)[1:] + ".",
        _DOWN_TRY if _code.endswith("_down") else "wispd doctor")
ERRORS["E_STALE_PROMPT"] = ("That prompt expired.", "wispd watch")
ERRORS["E_BUSY"] = ("Busy with another request.",
                    "wispd interrupt, then try again")

# Codes that mean a dependency is unreachable or unhealthy (exit 4).
DEPENDENCY_CODES = frozenset(
    ["E_UNHEALTHY", "E_CUA_DOWN", "E_NOT_READY"]
    + ["E_" + c.upper() for c in errors_codes.CODES
       if c.endswith("_down")])

TRY_HELP = "wispd {path} --help"
NO_TASKS = "no agents on record"
