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
import re
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
for the app "{app}". Use exactly these sections, in this order:

## Overview        — what the app is and the 3 most common tasks
## Screens         — one line per screen/page: name — purpose
## Controls        — control — where it lives — what it does
## Workflows       — numbered click paths for the common tasks
## Tools           — APIs, CLIs or MCP tools that cover this app, or "none known"
## Verify before done — how to confirm an action worked before claiming it
## Gotchas         — modal traps, required logins, hidden states

Rules:
- Keep every control name verbatim from the descriptions.
- Populate every section from the descriptions. If a section has no
  evidence in the descriptions, write "unverified — needs a deeper
  capture" instead of inventing content.
- Never repeat the section spec as content. Workflows must be real
  numbered steps an operator could follow, e.g.:

  ## Workflows
  1. Compose a reply: open the thread → click the reply arrow at the
     bottom of the last message → type in the editor → Send.
  2. Search mail: click the search box top-center → type a query →
     Enter → results replace the list.

- No preamble — output only the section bodies.
{tools_note}"""


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


_TEMPLATE_ECHO = re.compile(r"^##\s+\w[^\n]*—", re.M)


def _assemble_fallback(app: str, parts: list, tools_note: str) -> str:
    """Deterministic merge when the brain echoes the template instead
    of merging — small local models do this. Screens/Controls come
    straight from the captures; reasoning sections stay honestly empty."""
    screens = [re.sub(r"^###\s*", "", p).split("\n", 1)[0].strip()
               for p in parts]
    body = [
        f"## Overview\n{app} — distilled from {len(parts)} captured "
        "screens. Common tasks: see Workflows.",
        "## Screens\n" + "\n".join(f"- {s}" for s in screens),
        "## Controls\n" + "\n".join(parts),
        "## Workflows\nunverified — needs a deeper capture",
        "## Tools\n" + (tools_note or "none known"),
        "## Verify before done\nunverified — needs a deeper capture",
        "## Gotchas\nunverified — needs a deeper capture",
    ]
    return "\n\n".join(body)


def merge(app: str, parts: list, spec: str, timeout: float,
          tools_note: str = "") -> str:
    cfg = {"brain": {"default": spec}}
    note = ("\nKnown tool coverage for this app (use in ## Tools): "
            + tools_note) if tools_note else ""
    prompt = (_MERGE.format(app=app, tools_note=note) + "\n\n"
              + "\n\n---\n\n".join(parts))
    body = brain.chat([{"role": "user", "content": prompt}],
                      cfg, timeout=timeout)["content"]
    if _TEMPLATE_ECHO.search(body):
        return _assemble_fallback(app, parts, tools_note)
    return body


_FRONTMATTER_WHITELIST = {
    "name", "description", "url_hosts", "app_classes", "asks",
    "tier", "provenance", "draft", "version",
}


def frontmatter(slug: str, app: str, hosts: list | None = None,
                classes: list | None = None, asks: list | None = None,
                provenance: str = "distilled", draft: bool = True) -> str:
    """Whitelist-only frontmatter — app skills are doc skills; `tool:`
    and foreign schema keys never reach the file."""
    lines = ["---", f"name: {slug}",
             f"description: UI map and workflows for {app} — "
             f"use when the user is in {app} or asks how to do "
             f"something in it"]
    if hosts:
        lines.append("url_hosts: " + ", ".join(hosts))
    if classes:
        lines.append("app_classes: " + ", ".join(classes))
    if asks:
        lines.append("asks: " + "; ".join(asks))
    lines.append("tier: safe")
    lines.append(f"provenance: {provenance}")
    if draft:
        lines.append("draft: first-run (unverified)")
    return "\n".join(lines) + "\n---\n\n"


def sanitize_frontmatter(text: str) -> str:
    """Strip non-whitelist keys from existing frontmatter — adapted or
    generated skills can never smuggle tool:/tier: or foreign schema."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return text
    keep = [ln for ln in m.group(1).splitlines()
            if ln.split(":", 1)[0].strip() in _FRONTMATTER_WHITELIST]
    return "---\n" + "\n".join(keep) + "\n---\n" + text[m.end():]


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
    ap.add_argument("--hosts", default="",
                    help="comma url_hosts for auto-inject, e.g. mail.google.com")
    ap.add_argument("--classes", default="",
                    help="comma app_classes for auto-inject")
    ap.add_argument("--asks", default="",
                    help="semicolon-separated example asks shown on match")
    ap.add_argument("--tools-note", default="",
                    help="known API/CLI/MCP coverage for the Tools section")
    ap.add_argument("--verified", action="store_true",
                    help="drop the first-run draft marker")
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

    body = merge(app, parts, a.provider, a.timeout,
                 tools_note=a.tools_note)
    outdir = a.out or SKILLS_DIR / a.slug
    outdir.mkdir(parents=True, exist_ok=True)
    fm = frontmatter(
        a.slug, app,
        hosts=[h.strip() for h in a.hosts.split(",") if h.strip()],
        classes=[c.strip() for c in a.classes.split(",") if c.strip()],
        asks=[q.strip() for q in a.asks.split(";") if q.strip()],
        draft=not a.verified)
    (outdir / "SKILL.md").write_text(fm + body + "\n")
    if a.keep_parts:
        (outdir / "parts.md").write_text("\n\n".join(parts) + "\n")
    print(f"wrote {outdir / 'SKILL.md'} "
          f"({len(parts)}/{len(caps)} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
