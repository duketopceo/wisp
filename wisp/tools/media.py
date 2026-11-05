"""Omarchy-native media control (TLY-430): playback and volume through
the commands Omarchy's own media keys run, never a click on a player
and never a key press. Falls back to playerctl, else SKIP."""
import shutil
import subprocess

_TIMEOUT_S = 5

_ALIASES = {
    "play_pause": "play_pause", "playpause": "play_pause",
    "toggle": "play_pause", "pause": "pause", "play": "play",
    "next": "next", "skip": "next", "previous": "previous",
    "prev": "previous", "back": "previous",
    "volume_up": "volume_up", "volumeup": "volume_up", "louder": "volume_up",
    "volume_down": "volume_down", "volumedown": "volume_down",
    "quieter": "volume_down", "mute": "mute", "unmute": "mute",
    "mute_toggle": "mute",
}

# arg -> argv, per control surface
_OMARCHY = {
    "play_pause": ["omarchy-shell", "media", "playPause"],
    "pause": ["omarchy-shell", "media", "playPause"],
    "play": ["omarchy-shell", "media", "playPause"],
    "next": ["omarchy-shell", "media", "next"],
    "previous": ["omarchy-shell", "media", "previous"],
    "volume_up": ["omarchy-audio-output-volume", "raise"],
    "volume_down": ["omarchy-audio-output-volume", "lower"],
    "mute": ["omarchy-audio-output-volume", "mute-toggle"],
}
_PLAYERCTL = {
    "play_pause": ["playerctl", "play-pause"],
    "pause": ["playerctl", "pause"],
    "play": ["playerctl", "play"],
    "next": ["playerctl", "next"],
    "previous": ["playerctl", "previous"],
    "volume_up": ["playerctl", "volume", "0.05+"],
    "volume_down": ["playerctl", "volume", "0.05-"],
}

ARGS = tuple(_OMARCHY)


def _which(name: str):
    return shutil.which(name)


def _run(argv: list) -> tuple:
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stderr or p.stdout or "").strip()


def media(arg: str) -> str:
    """Media playback and volume: play_pause, pause, play, next,
    previous, volume_up, volume_down, mute."""
    key = _ALIASES.get(
        "_".join(str(arg or "").strip().lower().replace("-", " ").split()))
    if key is None:
        return (f"SKIP (unknown media action {arg!r}; use one of "
                f"{', '.join(ARGS)})")
    argv = _OMARCHY[key]
    if _which(argv[0]):
        surface = "omarchy"
    elif key in _PLAYERCTL and _which("playerctl"):
        argv, surface = _PLAYERCTL[key], "playerctl"
    else:
        return (f"SKIP (no media control for {key}: {argv[0]} not found"
                f"{'' if key == 'mute' else ' and playerctl not installed'})")
    rc, err = _run(argv)
    if rc != 0:
        return f"SKIP ({' '.join(argv)} failed: {err or 'exit ' + str(rc)})"
    note = ""
    if surface == "omarchy" and key in ("pause", "play"):
        note = (" (Omarchy has one play/pause toggle; it flips the "
                "current state, so check it landed)")
    return f"MEDIA {key} via {surface}{note}"
