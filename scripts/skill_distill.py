#!/usr/bin/env python3
"""Distill an app's UI into a wisp SKILL.md (spike/lfm-local).

Two inputs, same idea as HeyClicky's app skill files: walk an app's
screens, describe each, then merge the descriptions into one
progressive-disclosure skill any brain can use in-context.

    # from a crawl directory: images + optional <img>.txt notes
    python scripts/skill_distill.py perplexity-app \
        --crawl ~/shots/perplexity \
        --app "Perplexity web app (perplexity.ai)"

    # or an explicit manifest jsonl: {"image": "...", "note": "...", "page": "..."}
    python scripts/skill_distill.py perplexity-app --spec crawl.jsonl

Writes ~/.local/share/wisp/skills/<slug>/SKILL.md (or --out DIR).
The distilling brain is `--provider` (default the local lfm lane —
screenshots stay on the box; use openrouter:* for better prose at a
paid call per capture + one merge call).

Requires nothing but a reachable provider. The result is a draft —
review before trusting it: a wrong control name teaches wrong points.
"""
import argparse
import base64
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import brain, config  # noqa: E402

SKILLS_DIR = config.DATA_DIR / "skills"

_DESCRIBE = ("You are documenting an application's UI for a voice "
             "assistant that must point at and explain controls. "
             "Describe this screenshot: page/panel name, every visible "
             "control and where it sits (top bar, left rail, main "
             "pane), and what a user does here. Terse bullets.")

_MERGE = """Merge these per-screen descriptions into one SKILL.md body
for the app "{app}". Use exactly these sections:

## Overview        — what the app is and the 3 most common tasks
## Screens         — one line per screen/page: name — purpose
## Controls        — control — where it lives — what it does
## Workflows       — numbered click paths for the common tasks
## Gotchas         — modal traps, required logins, hidden states

Keep every control name verbatim from the descriptions. No preamble —
output only the section bodies.
"""


def _data_url(path: pathlib.Path) -> str:
    b = base64.b64encode(path.read_bytes()).decode()
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{b}"


def captures_from(crawl: pathlib.Path, spec: pathlib.Path | None) -> list:
    """[{image, page, note}] — images only are mandatory."""
    rows = []
    if spec:
        for line in spec.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["image"] = spec.parent / r["image"]
                rows.append(r)
    else:
        for img in sorted(crawl.iterdir()):
            if img.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            note = img.with_suffix(".txt")
            rows.append({"image": img, "page": img.stem,
                         "note": note.read_text().strip()
                         if note.exists() else ""})
    return [r for r in rows if pathlib.Path(r["image"]).exists()]


def describe(cap: dict, spec: str, timeout: float) -> str:
    prompt = _DESCRIBE
    if cap.get("note"):
        prompt += f"\nOperator note about this screen: {cap['note']}"
    if cap.get("page"):
        prompt += f"\nScreen is labelled: {cap['page']}"
    cfg = {"brain": {"default": spec}}
    msg = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": _data_url(pathlib.Path(cap["image"]))}}]}]
    return brain.chat(msg, cfg, timeout=timeout)["content"]


def merge(app: str, parts: list, spec: str, timeout: float) -> str:
    cfg = {"brain": {"default": spec}}
    prompt = _MERGE.format(app=app) + "\n\n" + "\n\n---\n\n".join(parts)
    return brain.chat([{"role": "user", "content": prompt}],
                      cfg, timeout=timeout)["content"]


def frontmatter(slug: str, app: str) -> str:
    return (f"---\nname: {slug}\n"
            f"description: UI map and workflows for {app} — "
            f"use when the user is in {app} or asks how to do "
            f"something in it\n---\n\n")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", help="skill dir name, e.g. perplexity-app")
    ap.add_argument("--crawl", type=pathlib.Path,
                    help="directory of screenshots (+ .txt notes)")
    ap.add_argument("--spec", type=pathlib.Path,
                    help="jsonl manifest of captures")
    ap.add_argument("--app", default="",
                    help="human app name for prompts/frontmatter")
    ap.add_argument("--provider", default="lfm:lfm25-vl-1.6b")
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="skill dir (default ~/.local/share/wisp/skills/<slug>)")
    ap.add_argument("--keep-parts", action="store_true",
                    help="write per-screen descriptions alongside SKILL.md")
    a = ap.parse_args(argv)

    if not a.crawl and not a.spec:
        ap.error("need --crawl DIR or --spec FILE")
    caps = captures_from(a.crawl or pathlib.Path("."), a.spec)
    if not caps:
        print("no captures found", file=sys.stderr)
        return 2

    app = a.app or a.slug
    parts = []
    for cap in caps:
        t0 = time.monotonic()
        try:
            d = describe(cap, a.provider, a.timeout)
        except Exception as e:                        # noqa: BLE001
            print(f"  {cap['image'].name}: FAILED {e}", file=sys.stderr)
            continue
        parts.append(f"### {cap.get('page') or cap['image'].name}\n{d}")
        print(f"  {cap['image'].name}: {round(time.monotonic()-t0)}s")
    if not parts:
        print("all captures failed", file=sys.stderr)
        return 2

    body = merge(app, parts, a.provider, a.timeout)
    outdir = a.out or SKILLS_DIR / a.slug
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "SKILL.md").write_text(frontmatter(a.slug, app) + body + "\n")
    if a.keep_parts:
        (outdir / "parts.md").write_text("\n\n".join(parts) + "\n")
    print(f"wrote {outdir / 'SKILL.md'} "
          f"({len(parts)}/{len(caps)} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
