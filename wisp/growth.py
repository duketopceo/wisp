"""Private weekly recap. Local decision and usage logs only; no telemetry.

The recap covers the last completed Monday-Sunday week in the user's local
calendar. Ledger costs lack provenance, so recorded dollars are never called
measured spend or billed totals.
"""
import json
import math
import os
from datetime import datetime, timedelta

from . import config, ledger, telemetry


def weekly_recap(cfg, *, now=None, data_dir=None, claim=False):
    """Build last week's card without modifying the source logs."""
    if str((cfg or {}).get("growth", {}).get(
            "weekly_recap", "false")).strip().lower() != "true":
        return {"enabled": False, "reason": "disabled", "card": None, "logs": {}}
    tz = now.tzinfo if now is not None else None
    now = now or datetime.now().astimezone()
    end = now.date() - timedelta(days=now.weekday())
    start = end - timedelta(days=7)
    data_dir = data_dir or config.DATA_DIR
    marker = data_dir / "recap-weeks" / (start.isoformat() + ".json")
    if marker.exists():
        return {"enabled": True, "reason": "already_seen", "card": None, "logs": {}}

    def local_day(row):
        ts = datetime.fromisoformat(row["ts"])
        if ts.tzinfo is None and tz is not None:
            ts = ts.replace(tzinfo=tz)
        return ts.astimezone(tz).date()

    logs = {"decisions": {}, "usage": {}, "legacy_usage": {}}

    def skip(status):
        status["state"] = "partial"
        status["skipped"] += 1

    def rows_in_week(name, filename=None):
        status = logs[name]
        rows = telemetry._load(data_dir / (filename or name + ".jsonl"), status=status)
        selected = []
        for row in rows:
            if name == "legacy_usage":
                converted = ledger._legacy_row(row)
                if converted is not None:
                    # The ledger adapter coerces unknown historical costs
                    # to zero for compatibility. A recap must not do that.
                    converted["usd"] = row.get("cost")
                row = converted
            try:
                day = local_day(row)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                skip(status)
                continue
            if start <= day < end:
                if name != "decisions":
                    usd = row.get("usd")
                    if (isinstance(usd, bool) or
                            not isinstance(usd, (int, float)) or
                            not math.isfinite(usd) or usd < 0):
                        skip(status)
                        continue
                selected.append(row)
        return selected

    decisions, usage = rows_in_week("decisions"), rows_in_week("usage")
    usage += rows_in_week("legacy_usage", "spend.jsonl")
    if not decisions:
        return {"enabled": True, "reason": "no_activity", "card": None,
                "logs": logs}
    days = len({local_day(r) for r in decisions})
    states = [logs[k]["state"] for k in ("usage", "legacy_usage")]
    available = "ok" in states or bool(usage)
    usd = round(sum(r["usd"] for r in usage), 6) if available else None
    complete = available and all(s in ("ok", "missing") for s in states)
    spend_text = (f"${usd:.2f} " + ("recorded" if complete else "partial recorded")
                  if usd is not None else "spend unavailable")
    card = {
        "week_start": start.isoformat(),
        "week_end": (end - timedelta(days=1)).isoformat(),
        "days_used": days, "turns": len(decisions),
        "spend": {"recorded_usd": usd, "measured_usd": None,
                  "estimated_usd": None, "basis": "source_not_recorded",
                  "complete": complete},
        "title": "your week with wisp",
        "summary": f"you used wisp {days} days, {len(decisions)} turns, "
                   + spend_text,
        "activity_note": ("Days and turns are partial; some local activity "
                          "rows could not be read."
                          if logs["decisions"]["state"] != "ok" else ""),
        "spend_note": "Recorded costs may include estimates; measured and "
                      "estimated shares are unknown.",
    }
    if claim:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"week_start": start.isoformat(),
                           "claimed_at": now.isoformat()}, stream)
                stream.write("\n")
        except FileExistsError:
            return {"enabled": True, "reason": "already_seen", "card": None, "logs": {}}
        except OSError:
            return {"enabled": True, "reason": "state_unavailable", "card": None,
                    "logs": logs}
    return {"enabled": True, "reason": "ready", "card": card, "logs": logs}
