"""Which spoken questions need live public information, and whether the
answer brain may search the web for them.

`needs_web` is a pure text check. A question about what is on the screen
never matches; a question about the world right now does."""
import re

from . import brain

# Questions about the screen or the user's own machine are never live
# lookups, even when they hold a trigger word ("what does current mean
# here", "the latest message on my screen").
_SCREEN = re.compile(
    r"\b(on (my|the) screen|this (button|menu|page|window|tab|error|"
    r"dialog|setting|icon|field|app)|what does this|what is this|"
    r"what's this|where do i (change|click|find|set)|display scale|"
    r"in this (app|window|file|document)|i'm (looking|looking at)|"
    r"highlighted|selected text|"
    r"(current|this|my) (folder|directory|file|workspace|window|tab|page|"
    r"app|branch|project|repo|terminal)|"
    r"my (computer|machine|laptop|desktop|files|downloads))\b", re.I)

_TOPIC = re.compile(
    r"\b(weather|forecast|temperature|how (hot|cold|warm) is it|"
    r"(is|will) it (going to )?(rain|snow|storm)|raining|snowing|"
    r"humidity|wind speed|"
    r"news|headlines?|"
    r"(score|scores)\b|who (won|is winning|wins)|"
    r"(stock|share) price|price of (bitcoin|ethereum|btc|eth|gold|"
    r"silver|oil)|(bitcoin|ethereum|btc|eth|crypto)\b.*\bprice|"
    r"\bprice of [a-z]+ stock|exchange rate|"
    r"(how much|what) is [a-z0-9 ]{1,20} (worth )?in "
    r"(dollars|euros|pounds|yen|usd|eur|gbp|jpy)|"
    r"what time is it in|current time in|time in [a-z]+ (right )?now)\b",
    re.I)

# a freshness word counts only beside an information question
_FRESH = re.compile(
    r"\b(right now|today'?s|tonight'?s|latest|current(ly)?|"
    r"this (morning|evening|week)|breaking)\b", re.I)
_INFO_Q = re.compile(
    r"\b(what|what's|whats|who|who's|when|where|how much|how many|"
    r"is there|are there|tell me|give me)\b", re.I)


def needs_web(transcript: str) -> bool:
    t = (transcript or "").strip()
    if not t or _SCREEN.search(t):
        return False
    if _TOPIC.search(t):
        return True
    return bool(_FRESH.search(t) and _INFO_Q.search(t))


def search_mode(cfg: dict) -> str:
    v = str((cfg.get("web") or {}).get("search", "auto")).strip().lower()
    return v if v in ("auto", "true", "false") else "auto"


def max_results(cfg: dict) -> int:
    try:
        n = int(str((cfg.get("web") or {}).get("search_max_results", "3")))
    except ValueError:
        n = 3
    return min(max(n, 1), 10)


def web_request(cfg: dict, transcript: str) -> dict | None:
    """{"max_results": n} when this turn should search, else None. `cfg`
    is the config the answer call will use."""
    mode = search_mode(cfg)
    if mode == "false" or not needs_web(transcript):
        return None
    if mode == "auto" and not brain.is_openrouter(brain.provider(cfg)):
        return None
    return {"max_results": max_results(cfg)}


# one system line appended for a search turn
PROMPT = (
    "Live web results are attached to this turn. Answer the question from "
    "them in one or two spoken sentences. Never read a URL or a source "
    "name aloud.")
