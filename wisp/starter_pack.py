"""The starter pack (B32): four spoken questions after the tour.

Asks what you do, which apps you live in, what annoys you and how you like
answers; writes the answers to the user profile memory; then offers exactly
three starters that finish in different ways: a thing to use (a named
helper), a straight answer (a line to try), and work done in an app (a
routine). A routine repeats, so it is only scheduled after a spoken yes to
"this will repeat, keep it going?". Saying skip, stop or later at any point
ends cleanly and writes nothing, and the pack is offered again next run.
Nothing here speaks or listens itself: `ask(question)` returns the user's
words or None, `confirm(prompt)` returns a bool, so tests script both.
"""
import json
import re
import time

from . import config

QUESTIONS = (
    ("role", "What do you do? A few words is fine."),
    ("apps", "Which apps do you spend your day in?"),
    ("annoys", "What is the most annoying thing about your computer?"),
    ("style", "How do you like answers: short and blunt, or with detail?"),
)
SKIP_WORDS = ("skip", "stop", "later", "never mind", "nevermind", "cancel",
              "not now", "no thanks")
KINDS = ("use", "answer", "work")


def wants_skip(text) -> bool:
    t = re.sub(r"[^a-z ]", "", str(text or "").lower()).strip()
    if not t:
        return True       # silence or nothing heard counts as "not now"
    if len(t.split()) > 4:
        return False      # a real answer that happens to contain "later"
    return any(t == w or t.startswith(w + " ") or t.endswith(" " + w)
               for w in SKIP_WORDS)


def profile_lines(answers: dict) -> list:
    """The bullets written to the user profile. Answers are capped so one
    long ramble cannot eat the profile budget."""
    c = {k: " ".join(str(v).split())[:160] for k, v in answers.items()}
    return [f"Works as: {c['role']}",
            f"Lives in these apps: {c['apps']}",
            f"Finds this annoying: {c['annoys']}",
            f"Likes answers: {c['style']}"]


def _first_app(apps: str) -> str:
    for part in re.split(r",| and | & ", apps or "", flags=re.I):
        part = part.strip(" .")
        if part:
            return part[:30]
    return "your main app"


def starters(answers: dict) -> list:
    """Exactly three starters, one of each outcome kind."""
    app = _first_app(answers.get("apps", ""))
    annoy = " ".join(str(answers.get("annoys", "")).split())[:80] or "the slow bits"
    return [
        {"kind": "use", "id": "helper", "repeats": False,
         "offer": f"A helper named Scout that keeps notes about {annoy} "
                  "and answers when you ask. Want it?",
         "helper": {"name": "Scout",
                    "role": f"Helps with {annoy}. {answers.get('style', '')}"
                            .strip()}},
        {"kind": "answer", "id": "tryit", "repeats": False,
         "offer": f"A straight answer to try right now: hold the key and "
                  f"ask how to do {annoy} in {app}. Want me to remember "
                  "that as your first question?",
         "note": f"First question to try: how to handle {annoy} in {app}."},
        {"kind": "work", "id": "morning", "repeats": True,
         "offer": f"Every weekday morning, check {app} and tell you what "
                  "needs you first. This will repeat. Keep it going?",
         "routine": {"name": f"Morning look at {app}",
                     "task": f"Look at {app} and say what needs me first.",
                     "schedule": "daily at 9am"}},
    ]


def transcripts_since(since_iso: str, decisions=None) -> list:
    """What the user said in turns decided after `since_iso` (oldest first)."""
    out = []
    try:
        lines = (decisions or config.DECISIONS).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and str(rec.get("ts") or "") > since_iso \
                and rec.get("transcript"):
            out.append(str(rec["transcript"]))
    return out


def run(ask, confirm, say, *, write_profile, make_helper, make_routine,
        note=lambda text: None, mark=lambda: None, log=print) -> dict:
    """Run the interview. Returns {status, answers, accepted}; status is
    done or skipped. `write_profile(lines)`, `make_helper(spec)`,
    `make_routine(spec)` do the writing; `make_routine` is only called after
    `confirm` says yes to the repeat prompt."""
    answers = {}
    for key, question in QUESTIONS:
        reply = ask(question)
        if wants_skip(reply):
            say("No problem. I'll offer this again next time.")
            log("starter: skipped")
            return {"status": "skipped", "answers": {}, "accepted": []}
        answers[key] = str(reply)
    write_profile(profile_lines(answers))
    accepted = []
    for s in starters(answers):
        if not confirm(s["offer"]):
            continue
        if s["kind"] == "use":
            make_helper(s["helper"])
        elif s["kind"] == "answer":
            note(s["note"])
        else:
            make_routine(s["routine"])
        accepted.append(s["id"])
    mark()
    say("That's your starter pack. Say, show me my starters, any time.")
    log(f"starter: done, accepted {accepted}")
    return {"status": "done", "answers": answers, "accepted": accepted}


def clock_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
