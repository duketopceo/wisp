"""FakeElementTree: an `ElementTree` served from a recorded-tree fixture
(`wisp-elementtree/1` JSON, see wisp/elementtree.py). No AT-SPI, no
compositor. The same fixture shape is what the U1 teaching harness reads."""
import json

from wisp import elementtree as et


class FixtureError(ValueError):
    pass


def load_fixture(path_or_data) -> dict:
    """A validated fixture dict from a path or an already-parsed dict."""
    data = path_or_data
    if not isinstance(data, dict):
        try:
            with open(path_or_data, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise FixtureError(f"unreadable tree fixture: {e}") from None
    if data.get("format") != et.FIXTURE_FORMAT:
        raise FixtureError(f"not a {et.FIXTURE_FORMAT} fixture")
    if data.get("state", et.OK) not in (et.OK, et.UNAVAILABLE, et.UNBOUND):
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


class FakeElementTree(et.ElementTree):
    def __init__(self, data):
        self.data = load_fixture(data)
        self.wins = self.data["windows"]
        self.queries = []                      # (method, args), for asserts

    @classmethod
    def from_file(cls, path):
        return cls(path)

    def state(self):
        return self.data.get("state", et.OK), self.data.get("reason", "")

    def app_name(self):
        return self.data.get("app", "") if self.state()[0] == et.OK else ""

    def _focused(self):
        for w in self.wins:
            if w.get("focused"):
                return w
        return None

    def focused_frame(self):
        w = self._focused()
        return tuple(w["frame"]) if w else None

    def _elements(self):
        # every window's elements: the snap code, not the tree, is what
        # must refuse a control in an unfocused window
        return [et.Element(e.get("label", ""), e.get("role", ""),
                           tuple(e["rect"]), w.get("title", ""))
                for w in self.wins for e in w.get("elements", [])]

    def occluded(self, rect):
        cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
        return any(w.get("above") and et.contains(tuple(w["frame"]), cx, cy)
                   for w in self.wins if not w.get("focused"))

    def find_by_label(self, label):
        self.queries.append(("find_by_label", (label,)))
        return super().find_by_label(label)

    def at_point(self, x, y):
        self.queries.append(("at_point", (x, y)))
        return super().at_point(x, y)
