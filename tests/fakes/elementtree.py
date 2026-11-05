"""FakeElementTree: an `ElementTree` served from a recorded-tree fixture
(`wisp-elementtree/1` JSON, see wisp/elementtree.py). No AT-SPI, no
compositor. The same fixture shape is what the U1 teaching harness reads."""
from wisp import elementtree as et


class FakeElementTree(et.ElementTree):
    def __init__(self, data):
        self.data = et.load_fixture(data)
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
