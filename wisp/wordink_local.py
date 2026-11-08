"""Optional speech to text through a running WordInk desktop app.

WordInk serves a small HTTP API on 127.0.0.1 (docs: duketopceo/WordInk,
apps/desktop/docs/local-api.md). It transcribes on this machine (Neural
Engine or GPU), so no audio leaves the computer. Wisp uses it only when
`[stt] provider = "wordink"`; install and onboarding never require it, and
any failure here falls back to the configured hosted STT.

Discovery: while the app runs it writes `local-api.json`
(`{"port", "token", "apiVersion", "pid"}`, mode 0600) in its data folder.
The token changes on every app start, so it is read per call and never
stored or logged. A file left by a crash is stale: the pid must be alive
and `/health` must answer before it is trusted. Only `apiVersion` "2" is
spoken; an unknown version is refused, not guessed.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

API_VERSIONS = ("2",)
TIMEOUT_S = 30
PROBE_TIMEOUT_S = 0.6
MAX_WAV = 64 * 1024 * 1024
HINT = ('WordInk is running: set [stt] provider = "wordink" to transcribe '
        "on this machine with no cloud (the hosted speech to text stays "
        "the fallback).")


class WordinkError(Exception):
    """Any reason the local API cannot transcribe right now."""


def data_dir(env=None, platform=None) -> pathlib.Path:
    env = os.environ if env is None else env
    platform = platform or sys.platform
    override = env.get("HEX_APPLICATION_SUPPORT_DIR")
    if override:
        return pathlib.Path(override)
    home = pathlib.Path(env.get("HOME") or pathlib.Path.home())
    if platform == "darwin":
        return home / "Library" / "Application Support" / "wordink"
    if platform.startswith("win"):
        return pathlib.Path(env.get("APPDATA") or home) / "wordink"
    base = env.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return pathlib.Path(base) / "wordink"


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def _opener():
    # loopback only: never through a proxy
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(conn: dict, path: str, *, data=None, headers=None,
             timeout=TIMEOUT_S, opener=None):
    req = urllib.request.Request(
        conn["base"] + path, data=data,
        method="POST" if data is not None else "GET",
        headers={"Authorization": "Bearer " + conn["token"],
                 **(headers or {})})
    with (opener or _opener()).open(req, timeout=timeout) as r:
        return r.read()


def find(path=None, *, alive=_pid_alive, opener=None,
         probe: bool = True) -> dict | None:
    """{"base", "token", "apiVersion"} for a live, supported app, else
    None. Never raises."""
    p = pathlib.Path(path) if path else data_dir() / "local-api.json"
    try:
        info = json.loads(p.read_text())
        port = int(info["port"])
        token = str(info["token"])
        ver = str(info.get("apiVersion", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not token or not 0 < port < 65536 or ver not in API_VERSIONS:
        return None
    if not alive(info.get("pid")):
        return None
    conn = {"base": f"http://127.0.0.1:{port}", "token": token,
            "apiVersion": ver}
    if probe:
        try:
            json.loads(_request(conn, "/health", timeout=PROBE_TIMEOUT_S,
                                opener=opener))
        except (OSError, ValueError, urllib.error.URLError):
            return None
    return conn


def installed_models(conn: dict, opener=None) -> list:
    """Installed model records from GET /models."""
    try:
        data = json.loads(_request(conn, "/models", opener=opener,
                                   timeout=5))
    except (OSError, ValueError, urllib.error.URLError) as e:
        raise WordinkError(f"models list failed: {type(e).__name__}") from e
    rows = data if isinstance(data, list) else data.get("models", [])
    return [m for m in rows if isinstance(m, dict) and m.get("installed")
            and m.get("id")]


def pick_model(rows: list, want: str = "") -> str:
    """The configured model if installed, else an installed Parakeet (the
    fast one), else the first installed model. "" when none."""
    ids = [str(m["id"]) for m in rows]
    if want:
        return want if want in ids else ""
    for i in ids:
        if "parakeet" in i.lower():
            return i
    return ids[0] if ids else ""


def available(path=None, **kw) -> bool:
    """True when the app is running and has an installed model: the
    condition for suggesting `provider = "wordink"` in onboarding."""
    conn = find(path, **kw)
    if not conn:
        return False
    try:
        return bool(installed_models(conn, kw.get("opener")))
    except WordinkError:
        return False


def transcribe(wav, cfg: dict | None = None, *, path=None, opener=None):
    """Transcribe `wav` through the local API -> lang.Transcript. Raises
    WordinkError for anything that should send the caller to its
    fallback."""
    from . import lang as _lang
    wav = pathlib.Path(wav)
    conn = find(path, opener=opener)
    if conn is None:
        raise WordinkError("WordInk is not running (no live local API)")
    try:
        audio = wav.read_bytes()
    except OSError as e:
        raise WordinkError("recording unreadable") from e
    if len(audio) > MAX_WAV:
        raise WordinkError("recording too large for the local API")
    want = str(((cfg or {}).get("stt") or {}).get("wordink_model", "")
               ).strip()
    model = pick_model(installed_models(conn, opener), want)
    if not model:
        raise WordinkError("no installed WordInk model"
                           + (f" named {want!r}" if want else ""))
    q = "?model=" + urllib.parse.quote(model, safe="")
    pinned = _lang.base(_lang.configured(cfg or {}))
    if pinned and pinned != "auto":
        q += "&language=" + urllib.parse.quote(pinned, safe="")
    try:
        out = json.loads(_request(
            conn, "/transcriptions" + q, data=audio,
            headers={"Content-Type": "audio/wav"}, opener=opener))
    except urllib.error.HTTPError as e:
        code = ""
        try:
            code = json.loads(e.read() or b"{}").get("code", "")
        except ValueError:
            pass
        raise WordinkError(f"WordInk answered {e.code} {code}".strip()) from e
    except (OSError, ValueError, urllib.error.URLError) as e:
        raise WordinkError(f"transcription failed: {type(e).__name__}") from e
    text = " ".join(str(out.get("transcript", "")).split())
    return _lang.Transcript(text, "")
