"""The capped trial brain, client side (B34 option A). Off, and not live.

A first run with no keys can answer from a proxy the owner runs
(scripts/trial_proxy/proxy.py). Nothing here reaches the network unless
`[trial] enabled = "true"` and `[trial] url` names the proxy; both default
to off and empty, so a shipped build never calls out. The install holds a
random token, never a provider key: the proxy keeps the real key and the
caps (per token, per day, per address, and a global daily dollar ceiling).
"""
import os
import secrets
import urllib.parse

from . import config

TOKEN_FILE = config.CFG_DIR / "trial_token"
LIMIT_LINE = ("This is a trial and it has reached its limit. Add your own "
              "keys to continue: wispd onboard.")


def _section(cfg) -> dict:
    return (cfg or {}).get("trial", {}) or {}


def url(cfg) -> str:
    """The proxy base URL when the trial is on, else "". https only (a
    loopback address may use http, for the owner's own test proxy)."""
    s = _section(cfg)
    if str(s.get("enabled", "false")).strip().lower() != "true":
        return ""
    u = str(s.get("url", "")).strip().rstrip("/")
    p = urllib.parse.urlparse(u)
    if p.scheme == "https" and p.hostname:
        return u
    if p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost", "::1"):
        return u
    return ""


def token(path=None) -> str:
    """This install's trial token: `wt_` plus 32 random hex digits, kept
    0600. It names the install to the proxy and unlocks nothing else."""
    f = path or TOKEN_FILE
    try:
        t = f.read_text().strip()
        if t.startswith("wt_") and len(t) == 35:
            return t
    except OSError:
        pass
    t = "wt_" + secrets.token_hex(16)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as h:
        h.write(t + "\n")
    return t


def limit_reached(err) -> bool:
    """Did the proxy refuse because a cap was hit (HTTP 402/429)?"""
    return getattr(err, "code", None) in (402, 429)


def text_only(messages: list) -> list:
    """The trial is text only: screenshots and image parts never leave the
    machine for it (the proxy drops them as well)."""
    out = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list):
            c = "\n".join(str(p.get("text", "")) for p in c
                          if isinstance(p, dict) and p.get("type") == "text")
        out.append({"role": str((m or {}).get("role", "user")),
                    "content": str(c or "")})
    return out
