"""Verify ladder + verdict model (U2, KTD2).

Every cua-recorded mutating step flows through a cheap-first ladder:

    action_truth refused  -> verdict refused (no compare, no judge)
    deny-listed surface visible / window list unreadable (R9)
                          -> verdict suppressed, turn-dir PNGs deleted
    delivered             -> run ALL applicable cheap rungs
        masked pixel diff at the predicted region (before.png vs
            after.png cropped to the predicted rect — PIL first,
            ImageMagick `compare` fallback)
        channel rungs from the registry (U3's control lane plugs in
            via register_rung; unregistered = abstains by absence)
    two rungs agree       -> verdict, corroborated: true
    one rung votes        -> verdict, corroborated: false (R2a: a lone
                           "region changed" or "region unchanged" is
                           down-weighted — symmetric)
    disagreement / mutual abstention
                          -> VLM judge on the before/after pair
        (image-pair brain.chat when supports_vision, or a named
        `[verify] vlm` provider — ask_jev is text-only, never used).
        Judge timeout/error/garbage -> unverifiable.

Unknown evidence NEVER resolves to `landed`: abstentions, missing
frames, dead judges and parse failures all land on `unverifiable`.

The verdict dict {verdict, source, corroborated, evidence, detail,
claim} rides the tool_result suffix in act.py, a `verify` trace event,
and the step record — the loop surfaces `missed` to the model rather
than auto-retrying (a forged negative must not become an action-
repetition primitive).
"""
import json
import pathlib
import re
import shutil
import time
from types import SimpleNamespace

from . import cua_safety

try:
    from PIL import Image, ImageChops
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

_VOTES = ("landed", "missed")
_XY = re.compile(r"(-?\d+)\s*,\s*(-?\d+)")


def _f(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def settings(cfg: dict | None) -> dict:
    v = (cfg or {}).get("verify", {}) or {}
    return {
        # named VLM judge endpoint: "provider:model" resolved through
        # the brain provider machinery (empty -> primary brain)
        "vlm": str(v.get("vlm") or "").strip(),
        "judge_timeout_s": _f(v.get("judge_timeout_s"), 20.0),
        # masked-diff thresholds: >=landed_min votes landed, <=missed_max
        # votes missed, between -> abstain (conservative: ambiguity pays
        # the judge, not a false verdict)
        "pixel_landed_min": _f(v.get("pixel_landed_min"), 0.02),
        "pixel_missed_max": _f(v.get("pixel_missed_max"), 0.001),
        "pixel_eps": int(_f(v.get("pixel_eps"), 16)),
        "region_px": int(_f(v.get("region_px"), 96)),
        "frame_wait_s": _f(v.get("frame_wait_s"), 0.5),
    }


class JudgeUnavailable(Exception):
    """The VLM judge cannot see this pair — endpoint absent, not
    vision-capable, or a frame won't encode. Always -> unverifiable."""


# ------------------------------------------------------------- rungs
#
# The rung registry: name -> fn(ctx) -> {"vote", "detail"}. `pixel`
# ships here; U3's control lane registers its diff hook as "control"
# when an app's channel exists — an unregistered channel simply
# abstains by absence (no entry, no vote).

def _abstain(detail: str) -> dict:
    return {"vote": "abstain", "detail": str(detail)[:120]}


def _pixel_rung(ctx) -> dict:
    """Masked pixel diff of before/after at the predicted region."""
    rect = (ctx.claim or {}).get("rect")
    if not rect:
        return _abstain("no predicted region")
    wait = ctx.st["frame_wait_s"]
    if not _wait_file(ctx.before, wait) \
            or not _wait_file(ctx.after, wait):
        return _abstain("frame missing")
    box = _frame_rect(rect, ctx.mons)
    frac = _diff_frac(ctx.before, ctx.after, box, ctx.st)
    if frac is None:
        return _abstain("no diff backend")
    if frac >= ctx.st["pixel_landed_min"]:
        return {"vote": "landed", "detail": f"region changed {frac:.1%}"}
    if frac <= ctx.st["pixel_missed_max"]:
        return {"vote": "missed",
                "detail": f"region unchanged ({frac:.3%})"}
    return _abstain(f"ambiguous change {frac:.2%}")


RUNGS = {"pixel": _pixel_rung}


def register_rung(name: str, fn) -> None:
    """Add/replace a verify rung. U3 registers its control-lane diff as
    "control" for apps with a channel — the same ctx contract applies:
    vote landed|missed|abstain plus a short detail."""
    RUNGS[str(name)] = fn


def unregister_rung(name: str) -> None:
    if name != "pixel":
        RUNGS.pop(name, None)


def _wait_file(path, seconds: float) -> bool:
    """The driver's after.png can lag its action.json — a short poll
    before abstaining (the same race match_turn's bounded wait covers
    in U1)."""
    p = pathlib.Path(path)
    deadline = time.monotonic() + seconds
    while True:
        try:
            if p.stat().st_size > 0:
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _frame_rect(rect, mons) -> list:
    """Logical (x,y,w,h) -> compositor-frame px. grim composites each
    output at logical_pos*scale, so a region lands at scale*s under
    the monitor containing its center. Scale 1 when nothing matches."""
    x, y, w, h = (float(v) for v in list(rect)[:4])
    cx, cy = x + w / 2.0, y + h / 2.0
    s = 1.0
    for m in mons or []:
        if not isinstance(m, dict):
            continue
        try:
            ms = float(m.get("scale", 1) or 1)
            mx, my = float(m.get("x", 0)), float(m.get("y", 0))
            mw, mh = float(m.get("width", 0)) / ms, \
                float(m.get("height", 0)) / ms
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if ms <= 0 or mw <= 0 or mh <= 0:
            continue
        if mx <= cx < mx + mw and my <= cy < my + mh:
            s = ms
            break
    return [int(round(x * s)), int(round(y * s)),
            int(round(w * s)), int(round(h * s))]


def _diff_frac(before, after, rect, st) -> float | None:
    """Fraction of region pixels differing past pixel_eps, or None to
    abstain. PIL in-process first; ImageMagick compare fallback."""
    if _PIL_AVAILABLE:
        return _diff_pil(before, after, rect, st["pixel_eps"])
    return _diff_magick(before, after, rect, st["pixel_eps"])


def _diff_pil(before, after, rect, eps: int):
    try:
        with Image.open(before) as a, Image.open(after) as b:
            if a.size != b.size:
                return None
            x0, y0 = max(0, rect[0]), max(0, rect[1])
            x1 = min(a.size[0], rect[0] + rect[2])
            y1 = min(a.size[1], rect[1] + rect[3])
            if x1 - x0 <= 0 or y1 - y0 <= 0:
                return None
            d = ImageChops.difference(
                a.convert("RGB").crop((x0, y0, x1, y1)),
                b.convert("RGB").crop((x0, y0, x1, y1)))
        # a change in ANY channel counts: per-pixel max across bands so
        # a hue-only flip still registers
        mx = None
        for band in d.split():
            mx = band if mx is None else ImageChops.lighter(mx, band)
        hist = mx.histogram()
        changed = sum(hist[eps + 1:])
        return changed / float((x1 - x0) * (y1 - y0))
    except Exception:
        return None


def _diff_magick(before, after, rect, eps: int):
    """Fraction of region pixels differing past eps via the ImageMagick
    pipeline: crop both to the region, per-pixel difference, per-pixel
    max across RGB bands (a hue-only flip still counts), threshold at
    eps, and %[fx:mean] of the binary = the changed fraction. `compare
    -metric AE` is a weighted sum, not a count — it can't do this."""
    im = shutil.which("magick") or shutil.which("convert")
    if not im:
        return None
    try:
        from . import cancel as _cancel
        idr = _cancel.run([im, "identify", "-format", "%w %h ",
                           str(before), str(after)],
                          capture_output=True, timeout=15)
        dims = (idr.stdout or b"").decode("utf-8", "replace").split()
        if len(dims) != 4 or dims[:2] != dims[2:]:
            return None
    except Exception:
        return None
    x, y, w, h = (int(v) for v in rect)
    cmd = [im, str(before), str(after),
           "-crop", f"{w}x{h}+{x}+{y}", "+repage",
           "-compose", "difference", "-composite",
           "-channel", "RGB", "-separate",
           "-evaluate-sequence", "max",
           "-threshold", f"{eps / 255 * 100:.1f}%",
           "-format", "%[fx:mean]", "info:"]
    try:
        r = _cancel.run(cmd, capture_output=True, timeout=15)
        if r.returncode != 0:
            return None
        return float((r.stdout or b"").decode("utf-8", "replace")
                     .strip())
    except Exception:
        return None


# -------------------------------------------------------- postcondition

def postcondition(name: str, arg: str = "", tool_arg: str = "",
                  tgt=None, cfg: dict | None = None) -> dict:
    """The claim the ladder verifies, predicted at dispatch: the
    element rect when grounding resolved one (a11y/control lane), else
    the target's pixel region, else a bare 'effect visible' claim the
    pixel rung abstains on and only the judge can score."""
    st = settings(cfg)
    rect = getattr(tgt, "rect", None) if tgt is not None else None
    if rect:
        try:
            r = [int(round(float(v))) for v in list(rect)[:4]]
        except (TypeError, ValueError):
            r = []
        if len(r) == 4:
            return {"kind": "element", "tool": name, "rect": r,
                    "label": getattr(tgt, "label", "") or ""}
    pt = None
    if tgt is not None:
        try:
            pt = (int(tgt.x), int(tgt.y))
        except (TypeError, ValueError, AttributeError):
            pt = None
    if pt is None:
        m = _XY.search(tool_arg or "") or _XY.search(arg or "")
        if m:
            pt = (int(m.group(1)), int(m.group(2)))
    if pt is None:
        return {"kind": "effect", "tool": name}
    side = st["region_px"]
    return {"kind": "region", "tool": name,
            "rect": [pt[0] - side // 2, pt[1] - side // 2, side, side],
            "point": [pt[0], pt[1]],
            "label": getattr(tgt, "label", "") if tgt else ""}


# ------------------------------------------------------------- privacy
#
# R9/KTD6: a deny-listed surface that is VISIBLE (a mapped client on a
# workspace some monitor shows — focus is irrelevant; credential
# dialogs render unfocused) suppresses capture entirely. An unreadable
# compositor window list suppresses too (fail-safe). Suppression is
# quarantine-by-deletion: no deny-interval frame survives the turn.

def _clients():
    from . import hypr
    return hypr.query("clients")


def _monitors():
    from . import points
    return points.monitors()


def _resolve(v, default_fn):
    """list|callable|None -> resolved value or None on any failure."""
    try:
        if callable(v):
            return v()
        if v is not None:
            return v
        return default_fn()
    except Exception:
        return None


def visible_deny(cfg, clients=None, monitors=None):
    """(offender|None, readable) — the mapped client of a deny-listed
    class on a visible workspace. `clients`/`monitors` take the
    compositor lists directly or as callables (None -> hypr socket).
    readable=False when the window list can't be fetched: the caller
    suppresses rather than captures."""
    try:
        if callable(clients):
            listing = clients()
        elif clients is not None:
            listing = clients
        else:
            listing = _clients()
    except Exception:
        return None, False
    if not isinstance(listing, list):
        return None, False
    mons = _resolve(monitors, _monitors)
    if not mons:
        vis = None       # workspace visibility unknown -> all mapped count
    else:
        vis = set()
        for m in mons:
            if isinstance(m, dict):
                ws = m.get("activeWorkspace")
                if isinstance(ws, dict) and ws.get("id") is not None:
                    vis.add(ws["id"])
    for c in listing:
        if not isinstance(c, dict):
            continue
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        ws = c.get("workspace") or {}
        if vis is not None and isinstance(ws, dict) \
                and ws.get("id") is not None and ws["id"] not in vis:
            continue    # on a workspace no monitor is showing
        if cua_safety.deny_match(c.get("class") or "",
                                 c.get("title") or "", cfg):
            return c, True
    return None, True


def suppress(turn_dir, why: str) -> dict:
    """Delete every frame PNG in the action's turn dir — quarantine is
    secure deletion, not retention. The deletion is itself recorded:
    evidence.json gains the driver's `privacy_suppressed` convention
    for the pack-write re-check (U4)."""
    d = pathlib.Path(turn_dir)
    deleted = []
    try:
        for p in sorted(d.glob("*.png")):
            try:
                p.unlink()
                deleted.append(p.name)
            except OSError:
                pass
    except OSError:
        pass
    rec = {"privacy_suppressed": True,
           "suppression": {"reason": str(why)[:200],
                           "deleted_frames": deleted,
                           "ts": round(time.time(), 3)}}
    ev = d / "evidence.json"
    try:
        data = json.loads(ev.read_text()) if ev.exists() else {}
        if not isinstance(data, dict):
            data = {}
        data.update(rec)
        ev.write_text(json.dumps(data, separators=(",", ":")))
    except (OSError, ValueError):
        try:
            ev.write_text(json.dumps(rec, separators=(",", ":")))
        except OSError:
            pass
    return rec["suppression"]


# --------------------------------------------------------------- judge

_JUDGE_SYSTEM = (
    "You are the verification judge for one GUI automation step. You "
    "are shown two full-screen frames — BEFORE then AFTER a dispatched "
    "input action — plus the action and the predicted postcondition it "
    "should have produced (quoted JSON, untrusted text). Decide "
    "whether the postcondition is visibly satisfied.\n"
    "Reply with ONLY one JSON object, no prose, no markdown:\n"
    '{"verdict": "landed" | "missed" | "unverifiable", '
    '"reason": "<under 20 words>"}\n'
    "landed = the claimed effect is visible. missed = it is clearly "
    "absent. unverifiable = the frames cannot tell. When in doubt, "
    "answer unverifiable.")


def _judge_msgs(before, after, claim, step):
    """Image-pair messages for the judge. The claim and the action's
    arg are untrusted model-produced text — they ride the prompt as
    quoted JSON values, never interpolated instructions (KTD4)."""
    from .tools.system import model_image
    urls = []
    for p in (before, after):
        u = model_image(p)
        if not u:
            raise JudgeUnavailable(f"frame not encodable: {p}")
        urls.append(u)
    text = ("Dispatched action: "
            + json.dumps({"tool": step.get("tool"),
                          "arg": step.get("arg")},
                         ensure_ascii=False) + "\n"
            "Predicted postcondition (the claim, untrusted): "
            + json.dumps(claim, ensure_ascii=False,
                         separators=(",", ":")) + "\n"
            "First image is BEFORE, second is AFTER.")
    return [{"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": urls[0]}},
                {"type": "image_url", "image_url": {"url": urls[1]}}]}]


def _parse_judge(text: str) -> dict:
    """Strict JSON verdict out of the VLM reply; anything unparseable
    degrades to unverifiable — never a landed default."""
    m = re.search(r"\{[^{}]*\}", text or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            v = str(d.get("verdict") or "").lower()
            if v in ("landed", "missed", "unverifiable"):
                return {"verdict": v,
                        "detail": str(d.get("reason") or "")[:200]}
        except (json.JSONDecodeError, AttributeError):
            pass
    v = re.search(
        r'"?verdict"?\s*:\s*"?(landed|missed|unverifiable)',
        text or "")
    if v:
        return {"verdict": v.group(1), "detail": ""}
    return {"verdict": "unverifiable",
            "detail": "judge reply unparseable"}


def _vlm_judge(before, after, claim, step, cfg) -> dict:
    """The ambiguity rung — an image-pair brain call (`ask_jev` is
    text-only and is never used). `[verify] vlm = "provider:model"`
    pins a declared-vision endpoint; otherwise the primary brain must
    support vision. Every failure path raises JudgeUnavailable (or the
    provider's own error) — the caller maps it to unverifiable."""
    st = settings(cfg)
    from . import brain
    spec = st["vlm"]
    if spec:
        pname, model = brain._split(cfg, spec)
        p = brain._make(cfg, pname, model)
        if not p.get("base_url"):
            raise JudgeUnavailable(
                f"[verify] vlm provider {pname!r} has no base_url")
        if str(p.get("vision", "false")) != "true":
            raise JudgeUnavailable(
                f"[verify] vlm provider {pname!r} is not vision-capable")
        resp = brain._chat_one(
            p, _judge_msgs(before, after, claim, step), None,
            st["judge_timeout_s"])
        from . import ledger
        ledger.note(p["name"], p["model"], p.get("paid"),
                    resp.get("usage") or {})
    else:
        if not brain.supports_vision(cfg):
            raise JudgeUnavailable(
                "primary brain is not vision-capable — set [verify] "
                "vlm to a named VLM provider")
        resp = brain.chat(_judge_msgs(before, after, claim, step),
                          cfg, timeout=st["judge_timeout_s"])
    txt = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    return _parse_judge(txt)


# -------------------------------------------------------------- ladder

def _mk(verdict: str, source: str, corroborated: bool, evidence: str,
        detail: str) -> dict:
    return {"verdict": verdict, "source": source,
            "corroborated": bool(corroborated), "evidence": evidence,
            "detail": (detail or "")[:300]}


def _ladder(step, claim, tdir, after_path, cfg, *, rungs, judge,
            monitors) -> dict:
    """All applicable cheap rungs vote; agreement corroborates,
    disagreement or mutual abstention escalates to the judge."""
    st = settings(cfg)
    mons = _resolve(monitors, _monitors) or []
    ctx = SimpleNamespace(
        step=step, claim=claim, cfg=cfg, st=st, turn_dir=tdir,
        before=tdir / "before.png",
        after=pathlib.Path(str(after_path)) if after_path
        else tdir / "after.png",
        mons=mons)
    rs = dict(RUNGS if rungs is None else rungs)
    votes, abstained = {}, []
    for rname in sorted(rs):
        try:
            r = rs[rname](ctx) or {}
        except Exception as e:
            r = {"vote": "abstain", "detail": f"rung error: {e}"}
        if r.get("vote") in _VOTES:
            votes[rname] = r
        else:
            abstained.append((rname, (r.get("detail") or "abstain")[:80]))
    evidence = str(tdir)
    distinct = {r["vote"] for r in votes.values()}
    if len(distinct) == 1:
        v = distinct.pop()
        return _mk(v, "+".join(sorted(votes)), len(votes) >= 2,
                   evidence,
                   "; ".join(f"{n}: {votes[n].get('detail', '')}"
                             for n in sorted(votes)))
    why = "rungs disagree" if len(distinct) > 1 \
        else "all rungs abstained"
    tally = "; ".join(
        [f"{n}: {votes[n]['vote']} ({votes[n].get('detail', '')})"
         for n in sorted(votes)]
        + [f"{n}: abstain ({d})" for n, d in abstained]) or "no rungs"
    fn = judge or _vlm_judge
    try:
        out = fn(ctx.before, ctx.after, claim, step, cfg) or {}
    except Exception as e:
        return _mk("unverifiable", "judge", False, evidence,
                   f"{why} ({tally}); judge error: {e}"[:300])
    v = str(out.get("verdict") or "").lower()
    detail = str(out.get("detail") or out.get("reason") or "")
    if v in _VOTES:
        # the judge confirmed on the full before/after pair — R2a's
        # label-grade path (judge-confirmation counts as corroboration)
        return _mk(v, "judge", True, evidence,
                   f"{why} ({tally}); judge: {detail}"[:300])
    return _mk("unverifiable", "judge", False, evidence,
               f"{why} ({tally}); judge: {detail or v or 'no verdict'}"
               [:300])


def _emit(turn, step, vd: dict, terminal: bool) -> None:
    """`verify` trace event — same emit shape as ground/ground_refused
    (kind = subsystem so `wispd trace --kind verify` works)."""
    try:
        from . import trace as _trace
        _trace.emit(turn or _trace.current(), "verify", "verify", {
            "tool": step.get("tool"),
            "turn_dir": vd.get("evidence"),
            "verdict": vd.get("verdict"),
            "source": vd.get("source"),
            "corroborated": vd.get("corroborated"),
            "claim": vd.get("claim"),
            "detail": (vd.get("detail") or "")[:200],
            "terminal": bool(terminal)})
    except Exception:
        pass


def verdict(step: dict, *, name: str = "", arg: str = "",
            tool_arg: str = "", tgt=None, claim: dict | None = None,
            after_path=None, cfg: dict | None = None,
            terminal: bool = False, turn: str | None = None,
            clients=None, monitors=None, rungs=None,
            judge=None) -> dict | None:
    """Run the ladder for one recorded step; return the verdict dict.

    None when the step wasn't recorded (no turn_dir — the U1
    `not_recorded` seed stands). Otherwise ALWAYS a dict: refused,
    suppressed, a rung verdict, judge's, or unverifiable."""
    tdir = step.get("turn_dir")
    if not tdir:
        return None
    cfg = cfg or {}
    tdir = pathlib.Path(str(tdir))
    if claim is None:
        claim = postcondition(
            name or step.get("tool", ""),
            arg or step.get("arg", ""),
            tool_arg or step.get("arg", ""), tgt, cfg)
    evidence = str(tdir)
    # R9 before ANY frame is read: the post-dispatch re-check catches
    # the credential dialog the click just spawned
    off, readable = visible_deny(cfg, clients=clients,
                               monitors=monitors)
    if not readable:
        suppress(tdir, "compositor window list unreadable")
        vd = _mk("suppressed", "privacy", False, evidence,
                 "window list unreadable — capture suppressed "
                 "(fail-safe)")
    elif off is not None:
        cls = off.get("class") or "?"
        suppress(tdir, f"deny-listed surface visible: {cls}")
        vd = _mk("suppressed", "privacy", False, evidence,
                 f"deny-listed surface {cls!r} on a visible workspace "
                 "— frames deleted")
    else:
        truth = step.get("action_truth") or {}
        if str(truth.get("effect") or "").lower() == "refused":
            vd = _mk("refused", "action_truth", False, evidence,
                     str(truth.get("refusal") or "dispatch refused"))
        else:
            vd = _ladder(step, claim, tdir, after_path, cfg,
                         rungs=rungs, judge=judge, monitors=monitors)
    if claim:
        vd["claim"] = claim
    _emit(turn, step, vd, terminal)
    return vd


def _capture(path) -> bool:
    """Fresh full-screen PNG at `path` via the platform screenshot
    command — raw compositor pixels, the same space the driver's
    before.png uses (no logical normalization)."""
    try:
        from . import cancel as _cancel
        from . import platform as _pf
        from .pipeline import hypr_env
        cmd = _pf.screenshot_cmd(pathlib.Path(path))
        if not cmd:
            return False
        r = _cancel.run(cmd, capture_output=True, env=hypr_env(),
                        timeout=15)
        return r.returncode == 0 and pathlib.Path(path).exists()
    except Exception:
        return False


def terminal_verdict(step: dict, *, cfg: dict | None = None,
                     claim: dict | None = None, turn: str | None = None,
                     clients=None, monitors=None, rungs=None,
                     judge=None, capture=None) -> dict | None:
    """R3: capture once more at loop exit and re-run the ladder for the
    turn's final recorded mutation — the driver's after.png can predate
    the effect rendering (the FilmCraft ~70px miss sat behind exactly
    this gap). Returns the fresh verdict, or None when capture failed
    (the recorded verdict stands)."""
    tdir = step.get("turn_dir")
    if not tdir:
        return None
    cfg = cfg or {}
    tdir = pathlib.Path(str(tdir))
    if claim is None:
        claim = (step.get("verify") or {}).get("claim")
    # the capture path gets its own R9 check BEFORE a frame is written
    off, readable = visible_deny(cfg, clients=clients,
                               monitors=monitors)
    if not readable:
        suppress(tdir, "compositor window list unreadable")
        vd = _mk("suppressed", "privacy", False, str(tdir),
                 "window list unreadable — capture suppressed "
                 "(fail-safe)")
    elif off is not None:
        cls = off.get("class") or "?"
        suppress(tdir, f"deny-listed surface visible: {cls}")
        vd = _mk("suppressed", "privacy", False, str(tdir),
                 f"deny-listed surface {cls!r} on a visible workspace "
                 "— frames deleted")
    else:
        cap = capture or _capture
        shot = tdir / "after_terminal.png"
        try:
            ok = bool(cap(shot))
        except Exception:
            ok = False
        if not ok:
            return None
        return verdict(step, claim=claim, after_path=shot, cfg=cfg,
                       terminal=True, turn=turn, clients=clients,
                       monitors=monitors, rungs=rungs, judge=judge)
    if claim:
        vd["claim"] = claim
    _emit(turn, step, vd, True)
    return vd
