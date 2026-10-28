"""Ask chips (B21): "what can I ask here?" for a new user.

A quick tap of the talk key (held less than TAP_MAX_S, nothing said) shows up
to three short asks that fit the focused app. Saying one runs it as any other
turn; the chips are text only, nothing to click. They appear only on a tap,
never unprompted, only for the first `[chips] days` days from the first tap,
and not at all with `[chips] enabled = "false"`. A tap takes no screenshot:
the press-time speculative capture waits TAP_MAX_S and is cancelled by the
release (see context.Speculative `delays`).
"""
import datetime as _dt
import json

from . import config, skills

TAP_MAX_S = 0.25          # held shorter than this and silent: a tap
GENERIC = ["What can you do on this screen?",
           "What does this window do?",
           "How do I get started with Wisp?"]


def settings(cfg: dict | None) -> dict:
    c = (cfg or {}).get("chips", {}) or {}
    try:
        days = max(1, int(c.get("days", "7")))
    except (TypeError, ValueError):
        days = 7
    return {"enabled": str(c.get("enabled", "true")).lower() != "false",
            "days": days}


def _since_file():
    return config.DATA_DIR / "chips.json"


def _read_since():
    try:
        return _dt.datetime.fromisoformat(
            json.loads(_since_file().read_text("utf-8"))["since"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def in_window(cfg, now=None, mark: bool = False) -> bool:
    """True while the first-week window is open. The window starts at the
    first tap (`mark=True` records it); before any tap it is open."""
    s = settings(cfg)
    if not s["enabled"]:
        return False
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = _read_since()
    if since is None:
        if mark:
            try:
                _since_file().parent.mkdir(parents=True, exist_ok=True)
                _since_file().write_text(
                    json.dumps({"since": now.isoformat()}), "utf-8")
            except OSError:
                pass
        return True
    return now - since <= _dt.timedelta(days=s["days"])


def armed(cfg, now=None) -> bool:
    """Cheap check the press path uses: should the screenshot wait?"""
    return in_window(cfg, now)


def asks_for(app_class: str, url_host: str | None = None,
             skills_dir=None) -> list:
    info = skills.match_app_skill_info(app_class, url_host, skills_dir) \
        if (app_class or url_host) else None
    asks = (info or {}).get("asks") or []
    return list(asks) if asks else list(GENERIC)


def build(cfg, app_class: str, seq: int = 1, now=None, mark: bool = True,
          skills_dir=None) -> dict | None:
    """The state payload for a tap, or None (off, outside the window)."""
    if not in_window(cfg, now, mark=mark):
        return None
    return {"app": app_class or "", "asks": asks_for(app_class, None,
                                                     skills_dir),
            "seq": seq}


def is_tap(held_s: float) -> bool:
    return 0 <= held_s < TAP_MAX_S
