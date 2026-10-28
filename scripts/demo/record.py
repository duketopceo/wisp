#!/usr/bin/env python3
"""Record a demo clip from a real Wisp turn, the same way every time.

    python3 scripts/demo/record.py --dry-run draw-and-teach
    python3 scripts/demo/record.py draw-and-teach --out build/demo
    python3 scripts/demo/record.py draw-and-teach --out build/demo --publish

A script (scripts/demo/scripts/<name>.md) lists the keys, speech and capture
commands. The harness starts `wf-recorder`, drives the real daemon with
`wispd trigger start|stop`, then checks the script's `proof:` line against
the decision log: a demo that did not do what it claims fails and writes
nothing. Before anything is encoded the whole-screen blanker (B9) rules are
applied to the video itself, and every text artefact is scrubbed. Nothing
here uploads, posts or sends anything: the output is files in --out.

Script format: `key: value` header lines, then `## steps` and `## captions`.
Steps: `show <text>`, `human <secs> <text>` (you do this), `say <secs>
"<words>"` (hold the talk key for secs; with --tts the words are spoken by
espeak-ng into the default output, otherwise speak them yourself), `wait
<secs>`, `run wispd ...` (only wispd is allowed).
"""
import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPTS = pathlib.Path(__file__).resolve().parent / "scripts"
CHANNELS = ("readme", "release", "omarchy", "x", "short")
VIDEO_CAP = 5 * 1024 * 1024
POSTER_CAP = 250 * 1024
WIDTH = 1280
SECRET = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{8,}|\bgh[pousr]_[A-Za-z0-9]{8,}|\bgithub_pat_"
    r"|\bxox[abprs]-|\bAKIA[0-9A-Z]{12,}|(?i:\bBearer\s+\S{6,})"
    r"|(?i:\b(?:api[_-]?key|token|secret|password)=\S+)")
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s\"':]+")


class DemoError(Exception):
    pass


# -- script parsing ---------------------------------------------------------

def load(name_or_path) -> dict:
    p = pathlib.Path(name_or_path)
    if not p.is_file():
        p = SCRIPTS / (str(name_or_path).removesuffix(".md") + ".md")
    if not p.is_file():
        raise DemoError(f"no such script: {name_or_path}")
    return parse(p.read_text("utf-8"), p.stem)


def parse(text: str, name: str) -> dict:
    s = {"name": name, "title": name, "length": 0, "setup": "", "proof": "",
         "steps": [], "captions": {}}
    section = "head"
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and section == "head":
            s["name"] = line[2:].strip() or name
        elif line.startswith("## "):
            section = line[3:].strip().lower()
            if section not in ("steps", "captions"):
                raise DemoError(f"{name}: unknown section {section!r}")
        elif not line.strip():
            continue
        elif section == "head":
            k, _, v = line.partition(":")
            if not _:
                raise DemoError(f"{name}: bad header line {line!r}")
            k, v = k.strip().lower(), v.strip()
            s[k] = int(v) if k == "length" else v
        elif section == "steps":
            if not line.startswith("- "):
                raise DemoError(f"{name}: bad step {line!r}")
            s["steps"].append(_step(line[2:].strip(), name))
        else:
            k, _, v = line.partition(":")
            if k.strip() not in CHANNELS:
                raise DemoError(f"{name}: unknown channel {k.strip()!r}")
            s["captions"][k.strip()] = v.strip()
    if not s["proof"]:
        raise DemoError(f"{name}: a script needs a `proof:` line")
    if not s["steps"]:
        raise DemoError(f"{name}: no steps")
    missing = [c for c in CHANNELS if c not in s["captions"]]
    if missing:
        raise DemoError(f"{name}: missing captions for {missing}")
    parse_proof(s["proof"])
    return s


def _step(body: str, name: str) -> dict:
    if body.startswith("show "):
        return {"verb": "show", "text": body[5:].strip()}
    try:
        parts = shlex.split(body)
    except ValueError as e:
        raise DemoError(f"{name}: {e}")
    verb, rest = (parts[0], parts[1:]) if parts else ("", [])
    try:
        if verb == "wait":
            return {"verb": "wait", "secs": float(rest[0])}
        if verb == "human":
            return {"verb": "human", "secs": float(rest[0]),
                    "text": " ".join(rest[1:])}
        if verb == "say":
            return {"verb": "say", "secs": float(rest[0]),
                    "text": " ".join(rest[1:])}
        if verb == "run":
            if not rest or rest[0] != "wispd":
                raise DemoError(f"{name}: run only allows wispd: {body!r}")
            return {"verb": "run", "argv": rest}
    except (IndexError, ValueError):
        pass
    raise DemoError(f"{name}: bad step {body!r}")


# -- proof ------------------------------------------------------------------

def parse_proof(spec: str) -> list:
    """`a.b=x && c~y && d>=3` -> [(path, op, value)]."""
    out = []
    for part in spec.split("&&"):
        m = re.fullmatch(r"\s*([A-Za-z0-9_.]+)\s*(>=|=|~)\s*(.+?)\s*", part)
        if not m:
            raise DemoError(f"bad proof condition {part!r}")
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _dig(rec, path):
    for k in path.split("."):
        if not isinstance(rec, dict) or k not in rec:
            return None
        rec = rec[k]
    return rec


def _holds(rec, cond) -> bool:
    path, op, want = cond
    got = _dig(rec, path)
    if got is None:
        return False
    if op == "=":
        return str(got).lower() == want.lower()
    if op == "~":
        return want.lower() in str(got).lower()
    try:
        return float(got) >= float(want)
    except (TypeError, ValueError):
        return False


def proof_ok(spec: str, records) -> tuple:
    """(ok, why): at least one decision record satisfies every condition."""
    conds = parse_proof(spec)
    for rec in records:
        if all(_holds(rec, c) for c in conds):
            return True, f"turn {rec.get('turn', '?')}"
    return False, f"no turn in the log satisfied `{spec}`"


def decisions_since(path, since_epoch: float) -> list:
    out = []
    try:
        lines = pathlib.Path(path).read_text("utf-8").splitlines()
    except OSError:
        return out
    from datetime import datetime
    for ln in lines:
        try:
            rec = json.loads(ln)
            ts = datetime.fromisoformat(rec["ts"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        if ts >= since_epoch:
            out.append(rec)
    return out


# -- plan (what the dry run prints) -----------------------------------------

def plan(script: dict, out_dir, tts=False) -> list:
    out = pathlib.Path(out_dir)
    raw = out / f"{script['name']}.raw.mkv"
    lines = [f"record: wf-recorder --audio -f {raw}",
             f"mic: default source, captured by wf-recorder --audio"]
    for st in script["steps"]:
        v = st["verb"]
        if v == "show":
            lines.append(f"note: {st['text']}")
        elif v == "human":
            lines.append(f"you ({st['secs']:g}s): {st['text']}")
        elif v == "wait":
            lines.append(f"wait {st['secs']:g}s")
        elif v == "run":
            lines.append("run: " + shlex.join(st["argv"]))
        else:
            lines.append("key: wispd trigger start")
            lines.append(f"speech ({st['secs']:g}s): " + (
                f"espeak-ng {shlex.quote(st['text'])}" if tts
                else f"you say: {st['text']}"))
            lines.append("key: wispd trigger stop")
    lines.append(f"proof: {script['proof']}  (checked against decisions.jsonl)")
    lines.append("blank: every sensitive window, sampled once a second "
                 "(the B9 rule), burned into the encode")
    lines.append(f"encode: {out}/{script['name']}.mp4 (<= {VIDEO_CAP // 1024}"
                 f" KB), {script['name']}.poster.png, "
                 f"{script['name']}.<channel>.txt x{len(CHANNELS)}")
    return lines


# -- redaction ---------------------------------------------------------------

def scrub_text(s: str) -> str:
    s = HOME_PATH.sub("~", str(s))
    home = os.path.expanduser("~")
    if home and home not in ("/", "~"):
        s = s.replace(home, "~")
    return SECRET.sub("[redacted]", s)


def leaks(text: str) -> list:
    return [m.group(0) for r in (HOME_PATH, SECRET) for m in r.finditer(text)]


def drawbox_filter(timeline, bbox, size) -> str:
    """ffmpeg filter that blacks out each sampled sensitive rect for the
    second it was seen. `timeline` is [(t_seconds, [(x, y, w, h), ...])];
    bbox is the captured logical area, size the video (w, h)."""
    from wisp import redact
    parts = []
    for i, (t, rects) in enumerate(timeline):
        t_end = timeline[i + 1][0] if i + 1 < len(timeline) else t + 1.0
        for r in rects:
            b = redact._to_pixels(r, bbox, *size)
            if b:
                x0, y0, x1, y1 = b
                parts.append(
                    f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:"
                    f"color=black:t=fill:enable='between(t,{t:g},{t_end:g})'")
    return ",".join(parts)


def ocr_findings(frames, ocr=None) -> list:
    """Frames whose text shows a home path or a token. Needs tesseract;
    without it returns None (the caller says it was not checked)."""
    exe = shutil.which("tesseract")
    if ocr is None and not exe:
        return None
    ocr = ocr or (lambda f: subprocess.run(
        [exe, str(f), "-", "--psm", "11"], capture_output=True, text=True,
        timeout=60).stdout)
    out = []
    for f in frames:
        hit = leaks(ocr(f))
        if hit:
            out.append((str(f), hit))
    return out


# -- README hero ---------------------------------------------------------------

HERO_START, HERO_END = "<!-- hero:start -->", "<!-- hero:end -->"


def hero_block(name, title) -> str:
    return (f"{HERO_START}\n[![{title}](assets/readme/{name}.poster.png)]"
            f"(assets/readme/{name}.mp4)\n{HERO_END}")


def patch_readme(text: str, name: str, title: str) -> str:
    if HERO_START not in text or HERO_END not in text:
        raise DemoError("README has no hero markers")
    a = text.index(HERO_START)
    b = text.index(HERO_END) + len(HERO_END)
    return text[:a] + hero_block(name, title) + text[b:]


# -- the real run --------------------------------------------------------------

def _need(*tools):
    miss = [t for t in tools if not shutil.which(t)]
    if miss:
        raise DemoError("missing tools: " + ", ".join(miss))


def _sh(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def record(script, out_dir, tts=False, publish=False, cfg=None) -> dict:
    _need("wf-recorder", "ffmpeg", "ffprobe", "wispd")
    from wisp import config, redact
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = script["name"]
    raw = out / f"{name}.raw.mkv"
    start = time.time()
    rec = subprocess.Popen(["wf-recorder", "--audio", "-f", str(raw)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    timeline = []
    t0 = time.monotonic()

    def sample():
        found, readable = redact.rects(cfg or {})
        if not readable:
            raise DemoError("the window list could not be read: refusing to "
                            "record an unblanked screen")
        timeline.append((round(time.monotonic() - t0, 1), found))

    def pause(secs):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            sample()
            time.sleep(min(1.0, max(0.0, end - time.monotonic())))
    try:
        time.sleep(1.0)
        for st in script["steps"]:
            v = st["verb"]
            if v == "show":
                print(f"  {st['text']}")
            elif v == "human":
                print(f"  YOU: {st['text']}")
                pause(st["secs"])
            elif v == "wait":
                pause(st["secs"])
            elif v == "run":
                _sh(st["argv"])
            else:
                _sh(["wispd", "trigger", "start"])
                if tts and shutil.which("espeak-ng"):
                    subprocess.Popen(["espeak-ng", st["text"]])
                else:
                    print(f"  SAY: {st['text']}")
                pause(st["secs"])
                _sh(["wispd", "trigger", "stop"])
    finally:
        rec.terminate()
        rec.wait(timeout=20)
    ok, why = proof_ok(script["proof"],
                       decisions_since(config.DECISIONS, start))
    if not ok:
        raw.unlink(missing_ok=True)
        raise DemoError(f"proof failed, nothing kept: {why}")
    return finish(script, raw, out, timeline, publish)


def finish(script, raw, out, timeline, publish=False) -> dict:
    from wisp import points
    name = script["name"]
    probe = _sh(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0",
                 str(raw)]).stdout.strip()
    try:
        w, h = (int(x) for x in probe.split(","))
    except ValueError:
        raise DemoError("could not read the recording size")
    bbox = points.logical_bbox(points.monitors())
    vf = drawbox_filter(timeline, bbox, (w, h))
    scale = f"scale={WIDTH}:-2"
    flt = f"{vf},{scale}" if vf else scale
    mp4, poster = out / f"{name}.mp4", out / f"{name}.poster.png"
    for crf in (28, 33):
        r = _sh(["ffmpeg", "-y", "-i", str(raw), "-vf", flt, "-c:v",
                 "libx264", "-crf", str(crf), "-preset", "slow", "-c:a",
                 "aac", "-b:a", "64k", "-movflags", "+faststart", str(mp4)])
        if r.returncode != 0:
            raise DemoError("ffmpeg failed: " + scrub_text(r.stderr[-300:]))
        if mp4.stat().st_size <= VIDEO_CAP:
            break
    else:
        raise DemoError(f"{mp4.name} is over {VIDEO_CAP // 1024} KB; cut the "
                        "script shorter")
    _sh(["ffmpeg", "-y", "-ss", str(max(1, script["length"] // 2)), "-i",
         str(mp4), "-frames:v", "1", "-vf", f"scale={WIDTH // 2}:-2",
         str(poster)])
    if not poster.is_file() or poster.stat().st_size > POSTER_CAP:
        raise DemoError("poster missing or over the size cap")
    frames_dir = out / f"{name}.frames"
    frames_dir.mkdir(exist_ok=True)
    _sh(["ffmpeg", "-y", "-i", str(mp4), "-vf", "fps=1", str(frames_dir /
         "f%04d.png")])
    frames = sorted(frames_dir.glob("f*.png"))
    found = ocr_findings(frames)
    if found:
        for p in (mp4, poster):
            p.unlink(missing_ok=True)
        raise DemoError("a path or token is visible in the frames: " +
                        scrub_text(json.dumps(found)[:200]))
    shutil.rmtree(frames_dir, ignore_errors=True)
    raw.unlink(missing_ok=True)
    caps = write_captions(script, out)
    res = {"mp4": str(mp4), "poster": str(poster), "captions": caps,
           "ocr": "checked" if found is not None else "not checked "
                                                      "(no tesseract)"}
    if publish:
        dst = ROOT / "assets" / "readme"
        for p in (mp4, poster):
            shutil.copy2(p, dst / p.name)
        rd = ROOT / "README.md"
        rd.write_text(patch_readme(rd.read_text("utf-8"), name,
                                   script["title"]), "utf-8")
        res["published"] = str(dst)
    return res


def write_captions(script, out) -> list:
    paths = []
    for ch in CHANNELS:
        text = scrub_text(script["captions"][ch])
        if leaks(text):
            raise DemoError(f"caption {ch} leaks a path or token")
        p = pathlib.Path(out) / f"{script['name']}.{ch}.txt"
        p.write_text(text + "\n", "utf-8")
        paths.append(str(p))
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("script", nargs="?", help="script name or path")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan; record nothing")
    ap.add_argument("--out", default="build/demo")
    ap.add_argument("--tts", action="store_true",
                    help="speak the words with espeak-ng")
    ap.add_argument("--publish", action="store_true",
                    help="copy the clip into assets/readme and the README "
                         "hero block (still posts nothing)")
    a = ap.parse_args(argv)
    if a.list:
        for p in sorted(SCRIPTS.glob("*.md")):
            print(p.stem)
        return 0
    if not a.script:
        ap.error("a script name is required")
    try:
        s = load(a.script)
        if a.dry_run:
            print(f"{s['name']}: {s['title']} ({s['length']}s)")
            print(f"setup: {s['setup']}")
            print("\n".join(plan(s, a.out, a.tts)))
            return 0
        sys.path.insert(0, str(ROOT))
        res = record(s, a.out, a.tts, a.publish)
    except DemoError as e:
        print(f"demo: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
