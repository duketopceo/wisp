"""First-run onboarding (W28): `wispd onboard` and the Panel first-run card.

Five steps, in order: mic, models, cua (optional), notifications and
keybinding (optional). Each is a read-only check plus, at most, one
explicit side effect:

  - models only probes the local ladder over loopback HTTP; it never
    starts or stops a service (`wispd health start` stays a manual act),
  - notifications sends one test notification, and only when the caller
    passes confirm=True,
  - keybinding needs the W24 submap and is "na" while that is absent.

Every step is skippable and reversible. A skip is not recorded and writes
nothing (the step is offered again next run). Only a step that passed is
recorded, in ~/.local/share/wisp/onboard.json, so a half finished run
resumes where it stopped. Undo removes the record. Config is never edited.

All probes are injected through `Probes`, so the tests run with fakes and
never touch the network, services or notifications.
"""
import dataclasses
import datetime
import json
import os
import pathlib
import shutil
import urllib.error
import urllib.parse
import urllib.request

from . import config

# local model ladder, probed over loopback only: (name, url)
LADDER = (
    ("ornith", "http://127.0.0.1:8080/v1/models"),
    ("jev", "http://127.0.0.1:8091/v1/models"),
    ("jev-shim", "http://127.0.0.1:8931/"),
    ("uitars", "http://127.0.0.1:8081/v1/models"),
    ("ollama", "http://127.0.0.1:11434/api/tags"),
)
# a brain needs one of these; jev and uitars alone cannot answer
_BRAINS = ("ornith", "ollama")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


@dataclasses.dataclass(frozen=True)
class Step:
    id: str
    title: str
    optional: bool = False
    confirm: bool = False      # has a side effect that needs an explicit ok


STEPS = (
    Step("mic", "microphone"),
    Step("models", "local models"),
    Step("cua", "cua pointer driver", optional=True),
    Step("notifications", "notifications", confirm=True),
    Step("keybinding", "keybinding", optional=True),
)
_BY_ID = {s.id: s for s in STEPS}


# -- probes ---------------------------------------------------------------

def http_up(url: str, timeout: float = 0.5) -> bool:
    """True when a loopback server answered at all (any status below 500).
    Anything that is not loopback is refused without a request."""
    if (urllib.parse.urlparse(url).hostname or "") not in _LOOPBACK:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        e.close()
        return e.code < 500
    except Exception:
        return False


def _whisper_ok(cfg: dict) -> bool:
    if cfg.get("stt", {}).get("provider", "local") != "local":
        return True
    return config.whisper_model(cfg).exists()


def _cua(cfg: dict) -> dict:
    from . import probes_cua
    return probes_cua.CuaProbe(cfg).check(version=False)


def _notify_cmd():
    from . import platform
    cmd = platform.notify_cmd("Wisp", "test")
    return cmd if cmd and shutil.which(cmd[0]) else None


def _notify_send(cfg: dict) -> str:
    import time
    from . import notify
    r = notify.send("This is a test notification from wispd.", "info",
                    cfg=cfg, key=f"onboard-test:{time.time()}")
    getattr(notify._default, "join", lambda *a: None)()
    return "sent" if r in ("sent", True) else str(r)


def _submap() -> bool:
    """True when the W24 keyboard submap module is on this branch."""
    import importlib
    import importlib.util
    try:
        if importlib.util.find_spec("wisp.keys") is None:
            return False
        keys = importlib.import_module("wisp.keys")
    except Exception:
        return False
    reg = getattr(keys, "registered", None)
    try:
        return bool(reg()) if callable(reg) else True
    except Exception:
        return False


@dataclasses.dataclass
class Probes:
    which: object = shutil.which
    whisper_ok: object = _whisper_ok
    fetch: object = http_up
    cua: object = _cua
    notify_ready: object = lambda: _notify_cmd() is not None
    notify_send: object = _notify_send
    submap: object = _submap


# -- progress -------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class Progress:
    """The persisted record: {"done": {step: iso time}, "finished": iso}.
    Read fresh on every access, written atomically, never created by a
    read."""

    def __init__(self, path=None):
        self._path = pathlib.Path(path) if path else None

    @property
    def path(self) -> pathlib.Path:
        return self._path or (config.DATA_DIR / "onboard.json")

    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            if not isinstance(d, dict):
                raise ValueError
        except (OSError, ValueError):
            d = {}
        if not isinstance(d.get("done"), dict):
            d["done"] = {}
        return d

    def _write(self, d: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, **d}, indent=1) + "\n")
        os.replace(tmp, self.path)

    @property
    def done(self) -> dict:
        return self._read()["done"]

    @property
    def finished(self) -> bool:
        return bool(self._read().get("finished"))

    def mark(self, step: str):
        d = self._read()
        d["done"][step] = _now()
        self._write(d)

    def unmark(self, step: str) -> bool:
        d = self._read()
        if step not in d["done"]:
            return False
        del d["done"][step]
        d["finished"] = None
        self._write(d)
        return True

    def finish(self):
        d = self._read()
        d["finished"] = _now()
        self._write(d)

    def reset(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# -- checks ---------------------------------------------------------------

def _res(step, state, detail, fix=""):
    return {"id": step, "name": _BY_ID[step].title, "state": state,
            "ok": state == "ok", "detail": detail, "fix": fix}


def _check_mic(cfg, p):
    rec = next((b for b in ("pw-record", "parecord", "arecord")
                if p.which(b)), None)
    if not rec:
        return _res("mic", "todo", "no recorder found",
                    "omarchy pkg add pipewire")
    if not p.whisper_ok(cfg):
        return _res("mic", "todo", f"{rec} found, speech model missing",
                    "scripts/fetch_whisper.sh")
    return _res("mic", "ok", f"{rec} and the speech model are ready")


def _check_models(cfg, p):
    up = {name: bool(p.fetch(url)) for name, url in LADDER}
    detail = ", ".join(f"{n} {'up' if up[n] else 'down'}" for n, _ in LADDER)
    if any(up[b] for b in _BRAINS):
        return _res("models", "ok", detail)
    return _res("models", "todo", detail, "wispd health start")


def _check_cua(cfg, p):
    r = p.cua(cfg) or {}
    state = r.get("state", "absent")
    if state == "absent":
        return _res("cua", "na", "cua-driver is not installed (optional)")
    if r.get("ok"):
        return _res("cua", "ok", f"cua-driver {state.replace('_', ' ')}")
    return _res("cua", "todo", f"cua-driver {state.replace('_', ' ')}",
                r.get("fix") or "wispd cua status")


def _check_notifications(cfg, p):
    if not p.notify_ready():
        return _res("notifications", "todo", "no notifier found",
                    "omarchy pkg add libnotify")
    return _res("notifications", "todo",
                "ready; a test send needs your ok",
                "wispd onboard --step notifications --yes")


def _check_keybinding(cfg, p):
    if not p.submap():
        return _res("keybinding", "na",
                    "needs the keyboard submap (not installed yet)")
    return _res("keybinding", "ok", "keyboard submap is registered")


_CHECKS = {"mic": _check_mic, "models": _check_models, "cua": _check_cua,
           "notifications": _check_notifications,
           "keybinding": _check_keybinding}


def check(step: str, cfg: dict, probes: Probes) -> dict:
    """Read-only live check: {id, name, state ok|todo|na, ok, detail,
    fix}. Raises KeyError for an unknown step. Never raises otherwise."""
    if step not in _BY_ID:
        raise KeyError(step)
    try:
        return _CHECKS[step](cfg, probes)
    except Exception as e:
        return _res(step, "todo", f"check failed: {type(e).__name__}",
                    "wispd doctor")


def run_step(step: str, cfg: dict, probes: Probes, progress: Progress,
             confirm: bool = False) -> dict:
    """Run one step and record it when it passed. A step with a side
    effect (notifications) only acts when confirm is True. -> the check
    result plus `done` (recorded)."""
    s = _BY_ID[step]
    r = check(step, cfg, probes)
    r["done"] = False
    if s.confirm:
        # the check is "todo, ready" until the test send goes out
        if r["state"] == "na" or not probes.notify_ready() or not confirm:
            return r
        try:
            got = probes.notify_send(cfg)
        except Exception as e:
            got = type(e).__name__
        if got != "sent":
            r.update(state="todo", ok=False,
                     detail=f"the test send did not go out ({got})",
                     fix="wispd notify test")
            return r
        r.update(state="ok", ok=True, detail="test notification sent",
                 fix="")
    if r["state"] == "ok":
        progress.mark(step)
        r["done"] = True
        if _required_done(progress.done):
            progress.finish()
    return r


def undo(step: str, progress: Progress) -> dict:
    """Forget one recorded step. Nothing else was changed by it, so this
    is the whole reversal. Raises KeyError for an unknown step."""
    if step not in _BY_ID:
        raise KeyError(step)
    return {"id": step, "undone": progress.unmark(step)}


def _required_done(done: dict) -> bool:
    return all(s.id in done for s in STEPS if not s.optional)


def status(cfg: dict, probes: Probes, progress: Progress) -> dict:
    """Read-only checklist for the CLI and the Panel card. state is
    done (recorded), todo or na."""
    done = progress.done
    steps = []
    for s in STEPS:
        r = check(s.id, cfg, probes)
        is_done = s.id in done
        state = "done" if is_done else ("na" if r["state"] == "na" else "todo")
        steps.append({"id": s.id, "name": s.title, "optional": s.optional,
                      "state": state, "ok": r["ok"] or is_done,
                      "done": is_done, "detail": r["detail"],
                      "try": "" if (r["ok"] or is_done) else r["fix"]})
    live = [x for x in steps if x["state"] != "na"]
    return {"finished": progress.finished,
            "ready": all(x["ok"] for x, s in zip(steps, STEPS)
                         if not s.optional),
            "done_count": sum(1 for x in live if x["done"]),
            "total": len(live), "steps": steps}


# -- the interactive walk -------------------------------------------------

def walk(cfg: dict, probes: Probes, progress: Progress, ask, out) -> dict:
    """Offer each unfinished step in turn. `ask(prompt)` returns the
    answer (EOFError quits); `out(line)` prints. y runs the step, s or n
    skips it (nothing written), q stops. -> {done, skipped, failed, na,
    resumed, quit, finished}."""
    done0 = dict(progress.done)
    res = {"done": [], "skipped": [], "failed": [], "na": [],
           "resumed": [s.id for s in STEPS if s.id in done0],
           "quit": False, "finished": False}
    for s in STEPS:
        if s.id in done0:
            continue
        r = check(s.id, cfg, probes)
        if r["state"] == "na":
            out(f"{s.title}: {r['detail']}")
            res["na"].append(s.id)
            continue
        out(f"{s.title}: {r['detail']}")
        if s.confirm:
            prompt = f"Send a test {s.title[:-1]} now? [y/N/s/q] "
        else:
            prompt = f"Check {s.title} now? [Y/s/q] "
        try:
            ans = ask(prompt).strip().lower()
        except EOFError:
            res["quit"] = True
            break
        if ans in ("q", "quit"):
            res["quit"] = True
            break
        yes = ans in ("y", "yes") or (ans == "" and not s.confirm)
        if not yes:
            res["skipped"].append(s.id)
            continue
        got = run_step(s.id, cfg, probes, progress, confirm=True)
        if got["done"]:
            out(f"  ok: {got['detail']}")
            out(f"  undo with: wispd onboard --undo {s.id}")
        else:
            res["failed"].append(s.id)
            out(f"  not yet: {got['detail']}")
            if got["fix"]:
                out(f"  Try: {got['fix']}")
    now_done = progress.done
    res["done"] = [s.id for s in STEPS if s.id in now_done]
    if _required_done(now_done) and not progress.finished:
        progress.finish()
    res["finished"] = progress.finished
    return res
