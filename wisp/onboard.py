"""First-run onboarding (W28): `wispd onboard` and the Panel first-run card.

Six steps, in order: mic, models, keys, cua (optional), notifications
and keybinding (optional). Each is a read-only check plus, at most, one
explicit side effect:

  - models only probes the local ladder over loopback HTTP, and only
    when [local] enabled = "true"; it never starts or stops a service
    (`wispd health start` stays a manual act),
  - keys stores a key only when the user chooses a store and supplies
    one (never printed); the walk may update its key source,
  - notifications sends one test notification, and only when the caller
    passes confirm=True,
  - keybinding needs the W24 submap and is "na" while that is absent.

Every step is skippable and reversible. A skip is not recorded and writes
nothing (the step is offered again next run). Only a step that passed is
recorded, in ~/.local/share/wisp/onboard.json, so a half finished run
resumes where it stopped. Undo removes the record, not stored keys or config.

All probes are injected through `Probes`, so the tests run with fakes and
never touch the network, services or notifications.
"""
import dataclasses
import datetime
import getpass
import json
import os
import pathlib
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

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
    """Store a key in the configured store or an owner-only .env file.

    Secret-manager commands receive the value on stdin, never in argv.
    """
    if not value or any(c.isspace() for c in value):
        raise ValueError("a key cannot be empty or contain whitespace")
    cands = [c.strip() for c in key_env.split(",") if c.strip()]
    first_store = next((c for c in cands if c.startswith(
        ("keyring://", "omaseal://"))), "")
    if first_store.startswith("keyring://"):
        keyring = first_store[len("keyring://"):].split("/", 1)
        exe = shutil.which("secret-tool")
        if len(keyring) == 2 and all(keyring) and exe:
            r = subprocess.run(
                [exe, "store", "--label=Wisp credential", "service",
                 keyring[0], "account", keyring[1]], input=value,
                capture_output=True, text=True,
                timeout=config.OMASEAL_TIMEOUT_S)
            if r.returncode != 0:
                raise RuntimeError("Secret Service could not store the key")
            return f"keyring {keyring[0]}/{keyring[1]}"
        name = config.key_label(key_env)
        if name.startswith("keyring://"):
            raise ValueError("Secret Service keyring is unavailable")
    ref = (first_store[len("omaseal://"):].split("/", 1)
           if first_store.startswith("omaseal://") else None)
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


def _set_key_source(section: str, source: str) -> None:
    """Update a key source, reloading the daemon's config when it is live."""
    key = f"{section}.key_env"
    try:
        from . import ipc
        reply = ipc.send({"cmd": "config", "set": {key: source}}, timeout=2)
    except (ConnectionError, FileNotFoundError):
        config.set_config(section, "key_env", source)
        return
    except TimeoutError as e:
        raise RuntimeError("the daemon did not acknowledge the config update") from e
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "daemon refused the config update")


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
    set_source: object = _set_key_source
    secret: object = getpass.getpass


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
    if up.get("ollama"):
        from . import model_catalog
        seen = sorted(
            {o["ollama"] for lane in model_catalog.CATALOG.values()
             for o in lane if o.get("ollama")}
            & model_catalog.ollama_tags())
        if seen:
            detail += f"; catalog weights pulled: {len(seen)}"
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
           "keys": _check_keys, "cua": _check_cua,
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

def _offer_keys(cfg: dict, probes: Probes, ask, out):
    """Ask for each missing key (hidden input, blank skips) and store it.
    Never prints the value."""
    for role, env in _missing_keys(cfg, probes):
        label = config.key_label(env)
        source = env
        configure_section = ""
        recall = cfg.get("recall") or {}
        shared_recall = (
            role == "brain" and recall.get("key_env") == env
            and config.is_openrouter_endpoint(
                recall.get("base_url", "https://openrouter.ai/api/v1")))
        has_store = any(c.strip().startswith(("keyring://", "omaseal://"))
                        for c in env.split(","))
        if not has_store:
            out(f"  Storage for {label}: [f] plaintext "
                f"{config.ENV_FILE} (0600, yours only), "
                "[e] set environment yourself, [s] skip.")
            if shared_recall:
                out("  Memory uses this same source; a secret-store choice "
                    "updates memory too.")
            if probes.which("secret-tool"):
                out("  [k] Linux Secret Service keyring (recommended).")
            if probes.which("omaseal"):
                out("  [o] OmaSeal.")
            try:
                choice = ask("  Choose storage [k/f/o/e/s]: ").strip().lower()
            except EOFError:
                return
            if choice in ("e", "s", ""):
                out(f"  Set {label} for the Wisp service, then retry onboarding.")
                continue
            if choice in ("k", "o"):
                program = "secret-tool" if choice == "k" else "omaseal"
                if not probes.which(program):
                    out(f"  {program} is unavailable; no key was stored.")
                    continue
                scheme = "keyring" if choice == "k" else "omaseal"
                source = f"{scheme}://wisp/{role}-{uuid.uuid4().hex}"
                if role == "brain":
                    from . import brain
                    configure_section = f"brain.{brain.provider(cfg)['name']}"
                else:
                    configure_section = "stt"
            elif choice != "f":
                out("  No storage selected; no key was stored.")
                continue
        else:
            first_store = next(c.strip() for c in env.split(",")
                               if c.strip().startswith(
                                   ("keyring://", "omaseal://")))
            if first_store.startswith("keyring://") and not probes.which("secret-tool"):
                if label.startswith("keyring://"):
                    out("  Secret Service is unavailable; no key was stored.")
                    continue
                out("  Secret Service is unavailable; the configured fallback "
                    "stores the key in a private plaintext .env file.")
            if first_store.startswith("omaseal://") and not probes.which("omaseal"):
                if label.startswith("omaseal://"):
                    out("  OmaSeal is unavailable; no key was stored.")
                    continue
                out("  OmaSeal is unavailable; the configured fallback stores "
                    "the key in a private plaintext .env file.")
            else:
                out(f"  Key will be stored using the configured source for {label}.")
        try:
            value = probes.secret(f"  paste {label} ({role}), blank to "
                                  "skip: ").strip()
        except EOFError:
            return
        if not value:
            continue
        try:
            where = probes.store_key(source, value)
            if probes.key(source) != value:
                out(f"  Could not verify the key in {where}; configuration unchanged.")
                continue
            if configure_section:
                try:
                    probes.set_source(configure_section, source)
                except (OSError, ValueError, RuntimeError) as e:
                    out(f"  Key stored in {where}, but configuration failed: {e}")
                    continue
                cfg.setdefault(configure_section, {})["key_env"] = source
                if shared_recall and configure_section == "brain.openrouter":
                    try:
                        probes.set_source("recall", source)
                        cfg["recall"]["key_env"] = source
                    except (OSError, ValueError, RuntimeError) as e:
                        out(f"  Brain configured; memory source update failed: {e}")
            out(f"  stored {label} in {where}")
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
            _offer_keys(cfg, probes, ask, out)
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
