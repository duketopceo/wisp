"""Pure suggestion etiquette policy (H6).

Evaluates whether a proactive suggestion card may be surfaced right now,
tracks 7-day backoff after 3 consecutive dismissed days, and formats recent
decline reasons for injection into the next suggestion batch prompt.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

EARLIEST_LOCAL_HOUR = 6
DISMISSAL_STREAK_LIMIT = 3
PAUSE_DAYS = 7


def _parse_day(d: str | date | datetime | None) -> date | None:
    if d is None or d == "":
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d).strip()[:10])
    except ValueError:
        return None


def format_declined_reasons_prompt(
    declined_reasons: Iterable[str | dict] | None,
) -> str:
    """Format recent user decline reasons into a prompt block for the next
    batch mining pass. Empty string when no valid reasons exist."""
    if not declined_reasons:
        return ""
    cleaned: list[str] = []
    for item in declined_reasons:
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            reason = str(
                item.get("reason") or item.get("declined_reason") or ""
            ).strip()
            entry = f"{title}: {reason}" if (title and reason) else (reason or title)
        else:
            entry = str(item or "").strip()
        if entry and entry not in cleaned:
            cleaned.append(entry)
    if not cleaned:
        return ""
    bullets = "\n".join(f"- {r}" for r in cleaned)
    return (
        "Previously declined suggestions (do not suggest similar workflows):\n"
        f"{bullets}"
    )


def evaluate_suggestion_etiquette(
    local_hour: int = 12,
    in_call: bool = False,
    screen_sharing: bool = False,
    fullscreen: bool = False,
    dismissal_streak_days: int = 0,
    paused_until_day: str | date | None = None,
    current_day: str | date | None = None,
    declined_reasons: Iterable[str | dict] | None = None,
) -> dict:
    """Evaluate suggestion etiquette rules over current state.

    Rules:
    1. If `paused_until_day` is in the future (`current_day < paused_until_day`),
       remain paused (`action="pause"`, `allow=False`, `reason="paused_backoff"`).
    2. If `dismissal_streak_days >= 3` (and not resuming from an expired pause),
       pause for 7 days (`paused_until_day = current_day + 7 days`,
       `action="pause"`, `allow=False`, `reason="dismissal_streak"`).
    3. Block before 6am local (`0 <= local_hour < 6`, `action="block"`,
       `allow=False`, `reason="before_6am"`).
    4. Hold during calls, screen sharing, or fullscreen (`action="hold"`,
       `allow=False`, `reason="in_call" | "screen_sharing" | "fullscreen"`).
    5. Otherwise allow (`action="allow"`, `allow=True`, `reason="ok"`).

    Always includes `declined_prompt` built from `declined_reasons`.
    """
    cur = _parse_day(current_day) or date.today()
    paused_until = _parse_day(paused_until_day)
    prompt_addon = format_declined_reasons_prompt(declined_reasons)

    # Active pause window
    if paused_until is not None and cur < paused_until:
        return {
            "allow": False,
            "allowed": False,
            "action": "pause",
            "reason": "paused_backoff",
            "paused_until_day": paused_until.isoformat(),
            "declined_prompt": prompt_addon,
        }

    # A pause that just expired resumes suggestions; the caller resets the
    # streak, so a stale streak count must not immediately re-pause.
    pause_just_expired = paused_until is not None and cur >= paused_until
    if int(dismissal_streak_days or 0) >= DISMISSAL_STREAK_LIMIT and not pause_just_expired:
        until = (cur + timedelta(days=PAUSE_DAYS)).isoformat()
        return {
            "allow": False,
            "allowed": False,
            "action": "pause",
            "reason": "dismissal_streak",
            "paused_until_day": until,
            "declined_prompt": prompt_addon,
        }

    # any pause still in force returned above; past this point none is active
    active_pause_str = None

    if int(local_hour) < EARLIEST_LOCAL_HOUR:
        return {
            "allow": False,
            "allowed": False,
            "action": "block",
            "reason": "before_6am",
            "paused_until_day": active_pause_str,
            "declined_prompt": prompt_addon,
        }

    if in_call:
        return {
            "allow": False,
            "allowed": False,
            "action": "hold",
            "reason": "in_call",
            "paused_until_day": active_pause_str,
            "declined_prompt": prompt_addon,
        }
    if screen_sharing:
        return {
            "allow": False,
            "allowed": False,
            "action": "hold",
            "reason": "screen_sharing",
            "paused_until_day": active_pause_str,
            "declined_prompt": prompt_addon,
        }
    if fullscreen:
        return {
            "allow": False,
            "allowed": False,
            "action": "hold",
            "reason": "fullscreen",
            "paused_until_day": active_pause_str,
            "declined_prompt": prompt_addon,
        }

    return {
        "allow": True,
        "allowed": True,
        "action": "allow",
        "reason": "ok",
        "paused_until_day": active_pause_str,
        "declined_prompt": prompt_addon,
    }
