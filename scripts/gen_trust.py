#!/usr/bin/env python3
"""Generate docs/TRUST.md: what leaves your machine, from the code.

    python3 scripts/gen_trust.py            # write docs/TRUST.md
    python3 scripts/gen_trust.py --check    # exit 1 when the page is stale

The page is built from two things that cannot drift apart:

1. a scan of the source (Python string constants, Rust, QML and JS) for
   every host name Wisp's code can name, and
2. the entries below, one per host, saying what it gets, who holds the key
   and what you control.

A host the scan finds with no entry here fails `tests/test_trust.py` with
the host name, so a new outbound destination cannot ship unexplained, and
an entry whose host is gone from the code fails it too. The test also
regenerates the page and fails on any difference.
"""
import argparse
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "TRUST.md"

SCAN_DIRS = ("wisp", "rs", "shell-plugin", "shells")
SCAN_FILES = ("wispd",)
SKIP_DIRS = {"__pycache__", "target", "node_modules", ".git"}
CODE_SUFFIX = {".py", ".rs", ".qml", ".js"}

HOST = re.compile(
    r"(?:https?://)?((?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|app|dev|co|gg|me))"
    r"(?=[/:?\s\"'<>]|$)", re.I)
URL = re.compile(
    r"https?://((?:[a-z0-9-]+\.)+[a-z]{2,})(?=[/:?\s\"'<>]|$)", re.I)
LOOPBACK = re.compile(r"(?:https?://)?(127\.0\.0\.1|localhost|\[::1\])", re.I)

# Payload classes, in the words the page uses.
AUDIO = "audio"
SHOT = "screenshot"
TEXT = "text"
NONE = "nothing of yours"

# Hosts Wisp contacts. Keys must equal the host the scan finds.
HOSTS = {
    "openrouter.ai": dict(
        what="Answer model, router and decision calls, the vision fallback "
             "for finding a control on screen, and (only if you turn "
             "`[recall] provider` on) memory embeddings.",
        sends=[TEXT, SHOT],
        detail="What you said (as text), the focused app and window "
               "names, recent turns, memory notes, a selection or copied "
               "text you pointed at, and a screenshot on answer calls "
               "(`[agent] screenshots`) and the vision fallback. Windows "
               "that look like a password manager, a keyring or "
               "authentication prompt or a sudo terminal (plus any you "
               "add under `[cua]`) are blanked first, and a capture is "
               "refused while one has focus.",
        default="Yes. It is the default answer brain.",
        key="You. `OPENROUTER_API_KEY` in your environment, "
            "`~/.config/wisp/.env` or your keyring.",
        control="`[brain] default` and `[brain] fallback` take a local "
                "model (`ollama:`, `lmstudio:`, `mlx:`) and nothing then "
                "leaves; `[agent] screenshots = false` keeps the screen "
                "out of answers. How long OpenRouter and the model "
                "provider keep a request is set by your OpenRouter "
                "account's privacy settings, not by Wisp."),
    "api.groq.com": dict(
        what="Speech to text for each push-to-talk turn (any "
             "OpenAI-compatible endpoint works in its place).",
        sends=[AUDIO],
        detail="The recording of that turn, and the vocabulary prompt "
               "from `[stt] prompt`.",
        default="Yes. `[stt] provider` is `openai` with this base URL.",
        key="You. `GROQ_API_KEY` in your environment, "
            "`~/.config/wisp/.env` or your keyring.",
        control="`[stt] provider = \"local\"` transcribes on this "
                "machine with whisper.cpp and sends no audio; "
                "`[stt] base_url` points at any other host. The "
                "provider's retention is its own."),
    "api.github.com": dict(
        what="Update check and release lookup for `wispd update`.",
        sends=[NONE],
        detail="A plain GET with the user agent `wispd-update`. Nothing "
               "from your machine is in it.",
        default="No. Only when you run `wispd update`; the daemon never "
                "calls it.",
        key="None.",
        control="Do not run `wispd update`. A release is verified "
                "against its published SHA-256 before anything is "
                "installed."),
    "upload.wikimedia.org": dict(
        what="Pictures for answer cards.",
        sends=[NONE],
        detail="A plain GET for one picture an answer named. Nothing "
               "from your machine is in it, but the picture's address "
               "comes from the answer.",
        default="Only when an answer shows a picture. This is the only "
                "host fetched by default.",
        key="None.",
        control="`[images] allow` is the full list of hosts that may be "
                "fetched, https only, size-capped, private addresses "
                "refused. Set it to a host you do not use to turn "
                "pictures off."),
}

# Names the code mentions that Wisp does not send anything to: a browser
# is opened to them for you, or the text only appears in a message, a
# comment, a header label or an XML namespace.
MENTIONS = {
    "github.com": "Release downloads for `wispd update` (the same GET as "
                  "api.github.com above) and the project address Wisp "
                  "names itself with in an `HTTP-Referer` header so "
                  "OpenRouter can show an app name.",
    "mail.google.com": "Opened in your browser when you say \"open "
                       "mail\" and no native mail client is set "
                       "(`[web] mail`).",
    "calendar.google.com": "Opened in your browser when you say \"open "
                           "calendar\" and no native client is set "
                           "(`[web] calendar`).",
    "x.com": "A compose window is opened in your browser with the text "
             "filled in. Nothing is posted until you press Post.",
    "gmail.com": "An example in help text: a domain you say is opened in "
                 "your browser.",
    "cal.com": "A name in a list of apps Wisp can connect to, in help "
               "text.",
    "wisp.ai": "An example in help text.",
    "example.com": "An example address in help text.",
    "amara.org": "A credit line for subtitle text in a bundled sample.",
    "www.w3.org": "An XML namespace in a generated icon. Never "
                  "requested.",
}

# What stays on this machine, and for how long.
STORES = (
    ("session.jsonl", "Recent turns: what you said, the route, the reply.",
     "Not trimmed automatically. Delete the file any time."),
    ("decisions.jsonl, route_ab.jsonl",
     "One line per turn: transcript, route choice, timings. Used to "
     "label and compare routing.",
     "Not trimmed automatically. Delete the files any time."),
    ("trace.jsonl",
     "Per-stage event stream for debugging, including the transcript "
     "and answer text. Keys are never written.",
     "`[debug] trace = false` writes nothing. Rotates at 10 MB and "
     "keeps one earlier file."),
    ("dictation history",
     "Each finished dictation, so a failed insert loses nothing. Never "
     "sent anywhere and never put in a prompt.",
     "`[dictation] history`, `history_max` and `history_days` bound it "
     "(100 entries, 7 days by default). `wispd dictate clear` empties "
     "it."),
    ("utterance.wav", "The recording of your last turn, in "
     "`~/.config/wisp`.", "Overwritten by the next turn. Delete it any "
     "time."),
    ("recall.db", "Memory notes and their search index.",
     "Delete the file any time."),
    ("errors.jsonl",
     "The last typed error codes and exception type names, for "
     "`wispd bugreport`. Never a message, transcript or path.",
     "Bounded to about 200 entries. Delete the file any time."),
    ("report_queue.jsonl",
     "Typed error codes waiting to be reported, only if you set "
     "`[report] dsn`. No transcripts, screenshots, typed text, keys or "
     "home paths.",
     "Bounded by `[report] queue_max`. Off while `dsn` is empty."),
    ("imports.json",
     "The hash and location of each lesson, skill or helper you "
     "imported, so importing the same file twice changes nothing.",
     "Delete the file any time; the imported items stay."),
    ("state.json", "What the panel shows right now. In your runtime "
     "directory (memory-backed).", "Gone at logout or reboot."),
)

NEVER = (
    "API keys, other than as the authorization header of the one "
    "provider they belong to. They are never written to a log, trace, "
    "decision file or error report (`tests/test_log_hygiene.py` checks "
    "this with a sentinel key, including when a provider's error "
    "message echoes it back).",
    "Your home folder path or user name, in error reports.",
    "The clipboard, a selection, or a file you did not point at. They are "
    "read when you press the key and ask about \"this\", \"that\" or "
    "\"what I copied\", and go to the answer only, as quoted data.",
    "Anything from a password manager, keyring or authentication prompt "
    "or sudo terminal window: it is painted over, or the capture is "
    "refused.",
    "Your voice or screen when nothing is asked: there is no background "
    "recording, and the passive activity sense is off until you turn it "
    "on.",
)

CHOOSE = (
    ("`[stt] base_url`", "Receives the audio of each turn."),
    ("`[brain.<name>] base_url`", "Receives what the answer brain "
     "receives (see OpenRouter above)."),
    ("`[recall] base_url`", "Receives memory text to embed, when "
     "`[recall] provider` is not `none`."),
    ("`[report] dsn`", "Receives typed error codes, only when set."),
    ("MCP servers you configure", "Receive the tool calls you "
     "approve."),
    ("`[images] allow`", "Hosts a picture may be fetched from."),
    ("`wispd import <https address>`", "One GET of the address you typed "
     "(https only, 256 KB), after which nothing is written until you read "
     "the full text and say yes."),
)


def _walk(root: pathlib.Path):
    for d in SCAN_DIRS:
        base = root / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and p.suffix in CODE_SUFFIX and not (
                        set(p.relative_to(root).parts) & SKIP_DIRS):
                    yield p
    for f in SCAN_FILES:
        if (root / f).is_file():
            yield root / f


def _strings(path: pathlib.Path):
    """Text to search, and whether a bare host name counts (Python
    strings only; in QML and JS a `a.b` is a property, so only a URL
    counts)."""
    text = path.read_text(errors="replace")
    if path.suffix == ".py" or path.name == "wispd":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            yield text, False
            return
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and len(n.value) < 600:
                yield n.value, True
    else:
        yield text, False


def scan(root: pathlib.Path = ROOT) -> dict:
    """{host: sorted source files naming it}. Loopback is left out."""
    found: dict = {}
    for p in _walk(root):
        rel = str(p.relative_to(root))
        for s, bare in _strings(p):
            for m in (HOST if bare else URL).finditer(LOOPBACK.sub("", s)):
                found.setdefault(m.group(1).lower(), set()).add(rel)
    return {h: sorted(f) for h, f in sorted(found.items())}


def unexplained(found: dict) -> list:
    """Hosts the code names that have no entry."""
    return [h for h in found if h not in HOSTS and h not in MENTIONS]


def stale_entries(found: dict) -> list:
    """Entries for hosts the code no longer names."""
    return [h for h in list(HOSTS) + list(MENTIONS) if h not in found]


def problems(root: pathlib.Path = ROOT) -> list:
    """Human-readable problems with the host list: a host the code names
    with no entry, or an entry for a host the code no longer names."""
    found = scan(root)
    out = [f"host {h} is named in the code ({', '.join(found[h][:3])}) "
           f"but has no entry in scripts/gen_trust.py"
           for h in unexplained(found)]
    out += [f"scripts/gen_trust.py has an entry for {h}, which no code "
            f"names any more" for h in stale_entries(found)]
    return out


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render(found: dict) -> str:
    out = [
        "# What leaves your machine",
        "",
        "<!-- Generated by scripts/gen_trust.py. Do not edit by hand: "
        "`python3 scripts/gen_trust.py` rewrites it and "
        "`tests/test_trust.py` fails when it is stale. -->",
        "",
        "Wisp is a voice assistant that listens when you hold the key "
        "and looks at your screen when you ask about it. This page "
        "lists every outside host its code can contact, what each one "
        "gets, who holds the key, and what you control. It is built "
        "from the source, and a test fails when a new host appears "
        "without an entry here.",
        "",
        "Nothing is sent between key presses. There is no analytics, no "
        "account and no Wisp server: each request goes from your "
        "machine to a provider you choose, with your key.",
        "",
        "## Hosts Wisp contacts",
        "",
        "| Host | What it is for | What it gets | On by default | Key | "
        "What you control |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for host, e in HOSTS.items():
        sends = ", ".join(e["sends"])
        out.append("| `%s` | %s | **%s.** %s | %s | %s | %s |" % (
            host, _cell(e["what"]), _cell(sends), _cell(e["detail"]),
            _cell(e["default"]), _cell(e["key"]), _cell(e["control"])))
    out += [
        "",
        "## Hosts you choose",
        "",
        "These settings take any address. Whatever you put there gets "
        "what the stage sends.",
        "",
        "| Setting | Receives |",
        "| --- | --- |",
    ]
    for k, v in CHOOSE:
        out.append(f"| {k} | {_cell(v)} |")
    out += [
        "",
        "## On this machine only",
        "",
        "Loopback addresses (`127.0.0.1`, `localhost`) are local "
        "services: whisper.cpp, a local model server (Ollama, LM "
        "Studio, MLX), the UI-grounding model, the browser debugging "
        "port and per-app control ports. A grounding model on loopback "
        "means screenshots never leave the box for that step.",
        "",
        "## Names in the code that are not requests",
        "",
        "| Name | What it is |",
        "| --- | --- |",
    ]
    for host, why in MENTIONS.items():
        out.append(f"| `{host}` | {_cell(why)} |")
    out += [
        "",
        "## Stored on this machine",
        "",
        "Everything below lives in `~/.local/share/wisp` (a 0700 "
        "folder of 0600 files), `~/.config/wisp` or your runtime directory, never in a "
        "synced or shared place.",
        "",
        "| What | Holds | How long, and your control |",
        "| --- | --- | --- |",
    ]
    for name, holds, ctl in STORES:
        out.append(f"| {_cell(name)} | {_cell(holds)} | {_cell(ctl)} |")
    out += ["", "## Never sent", ""]
    for n in NEVER:
        out.append(f"- {n}")
    out += [
        "",
        "## Where each host appears in the code",
        "",
        "From the scan this page is built from.",
        "",
    ]
    for host, files in found.items():
        shown = ", ".join(f"`{f}`" for f in files[:6])
        more = f" and {len(files) - 6} more" if len(files) > 6 else ""
        out.append(f"- `{host}`: {shown}{more}")
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when docs/TRUST.md is not up to date")
    a = ap.parse_args(argv)
    found = scan()
    bad = unexplained(found)
    if bad:
        print("gen_trust: hosts in the code with no entry: "
              + ", ".join(bad), file=sys.stderr)
        return 2
    text = render(found)
    if a.check:
        cur = OUT.read_text() if OUT.is_file() else ""
        if cur != text:
            print("docs/TRUST.md is stale: run python3 "
                  "scripts/gen_trust.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(found)} hosts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
