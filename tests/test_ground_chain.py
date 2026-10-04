"""W13 grounding adapter: provider chain, frame math, confidence policy,
cua.target events, audit coordinates, P7 timeout plumbing, clicklab
offline suite. Everything faked: no network, no live cua-driver/hyprctl."""
import base64
import io
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                       / "scripts" / "clicklab"))
from wisp import act, cua_safety, grounding as g  # noqa: E402
from PIL import Image  # noqa: E402

EDP = {"name": "eDP-1", "x": 0, "y": 0, "width": 3456, "height": 2160,
       "scale": 2.0}
DP3 = {"name": "DP-3", "x": 1728, "y": 0, "width": 3440, "height": 1440,
       "scale": 1.0}
S1 = {"name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080,
      "scale": 1.0}


def png(w=200, h=100):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 20, 20)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def shot(w=3456, h=2160):
    return g.Shot(png(w // 16, h // 16), w, h)


def cand(x, y, conf, source="fake", size=None):
    return g.Candidate(x, y, conf, source, size=size)


class FrameMath(unittest.TestCase):
    def test_scale2_single_monitor(self):
        self.assertEqual(g.convert(1000, 600, "shot", [EDP]), (500, 300))

    def test_scale1_single_monitor(self):
        self.assertEqual(g.convert(1000, 600, "shot", [S1]), (1000, 600))

    def test_multi_monitor_mixed_scale_offset(self):
        # grim canvas scale = max scale (2): DP-3 starts at logical 1728
        # -> canvas px 3456. A point 100,50 logical into DP-3:
        px = (1728 + 100) * 2, 50 * 2
        self.assertEqual(g.convert(*px, "shot", [EDP, DP3]), (1828, 50))
        self.assertEqual(g.convert(10, 20, "shot", [EDP, DP3]), (5, 10))

    def test_negative_origin_layout(self):
        left = {"name": "L", "x": -1920, "y": 0, "width": 1920,
                "height": 1080, "scale": 1.0}
        main = {"name": "M", "x": 0, "y": 0, "width": 1920, "height": 1080,
                "scale": 1.0}
        self.assertEqual(g.convert(10, 10, "shot", [left, main]),
                         (-1910, 10))

    def test_single_output_capture_uses_that_monitors_origin(self):
        self.assertEqual(
            g.convert(200, 100, "shot", [EDP, DP3], output="DP-3"),
            (1728 + 200, 100))
        self.assertEqual(
            g.convert(200, 100, "shot", [EDP, DP3], output="eDP-1"),
            (100, 50))

    def test_canvas_frame_adds_origin(self):
        left = {"name": "L", "x": -100, "y": 0, "width": 200, "height": 100,
                "scale": 1.0}
        self.assertEqual(g.convert(10, 5, "canvas", [left]), (-90, 5))

    def test_global_and_logical_are_identity(self):
        for f in ("global", "logical"):
            self.assertEqual(g.convert(7, 9, f, [EDP]), (7, 9))

    def test_no_monitors_assumes_scale1(self):
        self.assertEqual(g.convert(7, 9, "shot", []), (7, 9))

    def test_unknown_frame_raises(self):
        with self.assertRaises(ValueError):
            g.convert(1, 1, "bogus", [EDP])


class UitarsParse(unittest.TestCase):
    def p(self, text, size=(1000, 500), coords="px"):
        return g.parse_uitars_text(text, size, coords)

    def test_forms(self):
        self.assertEqual(self.p("click(start_box='(100,200)')"), (100, 200))
        self.assertEqual(self.p("(100, 200)"), (100, 200))
        self.assertEqual(
            self.p("Action: click(start_box='<|box_start|>(10,20)"
                   "<|box_end|>')"), (10, 20))
        self.assertEqual(self.p("click(300, 400)"), (300, 400))

    def test_relative_float_and_rel1000(self):
        self.assertEqual(self.p("(0.5, 0.5)"), (500, 250))
        self.assertEqual(self.p("(500,500)", coords="rel1000"), (500, 250))

    def test_malformed(self):
        for bad in ("", None, "I cannot find it", "click(start_box='(a,b)')",
                    "(1)", "(-5,10)", "(5000,10)", "(10,9999)", "(nan,3)",
                    "x" * 10, "(99999999999999999999,1)", "(1.5, 0.2)"):
            self.assertIsNone(self.p(bad), bad)


def fake_post(reply):
    def _post(url, body, timeout, headers=None):
        _post.calls.append((url, body, timeout))
        if isinstance(reply, Exception):
            raise reply
        return reply
    _post.calls = []
    return _post


def chat(text, lp=None):
    ch = {"message": {"content": text}}
    if lp is not None:
        ch["logprobs"] = {"content": [{"token": "1", "logprob": v}
                                      for v in lp]}
    return {"choices": [ch]}


class Providers(unittest.TestCase):
    def ctx(self, cfg=None, cua=None, timeout=1.0):
        cfg = cfg or {}
        return types.SimpleNamespace(
            target="save", region_hint="", shot=shot(), cfg=cfg,
            st=g.settings(cfg), timeout=timeout, cua=cua)

    def test_uitars_ok_and_scaled_size(self):
        post = fake_post(chat("click(start_box='(100,200)')"))
        with mock.patch.object(g, "_post_json", post):
            c = g._uitars(self.ctx())
        self.assertEqual((c.x, c.y, c.source), (100, 200, "uitars"))
        self.assertEqual(c.frame, "shot")
        self.assertLessEqual(max(c.size), 1280)           # downscaled
        self.assertEqual(post.calls[0][0],
                         "http://127.0.0.1:8081/v1/chat/completions")

    def test_uitars_logprob_confidence(self):
        import math
        post = fake_post(chat("(100,200)", lp=[math.log(0.9)] * 3))
        with mock.patch.object(g, "_post_json", post):
            c = g._uitars(self.ctx())
        self.assertAlmostEqual(c.confidence, 0.9, places=3)

    def test_uitars_malformed_replies_return_none(self):
        for reply in (None, [], "str", {}, {"choices": []},
                      {"choices": [None]}, {"choices": [{}]},
                      {"choices": [{"message": None}]},
                      chat(""), chat("no coords"), chat("(9e9,1)")):
            with mock.patch.object(g, "_post_json", fake_post(reply)):
                self.assertIsNone(g._uitars(self.ctx()), repr(reply))

    def test_uitars_network_failure_is_provider_down(self):
        with mock.patch.object(g, "_post_json",
                               fake_post(g.ProviderDown("refused"))):
            with self.assertRaises(g.ProviderDown):
                g._uitars(self.ctx())

    def test_uitars_refuses_non_loopback_url(self):
        post = fake_post(chat("(1,2)"))
        cfg = {"ground": {"uitars_url": "http://10.0.0.5:8081"}}
        with mock.patch.object(g, "_post_json", post):
            with self.assertRaises(g.Skip):
                g._uitars(self.ctx(cfg))
        self.assertEqual(post.calls, [])

    def test_post_json_passes_timeout_and_maps_errors(self):
        import urllib.error
        seen = {}

        class R:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def read(s):
                return b'{"a":1}'

        def uo(req, timeout=None):
            seen["t"] = timeout
            return R()
        with mock.patch("urllib.request.urlopen", uo):
            self.assertEqual(g._post_json("http://127.0.0.1:1/x", {}, 0.7),
                             {"a": 1})
        self.assertEqual(seen["t"], 0.7)
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("no")):
            with self.assertRaises(g.ProviderDown):
                g._post_json("http://127.0.0.1:1/x", {}, 0.7)

        class Bad(R):
            def read(s):
                return b"not json"
        with mock.patch("urllib.request.urlopen", lambda r, timeout=None:
                        Bad()):
            self.assertIsNone(g._post_json("http://127.0.0.1:1/x", {}, 1))

    def test_jev_malformed_answers(self):
        for reply in (None, [], {"answers": None}, {"answers": []},
                      {"answers": {"p_0": "x"}},
                      {"answers": {"p_0": {"noul": "nan?"}}},
                      {"answers": {"p_0": {"noul": float("nan")}}}):
            with mock.patch.object(g, "_post_json", fake_post(reply)), \
                    mock.patch("wisp.config.load_api_key",
                               return_value="k"):
                ctx = self.ctx()
                ctx.shot = g.Shot(png(200, 100), 200, 100)
                self.assertIsNone(g._jev(ctx), repr(reply))

    def test_jev_confidence_is_max_probability(self):
        reply = {"answers": {"p_0": {"noul": 0.1}, "p_1": {"noul": 0.8}}}
        with mock.patch.object(g, "_post_json", fake_post(reply)), \
                mock.patch("wisp.config.load_api_key", return_value="k"):
            ctx = self.ctx()
            ctx.shot = g.Shot(png(200, 100), 200, 100)
            c = g._jev(ctx)
        self.assertAlmostEqual(c.confidence, 0.8)
        self.assertEqual(c.size, (200, 100))


class FakeCua:
    def __init__(self, windows=None, state=None, up=True, boom=None):
        self.windows, self.state, self.up, self.boom = (
            windows, state, up, boom)
        self.calls = []

    def available(self):
        return self.up

    def list_windows(self, timeout=3.0):
        self.calls.append(("list", timeout))
        if self.boom:
            raise self.boom
        return self.windows

    def window_state(self, pid, window_id, timeout=5.0):
        self.calls.append(("state", pid, window_id, timeout))
        return self.state


WIN = {"windows": [{"pid": 7, "window_id": 3, "title": "Settings",
                    "focused": True}]}
TREE = {"elements": [
    {"role": "button", "label": "Night Light",
     "frame": {"x": 100, "y": 200, "width": 40, "height": 20}},
    {"role": "button", "label": "Volume", "frame": [10, 10, 20, 20]}]}


class A11y(unittest.TestCase):
    def ctx(self, cua, target="night light", cfg=None):
        cfg = cfg or {}
        return types.SimpleNamespace(
            target=target, region_hint="", shot=shot(), cfg=cfg,
            st=g.settings(cfg), timeout=1.0, cua=cua)

    def test_exact_match_global_frame(self):
        c = g._a11y(self.ctx(FakeCua(WIN, TREE)))
        self.assertEqual((c.x, c.y, c.frame, c.source),
                         (120, 210, "global", "a11y"))
        self.assertEqual(c.confidence, 1.0)
        self.assertEqual(c.window, "Settings")

    def test_substring_lower_confidence_and_ambiguity(self):
        c = g._a11y(self.ctx(FakeCua(WIN, TREE), target="night"))
        self.assertLess(c.confidence, 1.0)
        self.assertGreaterEqual(c.confidence, 0.5)
        dup = {"elements": [
            {"label": "OK", "frame": [0, 0, 10, 10]},
            {"label": "OK", "frame": [100, 100, 10, 10]}]}
        c = g._a11y(self.ctx(FakeCua(WIN, dup), target="ok"))
        self.assertLess(c.confidence, 0.5)        # ambiguous -> low

    def test_window_relative_frames_option(self):
        win = {"windows": [{"pid": 1, "window_id": 2, "title": "w",
                            "focused": True,
                            "frame": {"x": 1000, "y": 500, "width": 800,
                                      "height": 600}}]}
        cfg = {"ground": {"a11y_frame": "window"}}
        c = g._a11y(self.ctx(FakeCua(win, TREE), cfg=cfg))
        self.assertEqual((c.x, c.y), (1120, 710))

    def test_unavailable_or_no_focus_skips(self):
        with self.assertRaises(g.Skip):
            g._a11y(self.ctx(FakeCua(WIN, TREE, up=False)))
        with self.assertRaises(g.Skip):
            g._a11y(self.ctx(None))
        with self.assertRaises(g.Skip):
            g._a11y(self.ctx(FakeCua({"windows": [{"pid": 1,
                                                   "window_id": 2}]},
                                     TREE)))

    def test_malformed_trees_return_none(self):
        for tree in (None, [], {}, {"elements": None}, {"elements": [1]},
                     {"elements": [{"label": "night light"}]},
                     {"elements": [{"label": "night light",
                                    "frame": {"x": "a", "y": 1,
                                              "width": 1, "height": 1}}]},
                     {"elements": [{"label": "night light",
                                    "frame": [0, 0, 0, 0]}]},
                     {"elements": [{"label": "night light",
                                    "frame": [float("nan"), 0, 5, 5]}]}):
            self.assertIsNone(g._a11y(self.ctx(FakeCua(WIN, tree))),
                              repr(tree))

    def test_driver_down_is_provider_down(self):
        from wisp import cua
        c = FakeCua(WIN, TREE, boom=cua.CuaError(cua.DOWN, "x"))
        with self.assertRaises(g.ProviderDown):
            g._a11y(self.ctx(c))


def chain(cfg=None, provs=None, caps=None, mons=(EDP,), cua=None,
          clock=None):
    caps = caps if caps is not None else [shot()]
    calls = []

    def capture():
        calls.append("cap")
        return caps.pop(0) if len(caps) > 1 else caps[0]
    kw = {}
    if clock:
        kw["clock"] = clock
    return calls, (lambda target="night light": g.ground_target(
        target, cfg or {}, capture=capture, monitors=list(mons),
        providers=provs, cua=cua, **kw))


def prov(name, results, log=None, fast=True):
    seq = list(results)

    def fn(ctx):
        if log is not None:
            log.append((name, ctx.timeout))
        r = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(r, Exception):
            raise r
        return r
    return {"fn": fn, "fast": fast}


class Chain(unittest.TestCase):
    def test_a11y_preferred_over_pixels(self):
        log = []
        provs = {"a11y": prov("a11y", [g.Candidate(5, 6, 1.0, "a11y",
                                                   frame="global")], log),
                 "uitars": prov("uitars", [cand(1, 1, 0.9)], log)}
        _, run = chain(provs=provs)
        t = run()
        self.assertEqual((t.x, t.y, t.frame, t.source, t.confidence),
                         (5, 6, "global", "a11y", 1.0))
        self.assertEqual([n for n, _ in log], ["a11y"])

    def test_falls_through_none_skip_and_down(self):
        provs = {"a11y": prov("a11y", [g.Skip("n/a")]),
                 "uitars": prov("uitars", [g.ProviderDown("x")]),
                 "jev": prov("jev", [cand(1000, 600, 0.9, "jev")],
                             fast=False)}
        _, run = chain(provs=provs)
        t = run()
        self.assertEqual((t.x, t.y, t.source), (500, 300, "jev"))
        self.assertEqual(t.frame, "global")

    def test_order_follows_config(self):
        log = []
        provs = {"a11y": prov("a11y", [None], log),
                 "uitars": prov("uitars", [None], log),
                 "jev": prov("jev", [None], log)}
        _, run = chain(cfg={"ground": {"providers": "jev,uitars"}},
                       provs=provs)
        with self.assertRaises(g.GroundRefused):
            run()
        self.assertEqual([n for n, _ in log][:2], ["jev", "uitars"])
        self.assertNotIn("a11y", [n for n, _ in log])

    def test_size_rescales_into_shot_frame(self):
        provs = {"uitars": prov("u", [cand(864, 540, 0.9, "uitars",
                                           size=(1728, 1080))])}
        _, run = chain(provs=provs)
        t = run()
        self.assertEqual((t.x, t.y), (864, 540))     # 1728px->3456px->/2

    def test_multi_monitor_through_chain(self):
        provs = {"uitars": prov("u", [cand(1000, 200, 0.9, "uitars",
                                           size=(2584, 720))])}
        caps = [g.Shot(png(100, 30), 10336, 2880)]
        _, run = chain(provs=provs, caps=caps, mons=(EDP, DP3))
        t = run()
        self.assertEqual((t.x, t.y), (2000, 400))

    def test_all_malformed_refuses_not_found(self):
        provs = {n: prov(n, [None]) for n in ("a11y", "uitars", "jev")}
        _, run = chain(provs=provs)
        with self.assertRaises(g.GroundRefused) as cm:
            run()
        self.assertEqual(cm.exception.code, "ground_failed")
        self.assertEqual(cm.exception.reason, "not_found")

    def test_all_down_is_ground_down(self):
        provs = {n: prov(n, [g.ProviderDown("x")])
                 for n in ("uitars", "jev")}
        _, run = chain(cfg={"ground": {"providers": "uitars,jev"}},
                       provs=provs)
        with self.assertRaises(g.GroundRefused) as cm:
            run()
        self.assertEqual(cm.exception.code, "ground_down")

    def test_provider_exception_is_contained(self):
        provs = {"uitars": prov("u", [RuntimeError("boom")]),
                 "jev": prov("j", [cand(100, 100, 0.9, "jev")],
                             fast=False)}
        _, run = chain(cfg={"ground": {"providers": "uitars,jev"}},
                       provs=provs)
        self.assertEqual(run().source, "jev")

    def test_out_of_bounds_candidate_rejected(self):
        provs = {"uitars": prov("u", [cand(99999, 5, 0.99, "uitars")])}
        _, run = chain(cfg={"ground": {"providers": "uitars"}},
                       provs=provs)
        with self.assertRaises(g.GroundRefused):
            run()

    def test_empty_target_refused(self):
        _, run = chain(provs={})
        with self.assertRaises(g.GroundRefused):
            run("   ")


class Confidence(unittest.TestCase):
    def test_low_then_reobserve_then_refuse(self):
        log = []
        provs = {"uitars": prov("u", [cand(100, 100, 0.3, "uitars")], log)}
        caps, run = chain(cfg={"ground": {"providers": "uitars"}},
                          provs=provs)
        with self.assertRaises(g.GroundRefused) as cm:
            run()
        self.assertEqual(caps, ["cap", "cap"])         # exactly one re-observe
        self.assertEqual(len(log), 2)
        self.assertEqual(cm.exception.reason, "low_confidence")
        self.assertEqual(cm.exception.code, "ground_failed")

    def test_reobserve_recovers(self):
        provs = {"uitars": prov("u", [cand(100, 100, 0.3, "uitars"),
                                      cand(200, 100, 0.9, "uitars")])}
        caps, run = chain(cfg={"ground": {"providers": "uitars"}},
                          provs=provs)
        t = run()
        self.assertEqual(caps, ["cap", "cap"])
        self.assertEqual((t.x, t.y), (100, 50))

    def test_high_confidence_does_not_reobserve(self):
        provs = {"uitars": prov("u", [cand(100, 100, 0.9, "uitars")])}
        caps, run = chain(cfg={"ground": {"providers": "uitars"}},
                          provs=provs)
        run()
        self.assertEqual(caps, ["cap"])

    def test_low_primary_defers_to_better_next_provider(self):
        provs = {"uitars": prov("u", [cand(100, 100, 0.2, "uitars")]),
                 "jev": prov("j", [cand(300, 300, 0.8, "jev")], fast=False)}
        caps, run = chain(cfg={"ground": {"providers": "uitars,jev"}},
                          provs=provs)
        t = run()
        self.assertEqual(t.source, "jev")
        self.assertEqual(caps, ["cap"])

    def test_threshold_configurable_and_bad_value_defaults(self):
        provs = {"uitars": prov("u", [cand(100, 100, 0.6, "uitars")])}
        _, run = chain(cfg={"ground": {"providers": "uitars",
                                       "min_confidence": "0.9"}},
                       provs=provs)
        with self.assertRaises(g.GroundRefused):
            run()
        self.assertEqual(g.settings({"ground": {"min_confidence": "zz"}})
                         ["min_conf"], 0.5)

    def test_capture_failure_refuses(self):
        with self.assertRaises(g.GroundRefused):
            g.ground_target("x", {}, capture=lambda: None,
                            monitors=[EDP], providers={})


class Budget(unittest.TestCase):
    def test_fast_providers_share_1200ms_budget(self):
        clock = Clock()
        log = []

        def slow(ctx):
            log.append(("first", ctx.timeout))
            clock.t += 1.25                       # burns the whole budget
            return None
        provs = {"a11y": {"fn": slow, "fast": True},
                 "uitars": prov("u", [cand(1, 1, 0.9)], log),
                 "jev": prov("j", [cand(100, 100, 0.9, "jev")], log,
                             fast=False)}
        _, run = chain(provs=provs, clock=clock)
        t = run()
        names = [n for n, _ in log]
        self.assertEqual(names, ["first", "j"])    # uitars skipped
        self.assertEqual(t.source, "jev")
        self.assertLessEqual(log[0][1], 1.2)
        self.assertEqual(log[1][1], 5.0)           # fallback timeout

    def test_each_fast_provider_gets_remaining_budget(self):
        clock = Clock()
        log = []

        def first(ctx):
            log.append(("a", ctx.timeout))
            clock.t += 0.5
            return None
        provs = {"a11y": {"fn": first, "fast": True},
                 "uitars": prov("u", [cand(10, 10, 0.9)], log)}
        _, run = chain(provs=provs, clock=clock)
        run()
        self.assertAlmostEqual(log[0][1], 1.2)
        self.assertAlmostEqual(log[1][1], 0.7)

    def test_budget_configurable(self):
        self.assertEqual(g.settings({"ground": {"budget_ms": "800"}})
                         ["budget"], 0.8)
        self.assertEqual(g.settings({})["budget"], 1.2)


# ---------------------------------------------------------------- act wiring

class FakeState:
    def __init__(self):
        self.events = []
        self.steps = []
        self.focus = {"app": "kate"}
        self.confirmed = set()

    def emit_event(self, name, **data):
        self.events.append((name, data))

    def transition(self, status, **f):
        pass


TARGET = g.Target(x=500, y=300, frame="global", confidence=0.9,
                  source="uitars")


def run_loop(arg, tool_result, ground, state, mode="drive", name="click",
             audit=None, extra_cfg=None, window=None):
    c = {"pointer": {"mode": mode, "backend": "auto"},
         "cua": {"audit": "true", "max_per_turn": "50"},
         "agent": {}, "brain": {}}
    c.update(extra_cfg or {})
    msgs = iter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": name,
                                     "arguments": json.dumps({"arg": arg})}}]},
        {"role": "assistant", "content": "done"}])
    ran = []

    def fake_run(n, a, cf, h=None):
        if n == "screenshot":
            return "SKIP (fake)"
        ran.append((n, a))
        return tool_result
    steps = []
    patches = [
        mock.patch.object(act, "_post", lambda m, cf: next(msgs)),
        mock.patch.object(act.tools, "run", fake_run),
        mock.patch.object(g, "ground_target", ground),
        mock.patch("wisp.brain.supports_tools", return_value=True),
        mock.patch("wisp.context.snapshot", return_value=""),
        mock.patch("wisp.context.focused_app", return_value=""),
        mock.patch("wisp.platform.active_window",
                   return_value=window or {"class": "kate",
                                           "title": "Doc"}),
        mock.patch("wisp.trajectories.context_for", return_value=""),
        mock.patch("wisp.trajectories.record"),
        mock.patch("wisp.train.hint_for", return_value=""),
        mock.patch("wisp.goals.context_text", return_value=""),
        mock.patch("wisp.goals.record_steps"),
        mock.patch("wisp.goals.close"),
        mock.patch("wisp.tools.system._parse_xy",
                   lambda a: (int(a.split(",")[0]),
                              int(a.split(",")[1].split("@")[0]))),
        mock.patch.object(cua_safety, "audit_default_path",
                          lambda: pathlib.Path(audit or os.devnull)),
    ]
    for p in patches:
        p.start()
    try:
        act.run_act_loop("do it", c, state=state, steps_out=steps)
    finally:
        for p in reversed(patches):
            p.stop()
    return ran, steps


def phases(state):
    return [(d.get("phase"), d.get("x"), d.get("y"))
            for n, d in state.events if n == "cua.target"]


class ActEvents(unittest.TestCase):
    def test_aim_click_done_with_global_coords(self):
        st = FakeState()
        ran, steps = run_loop("night light", "CLICKED(500,300)",
                              lambda *a, **k: TARGET, st)
        self.assertEqual(ran, [("click", "500,300@logical")])
        self.assertEqual(phases(st), [("aim", 500, 300),
                                      ("click", 500, 300),
                                      ("done", 500, 300)])
        d = st.events[0][1]
        self.assertEqual(d["label"], "night light")
        self.assertEqual(d["window"], "Doc")
        self.assertEqual(d["confidence"], 0.9)

    def test_guide_mode_parks_aim_only(self):
        st = FakeState()
        run_loop("night light", "GUIDE(500,300)", lambda *a, **k: TARGET,
                 st, mode="guide")
        self.assertEqual(phases(st), [("aim", 500, 300)])

    def test_failed_click_clears_and_is_not_retried(self):
        st = FakeState()
        calls = []

        def gt(*a, **k):
            calls.append(a)
            return TARGET
        ran, _ = run_loop("night light", "SKIP (click failed via cua)", gt,
                          st)
        self.assertEqual(len(ran), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(phases(st), [("aim", 500, 300),
                                      (None, None, None)])

    def test_refused_grounding_never_clicks_and_clears(self):
        st = FakeState()

        def gt(*a, **k):
            raise g.GroundRefused("ground_failed", "low_confidence", "0.3")
        ran, steps = run_loop("night light", "CLICKED(1,1)", gt, st)
        self.assertEqual(ran, [])
        res = [x for x in steps if x["tool"] == "click"][0]["result"]
        self.assertTrue(res.startswith("REFUSED"))
        self.assertIn("low", res)
        self.assertNotIn("click", [p[0] for p in phases(st)])

    def test_explicit_xy_still_emits_and_skips_grounding(self):
        st = FakeState()
        gt = mock.Mock(side_effect=AssertionError("must not ground"))
        ran, _ = run_loop("40,50", "CLICKED(40,50)", gt, st)
        self.assertEqual(ran, [("click", "40,50")])
        self.assertEqual([p[0] for p in phases(st)],
                         ["aim", "click", "done"])

    def test_no_state_no_crash(self):
        ran, _ = run_loop("night light", "CLICKED(500,300)",
                          lambda *a, **k: TARGET, None)
        self.assertEqual(ran, [("click", "500,300@logical")])

    def test_move_aims_without_click_phase(self):
        st = FakeState()
        run_loop("night light", "MOVED(500,300)", lambda *a, **k: TARGET,
                 st, name="move")
        self.assertEqual(phases(st), [("aim", 500, 300)])

    def test_guard_denial_emits_no_click_and_skips_grounding(self):
        st = FakeState()
        gt = mock.Mock(side_effect=AssertionError("must not ground"))
        ran, steps = run_loop("night light", "CLICKED", gt, st,
                              window={"class": "KeePassXC", "title": ""})
        self.assertEqual(ran, [])
        res = [x for x in steps if x["tool"] == "click"][0]["result"]
        self.assertTrue(res.startswith("REFUSED"))
        self.assertNotIn("click", [p[0] for p in phases(st)])


class ActAudit(unittest.TestCase):
    def test_audit_has_xy_for_name_target(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "cua.jsonl"
            run_loop("night light", "CLICKED(500,300)",
                     lambda *a, **k: TARGET, FakeState(), audit=str(p))
            rec = json.loads(p.read_text().splitlines()[0])
        self.assertEqual((rec["x"], rec["y"]), (500, 300))
        self.assertNotIn("len", rec)
        self.assertNotIn("night", json.dumps(rec))     # name never written


class TurnStateEvents(unittest.TestCase):
    def test_turnstate_forwards_emit_event(self):
        from wisp import state as S
        with tempfile.TemporaryDirectory() as td:
            bus = S.StateBus(state=S.State(
                state_file=pathlib.Path(td) / "s.json"))
            try:
                ts = bus.turn(bus.begin_turn())
                sub = bus.subscribe(topics=["events"])
                ts.emit_event("cua.target", x=1, y=2, phase="aim")
                ev = None
                for _ in range(5):
                    ev = sub.get(timeout=1)
                    if ev and ev.get("name") == "cua.target":
                        break
                self.assertEqual(ev["data"]["x"], 1)
            finally:
                bus.close()


class SystemResolve(unittest.TestCase):
    def test_resolve_target_uses_adapter_and_survives_refusal(self):
        from wisp.tools import system
        with mock.patch.object(g, "ground_target",
                               lambda *a, **k: TARGET):
            self.assertEqual(system._resolve_target_xy("night light", {}),
                             (500, 300))
        with mock.patch.object(g, "ground_target",
                               side_effect=g.GroundRefused("ground_failed",
                                                           "not_found")):
            self.assertIsNone(system._resolve_target_xy("night light", {}))


class ClicklabSuite(unittest.TestCase):
    def test_offline_suite_matches_recorded_outputs(self):
        import arena
        fx = (pathlib.Path(__file__).parent / "fixtures" / "ground"
              / "recorded.json")
        r = arena.ground_offline(fx)
        self.assertEqual(r["cases"], 4)
        self.assertEqual(r["uitars"]["hits"], 3)
        self.assertEqual(r["baseline"]["hits"], 3)
        self.assertTrue(r["ok"])                  # not lower than current
        self.assertEqual(r["uitars"]["misses"], ["search field"])

    def test_suite_fails_when_uitars_regresses(self):
        import arena
        fx = json.loads((pathlib.Path(__file__).parent / "fixtures"
                         / "ground" / "recorded.json").read_text())
        for c in fx["cases"]:
            c["recorded"]["uitars"]["text"] = "nope"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "f.json"
            p.write_text(json.dumps(fx))
            r = arena.ground_offline(p)
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
