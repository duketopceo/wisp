"""Usage ledger and spend caps (backend U10, W14).

Every model call that goes through `brain` appends one row to
`DATA_DIR/usage.jsonl`:

    {"ts": local ISO, "provider", "model", "in", "out", "usd", "paid"}

Local models are recorded too (tokens counted, `usd` 0.0). Cost is the
OpenRouter-reported `usage.cost` when the response carries it, else the
local `PRICES` table (USD per million tokens, no network fetch); a paid
model missing from the table is priced at `UNKNOWN_PRICE`, a deliberately
high ceiling, so an unknown model can never look free.

Caps live in `[budget] daily_usd` / `monthly_usd` (blank = no cap).
`daily_usd` falls back to the legacy `[brain] daily_cap_usd` alias, then
to DEFAULT_DAILY_USD; `monthly_usd` defaults to 160.00 (20 days x 8).
Day and month roll over by LOCAL date. A paid call is allowed only while
spend is strictly under every set cap; at the cap it is blocked before
the request is made. Local providers are never gated.

Policy (`paid_allowed`): at/over a cap, paid FALLBACK entries are
refused but the PRIMARY entry still runs (the agent lives), unless
`[budget] gate_primary = "true"`, which gates every paid entry. If the
ledger cannot be read (anything but "file does not exist") fallbacks are
refused and the primary runs only when gate_primary is off.

History: rows from the pre-merge `spend.jsonl` writer (sibling of the
ledger file: {ts epoch, model, cost, prompt_tokens, completion_tokens})
are read too, mapped to paid openrouter rows with source "spend.jsonl",
so spend recorded before the ledger counts toward today's cap. Nothing
writes that file any more.

The daemon calls `attach(bus, cfg)`; after that each recorded call
publishes `spend` ({today_usd, cap_usd, ...}) on the state stream, and
`health_hook` feeds a `spend` health row that goes down with code
`budget_exceeded` while a cap is reached.
"""
import datetime as _dt
import fcntl
import json
import os
import logging
import threading

from . import config

log = logging.getLogger(__name__)

# USD per million tokens (input, output). Small, cheap models only;
# anything else paid falls to UNKNOWN_PRICE.
PRICES = {
    "meta-llama/llama-4-maverick": (0.15, 0.60),
    "meta-llama/llama-4-scout": (0.08, 0.30),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "qwen/qwen3-235b-a22b": (0.13, 0.60),
    "x-ai/grok-4.7": (1.60, 4.80),
}
UNKNOWN_PRICE = (10.0, 30.0)
DEFAULT_DAILY_USD = 8.0
DEFAULT_MONTHLY_USD = 160.0
LEGACY_NAME = "spend.jsonl"

# Off until the daemon / CLI entry turns it on, so library code run from
# tests never writes to the real ledger.
ACTIVE = False

_LOCK = threading.Lock()
_SESSION = {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
            "calls": 0}
_HINTED = False
_BUS = None
_CFG = None


def path():
    return config.DATA_DIR / "usage.jsonl"


def _now():
    return _dt.datetime.now()


def price(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, UNKNOWN_PRICE)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def record(provider: str, model: str, tokens_in: int, tokens_out: int,
           usd=None, paid: bool = False, now=None, p=None, path=None):
    """Append one row and return it. `usd` None = price from the table
    (paid) or 0 (local)."""
    now = now or _now()
    if not paid:
        usd = 0.0
    elif usd is None:
        usd = price(model, int(tokens_in), int(tokens_out))
    row = {"ts": now.isoformat(timespec="seconds"), "provider": provider,
           "model": model, "in": int(tokens_in), "out": int(tokens_out),
           "usd": round(float(usd), 8), "paid": bool(paid)}
    target = path or p or globals()["path"]()
    line = (json.dumps(row, separators=(",", ":")) + "\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line)
        finally:
            os.close(fd)  # closing drops the flock
    return row


def _lines(target):
    """Parsed dict rows of one file. Missing file = none; any other read
    error raises."""
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict):
            yield r


def _legacy_row(r: dict):
    """Map a spend.jsonl row to a ledger row, or None if unusable."""
    try:
        ts = _dt.datetime.fromtimestamp(float(r["ts"]))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None
    return {"ts": ts.isoformat(timespec="seconds"),
            "provider": "openrouter", "model": r.get("model") or "?",
            "in": int(_num(r.get("prompt_tokens"))),
            "out": int(_num(r.get("completion_tokens"))),
            "usd": _num(r.get("cost")), "paid": True,
            "source": LEGACY_NAME}


def _rows(target):
    """Ledger rows plus the legacy spend.jsonl rows beside it."""
    yield from _lines(target)
    for r in _lines(target.with_name(LEGACY_NAME)):
        m = _legacy_row(r)
        if m is not None:
            yield m


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def totals(now=None, path=None) -> dict:
    now = now or _now()
    day, month = now.date().isoformat(), now.strftime("%Y-%m")
    t = {"today_usd": 0.0, "month_usd": 0.0, "calls_today": 0,
         "tokens_in": 0, "tokens_out": 0, "by_model": {}}
    for r in _rows(path or globals()["path"]()):
        ts = str(r.get("ts", ""))
        usd = _num(r.get("usd"))
        if ts[:7] == month:
            t["month_usd"] += usd
        if ts[:10] != day:
            continue
        t["today_usd"] += usd
        t["calls_today"] += 1
        t["tokens_in"] += int(_num(r.get("in")))
        t["tokens_out"] += int(_num(r.get("out")))
        key = f"{r.get('provider', '?')}:{r.get('model', '?')}"
        m = t["by_model"].setdefault(
            key, {"calls": 0, "usd": 0.0, "in": 0, "out": 0})
        m["calls"] += 1
        m["usd"] += usd
        m["in"] += int(_num(r.get("in")))
        m["out"] += int(_num(r.get("out")))
    t["today_usd"] = round(t["today_usd"], 6)
    t["month_usd"] = round(t["month_usd"], 6)
    for m in t["by_model"].values():
        m["usd"] = round(m["usd"], 6)
    return t


def _cap(v):
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return c if c >= 0 else None


def caps(cfg: dict) -> tuple:
    """(daily, monthly) USD caps; None = no cap. `[budget] daily_usd`
    wins; else the deprecated `[brain] daily_cap_usd`; else the default.
    A blank value means no cap."""
    global _HINTED
    cfg = cfg or {}
    b = cfg.get("budget", {})
    if "daily_usd" in b:
        daily = _cap(b["daily_usd"])
    elif "daily_cap_usd" in cfg.get("brain", {}):
        daily = _cap(cfg["brain"]["daily_cap_usd"])
        if not _HINTED:
            _HINTED = True
            log.warning("[brain] daily_cap_usd is deprecated; "
                        "use [budget] daily_usd")
    else:
        daily = DEFAULT_DAILY_USD
    monthly = _cap(b["monthly_usd"]) if "monthly_usd" in b \
        else DEFAULT_MONTHLY_USD
    return daily, monthly


def gate_primary(cfg: dict) -> bool:
    return str((cfg or {}).get("budget", {}).get(
        "gate_primary", "false")).strip().lower() == "true"


def status(cfg: dict, now=None, path=None) -> dict:
    """Totals plus caps and whether paid calls are blocked right now.
    Raises OSError when the ledger cannot be read."""
    t = totals(now, path)
    daily, monthly = caps(cfg)
    reason = None
    if daily is not None and t["today_usd"] >= daily:
        reason = "daily_cap"
    elif monthly is not None and t["month_usd"] >= monthly:
        reason = "monthly_cap"
    return {**t, "cap_usd": daily, "monthly_cap_usd": monthly,
            "blocked": reason is not None, "reason": reason}


def paid_allowed(cfg: dict, now=None, path=None,
                 primary: bool = False) -> bool:
    """May a paid entry run? Under every cap: yes. At/over a cap or with
    an unreadable ledger: a fallback is refused; the primary still runs
    unless `[budget] gate_primary = "true"`."""
    try:
        if not status(cfg, now, path)["blocked"]:
            return True
    except Exception:  # noqa: BLE001
        pass
    return primary and not gate_primary(cfg)


def spend_field(cfg: dict, now=None, path=None) -> dict:
    """The `spend` object on the state stream. W23 reads today_usd and
    cap_usd; the rest is additive."""
    try:
        s = status(cfg, now, path)
    except Exception:  # noqa: BLE001
        daily, monthly = caps(cfg)
        return {"today_usd": 0.0, "cap_usd": daily, "month_usd": 0.0,
                "monthly_cap_usd": monthly, "blocked": True}
    return {"today_usd": round(s["today_usd"], 4), "cap_usd": s["cap_usd"],
            "month_usd": round(s["month_usd"], 4),
            "monthly_cap_usd": s["monthly_cap_usd"],
            "blocked": s["blocked"]}


def attach(bus, cfg) -> None:
    """Daemon wiring: publish `spend` after every recorded call."""
    global _BUS, _CFG
    _BUS, _CFG = bus, cfg
    publish()


def publish() -> None:
    if _BUS is None or _CFG is None:
        return
    try:
        _BUS.publish(None, spend=spend_field(_CFG))
    except Exception:  # noqa: BLE001
        pass


def health_hook(cfg: dict, path=None, clock=None):
    """HealthRegistry hook: down with `budget_exceeded` while a cap is
    reached. Each probe also republishes `spend`, which carries the
    midnight rollover to the bar without a call being made."""
    def probe():
        now = clock() if clock else None
        spend = spend_field(cfg, now, path)
        if _BUS is not None and _CFG is cfg:
            try:
                _BUS.publish(None, spend=spend)
            except Exception:  # noqa: BLE001
                pass
        if spend["blocked"]:
            return {"ok": False, "code": "budget_exceeded"}
        return {"ok": True, "code": None}
    return probe


def usage_of(resp: dict) -> dict:
    """Normalise a provider usage block to {in, out, cost}."""
    resp = resp or {}
    u = resp.get("usage") or ({k: resp[k] for k in (
        "prompt_eval_count", "eval_count") if k in resp})
    if not isinstance(u, dict):
        u = {}
    tin = u.get("prompt_tokens", u.get("input_tokens", u.get("prompt_eval_count")))
    tout = u.get("completion_tokens",
                 u.get("output_tokens", u.get("eval_count")))
    cost = u.get("cost")
    return {"in": int(_num(tin)), "out": int(_num(tout)),
            "cost": None if cost is None else _num(cost)}


def reset_session() -> None:
    """Zero the in-process counters (clicklab calls this per task)."""
    for k in _SESSION:
        _SESSION[k] = 0


def session_totals() -> dict:
    """{cost, prompt_tokens, completion_tokens, calls} for calls noted in
    this process since reset_session(); counted even when not ACTIVE."""
    return dict(_SESSION)


def note(provider: str, model: str, paid: bool, usage: dict):
    """Record one finished brain call (the single place a call is
    recorded). Never raises; the file write is a no-op unless ACTIVE.
    `usage` is {in/out or prompt_tokens/..., cost}."""
    try:
        tin = usage.get("in", usage.get("prompt_tokens", 0))
        tout = usage.get("out", usage.get("completion_tokens", 0))
        cost = usage.get("cost")
        usd = 0.0 if not paid else (
            price(model, int(_num(tin)), int(_num(tout)))
            if cost is None else _num(cost))
        with _LOCK:
            _SESSION["calls"] += 1
            _SESSION["prompt_tokens"] += int(_num(tin))
            _SESSION["completion_tokens"] += int(_num(tout))
            _SESSION["cost"] += usd
    except Exception:  # noqa: BLE001
        pass
    if not ACTIVE:
        return None
    try:
        row = record(provider, model, tin, tout, usd=usage.get("cost"),
                     paid=paid)
    except Exception:  # noqa: BLE001
        return None
    publish()
    return row
