#!/usr/bin/env python3
"""Live click probe: how far does wisp's grounding land from a KNOWN target?

Opens scripts/probe/targets.html fullscreen in a throwaway browser profile
on each monitor, asks `grounding.ground_target` for each numbered button by
name, clicks where it says, and reads the window title back through
Hyprland. Because the button positions are known, the miss distance is
the model's grounding error alone; the coordinate math is proven offline by
tests/test_click_harness.py.

    orch python scripts/click_probe.py --live --config hybrid \\
        --ground-brain ollama:qwen2.5vl:3b-q8_0 --monitors eDP-1,DP-3

`--session isolated` drives the headless instance from
scripts/isolated_session.py instead of the owner's monitors: pages open
in the instance, clicks go through the virtual pointer (never uinput) and
hit titles are read from the instance's client list. The input canary
runs before the first target (a failure exits 2). The probe's monitors
are the instance's two outputs.

Run it under `orch` so any spend bills the eval key. Without --live it
only prints the plan. Each run appends one JSON row per target to --out
and prints a per-monitor, per-config, per-model summary. Spend (the usage
ledger's delta) is added to --spend-file when given, and the run stops
before a target once --max-usd is reached or the file's total hits
--cap-usd.

Exit codes: 0 probe ran and at least one target was hit (or plan only),
1 probe ran with zero hits, 2 usage or environment error (no Hyprland,
no browser, unknown monitor, spend cap reached).
"""
from __future__ import annotations

import argparse
import collections.abc
import dataclasses
import importlib.util
import json
import math
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGE = ROOT / "scripts" / "probe" / "targets.html"

_spec = importlib.util.spec_from_file_location(
    "isolated_session_mod", ROOT / "scripts" / "isolated_session.py")
isolated = sys.modules.get("isolated_session_mod") \
    or importlib.util.module_from_spec(_spec)
if "isolated_session_mod" not in sys.modules:
    sys.modules["isolated_session_mod"] = isolated
    _spec.loader.exec_module(isolated)

# (number, fraction of window width, fraction of window height): must
# match BUTTONS in targets.html (a test pins this).
TARGETS = [(1, 0.2, 0.2), (2, 0.5, 0.2), (3, 0.8, 0.2),
           (4, 0.2, 0.5), (5, 0.5, 0.5), (6, 0.8, 0.5),
           (7, 0.2, 0.8), (8, 0.5, 0.8), (9, 0.8, 0.8)]

_TITLE = re.compile(r"hit:(\d+):(\d+)")
EXIT_OK, EXIT_NO_HITS, EXIT_USAGE = 0, 1, 2


class ProbeError(Exception):
    """Environment problem: exit 2."""


def target_name(n: int) -> str:
    return f"the button labelled {n}"


def logical_rect(mon: dict) -> tuple:
    """A monitor's (x, y, w, h) in compositor-global logical px."""
    s = float(mon.get("scale", 1) or 1)
    return (mon.get("x", 0), mon.get("y", 0),
            mon.get("width", 0) / s, mon.get("height", 0) / s)


def expected_point(mon: dict, fx: float, fy: float) -> tuple:
    """Where a fullscreen page puts a button at fractions (fx, fy)."""
    x, y, w, h = logical_rect(mon)
    return round(x + fx * w), round(y + fy * h)


def parse_title(title: str):
    """'hit:N:seq' -> (N, seq), else None."""
    m = _TITLE.search(title or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def score_row(*, monitor: str, config: str, model: str, number: int,
              expected, got, title_before: str, title_after: str,
              error: str = "", ms: int = 0) -> dict:
    """One probe result. `got` is the grounded logical point or None.
    hit = the clicked window title reports THIS button after the click;
    wrong = it reports another button; miss = the title did not change."""
    row = {"monitor": monitor, "config": config, "model": model,
           "target": number, "expected": list(expected),
           "got": list(got) if got is not None else None,
           "grounded": got is not None, "dist_px": None,
           "outcome": "ungrounded", "error": error, "ms": ms}
    if got is None:
        return row
    row["dist_px"] = round(math.hypot(got[0] - expected[0],
                                      got[1] - expected[1]), 1)
    before, after = parse_title(title_before), parse_title(title_after)
    if after is None or after == before:
        row["outcome"] = "miss"
    elif after[0] == number:
        row["outcome"] = "hit"
    else:
        row["outcome"] = "wrong"
    return row


def summarize(rows: list) -> list:
    """Per (monitor, config, model): targets, grounded, hits, hit rate,
    and the median/max miss distance over grounded targets."""
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["monitor"], r["config"], r["model"]),
                          []).append(r)
    out = []
    for (mon, cfg, model), rs in sorted(groups.items()):
        dists = [r["dist_px"] for r in rs if r["dist_px"] is not None]
        hits = sum(1 for r in rs if r["outcome"] == "hit")
        out.append({
            "monitor": mon, "config": cfg, "model": model, "n": len(rs),
            "grounded": len(dists), "hits": hits,
            "hit_rate": round(hits / len(rs), 3),
            "median_miss_px": (round(statistics.median(dists), 1)
                               if dists else None),
            "max_miss_px": max(dists) if dists else None})
    return out


@dataclasses.dataclass
class Rig:
    """Everything that touches the desktop, injectable for tests."""
    monitors: collections.abc.Callable          # () -> [monitor dict]
    open_page: collections.abc.Callable         # (monitor) -> handle
    window_rect: collections.abc.Callable       # (handle) -> (x, y, w, h) logical or None
    ground: collections.abc.Callable            # (name) -> (x, y); GroundRefused -> None
    click: collections.abc.Callable             # (x, y) -> bool
    title: collections.abc.Callable             # (handle) -> window title
    close: collections.abc.Callable             # (handle) -> None
    spend: collections.abc.Callable = lambda: 0.0   # () -> cumulative usd
    sleep: collections.abc.Callable = time.sleep
    settle_s: float = 0.6


def run_probe(rig: Rig, monitor_names: list, *, config: str, model: str,
              max_usd: float = 0.0, numbers=None, now=time.monotonic) -> list:
    """Probe every named monitor; returns the rows. `max_usd` (> 0) stops
    the run before a target once the ledger delta reaches it."""
    mons = {m.get("name"): m for m in rig.monitors()}
    missing = [n for n in monitor_names if n not in mons]
    if missing:
        raise ProbeError(f"unknown monitor(s): {', '.join(missing)}")
    wanted = [t for t in TARGETS if numbers is None or t[0] in numbers]
    start = rig.spend()
    rows = []
    for name in monitor_names:
        mon = mons[name]
        handle = rig.open_page(mon)
        try:
            rig.sleep(rig.settle_s)
            rect = rig.window_rect(handle)
            want = logical_rect(mon)
            if rect is None or any(abs(a - b) > 4
                                   for a, b in zip(rect, want)):
                raise ProbeError(
                    f"{name}: probe window is not fullscreen on the "
                    f"monitor (got {rect}, want {want})")
            for number, fx, fy in wanted:
                if max_usd > 0 and rig.spend() - start >= max_usd:
                    return rows
                before = rig.title(handle)
                t0 = now()
                got, err = None, ""
                try:
                    got = rig.ground(target_name(number))
                except Exception as e:      # a probe row, not a crash
                    err = f"{type(e).__name__}: {e}"[:160]
                if got is not None:
                    rig.click(*got)
                    rig.sleep(rig.settle_s)
                rows.append(score_row(
                    monitor=name, config=config, model=model, number=number,
                    expected=expected_point(mon, fx, fy), got=got,
                    title_before=before, title_after=rig.title(handle),
                    error=err, ms=round((now() - t0) * 1000)))
        finally:
            rig.close(handle)
    return rows


# ------------------------------------------------------------- spend file

def spend_total(path) -> float:
    """Sum of `usd` over a JSONL spend file; 0 when absent."""
    total = 0.0
    try:
        for line in pathlib.Path(path).read_text().splitlines():
            try:
                total += float(json.loads(line).get("usd") or 0)
            except (ValueError, TypeError, AttributeError):
                continue
    except OSError:
        return 0.0
    return total


def record_spend(path, usd: float, config: str, model: str) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": "click_probe", "usd": round(usd, 6),
           "config": config, "model": model}
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Measure model grounding error per monitor against "
                    "known button positions.")
    ap.add_argument("--live", action="store_true",
                    help="actually drive the desktop and call the "
                         "grounding model (default: print the plan)")
    ap.add_argument("--config", default="default", dest="config_label",
                    help="label for this configuration (hybrid, openrouter)")
    ap.add_argument("--ground-brain", default="",
                    help="[ground] vlm_brain override, e.g. "
                         "ollama:qwen2.5vl:3b-q8_0")
    ap.add_argument("--profile", default="",
                    help="TOML of section.key overrides applied to the "
                         "loaded config")
    ap.add_argument("--monitors", default="",
                    help="comma list of output names (default: all)")
    ap.add_argument("--targets", default="",
                    help="comma list of button numbers 1-9 (default: all)")
    ap.add_argument("--out", default="",
                    help="JSONL results file (appended)")
    ap.add_argument("--spend-file", default="",
                    help="JSONL spend file the run's cost is appended to")
    ap.add_argument("--max-usd", type=float, default=0.5,
                    help="stop before a target once this run spent this "
                         "much (0 = no per-run stop)")
    ap.add_argument("--cap-usd", type=float, default=10.0,
                    help="refuse to start when --spend-file already "
                         "totals this much")
    ap.add_argument("--session", choices=("live", "isolated"),
                    default="live",
                    help="live (default): the owner's desktop; isolated: "
                         "the headless Hyprland from "
                         "scripts/isolated_session.py")
    ap.add_argument("--isolated-env", default="",
                    help="the isolated session's env file (default: "
                         "$WISP_ISOLATED_ENV or the state dir's "
                         "isolated.env)")
    return ap


def _numbers(text: str):
    if not text.strip():
        return None
    try:
        nums = {int(t) for t in text.split(",") if t.strip()}
    except ValueError:
        raise ProbeError(f"--targets wants numbers, got {text!r}")
    bad = nums - {t[0] for t in TARGETS}
    if bad:
        raise ProbeError(f"--targets {sorted(bad)} are not buttons 1-9")
    return nums


def isolate_config(cfg: dict) -> dict:
    """The run copy for an isolated session (KTD6): the safety key on,
    no real-pointer delivery, and driving (not guiding) enabled."""
    out = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in (cfg or {}).items()}
    out.setdefault("dev", {})["isolated_session"] = "true"
    out.setdefault("cua", {})["delivery"] = "background"
    out.setdefault("pointer", {}).update({"mode": "drive",
                                          "backend": "auto"})
    return out


def apply_overrides(cfg: dict, ground_brain: str, profile: dict) -> dict:
    """A config copy with profile overrides and the grounding brain."""
    out = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in (cfg or {}).items()}
    for section, keys in (profile or {}).items():
        if isinstance(keys, dict):
            out.setdefault(section, {}).update(keys)
    if ground_brain:
        out.setdefault("ground", {})["vlm_brain"] = ground_brain
    return out


def _model_label(cfg: dict, ground_brain: str) -> str:
    if ground_brain:
        return ground_brain
    return str((cfg.get("brain", {}) or {}).get("default") or "default")


def live_rig(cfg: dict) -> Rig:                     # pragma: no cover
    """The real desktop rig: Hyprland for windows and the cursor, the
    wisp pointer for clicks, a throwaway browser profile for the page."""
    from wisp import grounding, hypr, ledger, platform, pointer, vpointer
    browser = next((b for b in ("chromium", "google-chrome-stable",
                                "brave", "chrome") if shutil.which(b)), None)
    if not browser:
        raise ProbeError("no chromium-family browser on PATH")
    if not hypr.available():
        raise ProbeError("Hyprland socket not reachable")
    ptr = pointer.registry(cfg)
    iso = vpointer.is_isolated(cfg)

    def open_page(mon):
        x, y, w, h = logical_rect(mon)
        if iso:
            # park the instance's own cursor on the target output so the
            # new window opens there (virtual pointer, never hyprctl)
            ptr.move(int(x + w / 2), int(y + h / 2))
        else:
            hypr.run_lua(hypr.cursor_move(int(x + w / 2), int(y + h / 2)))
        prof = tempfile.mkdtemp(prefix="wisp-click-probe-")
        env = {k: v for k, v in os.environ.items()
               if "KEY" not in k and "TOKEN" not in k}
        flags = [f"--user-data-dir={prof}", "--no-first-run",
                 "--no-default-browser-check", "--password-store=basic",
                 "--start-fullscreen",
                 f"--app={PAGE.as_uri()}"]
        if iso:
            # the process env already points at the instance (the
            # caller ran under isolated.applied_env); never an X display
            env.pop("DISPLAY", None)
            flags.append("--ozone-platform=wayland")
        argv = [browser, *flags]
        proc = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env)
        return {"proc": proc, "profile": prof}

    def client(_h):
        for c in hypr.query("clients"):
            if str(c.get("title", "")).startswith(("probe-", "hit:")):
                return c
        return None

    def window_rect(h):
        for _ in range(40):
            c = client(h)
            if c and c.get("size", [0, 0])[0]:
                return (c["at"][0], c["at"][1], c["size"][0], c["size"][1])
            time.sleep(0.25)
        return None

    def close(h):
        h["proc"].terminate()
        shutil.rmtree(h["profile"], ignore_errors=True)

    def ground(name):
        try:
            t = grounding.ground_target(name, cfg)
        except grounding.GroundRefused:
            return None
        return t.x, t.y

    return Rig(monitors=platform.monitors, open_page=open_page,
               window_rect=window_rect, ground=ground,
               click=lambda x, y: ptr.click(x, y).ok,
               title=lambda h: (client(h) or {}).get("title", ""),
               close=close,
               spend=lambda: float(ledger.totals().get("today_usd", 0)))


def _canary(iso: dict) -> tuple:
    return isolated.canary_for(iso)


def main(argv=None, rig_factory=live_rig, canary=_canary) -> int:
    args = build_parser().parse_args(argv)
    iso = None
    if args.session == "isolated":
        try:
            iso = isolated.load_env_file(isolated.env_file_path(
                args.isolated_env or None))
            isolated.check_target(iso)
        except isolated.SessionError as e:
            print(f"click_probe: {e}", file=sys.stderr)
            return EXIT_USAGE
        with isolated.applied_env(iso):
            return _main(args, rig_factory, canary, iso)
    return _main(args, rig_factory, canary, None)


def _main(args, rig_factory, canary, iso) -> int:
    try:
        nums = _numbers(args.targets)
        profile = {}
        if args.profile:
            import tomllib
            profile = tomllib.loads(pathlib.Path(args.profile).read_text())
        from wisp import config
        cfg = apply_overrides(config.load_config(), args.ground_brain,
                              profile)
        if iso:
            cfg = isolate_config(cfg)
        model = _model_label(cfg, args.ground_brain)
        names = [n for n in args.monitors.split(",") if n.strip()]
        if args.spend_file and spend_total(args.spend_file) >= args.cap_usd:
            raise ProbeError(
                f"spend file already at the ${args.cap_usd:.2f} cap")
        if not args.live:
            print(f"plan: session={args.session} "
                  f"config={args.config_label} model={model} "
                  f"monitors={names or 'all'} "
                  f"targets={sorted(nums) if nums else 'all 9'}; "
                  f"pass --live to run")
            return EXIT_OK
        if iso:
            ok, detail = canary(iso)
            if not ok:
                raise ProbeError("isolated input canary failed; no "
                                 f"target was run: {detail}")
        rig = rig_factory(cfg)
        if not names:
            names = [m["name"] for m in rig.monitors() if m.get("name")]
        spend0 = rig.spend()
        rows = run_probe(rig, names, config=args.config_label, model=model,
                         max_usd=args.max_usd, numbers=nums)
    except ProbeError as e:
        print(f"click_probe: {e}", file=sys.stderr)
        return EXIT_USAGE
    out = pathlib.Path(args.out or pathlib.Path(
        os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share"))
        / "wisp-click-probe" / "results.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    spent = max(0.0, rig.spend() - spend0)
    if args.spend_file:
        record_spend(args.spend_file, spent, args.config_label, model)
    print(json.dumps({"summary": summarize(rows), "spent_usd": round(spent, 6),
                      "rows": str(out)}, indent=2))
    return EXIT_OK if any(r["outcome"] == "hit" for r in rows) \
        else EXIT_NO_HITS


if __name__ == "__main__":
    sys.exit(main())
