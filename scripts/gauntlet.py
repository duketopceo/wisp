#!/usr/bin/env python3
"""The gauntlet driver (U6): one command that runs the case battery under
both arm profiles, safely, and puts the owner's setup back.

    orch python scripts/gauntlet.py --profiles hybrid,openrouter --cap 10

What it does (KTD7-KTD12):

  1. Refuses to start (exit 2) unless it runs under `orch` (the eval key
     is in the environment as OPENROUTER_API_KEY) and, for the hybrid
     arm, Ollama answers. Nothing is stopped before these checks pass.
  2. Borrows the one daemon slot: stops the owner's `wispd.service` user
     unit, starts a gauntlet `wispd` with a throwaway HOME, XDG data,
     config and state directories and a seeded minimal config, and
     restarts the owner's service on every exit path, crash included.
  3. Builds a sandbox per attempt (browser, file manager and terminal
     with throwaway profiles, a scrubbed environment and a restricted
     read-only shell) and registers the window addresses with the run.
  4. Interleaves the arms per case: run 1, check, a learn turn when the
     case is learnable, a fresh sandbox, run 2, check, compare. A case
     passes or fails on run 1's check alone. Cases are scored on a
     deterministic check where there is one, the judge otherwise.
  5. Writes a run directory (rows, evidence, screenshots, a markdown
     report ranking tuning-case failures and scoring held-out cases) and
     prints the `wispd dev review` and `wispd dev import-labels`
     commands. The judge never writes an owner label.

Spend is capped across invocations by a persistent spend file in the
gauntlet directory. Exit codes: 0 finished (a spend stop is a normal
finish), 1 the run broke, 2 usage or a precondition failed.

Everything that touches the system is injected (see `Deps`), so the
offline tests drive the whole flow with fakes. Live runs are U8.
"""
import argparse
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import importlib.util
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wisp import gauntlet as gmode  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "gauntlet_sandbox", HERE / "gauntlet" / "sandbox.py")
sandbox = importlib.util.module_from_spec(_spec)
sys.modules["gauntlet_sandbox"] = sandbox
_spec.loader.exec_module(sandbox)

DEFAULT_CASES = ROOT / "docs" / "dev-tasks" / "gauntlet.jsonl"
DEFAULT_DIR = pathlib.Path.home() / ".local" / "share" / "wisp-gauntlet"
SERVICE = "wispd.service"
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
CATEGORIES = ("browser", "files", "terminal", "windows", "menu")
APPS = sandbox.APPS + ("menu",)
CHECK_TYPES = ("judge", "title_regex", "file_exists", "url_host", "rsh_log",
               "window_workspace", "geometry_changed", "window_focused")
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
TASK_CHARS = 300                # a task line is cut at this many chars
# wait this long past a run's own time limit before calling it hung
_SLACK_S = 180
# per-attempt reserve for the judge call when checking the cap
JUDGE_RESERVE_USD = 0.02
_ATTEMPT_INDEX = {1: 0, "learn": 1, 2: 2}


class CaseError(ValueError):
    pass


# -- the case battery -------------------------------------------------------

def validate_case(c) -> list:
    """The problems with one case dict (empty when it is sound)."""
    if not isinstance(c, dict):
        return ["a case is a JSON object"]
    errs = []
    if not isinstance(c.get("id"), str) or not _ID.fullmatch(c["id"]):
        errs.append("id must be a lowercase slug")
    if c.get("category") not in CATEGORIES:
        errs.append(f"category must be one of {CATEGORIES}")
    if c.get("app") not in APPS:
        errs.append(f"app must be one of {APPS}")
    goal = c.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errs.append("goal is required")
    elif len(" ".join(goal.split())) > TASK_CHARS:
        errs.append(f"goal is over {TASK_CHARS} chars")
    for k in ("learnable", "held_out"):
        if not isinstance(c.get(k), bool):
            errs.append(f"{k} must be true or false")
    if not isinstance(c.get("minimal_steps"), int) \
            or isinstance(c.get("minimal_steps"), bool) \
            or c["minimal_steps"] < 1:
        errs.append("minimal_steps must be a whole number of at least 1")
    chk = c.get("check")
    if not isinstance(chk, dict) or chk.get("type") not in CHECK_TYPES:
        errs.append(f"check.type must be one of {CHECK_TYPES}")
    for k in ("setup",):
        if k in c and not isinstance(c[k], dict):
            errs.append(f"{k} must be an object")
    also = c.get("also", [])
    if not isinstance(also, list) or any(a not in sandbox.APPS
                                         for a in also):
        errs.append("also must list sandbox apps")
    if c.get("learnable") is True and (
            c.get("app") not in sandbox.APPS or not c.get("skill_seed")):
        errs.append("a learnable case needs a sandbox app and a skill_seed")
    return errs


def load_cases(path) -> list:
    """The cases of a JSONL file (`#` comment and blank lines skipped).
    Raises CaseError naming the line and the problem."""
    out, seen = [], set()
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise CaseError(f"cannot read {path}: {e.strerror}") from None
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            c = json.loads(line)
        except ValueError:
            raise CaseError(f"line {n}: not JSON") from None
        errs = validate_case(c)
        if not errs and c["id"] in seen:
            errs = [f"duplicate id {c['id']}"]
        if errs:
            raise CaseError(f"line {n}: " + "; ".join(errs))
        seen.add(c["id"])
        out.append(c)
    if not out:
        raise CaseError("no cases")
    return out


def case_apps(case) -> list:
    """The sandbox apps a case opens, primary app first."""
    if case["app"] not in sandbox.APPS:
        return []
    return [case["app"]] + [a for a in case.get("also", [])
                            if a != case["app"]]


def learn_goal(case, win_class="") -> str:
    """The learn turn's task line. It starts with `learn how to` so the
    router sends it to the learn route; the skill must declare the app
    window class, or run 2 cannot match it."""
    goal = " ".join(case["goal"].split())
    goal = goal[0].lower() + goal[1:] if goal else goal
    tail = (f" - save an app skill with app_classes: {win_class}"
            if win_class else " - save an app skill")
    if (case.get("check") or {}).get("type") == "url_host":
        tail += f", url_hosts: {case['check']['host']}"
    return ("learn how to " + goal)[:TASK_CHARS - len(tail)] + tail


# -- scoring ----------------------------------------------------------------

def skill_outcome(case, r1, r2, reused: bool) -> dict:
    """Did run 2 earn a skill win? Counted only when run 2 reuses the
    skill and improves on run 1 (success where run 1 failed, or fewer
    steps). A case whose run 1 already succeeded in its minimal step
    count has no headroom and is left out of the tally."""
    if not case.get("learnable") or r2 is None:
        return {"eligible": False, "win": False, "reason": "not learnable"
                if not case.get("learnable") else "no run 2"}
    if r1["success"] and r1["steps"] <= case["minimal_steps"]:
        return {"eligible": False, "win": False, "reason": "no headroom"}
    better = (not r1["success"] and r2["success"]) or \
        (r1["success"] and r2["success"] and r2["steps"] < r1["steps"])
    win = bool(reused and better)
    return {"eligible": True, "win": win,
            "reason": "won" if win else
            ("skill not reused" if not reused else "no improvement")}


def failure_class(a) -> str:
    """A short class for a failed attempt, used to rank failures."""
    row = a.get("row")
    if row is None:
        return "not run (spend stop or driver error)"
    if row.get("outcome") == "stopped":
        for s in row.get("steps") or []:
            if s.get("stopped"):
                m = re.sub(r"[^a-z ]+", "", str(
                    s.get("result") or "").lower()).strip()
                return "stopped: " + " ".join(m.split()[:6])
        return "stopped: " + " ".join(str(row.get("result") or "")
                                      .lower().split()[:4])
    if row.get("outcome") == "success":
        return "acted, but the check failed"
    res = str(row.get("result") or "")
    if res.startswith("budget"):
        return "budget stop"
    return "incomplete: " + " ".join(re.sub(
        r"\d+", "N", res.lower()).split()[:4])


# -- injectable system access -------------------------------------------------

class Deps:
    """Everything the driver does to the system, replaceable in tests."""

    def __init__(self, env=None, clock=time.monotonic, sleep=time.sleep):
        self.env = dict(os.environ if env is None else env)
        self.clock, self.sleep = clock, sleep

    def systemctl(self, *argv) -> int:
        try:
            r = subprocess.run(["systemctl", "--user", *argv],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return 124
        return r.returncode

    def ollama_up(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:11434/api/tags", timeout=3) as r:
                return r.status == 200
        except OSError:
            return False

    def spawn_daemon(self, env, log_path):
        log = open(log_path, "ab")
        return subprocess.Popen(
            [sys.executable, str(ROOT / "wispd"), "daemon"], env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)

    def send(self, cmd: dict) -> dict:
        from wisp import ipc
        return ipc.send(cmd, timeout=30)

    def alive(self) -> bool:
        from wisp import ipc
        return ipc.alive()

    def make_sandbox(self, root):
        return sandbox.Sandbox(root)

    def screenshot(self, path) -> bool:
        try:
            r = subprocess.run(["grim", str(path)], capture_output=True,
                               timeout=15)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


# -- the run ------------------------------------------------------------------

def seed_config() -> str:
    """A minimal config for the gauntlet daemon: wisp's own defaults,
    with the OpenRouter key taken from the environment only. None of
    the owner's settings are read."""
    from wisp import config
    text = config.DEFAULT_CONFIG
    return re.sub(r'(?m)^key_env = "keyring://wisp/openrouter,'
                  r'OPENROUTER_API_KEY"$',
                  'key_env = "OPENROUTER_API_KEY"', text)


def daemon_env(base: dict, gdir) -> dict:
    """The gauntlet daemon's environment: the owner's session variables
    the compositor needs, a throwaway HOME and XDG dirs, never the
    owner's own."""
    gdir = pathlib.Path(gdir)
    env = dict(base)
    home = gdir / "home"
    env.update({"HOME": str(home),
                "XDG_DATA_HOME": str(gdir / "data"),
                "XDG_CONFIG_HOME": str(gdir / "config"),
                "XDG_STATE_HOME": str(gdir / "state"),
                "XDG_CACHE_HOME": str(gdir / "cache")})
    return env


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


class Gauntlet:
    def __init__(self, cases, profiles, gdir, cap, deps, out=print,
                 only=None):
        self.cases = [c for c in cases if not only or c["id"] in only]
        self.profiles = profiles                      # [(label, ref, dict)]
        self.gdir = pathlib.Path(gdir)
        self.data = self.gdir / "data" / "wisp"
        self.cap, self.deps, self.out = cap, deps, out
        self.run_id = "gauntlet-" + _now_id()
        self.rundir = self.gdir / "runs" / self.run_id
        self.spend = gmode.Spend(self.gdir / "spend.jsonl", cap)
        self.attempts: list = []
        self.stopped = ""
        self.seeded: set = set()
        self.box = None

    # -- service slot ---------------------------------------------------------

    def run(self) -> int:
        d = self.deps
        was_active = d.systemctl("is-active", SERVICE) == 0
        # a stop that fails or times out may still have stopped the unit,
        # so the restore below runs whenever a stop was attempted
        started = was_active
        proc = None
        code = EXIT_OK
        try:
            if was_active and d.systemctl("stop", SERVICE) != 0:
                self.out(f"could not stop {SERVICE}; nothing was started")
                return EXIT_FAIL
            if d.alive():
                self.out("a wisp daemon still answers; refusing to share "
                         "its socket")
                return EXIT_FAIL
            self._prepare_dirs()
            proc = d.spawn_daemon(daemon_env(d.env, self.gdir),
                                  self.rundir / "daemon.log")
            self._wait_alive()
            self._snapshot_seed()
            d.send({"cmd": "dev", "op": "on"})
            self.box = d.make_sandbox(self.gdir / "sandbox")
            self._cases()
        except KeyboardInterrupt:
            self.stopped = "interrupted"
            code = EXIT_FAIL
        except Exception as e:                          # noqa: BLE001
            self.stopped = f"driver error: {type(e).__name__}: {e}"[:200]
            self.out(self.stopped)
            code = EXIT_FAIL
        finally:
            self._cleanup(proc)
            if started and was_active:
                d.systemctl("start", SERVICE)          # always restore
            try:
                self._report()
            except Exception as e:                      # noqa: BLE001
                self.out(f"report failed: {e}")
                code = EXIT_FAIL
        return code

    def _prepare_dirs(self) -> None:
        for sub in ("data", "config/wisp", "state", "cache", "home",
                    "sandbox"):
            (self.gdir / sub).mkdir(parents=True, exist_ok=True)
        for sub in ("evidence", "tasks"):
            (self.rundir / sub).mkdir(parents=True, exist_ok=True)
        cfg = self.gdir / "config" / "wisp" / "config.toml"
        cfg.write_text(seed_config(), encoding="utf-8")
        os.chmod(cfg, 0o600)

    def _wait_alive(self, timeout=30.0) -> None:
        end = self.deps.clock() + timeout
        while not self.deps.alive():
            if self.deps.clock() > end:
                raise RuntimeError("the gauntlet daemon did not start")
            self.deps.sleep(0.5)

    def _snapshot_seed(self) -> None:
        sk = self.data / "skills"
        self.seeded = {p.name for p in sk.iterdir()} if sk.is_dir() \
            else set()

    def _cleanup(self, proc) -> None:
        try:
            if self.box is not None:
                self.box.close()
        except Exception:                               # noqa: BLE001
            pass
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:                           # noqa: BLE001
                try:
                    proc.kill()
                except Exception:                       # noqa: BLE001
                    pass

    # -- cases ----------------------------------------------------------------

    def _case_need(self, case) -> float:
        n = 3 if case["learnable"] else 1
        stops = sum(gmode.task_stop_usd(p) for _l, _r, p in self.profiles)
        # each attempt is also judged; reserve for it so a cap stop falls
        # between cases, not inside one
        return (stops + JUDGE_RESERVE_USD * len(self.profiles)) * n

    def _cases(self) -> None:
        for ci, case in enumerate(self.cases):
            if not self.spend.can_afford([self._case_need(case)]):
                self.stopped = (
                    f"spend cap: ${self.spend.remaining():.2f} left of "
                    f"${self.cap:.2f}; case {case['id']} needs "
                    f"${self._case_need(case):.2f}")
                self.out(self.stopped)
                return
            for label, ref, prof in self.profiles:
                self._case_arm(ci, case, label, ref)
                if self.stopped:
                    return

    def _reset_learning(self) -> None:
        """Back to the seeded skills and no trajectories, so one arm's
        saved skill and past runs never help the other arm."""
        sk = self.data / "skills"
        if sk.is_dir():
            import shutil
            for p in sk.iterdir():
                if p.name not in self.seeded:
                    shutil.rmtree(p, ignore_errors=True)
        for f in ("trajectories.jsonl", "trajectories.jsonl.1"):
            (self.data / f).unlink(missing_ok=True)

    def _case_arm(self, ci, case, arm, ref) -> None:
        self._reset_learning()
        r1 = self._attempt(ci, case, arm, ref, 1, case["goal"])
        if not case["learnable"] or r1["row"] is None:
            return
        learn = self._attempt(ci, case, arm, ref, "learn",
                              learn_goal(case, r1.get("win_class", "")))
        r2 = self._attempt(ci, case, arm, ref, 2, case["goal"])
        r2["reused"] = bool(r2.get("skill_events"))
        r1["skill"] = skill_outcome(case, r1, r2, r2["reused"])
        r1["skills_saved"] = sorted(
            p.name for p in (self.data / "skills").iterdir()
            if p.name not in self.seeded) \
            if (self.data / "skills").is_dir() else []
        learn["skills_saved"] = r1["skills_saved"]

    def _attempt(self, ci, case, arm, ref, n, goal) -> dict:
        tag = f"{case['id']}-{arm}-{n}"
        a = {"case": case["id"], "arm": arm, "n": n, "goal": goal,
             "row": None, "passed": None, "success": False, "steps": 0,
             "evidence": None, "skill_events": [], "usd": 0.0}
        self.attempts.append(a)
        self.box.prepare(case.get("setup"))
        wins = []
        try:
            for app in case_apps(case):
                wins.append(self.box.start(app, case.get("setup")))
            if wins:
                a["win_class"] = wins[0].cls
            row = self._drive(tag, ref, goal, [w.address for w in wins])
            a["row"] = row
            a["capped"] = row is None and bool(self.stopped)
            if row is not None:
                self._score(a, case, row, tag)
        except sandbox.SandboxError as e:
            a["error"] = str(e)
        finally:
            self.box.close()
        if n != "learn" and a["row"] is not None:
            self._store_row(ci, case, arm, n, a["row"])
        return a

    def _drive(self, tag, ref, goal, windows):
        d = self.deps
        tasks = self.rundir / "tasks" / f"{tag}.txt"
        tasks.write_text(goal + "\n", encoding="utf-8")
        r = d.send({"cmd": "dev_run", "path": str(tasks),
                    "profiles": [ref], "windows": windows,
                    "spend_file": str(self.spend.path),
                    "cap_usd": self.cap})
        if not r.get("ok"):
            raise sandbox.SandboxError(
                f"dev_run refused: {r.get('error')}")
        run_id = r["run_id"]
        prof = next(p for _l, rf, p in self.profiles if rf == ref)
        secs = float(((prof.get("agents") or {}).get(
            "act_max_seconds") or 600)) + _SLACK_S
        end = d.clock() + secs
        while True:
            st = d.send({"cmd": "dev", "op": "status"}).get("run") or {}
            if st.get("run_id") == run_id and not st.get("running"):
                if st.get("cap_stop"):
                    self.stopped = st["cap_stop"]
                break
            if d.clock() > end:
                d.send({"cmd": "dev_stop"})
                raise sandbox.SandboxError("run did not finish in time")
            d.sleep(1.0)
        rows = self._rows(run_id)
        return rows[0] if rows else None

    def _rows(self, run_id) -> list:
        p = self.data / "dev_runs" / f"{run_id}.jsonl"
        try:
            return [json.loads(x) for x in
                    p.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, ValueError):
            return []

    def _score(self, a, case, row, tag) -> None:
        ok, detail = sandbox.evaluate(case["check"], self.box)
        a["passed"] = ok
        judged = (row.get("judge") or {}).get("outcome")
        a["success"] = bool(ok) if ok is not None else judged == "success"
        a["steps"] = len(row.get("steps") or [])
        c = row.get("cost") or {}
        a["usd"] = float(c.get("task_usd") or 0) + float(
            c.get("judge_usd") or 0)
        ev = self.rundir / "evidence" / f"{tag}.json"
        shot = self.rundir / "evidence" / f"{tag}.png"
        a["evidence"] = str(ev)
        ev.write_text(json.dumps({
            "case": case["id"], "arm": a["arm"], "attempt": a["n"],
            "check": case["check"], "passed": ok, "detail": detail,
            "judge": row.get("judge"), "outcome": row.get("outcome"),
            "result": row.get("result"), "steps": row.get("steps"),
            "turn": row.get("turn"),
            "screenshot": str(shot) if self.deps.screenshot(shot) else None,
        }, indent=1, default=str), encoding="utf-8")
        a["skill_events"] = self._skill_events(row.get("turn"))

    def _skill_events(self, turn) -> list:
        out = []
        p = self.data / "trace.jsonl"
        if not turn:
            return out
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("turn") == turn and e.get("step") == "app_skill":
                    out.append(e.get("data") or {})
        except OSError:
            pass
        return out

    def _store_row(self, ci, case, arm, n, row) -> None:
        """One merged run store for the whole gauntlet, so a single
        `wispd dev review` covers every judged attempt. Both arms of an
        attempt share an index, so the report pairs them."""
        merged = dict(row, run_id=self.run_id,
                      index=ci * 3 + _ATTEMPT_INDEX[n], arm=arm,
                      profile=arm, case=case["id"], attempt=n,
                      goal=row.get("goal") or case["goal"])
        path = self.data / "dev_runs" / f"{self.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(merged, separators=(",", ":")) + "\n")

    # -- the report -------------------------------------------------------------

    def partial_cases(self) -> list:
        """Cases run 1 reached for some arms but not all (a cap stop that
        tripped inside a case). They are left out of every arm's score so
        the arms are compared on the same cases."""
        arms = {p[0] for p in self.profiles}
        seen: dict = {}
        for a in self.attempts:
            if a["n"] == 1 and not a.get("capped"):
                seen.setdefault(a["case"], set()).add(a["arm"])
        return sorted(c for c, got in seen.items() if got != arms)

    def summary(self) -> dict:
        """Per-arm scores over the cases every arm's run 1 reached."""
        cases = {c["id"]: c for c in self.cases}
        partial = set(self.partial_cases())
        out = {}
        for label, _ref, _p in self.profiles:
            mine = [a for a in self.attempts if a["arm"] == label
                    and a["n"] == 1 and not a.get("capped")
                    and a["case"] not in partial]
            tally = {"tuning": [0, 0], "held_out": [0, 0],
                     "skill_wins": 0, "skill_eligible": 0,
                     "skill_excluded": 0, "usd": 0.0}
            for a in self.attempts:
                if a["arm"] == label:
                    tally["usd"] += a["usd"]
            for a in mine:
                key = "held_out" if cases[a["case"]]["held_out"] \
                    else "tuning"
                tally[key][1] += 1
                tally[key][0] += bool(a["success"])
                sk = a.get("skill")
                if sk:
                    tally["skill_eligible"] += sk["eligible"]
                    tally["skill_wins"] += sk["win"]
                    tally["skill_excluded"] += (
                        not sk["eligible"] and sk["reason"] == "no headroom")
            out[label] = tally
        return out

    def ranked_failures(self) -> list:
        """Tuning-case failures (run 1 only), most common class first.
        Held-out cases never feed this list (KTD9)."""
        held = {c["id"] for c in self.cases if c["held_out"]}
        groups: dict = {}
        for a in self.attempts:
            if a["n"] == 1 and not a["success"] and a["case"] not in held:
                groups.setdefault(failure_class(a), []).append(a)
        return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def env_cmd(self) -> str:
        return (f"XDG_DATA_HOME={self.gdir / 'data'} "
                f"XDG_CONFIG_HOME={self.gdir / 'config'}")

    def review_commands(self) -> list:
        return [f"{self.env_cmd()} wispd dev review {self.run_id}",
                f"wispd dev import-labels {self.data}"]

    def _report(self) -> None:
        self.rundir.mkdir(parents=True, exist_ok=True)
        with open(self.rundir / "rows.jsonl", "w", encoding="utf-8") as f:
            for a in self.attempts:
                f.write(json.dumps({k: v for k, v in a.items()
                                    if k != "row"} | {"row": a["row"]},
                                   default=str) + "\n")
        text = self.render()
        (self.rundir / "report.md").write_text(text, encoding="utf-8")
        self.out(text)

    def render(self) -> str:
        sm = self.summary()
        ran = len({a["case"] for a in self.attempts if a["n"] == 1})
        L = [f"# Gauntlet {self.run_id}", "",
             f"- arms: {', '.join(p[0] for p in self.profiles)}",
             f"- cases run: {ran} of {len(self.cases)}",
             f"- spend: ${sum(t['usd'] for t in sm.values()):.4f} this run,"
             f" ${self.spend.total():.4f} of ${self.cap:.2f} cumulative"]
        if self.stopped:
            L.append(f"- stopped: {self.stopped}")
        partial = self.partial_cases()
        if partial:
            L.append(f"- not scored (not every arm ran it): "
                     f"{', '.join(partial)}")
        L += ["", "## Scores", "",
              "| arm | tuning | held-out | skill wins | spend | by provider |",
              "|---|---|---|---|---|---|"]
        by = self._by_provider()
        for label, t in sm.items():
            def frac(x):
                return f"{x[0]}/{x[1]}" + (f" ({round(100 * x[0] / x[1])}%)"
                                           if x[1] else "")
            prov = ", ".join(f"{k} ${v:.4f}" for k, v in
                             sorted(by.get(label, {}).items())) or "-"
            L.append(f"| {label} | {frac(t['tuning'])} | "
                     f"{frac(t['held_out'])} | {t['skill_wins']} of "
                     f"{t['skill_eligible']} (no headroom "
                     f"{t['skill_excluded']}) | ${t['usd']:.4f} | {prov} |")
        L += ["", "## Ranked failures (tuning cases)", ""]
        ranked = self.ranked_failures()
        if not ranked:
            L.append("none")
        for i, (cls, items) in enumerate(ranked, 1):
            L.append(f"{i}. **{cls}** ({len(items)})")
            for a in items:
                L.append(f"   - {a['case']} [{a['arm']}] "
                         f"{a.get('evidence') or a.get('error') or ''}")
        L += ["", "## Held-out cases", ""]
        held = [a for a in self.attempts if a["n"] == 1
                and any(c["id"] == a["case"] and c["held_out"]
                        for c in self.cases)]
        for a in held:
            L.append(f"- {a['case']} [{a['arm']}]: "
                     f"{'pass' if a['success'] else 'fail'} "
                     f"{a.get('evidence') or ''}")
        if not held:
            L.append("none run")
        L += ["", "## Skills", ""]
        any_skill = False
        for a in self.attempts:
            if a.get("skill"):
                any_skill = True
                sk = a["skill"]
                L.append(f"- {a['case']} [{a['arm']}]: {sk['reason']}; "
                         f"saved {a.get('skills_saved') or 'nothing'}")
        if not any_skill:
            L.append("none")
        L += ["", "## Next", "",
              "Label gauntlet turns yourself, then import them:", ""]
        L += [f"    {c}" for c in self.review_commands()]
        return "\n".join(L) + "\n"

    def _by_provider(self) -> dict:
        out: dict = {}
        for a in self.attempts:
            c = (a.get("row") or {}).get("cost") or {}
            for prov, usd in (c.get("by_provider") or {}).items():
                d = out.setdefault(a["arm"], {})
                d[prov] = d.get(prov, 0.0) + float(usd)
        return out


# -- entry point --------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="gauntlet.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profiles", default="hybrid,openrouter",
                   help="comma list of arm profiles (default both)")
    p.add_argument("--cap", type=float, default=gmode.DEFAULT_CAP_USD,
                   help="cumulative spend cap in USD (default 10)")
    p.add_argument("--cases", default=str(DEFAULT_CASES),
                   help="the case battery (JSONL)")
    p.add_argument("--dir", default=str(DEFAULT_DIR),
                   help="gauntlet directory (data, config, runs, spend)")
    p.add_argument("--only", default="", help="comma list of case ids")
    p.add_argument("--dry-run", action="store_true",
                   help="validate and list the plan; start nothing")
    return p


def main(argv=None, deps=None, out=print) -> int:
    args = build_parser().parse_args(argv)
    deps = deps or Deps()
    try:
        cases = load_cases(args.cases)
    except CaseError as e:
        out(f"cases: {e}")
        return EXIT_USAGE
    profiles = []
    for ref in [r.strip() for r in args.profiles.split(",") if r.strip()]:
        try:
            label, prof = gmode.load_profile(ref)
        except ValueError as e:
            out(f"profiles: {e}")
            return EXIT_USAGE
        profiles.append((label, ref, prof))
    if not profiles or len({p[0] for p in profiles}) != len(profiles):
        out("profiles: name at least one, each once")
        return EXIT_USAGE
    only = {x for x in args.only.split(",") if x}
    if only and only - {c["id"] for c in cases}:
        out(f"unknown case ids: {sorted(only - {c['id'] for c in cases})}")
        return EXIT_USAGE
    if args.cap <= 0:
        out("cap must be above 0")
        return EXIT_USAGE
    if args.dry_run:
        for c in cases:
            if not only or c["id"] in only:
                out(f"{c['id']:<28} {c['category']:<9} "
                    f"{'held-out' if c['held_out'] else 'tuning':<8} "
                    f"{'learnable' if c['learnable'] else '':<9} "
                    f"x{len(profiles)} arms")
        return EXIT_OK
    # preconditions come before anything is stopped
    if not deps.env.get("OPENROUTER_API_KEY"):
        out("run under orch: OPENROUTER_API_KEY (the eval key) is not set")
        return EXIT_USAGE
    if any("ollama:" in str((p[2].get("ground") or {}).get("vlm_brain", ""))
           for p in profiles) and not deps.ollama_up():
        out("Ollama does not answer on 127.0.0.1:11434 (the hybrid arm "
            "needs it)")
        return EXIT_USAGE

    def _term(signum, frame):
        raise KeyboardInterrupt
    old = signal.signal(signal.SIGTERM, _term)
    try:
        g = Gauntlet(cases, profiles, args.dir, args.cap, deps, out, only)
        return g.run()
    finally:
        signal.signal(signal.SIGTERM, old)


if __name__ == "__main__":
    sys.exit(main())
