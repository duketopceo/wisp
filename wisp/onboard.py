"""First-run onboarding (W28): `wispd onboard` and the Panel first-run card.

Seven steps, in order: mic, models, keys, agents (optional), cua
(optional), notifications and keybinding (optional). Each is a read-only check plus, at most, one
explicit side effect:

  - models only probes the local ladder over loopback HTTP, and only
    when [local] enabled = "true"; it never starts or stops a service
    (`wispd health start` stays a manual act),
  - keys stores a key only when the walk is given one to store (never
    printed), at the omaseal ref in the key's lookup list or in
    ~/.config/wisp/.env,
  - agents downloads the pinned ori and OpenCode (checksummed, user scope,
    no sudo), signs ori in to OpenRouter and writes the private agent
    config, only when the walk runs it; it never re-signs an
    authenticated ori,
  - notifications sends one test notification, and only when the caller
    passes confirm=True,
  - keybinding needs the W24 submap and is "na" while that is absent.

Every step is skippable and reversible. A skip is not recorded and writes
nothing (the step is offered again next run). Only a step that passed is
recorded, in ~/.local/share/wisp/onboard.json, so a half finished run
resumes where it stopped. Undo removes the record. config.toml is never edited.

All probes are injected through `Probes`, so the tests run with fakes and
never touch the network, services or notifications.
"""
import dataclasses
import datetime
import getpass
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
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
    Step("models", "models"),
    Step("keys", "API keys"),
    Step("agents", "background agents", optional=True),
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
    if config.stt_settings(cfg)["provider"] != "local":
        return True
    return config.whisper_model(cfg).exists()


def _store_key(key_env: str, value: str) -> str:
    """Store a key where config.load_env_key will find it and say where:
    the desktop keyring for a keyring:// ref when secret-tool stores it,
    the omaseal ref when there is one and omaseal is on PATH, else
    ~/.config/wisp/.env (0600). The value only ever travels on the
    store tool's stdin or into the 0600 file. Raises ValueError for a value
    that cannot be stored safely, OSError/RuntimeError when the store
    itself failed."""
    if not value or any(c.isspace() for c in value):
        raise ValueError("a key cannot be empty or contain whitespace")
    cands = [c.strip() for c in key_env.split(",") if c.strip()]
    kr = next((c[len("keyring://"):].split("/", 1) for c in cands
               if c.startswith("keyring://")), None)
    tool = shutil.which("secret-tool")
    if kr and len(kr) == 2 and tool:
        try:
            r = subprocess.run(
                [tool, "store", "--label", f"Wisp {kr[1]}",
                 "service", kr[0], "account", kr[1]],
                input=value, capture_output=True, text=True,
                timeout=config.OMASEAL_TIMEOUT_S)
            if r.returncode == 0:
                return "desktop keyring"
        except (OSError, subprocess.SubprocessError):
            pass  # no Secret Service answering: the 0600 file below
    ref = next((c[len("omaseal://"):].split("/", 1) for c in cands
                if c.startswith("omaseal://")), None)
    exe = shutil.which("omaseal")
    if ref and len(ref) == 2 and exe:
        r = subprocess.run([exe, "set", ref[0], ref[1]], input=value,
                           capture_output=True, text=True,
                           timeout=config.OMASEAL_TIMEOUT_S)
        if r.returncode != 0:
            raise RuntimeError("omaseal could not store the key")
        return f"omaseal {ref[0]}/{ref[1]}"
    name = config.key_label(key_env)
    if name.startswith("omaseal://"):
        raise ValueError("omaseal is not installed and the key has no "
                         "environment variable name to store under")
    path = config.ENV_FILE
    try:
        lines = [ln for ln in path.read_text().splitlines()
                 if not ln.startswith(f"{name}=")]
    except FileNotFoundError:
        lines = []
    lines.append(f"{name}={value}")
    from . import note  # its atomic writer is 0600, the mode a secret needs
    note._atomic_write_text(path, "\n".join(lines) + "\n")
    return str(path)


# the browser sign-in waits this long for ori's localhost callback
LOGIN_WAIT_S = 300
_URL = re.compile(r"https?://\S+")


def _agents(cfg: dict) -> dict:
    from . import probes_agents
    return probes_agents.AgentsProbe().check()


def _agent_install(tool: str):
    from . import agent_install
    return agent_install.install(tool)


def _ori_login_key(ori, key: str) -> tuple:
    """`ori login --with-key` with the key on stdin only (argv and the
    returned detail never carry it). -> (ok, detail)."""
    try:
        r = subprocess.run([str(ori), "login", "--with-key"],
                           input=key + "\n", capture_output=True, text=True,
                           timeout=30,
                           env=dict(os.environ, ORI_NO_UPDATE_CHECK="1"))
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"ori login did not run ({type(e).__name__})"
    if r.returncode != 0:
        return False, f"ori login exited {r.returncode}"
    return True, "signed in with your OpenRouter key"


def _open_url(url: str) -> None:
    from . import mcpauth
    mcpauth._open_auth_url(url)


def _ori_login_browser(ori, opener=_open_url,
                       timeout_s: float = LOGIN_WAIT_S) -> tuple:
    """`ori login --no-browser`: open the URL it prints, then wait for its
    localhost callback. -> (ok, detail)."""
    try:
        proc = subprocess.Popen(
            [str(ori), "login", "--no-browser"], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            env=dict(os.environ, ORI_NO_UPDATE_CHECK="1"))
    except OSError as e:
        return False, f"ori login did not run ({type(e).__name__})"

    def pump():
        opened = False
        for line in proc.stdout:
            m = None if opened else _URL.search(line)
            if m:
                opened = True
                try:
                    opener(m.group(0))
                except Exception:
                    pass

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        rc = proc.wait(timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False, "sign-in did not finish in time"
    finally:
        t.join(2)
        proc.stdout.close()
    if rc != 0:
        return False, f"ori login exited {rc}"
    return True, "signed in through the browser"


def _acp_smoke(cfg: dict) -> tuple:
    """Launch `ori opencode acp` as Wisp will and run `initialize` only
    (no session, no prompt, no model call). -> (ok, detail)."""
    from . import acp, agent_ochome
    argv, env = agent_ochome.launch(cfg, os.environ)
    conn = None
    try:
        conn = acp.AcpConnection(argv, env, cwd=str(pathlib.Path.home()))
        conn.initialize()
        return True, "the agent runtime answered"
    except (acp.AcpError, OSError) as e:
        return False, f"the agent runtime did not answer ({e})"
    finally:
        if conn is not None:
            conn.close()


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
    key: object = config.load_env_key
    store_key: object = _store_key
    secret: object = getpass.getpass
    agents: object = _agents
    agent_install: object = _agent_install
    ori_login_key: object = _ori_login_key
    ori_login_browser: object = _ori_login_browser
    acp_smoke: object = _acp_smoke


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

    @property
    def tour(self) -> dict:
        t = self._read().get("tour")
        return t if isinstance(t, dict) else {}

    def tour_mark(self, step: str):
        d = self._read()
        t = d.get("tour") if isinstance(d.get("tour"), dict) else {}
        t[step] = _now()
        d["tour"] = t
        self._write(d)

    @property
    def starter_done(self) -> bool:
        return bool(self._read().get("starter"))

    def starter_mark(self):
        d = self._read()
        d["starter"] = _now()
        self._write(d)

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
    if not config.local_enabled(cfg):
        brain = cfg.get("brain", {}).get("default")
        return _res("models", "ok", "local models off"
                    + (f"; brain is {brain}" if brain else ""))
    up = {name: bool(p.fetch(url)) for name, url in LADDER}
    detail = ", ".join(f"{n} {'up' if up[n] else 'down'}" for n, _ in LADDER)
    if any(up[b] for b in _BRAINS):
        return _res("models", "ok", detail)
    return _res("models", "todo", detail, "wispd health start")


def required_keys(cfg: dict) -> list:
    """[(role, key_env)] the hosted setup needs: the brain's key when its
    provider declares one, and the speech key when STT is hosted."""
    from . import brain
    out = []
    env = brain.provider(cfg).get("key_env") or ""
    if env:
        out.append(("brain", env))
    stt = config.stt_settings(cfg)
    if stt["provider"] == "openai" and stt.get("key_env") \
            and stt["key_env"] not in [e for _r, e in out]:
        out.append(("speech", stt["key_env"]))
    return out


def _missing_keys(cfg, p) -> list:
    return [(role, env) for role, env in required_keys(cfg)
            if not p.key(env)]


def _check_keys(cfg, p):
    need = required_keys(cfg)
    if not need:
        return _res("keys", "ok", "no API keys needed")
    miss = _missing_keys(cfg, p)
    if not miss:
        return _res("keys", "ok", "all API keys found")
    return _res("keys", "todo", "missing " + ", ".join(
        f"{config.key_label(e)} ({r})" for r, e in miss),
        "wispd onboard")


# memory reads reach OpenRouter-routed models (KTD11): said wherever the
# step is described, because this is where the user opts in
_AGENT_NOTE = ("agents can read your Wisp memory; those reads go to "
               "OpenRouter-routed models")
_AGENT_WORDS = {
    "absent": "not installed",
    "opencode_v1": "OpenCode 1.x found; Wisp only drives its own pinned "
                   "OpenCode 2.x",
    "wrong_version": "installed versions differ from the pin",
    "not_signed_in": "installed, not signed in to OpenRouter",
}


def _check_agents(cfg, p):
    r = p.agents(cfg) or {}
    state = r.get("state", "absent")
    if state == "ready":
        return _res("agents", "ok", f"ready; {_AGENT_NOTE}")
    return _res("agents", "todo",
                f"{_AGENT_WORDS.get(state, state.replace('_', ' '))}; "
                f"{_AGENT_NOTE}",
                r.get("fix") or "wispd install --agents")


def _openrouter_key_env(cfg: dict) -> str:
    from . import brain
    return brain.provider({**cfg, "brain": {"default": "openrouter"}}
                          )["key_env"]


def _run_agents(cfg, p, r) -> dict:
    """The agents step's side effects, each stage reporting its own
    detail: install both pinned tools, sign ori in only when it is not
    already, smoke-test the launch, then write the private config. A
    failing stage returns todo and nothing after it runs."""
    from . import agent_ochome, agent_pins

    def todo(detail):
        r.update(state="todo", ok=False, detail=detail)
        return r

    if r["state"] == "ok":
        return r
    state = (p.agents(cfg) or {}).get("state", "absent")
    if state in ("absent", "opencode_v1", "wrong_version"):
        for tool in ("ori", "opencode"):
            got = p.agent_install(tool)
            if got.status == "failed":
                return todo(got.reason)
        state = (p.agents(cfg) or {}).get("state", "absent")
    if state == "not_signed_in":
        ori = agent_pins.runtime_paths()["ori"]
        key = p.key(_openrouter_key_env(cfg))
        ok, detail = p.ori_login_key(ori, key) if key \
            else p.ori_login_browser(ori)
        if not ok:
            return todo(detail)
        state = (p.agents(cfg) or {}).get("state", "absent")
    if state != "ready":
        return todo(f"agent runtime is {state.replace('_', ' ')}")
    ok, detail = p.acp_smoke(cfg)
    if not ok:
        return todo(detail)
    agent_ochome.write_config(cfg)
    r.update(state="ok", ok=True, detail=f"ready; {_AGENT_NOTE}", fix="")
    return r


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


_CHECKS = {"mic": _check_mic, "models": _check_models,
           "keys": _check_keys, "agents": _check_agents,
           "cua": _check_cua,
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
    if step == "agents" and r["state"] == "todo":
        try:
            r = _run_agents(cfg, probes, r)
        except Exception as e:
            r.update(detail=f"agent setup failed: {type(e).__name__}")
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

def _offer_keys(cfg: dict, probes: Probes, out):
    """Ask for each missing key (hidden input, blank skips) and store it.
    Never prints the value."""
    for role, env in _missing_keys(cfg, probes):
        label = config.key_label(env)
        try:
            value = probes.secret(f"  paste {label} ({role}), blank to "
                                  "skip: ").strip()
        except EOFError:
            return
        if not value:
            continue
        try:
            out(f"  stored {label} in {probes.store_key(env, value)}")
        except (ValueError, OSError, RuntimeError,
                subprocess.SubprocessError) as e:
            out(f"  not stored: {e}")


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
        if s.id == "keys":
            _offer_keys(cfg, probes, out)
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
