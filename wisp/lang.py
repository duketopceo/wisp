"""Spoken languages (B23): which language the user spoke, what the answer
should be written in, and which voice reads it.

The hosted speech model (Groq's whisper-large-v3-turbo by default) is
multilingual: with `[stt] language = "auto"` it names the language it
heard, and a code like `es` or `pt-BR` pins it. The local `small.en`
model is English only. English changes nothing anywhere: no rule in the
prompt, the default voice, no extra log fields.
"""
import re
import subprocess

# ISO 639-1 code -> English name (the languages Whisper transcribes that
# a speech voice commonly exists for).
NAMES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "ca": "Catalan",
    "cs": "Czech", "cy": "Welsh", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian",
    "fa": "Persian", "fi": "Finnish", "fr": "French", "he": "Hebrew",
    "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian",
    "is": "Icelandic", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "lt": "Lithuanian", "lv": "Latvian", "ms": "Malay", "nl": "Dutch",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sk": "Slovak", "sl": "Slovenian",
    "sr": "Serbian", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil",
    "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "vi": "Vietnamese", "zh": "Chinese",
}
_BY_NAME = {v.lower(): k for k, v in NAMES.items()}
_BY_NAME.update({"mandarin": "zh", "castilian": "es", "farsi": "fa",
                 "norwegian bokmal": "no", "brazilian portuguese": "pt"})
REGION_NAMES = {"pt-BR": "Brazilian Portuguese",
                "pt-PT": "European Portuguese",
                "es-MX": "Mexican Spanish", "es-419": "Latin American "
                "Spanish", "en-GB": "British English",
                "zh-TW": "Traditional Chinese"}
_CODE = re.compile(r"^([A-Za-z]{2})(?:[-_]([A-Za-z]{2}|\d{3}))?$")


def parse(value) -> str:
    """A language as `xx` or `xx-RR` (`pt-BR`), or "" for none, "auto" or
    anything not recognised. Accepts codes (`ES`, `pt_br`) and the
    English names a provider returns (`spanish`)."""
    s = str(value or "").strip()
    if not s or s.lower() == "auto":
        return ""
    m = _CODE.match(s)
    if m:
        base = m.group(1).lower()
        if base not in NAMES:
            return ""
        reg = m.group(2)
        return f"{base}-{reg.upper()}" if reg else base
    return _BY_NAME.get(s.lower(), "")


class Transcript(str):
    """A transcript that remembers the language the speech model heard
    (`.language`, "" when unknown). Behaves as the plain string
    everywhere else."""
    language = ""

    def __new__(cls, text="", language=""):
        obj = super().__new__(cls, text)
        obj.language = language or ""
        return obj


class Refused(Exception):
    """The speech setup cannot transcribe the language; `str(e)` is a
    sentence to say out loud."""


def base(code: str) -> str:
    return (code or "").split("-")[0]


def is_english(code: str) -> bool:
    return base(code) in ("", "en")


def name(code: str) -> str:
    return REGION_NAMES.get(code) or NAMES.get(base(code), code)


def configured(cfg) -> str:
    """The pinned `[stt] language`, or "" for auto."""
    return parse(((cfg or {}).get("stt") or {}).get("language", "auto"))


def is_unsupported_setting(cfg) -> bool:
    """`[stt] language` names something that is not a language we can
    transcribe (a typo, a language outside the table)."""
    raw = str(((cfg or {}).get("stt") or {}).get("language", "auto")
              ).strip()
    return bool(raw) and raw.lower() != "auto" and not parse(raw)


def resolve(cfg, detected="") -> str:
    """The language of this turn: the pinned one, else what the speech
    model heard."""
    return configured(cfg) or parse(detected)


def reply_rule(code: str) -> str:
    """The one sentence added to the answer prompt, "" for English."""
    if is_english(code):
        return ""
    return (f"The user spoke {name(code)}. Reply in {name(code)} unless "
            "they ask for another language.")


def local_model_english_only(cfg) -> bool:
    model = str(((cfg or {}).get("audio") or {}).get(
        "whisper_model", "ggml-small.en.bin"))
    return model.endswith(".en.bin") or ".en." in model


def stt_refusal(cfg) -> str:
    """Why this setup cannot transcribe the pinned language, or "" when
    it can. This is the sentence spoken instead of hanging."""
    stt = (cfg or {}).get("stt") or {}
    if is_unsupported_setting(cfg):
        raw = str(stt.get("language", "")).strip()
        return (f"I can't listen in {raw}: it isn't a language my speech "
                "service can transcribe. Set a language like es or de in "
                "the stt section, or leave it on auto.")
    code = configured(cfg)
    if is_english(code):
        return ""
    if str(stt.get("provider", "openai")) == "local" and \
            local_model_english_only(cfg):
        return (f"I can't listen in {name(code)} with the local English "
                "only speech model. Switch to a multilingual model or "
                "the hosted speech service.")
    return ""


def provider_refusal(code: str) -> str:
    return (f"The speech service couldn't transcribe {name(code) or 'that'}"
            ". Try another language setting or the hosted speech service.")


# -- voices --------------------------------------------------------

def _lang_voices(cfg) -> dict:
    out = {}
    for item in str(((cfg or {}).get("voice") or {}).get(
            "lang_voices", "")).split(","):
        k, _, v = item.partition("=")
        k = parse(k)
        if k and v.strip():
            out[k] = v.strip()
    return out


def _espeak_has(binary: str, voice: str) -> bool:
    try:
        r = subprocess.run([binary, "--voices=" + base(voice)],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    rows = r.stdout.splitlines()[1:]
    want = voice.lower()
    for cols in (l.split() for l in rows):
        if len(cols) < 2:
            continue
        have = cols[1].lower()          # the Language column
        if have == want or ("-" not in want and have.split("-")[0] == want):
            return True
    return False


_HAVE: dict = {}


def voice(cfg, code: str, tts_binary=None) -> tuple:
    """(voice name or "", fallback). Empty name with fallback False is
    English or "no per-language voice needed"; fallback True means the
    default voice is used for a language that has no voice here."""
    if is_english(code):
        return "", False
    mapped = _lang_voices(cfg)
    chosen = mapped.get(code) or mapped.get(base(code))
    if chosen:
        return chosen, False
    cmd = str(((cfg or {}).get("voice") or {}).get("cmd", ""))
    if cmd:
        # a custom command picks its own voice from {lang}
        return "", not ("{lang}" in cmd or "{voice}" in cmd)
    binary = tts_binary
    if not binary:
        return "", True
    want = code.lower()
    for cand in (want, base(code)):
        key = (binary, cand)
        if key not in _HAVE:
            _HAVE[key] = _espeak_has(binary, cand)
        if _HAVE[key]:
            return cand, False
    return "", True


def fallback_note(code: str) -> str:
    return (f"I don't have a {name(code)} voice here, so I'm using the "
            "default one.")
