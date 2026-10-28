"""Idle cost as a number (B29): CPU percent and resident memory of the
running daemon over a short window with nothing asked, checked against
the `idle_cpu_pct` and `idle_rss_mb` rows of wisp/budgets.json."""
import os
import time


def _ticks_per_s() -> int:
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        return 100


def cpu_ticks(pid: int, proc="/proc") -> int | None:
    """utime + stime of a process, in clock ticks."""
    try:
        with open(f"{proc}/{pid}/stat") as f:
            raw = f.read()
        rest = raw[raw.rindex(")") + 2:].split()   # comm may hold spaces
        return int(rest[11]) + int(rest[12])
    except (OSError, ValueError, IndexError):
        return None


def rss_mb(pid: int, proc="/proc") -> float | None:
    try:
        with open(f"{proc}/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def sample(pid: int, seconds: float = 3.0, proc="/proc",
           clock=time.monotonic, sleep=time.sleep,
           hz: int | None = None) -> dict | None:
    """{pid, seconds, cpu_pct, rss_mb} measured over `seconds`, or None
    when the process is not readable."""
    hz = hz or _ticks_per_s()
    a, t0 = cpu_ticks(pid, proc), clock()
    if a is None:
        return None
    sleep(seconds)
    b, t1 = cpu_ticks(pid, proc), clock()
    rss = rss_mb(pid, proc)
    if b is None or rss is None or t1 <= t0:
        return None
    return {"pid": pid, "seconds": round(t1 - t0, 2),
            "cpu_pct": round(100.0 * (b - a) / hz / (t1 - t0), 2),
            "rss_mb": round(rss, 1)}


def budgets() -> dict:
    from . import telemetry
    r = telemetry.load_budgets()["resources"]
    return {"cpu_pct": float(r["idle_cpu_pct"]),
            "rss_mb": float(r["idle_rss_mb"])}


def breaches(s: dict, b: dict | None = None) -> list:
    """Plain sentences for each budget the sample is over; [] is fine."""
    b = b or budgets()
    out = []
    if s["cpu_pct"] > b["cpu_pct"]:
        out.append(f"idle CPU {s['cpu_pct']}% is over the "
                   f"{b['cpu_pct']:g}% budget")
    if s["rss_mb"] > b["rss_mb"]:
        out.append(f"idle memory {s['rss_mb']} MB is over the "
                   f"{b['rss_mb']:g} MB budget")
    return out
