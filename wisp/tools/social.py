"""Structured social integrations — prefer these over GUI automation.

X: the send path hands X's own `intent/post` composer to the signed-in
browser pre-filled. Wisp never scripts the Post button — the human
confirms in the composer window. `post` is a pure preview (safe tier,
always dry-run); `post_send` is the opt-in mutating tool the
confirm-gate guards.
"""
import shutil
import subprocess
import urllib.parse

INTENT = "https://x.com/intent/post?text="


def _text(arg: str) -> str:
    return (arg or "").strip().lstrip("!").strip()


def _open_url(url: str) -> str:
    """Hand a URL to the user's browser; returns the opener used."""
    for cmd in (["browseros", url], ["xdg-open", url], ["open", url]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return cmd[0]
    return ""


def post_draft(arg: str, cfg: dict | None = None) -> str:
    text = _text(arg)
    if not text:
        return "SKIP (nothing to post)"
    return (f"DRY-RUN POST ({len(text)} chars): {text[:200]}"
            " — use post_send to open the compose window")


def post_open(arg: str, cfg: dict | None = None) -> str:
    text = _text(arg)
    if not text:
        return "SKIP (nothing to post)"
    via = _open_url(INTENT + urllib.parse.quote(text))
    if not via:
        return "SKIP (no browser opener found)"
    return f"OPENED compose via {via} — press Post in the window"
