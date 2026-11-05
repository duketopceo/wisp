"""The accessibility element tree behind pointing (teaching plan U7, KTD4).

The model proposes a point; the tree disposes. `ElementTree` is the small
interface the snap code in `walkthrough_run.snap_point` talks to:

    state()            -> (OK | UNAVAILABLE | UNBOUND, reason)
    app_name()         -> the accessibility app name of the focused toplevel
    focused_frame()    -> (x, y, w, h) of that toplevel, logical global px
    find_by_label(s)   -> [Element] whose accessible name matches s
    at_point(x, y)     -> the smallest non-container Element holding the point
    rect(element)      -> (x, y, w, h), logical global px
    occluded(rect)     -> True when another window covers the rect

Three implementations: `AtspiTree` (Linux AT-SPI), `UnavailableTree` (what
`default_tree()` returns when AT-SPI cannot be reached) and
`tests/fakes/elementtree.py` (served from recorded JSON fixtures).

AT-SPI client choice: system GObject introspection (`gi`, `Atspi-2.0`),
imported lazily. The package keeps no runtime dependencies; without the
system package the tree reports UNAVAILABLE and pointing falls back to the
model's own box. Direct D-Bus was rejected: it would re-implement the
registry walk, the state sets and the coordinate types that Atspi already
gives, for no gain. See docs/LINUX.md.

Binding rule. Wayland gives no screen coordinates to clients, so AT-SPI
extents are read in WINDOW coordinates and moved into the logical global
frame by adding the origin of the focused toplevel, which Hyprland owns.
The tree binds only to the toplevel that (a) belongs to the application of
the Hyprland-focused window (same pid, else same app name) and (b) is the
ACTIVE frame, or the one frame whose title matches. Anything ambiguous is
UNBOUND, never guessed (docs/research/cua-tool-catalog.md:
`accessibility_window_identity_unproven`).
"""
from __future__ import annotations

import dataclasses
import json
import time

OK = "ok"
UNAVAILABLE = "unavailable"     # no AT-SPI client or bus: say so, once
UNBOUND = "unbound"             # AT-SPI is up but no toplevel can be bound

FIXTURE_FORMAT = "wisp-elementtree/1"

# Walk limits. Starting bounds, not measurements: the live read-only probe
# in the U7 PR body walked a typical GTK4 app in well under the budget, and
# the U1 harness per-app snap share is what should retune them.
MAX_NODES = 3000
MAX_DEPTH = 24
WALK_BUDGET_S = 0.6             # the snap sits between speech and pointer
FRAME_TOLERANCE_PX = 2          # rounding between AT-SPI and Hyprland edges

# Roles that group controls and are never a pointing target themselves.
CONTAINER_ROLES = frozenset({
    "application", "frame", "window", "dialog", "alert", "panel", "filler",
    "scroll pane", "viewport", "layered pane", "split pane", "tool bar",
    "menu bar", "status bar", "document frame", "document web",
    "document text", "embedded", "section", "form", "grouping",
    "redundant object", "unknown", "root pane", "glass pane",
    "internal frame", "desktop frame", "page tab list", "list", "table",
    "tree", "tree table", "menu", "popup menu", "canvas", "terminal",
    "landmark",
})
# Not groups, but not controls either: text and pictures can be named by a
# label match, yet a model point landing on one is not a control to snap to.
NON_CONTROL_ROLES = frozenset({
    "label", "static", "image", "heading", "paragraph", "separator",
    "article", "block quote",
})
_TOPLEVEL_ROLES = frozenset({"frame", "window", "dialog", "alert"})


class TreeUnavailable(Exception):
    """The tree cannot answer: `reason` says why."""


Rect = tuple


@dataclasses.dataclass(frozen=True)
class Element:
    label: str
    role: str
    rect: Rect                 # (x, y, w, h) logical global px
    window: str = ""           # title of the toplevel it came from, if known

    @property
    def center(self) -> tuple:
        return (int(self.rect[0] + self.rect[2] / 2),
                int(self.rect[1] + self.rect[3] / 2))

    @property
    def is_container(self) -> bool:
        return self.role in CONTAINER_ROLES


def contains(rect, x, y) -> bool:
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def inside(rect, frame, tol: int = FRAME_TOLERANCE_PX) -> bool:
    """rect lies within frame (with a small rounding tolerance)."""
    return (rect[0] >= frame[0] - tol and rect[1] >= frame[1] - tol
            and rect[0] + rect[2] <= frame[0] + frame[2] + tol
            and rect[1] + rect[3] <= frame[1] + frame[3] + tol)


def match_score(want: str, name: str) -> float:
    """1.0 exact, 0.85 one contains the other, else 0 (casefolded)."""
    want, name = want.strip().casefold(), name.strip().casefold()
    if not want or not name:
        return 0.0
    if want == name:
        return 1.0
    if want in name or name in want:
        return 0.85
    return 0.0


class ElementTree:
    """The interface. Subclasses fill in `_elements`; the query methods are
    shared so every implementation matches and filters the same way."""

    def state(self) -> tuple:
        return OK, ""

    def app_name(self) -> str:
        return ""

    def focused_frame(self) -> Rect | None:
        return None

    def occluded(self, rect) -> bool:
        return False

    def _elements(self) -> list:
        return []

    def rect(self, element) -> Rect:
        return element.rect

    def _require(self) -> None:
        st, why = self.state()
        if st != OK:
            raise TreeUnavailable(f"{st}: {why}" if why else st)

    def find_by_label(self, label: str) -> list:
        """Elements whose accessible name matches `label`, best match
        first. Raises TreeUnavailable when the tree cannot answer."""
        self._require()
        scored = [(match_score(label, e.label), e) for e in self._elements()
                  if e.role not in _TOPLEVEL_ROLES and e.label]
        scored = [(s, e) for s, e in scored if s > 0]
        scored.sort(key=lambda se: -se[0])
        return [e for _, e in scored]

    def at_point(self, x, y):
        """The smallest non-container element holding (x, y), or None."""
        self._require()
        hits = [e for e in self._elements()
                if not e.is_container and e.role not in NON_CONTROL_ROLES
                and contains(e.rect, x, y)]
        return min(hits, key=lambda e: e.rect[2] * e.rect[3], default=None)


class UnavailableTree(ElementTree):
    def __init__(self, reason: str):
        self.reason = reason

    def state(self) -> tuple:
        return UNAVAILABLE, self.reason


class AtspiTree(ElementTree):
    """AT-SPI through `gi` / Atspi-2.0, bound to the Hyprland-focused
    window. One instance is one consistent snapshot: it walks the bound
    toplevel once, on first use. Build a new one per step."""

    def __init__(self, *, focused=None, clients=None, atspi=None,
                 clock=time.monotonic):
        self._focused_fn, self._clients_fn = focused, clients
        self._atspi, self._clock = atspi, clock
        self._loaded = False
        self._state = (OK, "")
        self._name = ""
        self._frame = None
        self._els: list = []
        self._focus: dict = {}
        self.truncated = False

    # -- seams -----------------------------------------------------
    def _focused(self) -> dict:
        if self._focused_fn is not None:
            return self._focused_fn() or {}
        from . import hypr
        w = hypr.query("activewindow")
        return w if isinstance(w, dict) else {}

    def _clients(self) -> list:
        if self._clients_fn is not None:
            return self._clients_fn() or []
        from . import hypr
        c = hypr.query("clients")
        return c if isinstance(c, list) else []

    def _load_atspi(self):
        if self._atspi is not None:
            return self._atspi
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
        except (ImportError, ValueError) as e:
            raise TreeUnavailable(
                "gi/Atspi bindings not installed (python-gobject, "
                f"at-spi2-core): {type(e).__name__}") from None
        self._atspi = Atspi
        return Atspi

    # -- ElementTree -----------------------------------------------
    def state(self) -> tuple:
        self._load()
        return self._state

    def app_name(self) -> str:
        self._load()
        return self._name

    def focused_frame(self):
        self._load()
        return self._frame

    def _elements(self) -> list:
        self._load()
        return self._els

    def occluded(self, rect) -> bool:
        """Another mapped window on the focused workspace covers the rect's
        centre. Hyprland keeps the focused window above its tiled siblings,
        so the only stackers above it are floating windows when the focused
        one is tiled; when the focused window itself floats it is on top
        (focus raises). Fullscreen windows are not another window here."""
        self._load()
        focus = self._focus
        if not focus or focus.get("floating"):
            return False
        cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
        ws = (focus.get("workspace") or {}).get("id")
        try:
            clients = self._clients()
        except Exception:
            return False
        for c in clients:
            if not isinstance(c, dict) or c.get("address") == focus.get(
                    "address"):
                continue
            if not c.get("mapped", True) or c.get("hidden"):
                continue
            if not c.get("floating") or (c.get("workspace") or {}).get(
                    "id") != ws:
                continue
            try:
                at, size = c["at"], c["size"]
            except KeyError:
                continue
            if contains((at[0], at[1], size[0], size[1]), cx, cy):
                return True
        return False

    # -- loading ---------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            self._bind_and_walk()
        except TreeUnavailable as e:
            self._state = (UNAVAILABLE, str(e))
        except Exception as e:         # GLib.Error, hung app, dead bus
            self._state = (UNAVAILABLE,
                           f"AT-SPI call failed: {type(e).__name__}")

    def _bind_and_walk(self) -> None:
        atspi = self._load_atspi()
        try:
            self._focus = self._focused()
        except Exception as e:
            raise TreeUnavailable(f"compositor query failed: "
                                  f"{type(e).__name__}") from None
        at, size = self._focus.get("at"), self._focus.get("size")
        if not (isinstance(at, list) and isinstance(size, list)
                and len(at) == 2 and len(size) == 2):
            self._state = (UNBOUND, "no focused window")
            return
        desktop = atspi.get_desktop(0)
        n = desktop.get_child_count()
        if n <= 0:
            raise TreeUnavailable("AT-SPI registry has no applications")
        cls = str(self._focus.get("class") or "")
        pid = self._focus.get("pid")
        by_pid, by_name = [], []
        for i in range(n):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            if isinstance(pid, int) and pid > 0 \
                    and app.get_process_id() == pid:
                by_pid.append(app)
            elif cls and (app.get_name() or "").casefold() == cls.casefold():
                by_name.append(app)
        apps = by_pid or by_name
        top = self._pick_toplevel(atspi, apps,
                                  str(self._focus.get("title") or ""))
        if top is None:
            self._state = (UNBOUND, "no toplevel binds to the focused "
                                    "window")
            return
        app, frame = top
        self._name = app.get_name() or ""
        self._frame = (int(at[0]), int(at[1]), int(size[0]), int(size[1]))
        self._walk(atspi, frame)

    @staticmethod
    def _pick_toplevel(atspi, apps, title):
        """(app, frame) for the one ACTIVE toplevel, else the one whose
        title matches; None when zero or several qualify."""
        frames = []
        for app in apps:
            for j in range(app.get_child_count()):
                f = app.get_child_at_index(j)
                if f is not None and (f.get_role_name() or "") \
                        in _TOPLEVEL_ROLES:
                    frames.append((app, f))
        active = [af for af in frames if af[1].get_state_set().contains(
            atspi.StateType.ACTIVE)]
        if len(active) == 1:
            return active[0]
        titled = [af for af in (active or frames)
                  if title and (af[1].get_name() or "") == title]
        return titled[0] if len(titled) == 1 else None

    def _walk(self, atspi, frame) -> None:
        deadline = self._clock() + WALK_BUDGET_S
        ox, oy = self._frame[0], self._frame[1]
        title = frame.get_name() or ""
        stack = [(frame, 0)]
        while stack:
            if len(self._els) >= MAX_NODES or self._clock() > deadline:
                self.truncated = True
                return
            node, depth = stack.pop()
            if depth > 0:
                el = self._element(atspi, node, ox, oy, title)
                if el is not None:
                    self._els.append(el)
            if depth >= MAX_DEPTH:
                continue
            for k in range(node.get_child_count() - 1, -1, -1):
                child = node.get_child_at_index(k)
                if child is not None:
                    stack.append((child, depth + 1))

    @staticmethod
    def _element(atspi, node, ox, oy, title):
        if not node.get_state_set().contains(atspi.StateType.SHOWING):
            return None
        comp = node.get_component_iface()
        if comp is None:
            return None
        e = comp.get_extents(atspi.CoordType.WINDOW)
        if e.width <= 0 or e.height <= 0:
            return None
        return Element(label=" ".join((node.get_name() or "").split()),
                       role=node.get_role_name() or "",
                       rect=(ox + e.x, oy + e.y, e.width, e.height),
                       window=title)


def default_tree() -> ElementTree:
    """The live tree for this session, or an UnavailableTree. Never raises
    and never touches the bus without a compositor to bind against."""
    try:
        from . import hypr
        if not hypr.available():
            return UnavailableTree("no Hyprland session to bind against")
    except Exception as e:
        return UnavailableTree(f"compositor probe failed: "
                               f"{type(e).__name__}")
    return AtspiTree()


# -- recorded-tree fixtures -------------------------------------------------

class FixtureError(ValueError):
    pass


def tree_to_fixture(app: str, frame, elements, *, windows=None,
                    state: str = OK, reason: str = "") -> dict:
    """The JSON shape the U1 harness and the fake consume. `windows` is a
    list of {"title", "frame", "focused", "elements"}; with none given the
    elements form one focused window at `frame`. Elements are
    {"label", "role", "rect"} in logical global px."""
    wins = windows or [{"title": "main", "frame": list(frame),
                        "focused": True,
                        "elements": [_el_json(e) for e in elements]}]
    return {"format": FIXTURE_FORMAT, "app": app, "state": state,
            "reason": reason, "windows": wins}


def _el_json(e) -> dict:
    if isinstance(e, dict):
        return e
    return {"label": e.label, "role": e.role, "rect": list(e.rect)}


def load_fixture(path_or_data) -> dict:
    """A validated fixture dict from a path or an already-parsed dict."""
    data = path_or_data
    if not isinstance(data, dict):
        try:
            with open(path_or_data, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise FixtureError(f"unreadable tree fixture: {e}") from None
    if data.get("format") != FIXTURE_FORMAT:
        raise FixtureError(f"not a {FIXTURE_FORMAT} fixture")
    if data.get("state", OK) not in (OK, UNAVAILABLE, UNBOUND):
        raise FixtureError("bad state")
    wins = data.get("windows")
    if not isinstance(wins, list):
        raise FixtureError("windows must be a list")
    for w in wins:
        fr = w.get("frame")
        if not (isinstance(fr, list) and len(fr) == 4):
            raise FixtureError("window frame must be [x, y, w, h]")
        for e in w.get("elements", []):
            r = e.get("rect")
            if not (isinstance(r, list) and len(r) == 4):
                raise FixtureError("element rect must be [x, y, w, h]")
    return data


def fixture_from_case(case: dict) -> dict:
    """A tree fixture from a teaching-harness case dict (`app`, `size`,
    `elements` as [{label, rect}] in capture pixels, optional `role`), so a
    harness case can replay the snap with `FakeElementTree`. The capture is
    one focused window at the origin. Reads a plain dict: it does not
    import the harness."""
    w, h = (list(case.get("size") or [0, 0]) + [0, 0])[:2]
    els = [{"label": str(e.get("label", "")),
            "role": str(e.get("role") or "push button"),
            "rect": list(e["rect"])} for e in case.get("elements") or []]
    return tree_to_fixture(str(case.get("app", "")), (0, 0, w, h), els)


def snap_share(records) -> dict:
    """Per-app share of `ax | model | none` over snap records (each a dict
    with `app` and `snap`), for the harness report. Unavailable and
    no-matching-control are different failures, so they are counted apart:
    {app: {"n": int, "ax": f, "model": f, "none": f,
           "ax_unavailable": int, "no_match": int}}."""
    out: dict = {}
    for r in records:
        a = out.setdefault(r.get("app") or "(unknown)", {
            "n": 0, "ax": 0, "model": 0, "none": 0,
            "ax_unavailable": 0, "no_match": 0})
        a["n"] += 1
        a[r.get("snap") if r.get("snap") in ("ax", "model", "none")
          else "none"] += 1
        status = r.get("ax_status")
        if status in (UNAVAILABLE, UNBOUND):
            a["ax_unavailable"] += 1
        elif r.get("snap") == "model":
            a["no_match"] += 1
    for a in out.values():
        for k in ("ax", "model", "none"):
            a[k] = round(a[k] / a["n"], 3)
    return out
