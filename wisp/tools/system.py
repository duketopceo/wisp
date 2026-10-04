"""System tools: notifications, screenshot, typing, guarded shell, file search."""
import pathlib
import shutil
import subprocess

from .. import cancel as _cancel
from .. import config
from .. import hypr
from ..pipeline import hypr_env, notify


def notify_tool(msg: str) -> str:
    notify(msg or "Wisp")
    return "NOTIFIED"


def screenshot(arg: str = "", cfg: dict | None = None) -> str:
    out = config.DATA_DIR / "shots"
    out.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    f = out / f"shot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    dom_page = (cfg or {}).get("screen", {}).get("dom_page")
    if dom_page:
        return _dom_shot(f, cfg)
    # arg or [screen] output names a single output to capture (grim -o)
    output = ((arg or "").strip()
              or (cfg or {}).get("screen", {}).get("output", ""))
    from .. import platform
    cmd = platform.screenshot_cmd(f, output or None)
    if not cmd:
        return (f"SKIP (no screenshot tool — "
                f"{platform.missing_deps_hint()})")
    try:
        # screencopy can stall forever on a powered-off panel (lid
        # closed) — never let it block the loop
        r = _cancel.run(cmd, capture_output=True, env=hypr_env(),
                           timeout=15)
    except subprocess.TimeoutExpired:
        f.unlink(missing_ok=True)
        return "SKIP (screenshot timed out — output powered off?)"
    if r.returncode == 0 and f.exists():
        _normalize_shot(f, output or None)
        return f"SHOT {f}"
    return "SKIP (screenshot failed)"


_DOM_SELECTOR = ("button,[id^=dot-],.shape,input,select,textarea,"
                 "#scroller,[onclick],.sq,.mail,.ln,.star,[data-file]")
_DOM_META = f"""
var n=0;
document.querySelectorAll('{_DOM_SELECTOR}').forEach(el=>{{
  var r=el.getBoundingClientRect(); if(r.width<3||r.height<3)return; n++;
}});
return JSON.stringify({{w:innerWidth,h:innerHeight,n}});
"""


def _dom_slice(start: int, end: int) -> str:
    return f"""
var els=[];
document.querySelectorAll('{_DOM_SELECTOR}').forEach(el=>{{
  var r=el.getBoundingClientRect(); if(r.width<3||r.height<3)return;
  els.push({{id:el.id||el.tagName.toLowerCase(),
    label:(el.textContent||el.placeholder||'').trim().slice(0,24),
    tag:el.tagName.toLowerCase(), x:Math.round(r.x),y:Math.round(r.y),
    w:Math.round(r.width),h:Math.round(r.height)}});
}});
return JSON.stringify({{els:els.slice({start},{end})}});
"""


def _dom_shot(path, cfg: dict) -> str:
    """Synthetic screenshot built from DOM element rects — a labeled
    schematic the model can aim at when compositor screencopy is
    unavailable (lid closed / panel off). Image pixels are viewport
    CSS px; cfg.screen.dom_origin holds the viewport's logical origin
    so click mapping stays 1:1."""
    screen = (cfg or {}).get("screen", {})
    page = screen.get("dom_page")
    from . import mcpclient
    import json as _j
    import re as _re
    def _eval(code):
        out = mcpclient.call(
            'browseros evaluate '
            + _j.dumps({"page": page, "code": code}), {})
        m = _re.search(r"\{.*\}", out, _re.S)
        try:
            return _j.loads(m.group(0)) if m else None
        except _j.JSONDecodeError:
            return None

    meta = _eval(_DOM_META)
    if not meta:
        return "SKIP (dom shot failed)"
    dom = {"w": meta.get("w", 0), "h": meta.get("h", 0), "els": []}
    n = meta.get("n", 0)
    # paginate: a dense page (chess board + apps) overflows the MCP
    # 4k response cap in a single shot
    for s in range(0, n, 40):
        chunk = _eval(_dom_slice(s, s + 40))
        if not chunk:
            return "SKIP (dom shot parse failed)"
        dom["els"].extend(chunk.get("els", []))
    w, h = dom.get("w", 0), dom.get("h", 0)
    if not w or not h:
        return "SKIP (dom shot: empty viewport)"
    # stash a textual legend — the caption reads exact centers so label
    # OCR isn't the weak link
    screen["dom_els"] = [
        f"{e.get('id','?')}@({e['x'] + e['w'] // 2},{e['y'] + e['h'] // 2})"
        for e in dom.get("els", [])][:90]
    magick = shutil.which("magick")
    if not magick:
        return "SKIP (no magick for dom shot)"
    # build an SVG schematic — one shape per interactive element,
    # labeled with its id so the model can name-check its target
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{w}" height="{h}">'
           f'<rect width="{w}" height="{h}" fill="#0b0b12"/>')
    # set-of-mark grid in the same CSS px space — the model reads the
    # printed coordinates to aim
    for gx in range(100, w, 100):
        svg += (f'<line x1="{gx}" y1="0" x2="{gx}" y2="{h}" '
                f'stroke="rgba(255,80,80,0.35)" stroke-width="1"/>')
    for gy in range(100, h, 100):
        svg += (f'<line x1="0" y1="{gy}" x2="{w}" y2="{gy}" '
                f'stroke="rgba(255,80,80,0.35)" stroke-width="1"/>')
    for gx in range(0, w, 100):
        svg += (f'<text x="{gx + 2}" y="12" fill="rgba(255,80,80,0.9)" '
                f'font-size="12">{gx}</text>')
    for gy in range(0, h, 100):
        svg += (f'<text x="2" y="{gy + 12}" fill="rgba(255,80,80,0.9)" '
                f'font-size="12">{gy}</text>')
    for e in dom.get("els", []):
        x, y, ew, eh = e["x"], e["y"], e["w"], e["h"]
        eid = str(e.get("id", ""))
        if "red" in eid:
            fill = "#ef5350"
        elif "green" in eid:
            fill = "#9ece6a"
        elif "blue" in eid or eid.startswith("dot-"):
            fill = "#7aa2f7"
        else:
            fill = "#24283b"
        cx = x + ew // 2
        cy = y + eh // 2
        # label carries the center coords — pixel-grounding of left-edge
        # elements is unreliable even with a grid, so we print the aim
        # point; the model still has to pick the right element
        label = (eid + " " + str(e.get("label", ""))).strip()
        label = (label.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;"))[:30]
        coords = f"({cx},{cy})"
        dot = eid.startswith("dot-") or e["tag"] == "circle"
        if e["tag"] == "circle" or eid.startswith("dot-"):
            svg += (f'<circle cx="{cx}" cy="{cy}" r="{min(ew, eh) // 2}"'
                    f' fill="{fill}"/>')
        else:
            svg += (f'<rect x="{x}" y="{y}" width="{ew}" height="{eh}"'
                    f' rx="6" fill="{fill}" stroke="#7aa2f7"/>')
        # two-line label — name above coords — so neighboring labels
        # can't merge; dots get their label below the small circle
        if dot:
            ly = cy + min(ew, eh) // 2 + 10
            svg += (f'<text x="{cx}" y="{ly}" fill="#c0caf5" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{label}</text>'
                    f'<text x="{cx}" y="{ly + 12}" fill="#f5c97b" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{coords}</text>')
        else:
            svg += (f'<text x="{cx}" y="{cy - 7}" fill="#c0caf5" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{label}</text>'
                    f'<text x="{cx}" y="{cy + 8}" fill="#f5c97b" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{coords}</text>')
        # aim point — a crosshair at the element's true center so the
        # model targets the point, not the label text
        svg += (f'<circle cx="{cx}" cy="{cy}" r="9" fill="none" '
                f'stroke="#ffffff" stroke-width="1.5"/>'
                f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="#ffffff"/>')
    svg += "</svg>"
    svgp = path.with_suffix(".svg")
    svgp.write_text(svg)
    r = _cancel.run([magick, str(svgp), str(path)],
                       capture_output=True, timeout=15)
    svgp.unlink(missing_ok=True)
    if r.returncode != 0 or not path.exists():
        return "SKIP (dom shot rasterize failed)"
    from .. import points
    o = screen.get("dom_origin")
    points.SHOT_ORIGIN = tuple(o) if o else (0, 0)
    return f"SHOT {path}"


def _normalize_shot(path, output: str | None = None) -> None:
    """Resize the shot to its logical size so image pixels == Hyprland
    logical coords, then overlay a labeled 100px grid (set-of-mark
    style) — models localize noticeably better when the coordinate
    space is printed on the image. Providers downscale big images
    server-side to an unknowable size, so feeding raw HiDPI pixels makes
    emitted coords un-mappable; pinning to logical size keeps
    click/move 1:1 regardless. Records the shot's logical origin in
    points.SHOT_ORIGIN so coordinate mapping stays exact for
    single-output captures."""
    from .. import points
    magick = shutil.which("magick")
    if not magick:
        return
    mons = points.monitors()
    if output:
        m = next((m for m in mons if m.get("name") == output), None)
        if not m:
            return
        s = float(m.get("scale", 1) or 1)
        x, y = m.get("x", 0), m.get("y", 0)
        w, h = round(m.get("width", 0) / s), round(m.get("height", 0) / s)
    else:
        x, y, w, h = points.logical_bbox(mons)
    if not w or not h:
        return
    points.SHOT_ORIGIN = (x, y)
    try:
        draw = " ".join(
            [f"line {gx},0 {gx},{h}" for gx in range(100, w, 100)]
            + [f"line 0,{gy} {w},{gy}" for gy in range(100, h, 100)]
            + [f"text {gx + 2},12 '{gx}'" for gx in range(0, w, 100)]
            + [f"text 2,{gy + 12} '{gy}'" for gy in range(0, h, 100)])
        _cancel.run(
            [magick, str(path), "-resize", f"{w}x{h}!",
             "-stroke", "rgba(255,80,80,0.45)", "-strokewidth", "1",
             "-fill", "rgba(255,80,80,0.9)", "-pointsize", "12",
             "-draw", draw, str(path)],
            capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def _dom_eval(cfg: dict, code: str) -> str:
    """Evaluate JS on the configured DOM page; returns the returned
    string value or an error description."""
    import json as _j
    import re as _re
    from . import mcpclient
    page = cfg.get("screen", {}).get("dom_page")
    out = mcpclient.call(
        'browseros evaluate '
        + _j.dumps({"page": page, "code": code}), cfg)
    m = _re.search(r"nonce=\w+ origin=[^\]]*\]", out)
    body = out[m.end():].strip() if m else out
    if body.startswith("Untrusted page content"):
        body = body.split("\n", 1)[-1].strip()
    body = body.split("[END_UNTRUSTED")[0].strip()
    if body.startswith('"') and body.endswith('"'):
        try:
            body = _j.loads(body)
        except Exception:
            pass
    return body


def type_text(text: str, cfg: dict | None = None) -> str:
    if not text:
        return "SKIP (nothing to type)"
    if (cfg or {}).get("screen", {}).get("dom_page"):
        esc = text.replace("\\", "\\\\").replace("'", "\\'")
        r = _dom_eval(cfg, (
            "var el=document.activeElement;"
            "if(!el||!(el.tagName==='INPUT'||el.tagName==='TEXTAREA'))"
            "return 'miss:no-focus';"
            "var s=el.selectionStart||0,e=el.selectionEnd||0;"
            "el.value=el.value.slice(0,s)+'%s'+el.value.slice(e);"
            "var p=s+%d;el.selectionStart=el.selectionEnd=p;"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));"
            "return 'typed:'+el.id" % (esc, len(text))))
        return ("TYPED" if r.startswith("typed:")
                else f"SKIP ({r[:60]})")
    from .. import platform
    cmd = platform.type_text_cmd(text)
    if not cmd:
        return (f"SKIP (no typer — {platform.missing_deps_hint()})")
    r = _cancel.run(cmd, capture_output=True, env=hypr_env())
    return "TYPED" if r.returncode == 0 else "SKIP (typer failed)"


_KEYCODES = {"esc": 1, "enter": 28, "tab": 15, "space": 57,
             "backspace": 14, "up": 103, "down": 108, "left": 105,
             "right": 106, "pageup": 104, "pagedown": 109,
             "home": 102, "end": 107}


def key(arg: str, cfg: dict | None = None) -> str:
    """Press a named key — 'enter', 'tab', 'down', 'pagedown', …"""
    name = (arg or "").strip().lower().replace(" ", "")
    name = {"return": "enter", "escape": "esc", "pgdn": "pagedown",
            "pgup": "pageup", "arrowdown": "down",
            "arrowup": "up"}.get(name, name)
    if (cfg or {}).get("screen", {}).get("dom_page"):
        r = _dom_eval(cfg, (
            "var el=document.activeElement||document.body;"
            "for(var t of ['keydown','keypress','keyup'])"
            "el.dispatchEvent(new KeyboardEvent(t,{key:'%s',"
            "bubbles:true}));"
            "if(el.tagName==='SELECT'){"
            "var k='%s';"
            "if(k==='down'||k==='up'){"
            "el.selectedIndex=Math.max(0,Math.min(el.options.length-1,"
            "el.selectedIndex+(k==='down'?1:-1)));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));}"
            "else if(k==='enter')"
            "el.dispatchEvent(new Event('change',{bubbles:true}));}"
            "return 'key:'+(el.id||el.tagName)+"
            "(el.tagName==='SELECT'?'='+el.value:'')"
            % (name, name)))
        return (f"KEY {r[4:]}" if r.startswith("key:")
                else f"SKIP ({r[:60]})")
    code = _KEYCODES.get(name)
    if code is None:
        return f"SKIP (unknown key {name!r})"
    r = _cancel.run(["ydotool", "key", f"{code}:1", f"{code}:0"],
                       capture_output=True, env=hypr_env())
    return "KEY" if r.returncode == 0 else "SKIP (ydotool key failed)"


def scroll(arg: str, cfg: dict | None = None) -> str:
    """Scroll — 'down'/'up'/'down 400' (px/wheel units)."""
    parts = (arg or "down").split()
    up = parts[0].lower() in ("up", "-")
    bottom = parts[0].lower() in ("bottom", "end") \
        or (len(parts) > 1 and parts[1].lower() in ("bottom", "end"))
    top = parts[0].lower() in ("top", "home")
    try:
        amt = abs(int(parts[1])) if len(parts) > 1 \
            and parts[1].isdigit() else 720
    except ValueError:
        amt = 720
    if (cfg or {}).get("screen", {}).get("dom_page"):
        if bottom:
            delta = "best.scrollTop=best.scrollHeight"
            wd = "99999"
        elif top:
            delta = "best.scrollTop=0"
            wd = "-99999"
        else:
            delta = "best.scrollTop+=%d" % (-amt if up else amt)
            wd = str(-amt if up else amt)
        r = _dom_eval(cfg, (
            "var best=null,bs=0;"
            "document.querySelectorAll('*').forEach(function(el){"
            "if(el===document.documentElement||el===document.body)return;"
            "var sh=el.scrollHeight-el.clientHeight;"
            "if(sh>10&&el.clientWidth>0){"
            "var s=el.clientWidth*el.clientHeight;"
            "if(s>bs){bs=s;best=el}}});"
            "if(!best)best=document.scrollingElement||"
            "document.documentElement;"
            "%s;"
            "best.dispatchEvent(new Event('scroll'));"
            "best.dispatchEvent(new WheelEvent('wheel',"
            "{deltaY:%s,bubbles:true}));"
            "return 'scroll:'+(best.id||best.tagName)+'@'+best.scrollTop"
            % (delta, wd)))
        return (f"SCROLLED {r[7:]}" if r.startswith("scroll:")
                else f"SKIP ({r[:60]})")
    if bottom:
        amt = 7200
    elif top:
        amt, up = 7200, True
    r = _cancel.run(
        ["ydotool", "mousemove", "--wheel",
         "-y", str(-amt if up else amt)],
        capture_output=True, env=hypr_env())
    return ("SCROLLED" if r.returncode == 0
            else "SKIP (ydotool wheel failed)")


def shell(cmd: str) -> str:
    """Guarded shell — denylist is enforced in tools.run upstream; this
    executes via the user's shell and captures a bounded result."""
    if not cmd:
        return "SKIP (empty command)"
    r = _cancel.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=60, env=hypr_env())
    out = (r.stdout or r.stderr).strip()[:200]
    return f"SHELL rc={r.returncode} {out}"


def search_files(pattern: str) -> str:
    """Name-based file search under ~, bounded to 10 hits."""
    if not pattern:
        return "SKIP (empty pattern)"
    hits = []
    try:
        for p in pathlib.Path(config.HOME).glob(f"**/*{pattern}*"):
            if len(hits) >= 10:
                break
            if ".git" in p.parts or p.is_dir() and p.name.startswith("."):
                continue
            hits.append(str(p))
    except OSError:
        pass
    if not hits:
        return f"SKIP (no files matching {pattern!r})"
    return "FOUND " + ", ".join(hits)


_XY = None  # compiled lazily


def _parse_xy(arg: str):
    """'x,y' (screenshot pixels) or 'x,y@logical' → logical (x, y)."""
    global _XY
    import re
    if _XY is None:
        _XY = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*(@logical)?\s*$")
    m = _XY.match(arg or "")
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if m.group(3):
        return x, y
    from .. import points
    mons = points.monitors()
    if points.img_space_is_logical():
        pts = points.canvas_to_logical([{"x": x, "y": y}], mons)
    else:
        pts = points.to_logical([{"x": x, "y": y}], mons)
    return pts[0]["x"], pts[0]["y"]


def _resolve_target_xy(arg: str, cfg: dict | None = None):
    """Resolve 'x,y', 'x,y@logical', or natural language element via decision grounding."""
    xy = _parse_xy(arg)
    if xy is not None:
        return xy
    # Attempt decision-agent visual grounding
    try:
        from .. import pipeline, grounding
        shot = pipeline.capture_screen()
        if shot and shot.exists():
            try:
                import base64
                b64 = base64.b64encode(shot.read_bytes()).decode()
                hint = "menu bar" if any(w in (arg or "").lower() for w in ("menu", "bar", "top", "panel")) else ""
                res = grounding.ground_element(b64, target_description=arg, region_hint=hint, cfg=cfg)
                if res:
                    from .. import points
                    pts = points.to_logical([{"x": res[0], "y": res[1]}], points.monitors())
                    return pts[0]["x"], pts[0]["y"]
            finally:
                shot.unlink(missing_ok=True)
    except Exception:
        pass
    return None


def _run_cmds(cmds: list) -> bool:
    for c in cmds:
        try:
            r = _cancel.run(c, capture_output=True, env=hypr_env(),
                            timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        if r.returncode != 0:
            return False
    return True


def _drive(x: int, y: int, backend: str, do_click: bool) -> bool:
    """Pointer precedence: cua (when it is the live backend) always
    wins, so the user's real cursor is never touched; otherwise a
    move-only goes over the Hyprland socket eval (no fork); everything
    else runs the backend's argv (hyprcursor+ydotool / ydotool / wlrctl).
    """
    from .. import platform
    if backend != "cua" and not do_click and platform.uses_hypr() \
            and hypr.run_lua(hypr.cursor_move(x, y)):
        return True
    return _run_cmds(platform.pointer_cmds(x, y, backend, click=do_click))


def _move_fallback(x: int, y: int, cfg: dict | None) -> bool:
    """cua move failed: hypr eval (if on Hyprland), then the next
    backend in auto order (hyprcursor -> ydotool -> wlrctl)."""
    from .. import platform
    if platform.uses_hypr() and hypr.run_lua(hypr.cursor_move(x, y)):
        return True
    nxt = platform.pointer_backend(cfg, exclude=("cua",))
    return bool(nxt) and _run_cmds(
        platform.pointer_cmds(x, y, nxt, click=False))


def _pointer(arg: str, cfg: dict | None, do_click: bool) -> str:
    """click/move shared core. Returns 'GUIDE(x,y) label' when the
    pointer is user-driven (mode=guide or no backend) — the act loop
    publishes the ghost cursor and treats it as a handoff, not a
    failure."""
    # DOM mode: arg is viewport CSS px straight off the schematic shot —
    # skip screenshot-space conversion entirely (no compositor needed;
    # works with the lid closed / panel powered off)
    dom_page = (cfg or {}).get("screen", {}).get("dom_page")
    if dom_page:
        import re as _re
        m = _re.match(r"^\s*(-?\d+)\s*,\s*(-?\d+)", arg or "")
        if not m:
            return "FAIL (arg must be 'x,y')"
        cx, cy = int(m.group(1)), int(m.group(2))
        if not do_click:
            return f"MOVED({cx},{cy})"
        from . import mcpclient
        import json as _j
        code = ("var el=document.elementFromPoint(%d,%d);"
                "if(!el)return 'miss:empty';"
                "el.dispatchEvent(new MouseEvent('click',"
                "{clientX:%d,clientY:%d,bubbles:true}));"
                "try{el.focus()}catch(e){}"
                "return 'hit:'+(el.id||el.tagName)"
                % (cx, cy, cx, cy))
        out = mcpclient.call(
            'browseros evaluate '
            + _j.dumps({"page": dom_page, "code": code}), cfg)
        import re as _re
        hm = _re.search(r"hit:(\S+)", out)
        return (f"CLICKED {hm.group(1)}" if hm
                else f"SKIP ({out[:60]})")
    xy = _resolve_target_xy(arg, cfg)
    if xy is None:
        return f"FAIL (could not resolve coordinates or ground target {arg!r})"
    x, y = xy
    from .. import platform
    backend = platform.pointer_backend(cfg)
    mode = (cfg or {}).get("pointer", {}).get("mode", "guide")
    if mode == "drive" and backend:
        verb = "click" if do_click else "move"
        # pointer.Registry owns precedence: a move falls through the
        # chain, a failed click is NOT retried elsewhere (double-click
        # risk) and the act loop re-observes instead.
        from .. import pointer
        reg = pointer.Registry(cfg)
        ok = (reg.click if do_click else reg.move)(
            x, y, backend=backend).ok
        if not ok:
            return f"SKIP ({verb} failed via {backend})"
        return f"{'CLICKED' if do_click else 'MOVED'}({x},{y})"
    # guide mode — ghost cursor carries the intent, the user clicks
    verb = "GUIDE" if do_click else "MOVE-GUIDE"
    reason = "" if mode == "guide" else " (no pointer backend)"
    return f"{verb}({x},{y}){reason}"


def click(arg: str, cfg: dict | None = None) -> str:
    return _pointer(arg, cfg, True)


def move(arg: str, cfg: dict | None = None) -> str:
    return _pointer(arg, cfg, False)


def ground(arg: str, cfg: dict | None = None) -> str:
    """Locate on-screen element center using decision-agent grounding."""
    xy = _resolve_target_xy(arg, cfg)
    if xy is None:
        return f"FAIL (could not ground target {arg!r})"
    return f"GROUNDED({xy[0]},{xy[1]})"


_CODEGRAPH_TOOLS = frozenset({
    "search_graph", "trace_path", "get_code_snippet", "query_graph",
    "get_architecture", "search_code", "detect_changes", "list_projects",
})

_CBM_BIN = "codebase-memory-mcp"


def codegraph(arg: str) -> str:
    """Read-only query against a repo's CBM code-graph index.
    arg: '<cbm-tool> <json-args>' — e.g.
    'search_graph {"project":"wisp","query":"State"}'."""
    parts = (arg or "").split(None, 1)
    if len(parts) < 2 or parts[0] not in _CODEGRAPH_TOOLS:
        return ("FAIL (usage: codegraph '<tool> <json-args>' — tools: "
                + ", ".join(sorted(_CODEGRAPH_TOOLS)) + ")")
    import json as _json
    try:
        _json.loads(parts[1])
    except _json.JSONDecodeError:
        return "FAIL (args must be a JSON object, e.g. {\"project\":..})"
    if shutil.which(_CBM_BIN) is None:
        return ("SKIP (codebase-memory-mcp not installed — "
                "no code-graph index available)")
    try:
        r = _cancel.run(
            [_CBM_BIN, "cli", "--quiet", "--json", parts[0], parts[1]],
            capture_output=True, text=True, timeout=30)
    except subprocess.SubprocessError as e:
        return f"SKIP (codegraph failed: {e})"
    out = (r.stdout or r.stderr).strip()
    return ("GRAPH " + out[:1500]) if out else f"SKIP (rc={r.returncode})"
