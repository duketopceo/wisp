#!/usr/bin/env python3
"""Build the static landing page: site/ -> build/site/ (no framework, no
scripts, no third-party hosts).

    python3 scripts/site/build.py [--out build/site]

Fills `{{...}}` in site/index.html from README.md (install line, version),
site/costs.json (cost card) and site/compare.json (comparison table), and
copies the hero poster/video from assets/readme/ when a recording has been
published. Fails when the page would break a rule (see `check`).
"""
import argparse
import html
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SITE = ROOT / "site"
REPO = "https://github.com/duketopceo/wisp"
JOB = "Wisp is a voice teacher and doer for Omarchy that points at your screen."
INSTALL = ("git clone https://github.com/duketopceo/wisp && cd wisp && "
           "python3 wispd install")
BUDGET = 300 * 1024
URL = re.compile(r"""(?:src|href|action|data|poster)\s*=\s*["']?\s*"""
                 r"""((?:https?:)?//[^"'\s>]+)""", re.I)
CSS_URL = re.compile(r"url\(\s*[\"']?((?:https?:)?//[^)\"']+)", re.I)
OWN_HOSTS = ("github.com/duketopceo/",)


class SiteError(Exception):
    pass


def esc(s):
    return html.escape(str(s), quote=True)


def version_line() -> str:
    t = (ROOT / "README.md").read_text("utf-8")
    m = re.search(r"Status: v(\d+\.\d+) shipped", t)
    return f"Version {m.group(1)}." if m else ""


def cost_card(costs: dict) -> str:
    items = costs.get("items") or []
    rows = []
    for it in items:
        for k in ("label", "value", "source", "as_of"):
            if not it.get(k):
                raise SiteError(f"cost item missing {k}: {it}")
        rows.append(f"<tr><td>{esc(it['label'])}</td>"
                    f"<td><b>{esc(it['value'])}</b></td>"
                    f"<td class=\"mute\">{esc(it['source'])}, "
                    f"{esc(it['as_of'])}</td></tr>")
    pending = costs.get("status") != "measured"
    head = ('<p class="mute">Per-day numbers from the maintainer\'s own ledger '
            "are not published yet; below are the limits the code ships "
            "with.</p>" if pending else "")
    return (f'<div class="card">{head}<table><tr><th>What</th><th>Number</th>'
            f"<th>Where it comes from, and when</th></tr>{''.join(rows)}"
            f"</table><p class=\"mute\">{esc(costs.get('note', ''))}</p></div>")


def compare_table(c: dict) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in c["columns"])
    body = []
    for r in c["rows"]:
        cells = [f"<td>{esc(x)}</td>" for x in r[:-1]]
        src = r[-1]
        link = src.split(" ", 1)[0]
        note = src[len(link):].strip()
        cells.append(f'<td><a href="{esc(link)}">{esc(link)}</a> '
                     f"<span class=\"mute\">{esc(note)}</span></td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def hero(out: pathlib.Path) -> str:
    media = ROOT / "assets" / "readme"
    for mp4 in sorted(media.glob("*.mp4")):
        poster = mp4.with_name(mp4.name.replace(".mp4", ".poster.png"))
        if poster.is_file():
            shutil.copy2(poster, out / poster.name)
            shutil.copy2(mp4, out / mp4.name)
            return (f'<div class="hero"><video controls preload="none" '
                    f'poster="{esc(poster.name)}" width="1280" '
                    f'height="720"><source src="{esc(mp4.name)}" '
                    f'type="video/mp4"></video>'
                    '<p class="mute">A real turn, recorded unedited '
                    'apart from a crop.</p></div>')
    return ('<div class="hero card"><p class="mute">No recording is '
            'published yet. The scripts that make one are in '
            f'<a href="{REPO}/tree/master/scripts/demo">scripts/demo</a>.'
            "</p></div>")


def render(out) -> str:
    out = pathlib.Path(out)
    tpl = (SITE / "index.html").read_text("utf-8")
    costs = json.loads((SITE / "costs.json").read_text("utf-8"))
    cmp_ = json.loads((SITE / "compare.json").read_text("utf-8"))
    sub = {"install": esc(INSTALL), "repo": REPO,
           "version_line": esc(version_line()),
           "cost_card": cost_card(costs), "compare": compare_table(cmp_),
           "hero": hero(out)}
    for k, v in sub.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", tpl)
    if left:
        raise SiteError(f"unfilled placeholders: {left}")
    return tpl


def third_party(page: str, css: str = "") -> list:
    """External hosts the page would load or submit to. Links to the
    project's own GitHub, or plain <a href> citations, are not loads."""
    bad = []
    for m in URL.finditer(page):
        tag_start = page.rfind("<", 0, m.start())
        tag = page[tag_start:tag_start + 6].lower()
        if tag.startswith("<a "):
            continue
        bad.append(m.group(1))
    bad += CSS_URL.findall(css) + CSS_URL.findall(page)
    return bad


def check(out) -> list:
    out = pathlib.Path(out)
    page = (out / "index.html").read_text("utf-8")
    css = (out / "style.css").read_text("utf-8")
    problems = []
    first = page[:page.find("<h2")]
    if JOB not in first or INSTALL not in html.unescape(first):
        problems.append("the first screen must hold the job sentence and "
                        "the install line")
    if re.search(r"<script|<iframe|<form|@import", page + css, re.I):
        problems.append("no scripts, frames, forms or imports")
    if re.search(r"<link[^>]+(?:preload|prefetch|preconnect)", page, re.I):
        problems.append("no preloads")
    problems += [f"third-party load: {u}" for u in third_party(page, css)]
    size = (out / "index.html").stat().st_size + \
        (out / "style.css").stat().st_size + \
        sum(p.stat().st_size for p in out.glob("*.png"))
    if size > BUDGET:
        problems.append(f"page weighs {size} bytes (budget {BUDGET})")
    return problems


def build(out) -> pathlib.Path:
    out = pathlib.Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(SITE / "style.css", out / "style.css")
    (out / "index.html").write_text(render(out), "utf-8")
    (out / ".nojekyll").write_text("")
    problems = check(out)
    if problems:
        raise SiteError("; ".join(problems))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "build" / "site"))
    a = ap.parse_args(argv)
    try:
        out = build(a.out)
    except SiteError as e:
        print(f"site: {e}", file=sys.stderr)
        return 1
    size = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    print(f"site built in {out} ({size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
