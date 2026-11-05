"""U7: the ElementTree interface, the AT-SPI implementation (against a
fake Atspi module, no bus), the fixture format and the snap-share report."""
import pathlib
import sys
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fakes.elementtree import FakeElementTree  # noqa: E402
from wisp import elementtree as et  # noqa: E402

TREES = ROOT / "tests" / "fixtures" / "trees"


# -- a fake `gi.repository.Atspi` -------------------------------------------

class Node:
    def __init__(self, name, role, ext=None, states=("showing",), pid=0,
                 kids=()):
        self.name, self.role, self.ext = name, role, ext
        self.states, self.pid, self.kids = set(states), pid, list(kids)

    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_process_id(self): return self.pid
    def get_child_count(self): return len(self.kids)
    def get_child_at_index(self, i): return self.kids[i]

    def get_state_set(self):
        return SimpleNamespace(contains=lambda s: s in self.states)

    def get_component_iface(self):
        if self.ext is None:
            return None
        x, y, w, h = self.ext
        return SimpleNamespace(get_extents=lambda ct: SimpleNamespace(
            x=x, y=y, width=w, height=h, coord=ct))


class FakeAtspi:
    CoordType = SimpleNamespace(WINDOW="window", SCREEN="screen")
    StateType = SimpleNamespace(ACTIVE="active", SHOWING="showing")

    def __init__(self, apps):
        self.apps = apps

    def get_desktop(self, _):
        return Node("", "desktop", kids=self.apps)


def button(name, x, y, w=60, h=24, **kw):
    return Node(name, "push button", (x, y, w, h), **kw)


def focus(**kw):
    return {"class": "fixture-app", "title": "main", "pid": 4242,
            "at": [100, 50], "size": [800, 600], "floating": False,
            "address": "0xa", "workspace": {"id": 1}, **kw}


def app(frames, pid=4242, name="Fixture App"):
    return Node(name, "application", pid=pid, kids=frames)


def frame(title, kids, active=True):
    return Node(title, "frame", (0, 0, 800, 600),
                states=("showing", "active") if active else ("showing",),
                kids=kids)


class Atspi(unittest.TestCase):
    def tree(self, apps, focus=None, clients=()):
        win = focus or globals()["focus"]()
        return et.AtspiTree(focused=lambda: win, clients=lambda: list(clients),
                            atspi=FakeAtspi(apps))

    def test_window_coords_move_into_the_global_frame(self):
        t = self.tree([app([frame("main", [button("Save", 10, 20)])])])
        self.assertEqual(t.state(), (et.OK, ""))
        self.assertEqual(t.app_name(), "Fixture App")
        self.assertEqual(t.focused_frame(), (100, 50, 800, 600))
        (el,) = t.find_by_label("save")
        self.assertEqual(el.rect, (110, 70, 60, 24))
        self.assertEqual(t.at_point(115, 75).label, "Save")
        self.assertEqual(t.rect(el), el.rect)

    def test_binds_by_app_name_when_the_pid_is_unknown(self):
        t = self.tree([app([frame("main", [button("Save", 0, 0)])], pid=1)],
                      focus=focus(pid=0, **{"class": "Fixture App"}))
        self.assertEqual(t.state()[0], et.OK)

    def test_only_the_active_toplevel_is_read(self):
        a = app([frame("other", [button("Hidden", 0, 0)], active=False),
                 frame("main", [button("Save", 0, 0)])])
        t = self.tree([a])
        self.assertEqual([e.label for e in t._elements()], ["Save"])

    def test_two_frames_none_active_is_picked_by_title_or_unbound(self):
        two = [frame("main", [button("A", 0, 0)], active=False),
               frame("prefs", [button("B", 0, 0)], active=False)]
        self.assertEqual(self.tree([app(two)]).state()[0], et.OK)
        self.assertEqual(self.tree([app(two)],
                                   focus=focus(title="nope")).state()[0],
                         et.UNBOUND)

    def test_other_applications_are_never_bound(self):
        t = self.tree([app([frame("main", [button("Save", 0, 0)])], pid=7,
                           name="Other")])
        self.assertEqual(t.state()[0], et.UNBOUND)

    def test_not_showing_and_zero_size_nodes_are_skipped(self):
        kids = [button("Gone", 0, 0, states=()), button("Flat", 0, 0, h=0),
                Node("NoComp", "push button", None), button("Ok", 5, 5)]
        t = self.tree([app([frame("main", kids)])])
        self.assertEqual([e.label for e in t._elements()], ["Ok"])

    def test_missing_gi_is_unavailable_with_the_package_hint(self):
        t = et.AtspiTree(focused=lambda: focus())
        t._load_atspi = lambda: (_ for _ in ()).throw(
            et.TreeUnavailable("gi/Atspi bindings not installed"))
        self.assertEqual(t.state()[0], et.UNAVAILABLE)
        with self.assertRaises(et.TreeUnavailable):
            t.find_by_label("x")

    def test_a_bus_error_mid_walk_is_unavailable_not_a_crash(self):
        class Dead(FakeAtspi):
            def get_desktop(self, _):
                raise RuntimeError("bus gone")
        t = et.AtspiTree(focused=lambda: focus(), atspi=Dead([]))
        self.assertEqual(t.state()[0], et.UNAVAILABLE)
        self.assertIn("RuntimeError", t.state()[1])

    def test_no_apps_on_the_registry_is_unavailable(self):
        self.assertEqual(self.tree([]).state()[0], et.UNAVAILABLE)

    def test_walk_stops_at_the_node_and_time_budgets(self):
        many = [button(f"b{i}", 0, 0) for i in range(et.MAX_NODES + 50)]
        t = self.tree([app([frame("main", many)])])
        self.assertEqual(len(t._elements()), et.MAX_NODES)
        self.assertTrue(t.truncated)
        ticks = iter(range(0, 1000))
        t2 = et.AtspiTree(focused=lambda: focus(), atspi=FakeAtspi(
            [app([frame("main", many[:50])])]),
            clock=lambda: next(ticks) * et.WALK_BUDGET_S / 5)
        t2._elements()
        self.assertTrue(t2.truncated)
        self.assertLess(len(t2._elements()), 50)

    def test_floating_window_over_a_tiled_focus_occludes(self):
        clients = [{"address": "0xb", "floating": True, "mapped": True,
                    "hidden": False, "workspace": {"id": 1},
                    "at": [700, 500], "size": [300, 300]}]
        t = self.tree([app([frame("main", [])])], clients=clients)
        self.assertTrue(t.occluded((750, 550, 20, 20)))
        self.assertFalse(t.occluded((120, 70, 20, 20)))

    def test_other_workspace_hidden_or_focused_floating_never_occlude(self):
        base = {"address": "0xb", "floating": True, "mapped": True,
                "hidden": False, "workspace": {"id": 1},
                "at": [0, 0], "size": [2000, 2000]}
        for patch in ({"workspace": {"id": 2}}, {"hidden": True},
                      {"floating": False}):
            t = self.tree([app([frame("main", [])])],
                          clients=[{**base, **patch}])
            self.assertFalse(t.occluded((120, 70, 20, 20)), patch)
        t = self.tree([app([frame("main", [])])], clients=[base],
                      focus=focus(floating=True))
        self.assertFalse(t.occluded((120, 70, 20, 20)))


class Shared(unittest.TestCase):
    def test_label_match_is_exact_first_then_partial(self):
        t = FakeElementTree.from_file(TREES / "settings_dialog.json")
        self.assertEqual(t.find_by_label("Save")[0].label, "Save")
        self.assertEqual(t.find_by_label("dark")[0].label, "Dark mode")
        self.assertEqual(t.find_by_label("nonexistent"), [])

    def test_at_point_returns_the_smallest_non_container(self):
        t = FakeElementTree.from_file(TREES / "settings_dialog.json")
        self.assertEqual(t.at_point(310, 310).label, "Dark mode")
        self.assertIsNone(t.at_point(150, 400))     # only the big panel
        self.assertIsNone(FakeElementTree.from_file(
            TREES / "patchy.json").at_point(500, 500))

    def test_unavailable_tree_raises_on_queries(self):
        t = FakeElementTree.from_file(TREES / "unavailable.json")
        self.assertEqual(t.state()[0], et.UNAVAILABLE)
        with self.assertRaises(et.TreeUnavailable):
            t.at_point(1, 1)

    def test_default_tree_never_raises_without_a_compositor(self):
        self.assertIsInstance(et.default_tree(), et.UnavailableTree)


class Fixtures(unittest.TestCase):
    def test_every_checked_in_fixture_loads(self):
        files = sorted(TREES.glob("*.json"))
        self.assertGreaterEqual(len(files), 5)
        for f in files:
            self.assertEqual(et.load_fixture(f)["format"], et.FIXTURE_FORMAT)

    def test_generator_output_matches_the_checked_in_files(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_trees", TREES / "make_trees.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import json
        for name, data in mod.build().items():
            on_disk = json.loads((TREES / f"{name}.json").read_text())
            self.assertEqual(on_disk, data, name)

    def test_fixtures_carry_no_machine_detail(self):
        text = "".join(f.read_text() for f in TREES.glob("*.json"))
        for needle in ("/home/", "/Users/", "@", "omarchy", "<user>"):
            self.assertNotIn(needle, text)

    def test_bad_fixtures_are_refused(self):
        for bad in ({}, {"format": "x"},
                    {"format": et.FIXTURE_FORMAT, "windows": "no"},
                    {"format": et.FIXTURE_FORMAT, "state": "weird",
                     "windows": []},
                    {"format": et.FIXTURE_FORMAT, "windows": [
                        {"frame": [1, 2, 3]}]},
                    {"format": et.FIXTURE_FORMAT, "windows": [
                        {"frame": [0, 0, 1, 1],
                         "elements": [{"rect": [1]}]}]}):
            with self.assertRaises(et.FixtureError):
                et.load_fixture(bad)
        with self.assertRaises(et.FixtureError):
            et.load_fixture(TREES / "missing.json")

    def test_snap_share_separates_unavailable_from_no_match(self):
        rows = [{"app": "a", "snap": "ax", "ax_status": "ok"},
                {"app": "a", "snap": "model", "ax_status": "ok"},
                {"app": "a", "snap": "none", "ax_status": "unavailable"},
                {"app": "a", "snap": "none", "ax_status": "unbound"},
                {"app": "b", "snap": "ax", "ax_status": "ok"}]
        out = et.snap_share(rows)
        self.assertEqual(out["a"]["n"], 4)
        self.assertEqual((out["a"]["ax"], out["a"]["model"],
                          out["a"]["none"]), (0.25, 0.25, 0.5))
        self.assertEqual((out["a"]["ax_unavailable"], out["a"]["no_match"]),
                         (2, 1))
        self.assertEqual(out["b"]["ax"], 1.0)


if __name__ == "__main__":
    unittest.main()
