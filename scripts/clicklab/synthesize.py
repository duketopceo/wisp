#!/usr/bin/env python3
"""synthesize.py — generate task+oracle pairs from a live page's own
DOM/state inventory. This is the "for everyone" piece: tasks are not
hand-authored per app, they're synthesized from whatever interactive
surface is in front of the agent, then validated before use.

Every candidate oracle must:
  1. evaluate without throwing,
  2. return a boolean,
  3. be FALSE on the untouched page (an oracle that's already true
     verifies nothing — the classic synthesized-check degenerate case),
  4. reference state the page actually exposes.

Usage:
  synthesize.py --cdp 10.100.0.3:9223 --url file:///opt/lab/apps.html \
      --suite-name gen-apps --n 8 --out /tmp/gen.json
  # then: run.py --suite-file /tmp/gen.json --suite gen-apps --cdp ...
"""
import argparse
import base64
import json
import re
import sys
import time

# Inventory: every interactive element + its affordances + the score
# keys the page publishes (if any). Compact so it fits a prompt.
INVENTORY_JS = """
(function(){
var els=[];
document.querySelectorAll('button,input,select,textarea,a,[role=button],'
  +'[onclick],[data-act],[tabindex]').forEach(function(e){
  var r=e.getBoundingClientRect();
  if(r.width<2||r.height<2)return;
  var o={id:e.id||null,tag:e.tagName.toLowerCase(),
         txt:(e.textContent||'').trim().slice(0,40),
         x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
  if(e.tagName==='SELECT'){o.options=[];
    for(var i=0;i<e.options.length;i++)o.options.push(e.options[i].text);}
  if(e.tagName==='INPUT'){o.type=e.type;o.val=e.value;
    if(e.type==='range'){o.min=e.min;o.max=e.max;}}
  if(e.placeholder)o.ph=e.placeholder;
  els.push(o);});
var score=null;try{score=JSON.parse(JSON.stringify(window.__score||{}));}
catch(e){}
return JSON.stringify({title:document.title,url:location.href,
  n:els.length,els:els.slice(0,120),score:score});
})()
"""

PROMPT = """You are generating a verification suite for a GUI agent test.
Here is a live page's interactive inventory (JSON) and its exposed
state object `s` (= window.__score):

{inventory}

We also OBSERVED what actions do to `s` by probing the page — these
are ground truth, use them in checks instead of guessing:

{facts}

Propose {n} tasks an agent could plausibly perform by clicking, typing,
scrolling, and pressing keys. For each task emit:
  task  — one imperative sentence, specific (name the element/label)
  check — a JS expression body evaluated with `s` bound to
          window.__score; it must return true iff the task is done.
          You may also inspect the DOM (document.querySelector etc.).
          Start the body with `return `.

Rules:
- GROUND CHECKS IN THE OBSERVED FACTS — e.g. if a probe showed
  "click #tab-email → s.counts['tab-email']++", write
  `return (s.counts['tab-email']||0) > 0`, do NOT invent class names
  or state fields you haven't seen.
- Prefer `s.*` counters/events/moves over DOM predicates.
- Checks must be verifiable from page state alone (no timing, no
  network); keep tasks at 1-4 UI actions of difficulty; vary element
  types. Reply with ONLY a JSON array.
Example item: {{"task":"click the Settings tab","check":
"return (s.counts['tab-settings']||0) > 0"}}"""


def _eval(page, code):
    if hasattr(page, "evaluate"):
        return page.evaluate(code)
    import json as _j
    from wisp.tools import mcpclient
    return mcpclient.call('browseros-neo evaluate '
                          + _j.dumps({"page": page, "code": code}), {})


def _open(args):
    if args.cdp:
        host, _, port = args.cdp.partition(":")
        from wisp.tools import cdpx
        p = cdpx.open_page(host, args.url, int(port or 9222))
        time.sleep(1.5)
        return p
    return None


def _inventory(page):
    out = _eval(page, INVENTORY_JS)
    m = re.search(r"\{.*\}", out, re.S)
    return json.loads(m.group(0)) if m else None


def _validate(page, check):
    """Run the check on the untouched page. Pass iff it returns the
    boolean `false` — true means degenerate, exception means broken."""
    out = _eval(page, f"(function(){{var s=window.__score||{{}};{check}\n}})()")
    return out.strip() == "false"


SNAP_JS = "JSON.stringify(window.__score||{})"
RESTORE_JS = "(function(){window.__score=JSON.parse(atob('%s'));'ok'})()"


def _probe_battery(page, inv, max_probes=6):
    """Fire a click on each candidate element and diff window.__score
    before/after. Returns observed facts like
    "click on #tab-email → s.events+='tab-email', s.counts.tab-email=1".
    Oracles grounded in observed transitions beat model guesses."""
    facts, skip = [], []
    els = [e for e in inv.get("els", []) if e.get("id")]
    # prefer obviously-safe controls first
    els.sort(key=lambda e: any(k in (e.get("id") or "")
                               + (e.get("txt") or "").lower()
                               for k in ("send", "delete", "remove",
                                         "run", "exec")))
    for e in els[:max_probes]:
        eid = e["id"]
        before = _eval(page, SNAP_JS)
        _eval(page,
              f"var el=document.getElementById('{eid}');"
              "if(el)el.dispatchEvent(new MouseEvent('click',"
              "{bubbles:true}));'ok'")
        time.sleep(0.25)
        after = _eval(page, SNAP_JS)
        try:
            b, a = json.loads(before or "{}"), json.loads(after or "{}")
        except json.JSONDecodeError:
            skip.append(eid)
            continue
        diff = _score_diff(b, a)
        # restore pre-probe state so probes don't contaminate tasks
        _eval(page, RESTORE_JS % base64.b64encode(
            (before or "{}").encode()).decode())
        if diff:
            facts.append(f"click #{eid} → {diff}")
    return facts, skip


_MISSING = object()


def _score_diff(b: dict, a: dict, prefix="s") -> str:
    """Human-readable diff of two score snapshots."""
    out = []
    for k in sorted(set(b) | set(a)):
        pk, bv, av = f"{prefix}.{k}", b.get(k, _MISSING), a.get(k, _MISSING)
        if isinstance(bv, dict) and isinstance(av, dict):
            d = _score_diff(bv, av, prefix=pk)
            if d:
                out.append(d)
        elif bv is _MISSING:
            out.append(f"{pk}={json.dumps(av)} (new)")
        elif av is _MISSING:
            out.append(f"{pk} deleted")
        elif bv != av:
            if isinstance(bv, list) and isinstance(av, list):
                add = [x for x in av if x not in bv]
                out.append(f"{pk} += {json.dumps(add)}")
            else:
                out.append(f"{pk}: {json.dumps(bv)} → {json.dumps(av)}")
    return "; ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="")
    ap.add_argument("--url", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--suite-name", default="generated")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    page = _open(args)
    if page is None:
        raise SystemExit("only --cdp supported for now")
    inv = _inventory(page)
    if not inv:
        raise SystemExit("inventory failed — page reachable?")
    print(f"[synth] {inv['title']}: {inv['n']} interactive els, "
          f"score keys: {sorted((inv.get('score') or {}).keys())}")

    facts, _skip = _probe_battery(page, inv)
    print(f"[synth] probe battery observed {len(facts)} transitions")
    for f_ in facts[:8]:
        print(f"  {f_[:90]}")

    from wisp import config, brain
    cfg = config.load_config()
    inv_small = dict(inv); inv_small["els"] = inv["els"][:80]
    prompt = PROMPT.format(
        inventory=json.dumps(inv_small)[:12000],
        facts="\n".join(facts) or "(no observable transitions)",
        n=args.n)
    reply = brain.chat([{"role": "user", "content": prompt}], cfg)
    txt = reply.get("content", "") if isinstance(reply, dict) \
        else str(reply)
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        raise SystemExit(f"model returned no JSON array:\n{txt[:400]}")
    try:
        cands = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise SystemExit(f"bad JSON from model: {e}\n{m.group(0)[:300]}")

    good, bad = [], []
    for c in cands:
        t, chk = (c.get("task") or "").strip(), (c.get("check") or "").strip()
        if not t or not chk:
            bad.append((c, "empty"))
            continue
        if "return" not in chk:
            chk = "return " + chk
        # existence gate: every s.<root> referenced must be a real
        # score key; every querySelector arg must match something
        missing = [r for r in re.findall(r"\bs\.(\w+)", chk)
                   if r not in (inv.get("score") or {})]
        dead_sel = [sel for sel in
                    re.findall(r"querySelector[All]*\(['\"]([^'\"]+)",
                               chk)
                    if _eval(page, "!!document.querySelector("
                             + json.dumps(sel) + ")").strip() != "true"]
        if missing or dead_sel:
            bad.append((c, f"phantom refs: s.{missing} sel:{dead_sel}"))
            continue
        try:
            ok = _validate(page, chk)
        except Exception as e:
            bad.append((c, f"eval err {e}"))
            continue
        if ok:
            c["check"] = chk
            good.append(c)
        else:
            bad.append((c, "already-true/degenerate"))
    print(f"[synth] {len(good)}/{len(cands)} oracles validated")
    for c, why in bad:
        print(f"  drop: {(c.get('task') or '')[:60]} — {why}")

    suite = {args.suite_name: [[c["task"], c["check"], 0]
                               for c in good]}
    out = args.out or f"/tmp/suite-{args.suite_name}.json"
    with open(out, "w") as f:
        json.dump(suite, f, indent=1)
    print(f"[synth] wrote {out} ({len(good)} tasks)")


if __name__ == "__main__":
    main()
