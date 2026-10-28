"""Voice polish leftovers (B8b): captions, mic failover, a muted speaker,
and staying quiet on calls.

Every probe takes an injectable runner so tests never touch a real audio
stack, window manager or clipboard. Each helper is best effort: a probe
that cannot answer says "not muted", "not on a call", "no copy", never
raises into a turn.

    captions   [voice] captions = "false" hides the answer bubble text
               while the answer is spoken (the voice is the answer).
    muted      the default speaker is muted or at zero: the answer goes to
               the clipboard and the bubble says so, and nothing is spoken.
    failover   [audio] device names a mic; when it is gone the turn
               records from the system default instead and says so.
    quiet      announcements that nobody asked for just now (a finished
               background agent) wait while a call or a screen share is on.
"""
import dataclasses
import json
import re
import shlex
import shutil
import subprocess
import threading
import time

HINT_MUTED = "Speaker is muted, so I copied the answer to your clipboard."
HINT_MUTED_NOCOPY = "Speaker is muted, so I could not speak this answer."
HINT_MIC = "Your mic was not available, so I used the default one."

_TRUE = ("true", "1", "yes", "on")


def _flag(cfg: dict, section: str, key: str, default: str) -> bool:
    v = ((cfg or {}).get(section, {}) or {}).get(key, default)
    return str(v).strip().lower() in _TRUE


def _run(argv, timeout=1.5, data=None):
    """(returncode, stdout) — (1, "") when the tool is absent or hangs."""
    try:
        r = subprocess.run(argv, input=data, capture_output=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout.decode(errors="replace")


# -- captions ---------------------------------------------------------

def captions_on(cfg: dict) -> bool:
    """[voice] captions, default on (the bubble shows what is said)."""
    return _flag(cfg, "voice", "captions", "true")


def voice_on(cfg: dict) -> bool:
    return _flag(cfg, "voice", "enabled", "false")


# -- muted speaker ------------------------------------------------------

def speaker_muted(runner=None) -> bool:
    """True when the default output is muted or at 0%. wpctl first, then
    pactl; an unreadable answer is "not muted" so speech is never
    dropped on a guess."""
    run = runner or _run
    if shutil.which("wpctl") or runner:
        rc, out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        if rc == 0 and out.strip():
            if "[MUTED]" in out:
                return True
            m = re.search(r"Volume:\s*([0-9.]+)", out)
            return bool(m) and float(m.group(1)) <= 0.0
    if shutil.which("pactl") or runner:
        rc, out = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        if rc == 0 and "yes" in out.lower():
            return True
    return False


def copy_to_clipboard(text: str, runner=None) -> bool:
    """wl-copy the text (the dictate helper); False when there is no
    clipboard tool."""
    if not text:
        return False
    from . import dictate
    return dictate.copy_to_clipboard(text, timeout=2.0, runner=runner)


@dataclasses.dataclass
class Delivery:
    """What one spoken answer does: `cfg` is the config to speak with
    (voice off when the speaker is muted), `muted` and `hint` describe the
    muted case, `shown(text)` is what the bubble gets."""
    cfg: dict
    muted: bool = False
    copied: bool = False
    hint: str = ""
    captions: bool = True

    def shown(self, text: str) -> str:
        """Bubble text for `text`. A muted speaker always shows it (with
        the hint); captions off hides it only while it is being spoken."""
        if not text:
            return text
        if self.muted:
            return f"{text}\n{self.hint}" if self.hint else text
        return text if self.captions else ""

    def revealed(self, text: str) -> str:
        """Bubble text once nothing was spoken after all: the answer
        shows whatever the captions setting says."""
        if self.muted:
            return self.shown(text)
        return text

    def finish(self, text: str, runner=None) -> None:
        """Muted: put the final answer on the clipboard, set the hint."""
        if not self.muted:
            return
        self.copied = copy_to_clipboard(text, runner)
        self.hint = HINT_MUTED if self.copied else HINT_MUTED_NOCOPY


def voice_usable(cfg: dict) -> bool:
    """True when a TTS command exists to speak with: the [voice] cmd's
    program, else the built-in espeak. With none, captions stay on so the
    answer is never hidden and unspoken."""
    cmd = str(((cfg or {}).get("voice", {}) or {}).get("cmd", "")).strip()
    if cmd:
        try:
            first = shlex.split(cmd)[0]
        except (ValueError, IndexError):
            return False
        return bool(shutil.which(first))
    from . import platform
    return platform.tts_binary() is not None


def begin(cfg: dict, runner=None) -> Delivery:
    """Decide, once per spoken answer, how it is delivered. With voice off
    nothing is probed and the answer shows as before."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if not voice_on(cfg):
        return Delivery(cfg=cfg, captions=True)
    if speaker_muted(runner):
        quiet = dict(cfg)
        quiet["voice"] = dict(cfg.get("voice", {}), enabled="false")
        return Delivery(cfg=quiet, muted=True, hint=HINT_MUTED)
    return Delivery(cfg=cfg,
                    captions=captions_on(cfg) or not voice_usable(cfg))


# -- mic failover -------------------------------------------------------

def mic_device(cfg: dict) -> str:
    """[audio] device: the mic to record from, "" for the system default."""
    return str(((cfg or {}).get("audio", {}) or {}).get("device", "")
               ).strip()


def spawn_recorder(cmd_for, spawn, *, device: str = "",
                   settle_s: float = 0.35, sleep=time.sleep,
                   before_retry=None):
    """Start the recorder on `device`; when that process dies inside
    `settle_s` (the mic is gone) start it again on the default device.

    `cmd_for(device)` builds the argv, `spawn(argv)` returns a Popen,
    `before_retry()` clears what the dead attempt wrote. Returns
    (proc, failed_over). Never loops: one retry, then the caller's
    own "recording produced no audio" error ends the turn."""
    proc = spawn(cmd_for(device))
    if not device:
        return proc, False
    sleep(settle_s)
    if proc.poll() is None:
        return proc, False
    if before_retry is not None:
        before_retry()
    return spawn(cmd_for("")), True


# -- quiet on calls -------------------------------------------------------

_CALL_CLASS = re.compile(
    r"^(zoom|us\.zoom|teams|teams-for-linux|microsoft teams|webex|skype|"
    r"jitsi|slack huddle)", re.I)
_CALL_TITLE = re.compile(
    r"(^meet\s[-–]\s|google meet|zoom meeting|zoom workplace|"
    r"huddle with|\| microsoft teams|webex meeting)", re.I)
_SHARE_TITLE = re.compile(
    r"(is sharing your screen|you(?:'|’)re sharing|you are sharing|"
    r"sharing your screen|stop sharing|screen share)", re.I)


def call_state(runner=None) -> dict:
    """{"in_call", "screen_sharing"} from the open windows. Best effort:
    titles and classes of known call apps; nothing when hyprctl is not
    there."""
    run = runner or _run
    out = {"in_call": False, "screen_sharing": False}
    if not (shutil.which("hyprctl") or runner):
        return out
    rc, text = run(["hyprctl", "clients", "-j"], timeout=1.5)
    if rc != 0:
        return out
    try:
        clients = json.loads(text or "[]")
    except ValueError:
        return out
    for c in clients if isinstance(clients, list) else []:
        if not isinstance(c, dict):
            continue
        cls = str(c.get("class") or c.get("initialClass") or "")
        title = str(c.get("title") or "")
        if _CALL_CLASS.search(cls) or _CALL_TITLE.search(title):
            out["in_call"] = True
        if _SHARE_TITLE.search(title):
            out["screen_sharing"] = True
    return out


def quiet_enabled(cfg: dict) -> bool:
    """[quiet] on_calls, default on."""
    return _flag(cfg, "quiet", "on_calls", "true")


def hold_reason(cfg: dict, runner=None, now=None) -> str:
    """"in_call" or "screen_sharing" when announcements should wait, else
    "". Goes through the suggestion etiquette gate so one rule decides
    both."""
    if not quiet_enabled(cfg):
        return ""
    from . import suggest_policy
    st = call_state(runner)
    v = suggest_policy.evaluate_suggestion_etiquette(
        local_hour=12, in_call=st["in_call"],
        screen_sharing=st["screen_sharing"])
    return "" if v["allow"] else str(v["reason"])


class HoldCache:
    """hold_reason() at most once per `ttl` seconds: a burst of toasts
    costs one window listing."""

    def __init__(self, ttl: float = 5.0, clock=time.monotonic):
        self._ttl, self._clock = ttl, clock
        self._at = None
        self._val = ""
        self._on = None
        self._lock = threading.Lock()

    def get(self, cfg: dict, runner=None) -> str:
        with self._lock:
            now = self._clock()
            on = quiet_enabled(cfg)
            if on != self._on:           # the setting changed: probe again
                self._at, self._on = None, on
            if self._at is None or now - self._at >= self._ttl:
                try:
                    self._val = hold_reason(cfg, runner)
                except Exception:
                    self._val = ""
                self._at = now
            return self._val
