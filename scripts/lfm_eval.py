#!/usr/bin/env python3
"""Gate-eval a local LFM brain against a reference provider (spike/lfm-local).

    python scripts/lfm_eval.py tests/fixtures/lfm_gate.jsonl \
        --lfm "lfm:lfm25-vl-1.6b" --ref "openrouter:google/gemini-2.5-flash"

Each fixture row decides one screen-QA or text prompt:

    {"name": "dialog", "image": "images/shot.png", "prompt": "...",
     "expect": ["export", "file menu"]}            # all substrings
    {"name": "route", "prompt": "open firefox",
     "expect_any": ["launch", "act"]}              # any substring

`image` is fixture-relative. Providers resolve through wisp's own
[brain] registry (`provider:model`); `lfm:` hits the llama.cpp mtmd
server on :8082 (scripts/lfm-serve), `openrouter:` is a real paid call
— pass it only with keys and budget consent. Nothing is written except
--out JSON.

Gates (defaults, override via flags):
  --max-p50-ms 400    lfm p50 latency ceiling
  --min-gap 0.10      lfm accuracy must be >= ref accuracy - gap
  --min-acc 0.5       absolute lfm accuracy floor

Exit status 0 when every gate passes; 1 on gate failure; 2 on usage or
environment errors (server down, no fixtures scored).
"""
import argparse
import json
import pathlib
import statistics
import sys
import time
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import brain  # noqa: E402


def load_rows(path: pathlib.Path) -> list:
    rows = []
    if path.suffix == ".jsonl":
        lines = path.read_text().splitlines()
        rows = [json.loads(l) for l in lines if l.strip()]
    else:
        doc = json.loads(path.read_text())
        rows = doc if isinstance(doc, list) else [doc]
    for r in rows:
        r["_dir"] = path.parent
    return [r for r in rows if r.get("name") and r.get("prompt")]


def _image_url(row: dict) -> str | None:
    img = row.get("image")
    if not img:
        return None
    from wisp.tools.system import model_image
    return model_image(row["_dir"] / img)


def _messages(row: dict) -> list:
    url = _image_url(row)
    if not url:
        return [{"role": "user", "content": row["prompt"]}]
    return [{"role": "user", "content": [
        {"type": "text", "text": row["prompt"]},
        {"type": "image_url", "image_url": {"url": url}}]}]


def score(row: dict, content: str) -> bool:
    """True when the reply satisfies the fixture's expectation."""
    text = (content or "").lower()
    if row.get("expect"):
        return all(s.lower() in text for s in row["expect"])
    if row.get("expect_any"):
        return any(s.lower() in text for s in row["expect_any"])
    return bool(text.strip())


def run_provider(spec: str, rows: list, timeout: float) -> list:
    """[{'ms', 'content', 'ok', 'error'}] per row, same order."""
    cfg = {"brain": {"default": spec}}
    out = []
    for row in rows:
        t0 = time.monotonic()
        try:
            res = brain.chat(_messages(row), cfg, timeout=timeout)
            ms = round((time.monotonic() - t0) * 1000)
            content = res.get("content") or ""
            out.append({"ms": ms, "content": content,
                        "ok": score(row, content), "error": ""})
        except Exception as e:                        # noqa: BLE001
            ms = round((time.monotonic() - t0) * 1000)
            out.append({"ms": ms, "content": "", "ok": False,
                        "error": f"{type(e).__name__}: {e}"})
    return out


def summarize(results: list) -> dict:
    ok = [r for r in results if not r["error"]]
    acc = (sum(r["ok"] for r in results) / len(results)) if results else 0
    p50 = round(statistics.median([r["ms"] for r in ok])) if ok else None
    return {"n": len(results), "answered": len(ok), "accuracy": acc,
            "p50_ms": p50}


def gates(lfm: dict, ref: dict | None, max_p50_ms: int, min_gap: float,
          min_acc: float) -> list:
    """[(gate, detail, pass)] rows."""
    out = []
    p50 = lfm.get("p50_ms")
    out.append(("latency p50 <= %dms" % max_p50_ms,
                f"{p50}ms" if p50 is not None else "no answers",
                p50 is not None and p50 <= max_p50_ms))
    acc = lfm.get("accuracy", 0)
    out.append(("accuracy >= %.2f" % min_acc, f"{acc:.2f}",
                acc >= min_acc))
    if ref is not None:
        gap = ref["accuracy"] - acc
        out.append(("within %.2f of ref" % min_gap,
                    f"ref {ref['accuracy']:.2f} vs lfm {acc:.2f}",
                    gap <= min_gap))
    return out


def table(rows: list, cols: list) -> str:
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows))
         for i, c in enumerate(cols)]
    head = "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols))
    body = ["  ".join(str(r[i]).ljust(w[i]) for i in range(len(cols)))
            for r in rows]
    return "\n".join([head] + body)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixtures")
    ap.add_argument("--lfm", default="lfm:lfm25-vl-1.6b",
                    help="local provider spec (default lfm:lfm25-vl-1.6b)")
    ap.add_argument("--ref", default="",
                    help="reference provider spec, e.g. "
                         "openrouter:google/gemini-2.5-flash (paid call)")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--max-p50-ms", type=int, default=400)
    ap.add_argument("--min-gap", type=float, default=0.10)
    ap.add_argument("--min-acc", type=float, default=0.5)
    ap.add_argument("--out", help="write raw results JSON here")
    a = ap.parse_args(argv)

    path = pathlib.Path(a.fixtures)
    if not path.exists():
        print(f"fixture file not found: {path}", file=sys.stderr)
        return 2
    rows = load_rows(path)
    if not rows:
        print(f"no scorable fixtures in {path}", file=sys.stderr)
        return 2

    lfm_res = run_provider(a.lfm, rows, a.timeout)
    ref_res = run_provider(a.ref, rows, a.timeout) if a.ref else None
    lfm, ref = summarize(lfm_res), summarize(ref_res) if ref_res else None

    table_rows = []
    for i, r in enumerate(rows):
        l, rr = lfm_res[i], (ref_res[i] if ref_res else None)
        table_rows.append([
            r["name"],
            "ok" if l["ok"] else ("ERR" if l["error"] else "miss"),
            l["ms"],
            ("ok" if rr["ok"] else ("ERR" if rr["error"] else "miss"))
            if rr else "-", rr["ms"] if rr else "-"])
    print(table(table_rows, ["fixture", "lfm", "ms", "ref", "ms"]))
    if ref:
        print(f"\nref {a.ref}: acc {ref['accuracy']:.2f}, "
              f"p50 {ref['p50_ms']}ms")
    print(f"lfm {a.lfm}: acc {lfm['accuracy']:.2f}, "
          f"p50 {lfm['p50_ms']}ms")
    for name, detail, ok in gates(lfm, ref, a.max_p50_ms, a.min_gap,
                                  a.min_acc):
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")

    if a.out:
        pathlib.Path(a.out).write_text(json.dumps({
            "lfm": {"spec": a.lfm, "summary": lfm, "rows": lfm_res},
            "ref": ({"spec": a.ref, "summary": ref, "rows": ref_res}
                    if ref else None)}, indent=1) + "\n")
    return 0 if all(ok for _, _, ok in
                    gates(lfm, ref, a.max_p50_ms, a.min_gap, a.min_acc)) \
        else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
