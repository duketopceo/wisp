"""Verify ladder + verdict plumbing (U2).

The cheap-first ladder runs every applicable rung over a recorded
action's frames: `action_truth` refused -> refused (no compare); a
deny-listed *visible* surface or an unreadable compositor window list
-> suppressed (the turn dir's frames are deleted); the masked pixel
diff at the predicted region plus any registered channel rung vote ->
corroborated verdicts; disagreement or mutual abstention escalates to
the VLM judge — which can only land what it saw (unknown evidence
never resolves to `landed`).

Fixtures encode PNGs by hand (zlib+struct) so neither PIL nor
ImageMagick is required to build them.
"""
import json
import pathlib
import shutil
import struct
import sys
import tempfile
import time
import unittest
import zlib
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import act, cancel, cua_safety, platform, realinput, record, \
    tools  # noqa: E402
from wisp import trace as _trace  # noqa: E402
import wisp.verify as verify  # noqa: E402


MONS = [{"x": 0, "y": 0, "width": 200, "height": 200, "scale": 1,
         "activeWorkspace": {"id": 1, "name": "1"}}]
_GRAY = (110, 110, 110)
# the masked-diff rung needs one backend: PIL in-process or ImageMagick
_HAVE_DIFF = bool(verify._PIL_AVAILABLE or shutil.which("magick")
                  or shutil.which("convert"))


def _stub_frac(before, after, rect, st):
    """Hash-equality diff for loop tests: identical frames -> 0.0
    (missed), differing bytes -> 0.5 (landed). Keeps the full ladder
    deterministic on boxes where cancel.run is faked for cua argv."""
    same = pathlib.Path(before).read_bytes() \
        == pathlib.Path(after).read_bytes()
    return 0.0 if same else 0.5


def _png_bytes(w, h, px):
    """Minimal RGB8 PNG encoder — no PIL needed to build fixtures."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    raw = b"".join(
        b"\x00" + b"".join(bytes(px(x, y)) for x in range(w))
        for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _write_png(path, w=200, h=200, blocks=()):
    """Solid gray frame with optional white blocks."""
    def px(x, y):
        for x0, y0, x1, y1 in blocks:
            if x0 <= x < x1 and y0 <= y < y1:
                return (240, 240, 240)
        return _GRAY
    pathlib.Path(path).write_bytes(_png_bytes(w, h, px))


def _turn_dir(root, seq=1, effect="delivered"):
    """A driver-style turn-NNNNN dir: action.json with action_truth."""
    d = pathlib.Path(root) / f"turn-{seq:05d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "action.json").write_text(json.dumps({
        "tool": "click",
        "args": {"session": "wisp", "x": 100, "y": 100},
        "action_truth": {
            "effect": effect, "route": "global_input",
            "transport": "linux_wayland_virtual_pointer",
            "refusal": "deny" if effect == "refused" else None},
        "ts": time.time()}))
    return d


def _step(d, name="click", arg="100,100@logical", effect="delivered",
          extra=None):
    s = {"tool": name, "arg": arg, "turn_dir": str(d),
         "action_truth": {"effect": effect, "route": "global_input",
                          "transport": "linux_wayland_virtual_pointer",
                          "refusal": None}}
    if extra:
        s.update(extra)
    return s


def call(step, **kw):
    """verify.verdict with clean-window defaults injected."""
    kw.setdefault("clients", [])
    kw.setdefault("monitors", MONS)
    return verify.verdict(step, **kw)


class LadderCase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = pathlib.Path(self.td.name)
        self.trace_file = self.root / "trace.jsonl"
        for p in (mock.patch.object(_trace, "TRACE_FILE", self.trace_file),
                  mock.patch.object(_trace, "_enabled", True)):
            p.start()
            self.addCleanup(p.stop)

    def frames(self, d, changed=False, name="after.png"):
        _write_png(d / "before.png")
        _write_png(d / name,
                   blocks=[(60, 60, 150, 150)] if changed else ())

    def trace_events(self, step=None):
        evs = _trace.read(path=self.trace_file, tail=10000)
        return [e for e in evs if step is None or e["step"] == step]


@unittest.skipUnless(_HAVE_DIFF, "no PIL or ImageMagick diff backend")
class Ladder(LadderCase):
    def test_unrecorded_step_returns_none(self):
        # no turn_dir -> the U1 `not_recorded` seed stands
        self.assertIsNone(call({"tool": "click", "arg": "1,2"}))

    def test_refused_is_refused_without_any_compare(self):
        d = _turn_dir(self.root, effect="refused")
        self.frames(d, changed=True)
        calls = []

        def pixel(ctx):
            calls.append(ctx)
            return {"vote": "landed", "detail": "should not run"}
        vd = call(_step(d, effect="refused"), rungs={"pixel": pixel})
        self.assertEqual(vd["verdict"], "refused")
        self.assertEqual(vd["source"], "action_truth")
        self.assertFalse(vd["corroborated"])
        self.assertEqual(calls, [])
        self.assertEqual(vd["evidence"], str(d))

    def test_changed_region_is_landed_uncorroborated(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        vd = call(_step(d))
        self.assertEqual(vd["verdict"], "landed")
        self.assertEqual(vd["source"], "pixel")
        # lone-source landed is down-weighted, not label-grade (R2a)
        self.assertFalse(vd["corroborated"])
        self.assertEqual(vd["evidence"], str(d))
        self.assertEqual(vd["claim"]["kind"], "region")

    def test_unchanged_region_is_missed_uncorroborated(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=False)
        vd = call(_step(d))
        self.assertEqual(vd["verdict"], "missed")
        self.assertEqual(vd["source"], "pixel")
        # symmetric: a lone unchanged-region diff can't prove a miss
        self.assertFalse(vd["corroborated"])

    def test_agreeing_rungs_corroborate(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)

        def control(ctx):
            return {"vote": "landed", "detail": "ui.inspect diff"}
        vd = call(_step(d), rungs={"pixel": verify.RUNGS["pixel"],
                                   "control": control})
        self.assertEqual(vd["verdict"], "landed")
        self.assertEqual(vd["source"], "control+pixel")
        self.assertTrue(vd["corroborated"])

    def test_agreeing_miss_corroborates(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=False)

        def control(ctx):
            return {"vote": "missed", "detail": "state unchanged"}
        vd = call(_step(d), rungs={"pixel": verify.RUNGS["pixel"],
                                   "control": control})
        self.assertEqual(vd["verdict"], "missed")
        self.assertTrue(vd["corroborated"])

    def test_disagreement_fires_the_judge(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        seen = []

        def control(ctx):
            return {"vote": "missed", "detail": "state unchanged"}

        def judge(before, after, claim, step, cfg):
            seen.append((before, after))
            return {"verdict": "landed", "detail": "button toggled"}
        vd = call(_step(d), rungs={"pixel": verify.RUNGS["pixel"],
                                   "control": control}, judge=judge)
        self.assertEqual(len(seen), 1)
        self.assertEqual(vd["verdict"], "landed")
        self.assertEqual(vd["source"], "judge")
        self.assertTrue(vd["corroborated"])

    def test_mutual_abstention_calls_judge_with_both_frames(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        # a name target with no coords -> no predicted region -> pixel
        # abstains; no channel registered -> mutual abstention -> judge
        s = _step(d, arg="the menu icon", extra={"tool_arg": ""})
        s["arg"] = "the menu icon"
        seen = []

        def judge(before, after, claim, step, cfg):
            seen.append((pathlib.Path(before).name,
                         pathlib.Path(after).name, claim))
            return {"verdict": "missed", "detail": "nothing moved"}
        vd = call(s, judge=judge, name="click",
                  arg="the menu icon", tool_arg="")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:2], ("before.png", "after.png"))
        self.assertEqual(vd["verdict"], "missed")
        self.assertEqual(vd["source"], "judge")

    def test_ambiguous_fraction_abstains_to_judge(self):
        # ~1% of the region changes: between missed_max and landed_min
        d = _turn_dir(self.root)
        _write_png(d / "before.png")
        _write_png(d / "after.png", blocks=[(60, 60, 61, 160)])
        seen = []

        def judge(before, after, claim, step, cfg):
            seen.append(claim)
            return {"verdict": "landed", "detail": "saw it"}
        vd = call(_step(d), judge=judge)
        self.assertTrue(seen)
        self.assertEqual(vd["source"], "judge")
        self.assertEqual(vd["verdict"], "landed")

    def test_judge_error_is_unverifiable_never_landed(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)

        def control(ctx):
            return {"vote": "missed", "detail": "state unchanged"}

        def judge(*a):
            raise TimeoutError("endpoint down")
        vd = call(_step(d), rungs={"pixel": verify.RUNGS["pixel"],
                                   "control": control}, judge=judge)
        self.assertEqual(vd["verdict"], "unverifiable")
        self.assertEqual(vd["source"], "judge")
        self.assertFalse(vd["corroborated"])

    def test_judge_garbage_is_unverifiable(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)

        def control(ctx):
            return {"vote": "missed", "detail": "x"}
        vd = call(_step(d), rungs={"pixel": verify.RUNGS["pixel"],
                                   "control": control},
                  judge=lambda *a: {"verdict": "banana"})
        self.assertEqual(vd["verdict"], "unverifiable")
        self.assertFalse(vd["corroborated"])

    def test_verify_trace_event(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        call(_step(d))
        evs = self.trace_events("verify")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "verify")
        self.assertEqual(evs[0]["data"]["verdict"], "landed")
        self.assertEqual(evs[0]["data"]["source"], "pixel")


@unittest.skipUnless(_HAVE_DIFF, "no PIL or ImageMagick diff backend")
class Privacy(LadderCase):
    def test_deny_surface_visible_suppresses_and_deletes(self):
        # a deny-listed client mapped on the visible workspace — it
        # need NOT be focused: capture suppression keys on visibility
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        clients = [{"class": "1Password", "title": "Unlock",
                    "mapped": True, "hidden": False,
                    "workspace": {"id": 1, "name": "1"}}]
        vd = call(_step(d), clients=clients)
        self.assertEqual(vd["verdict"], "suppressed")
        self.assertEqual(vd["source"], "privacy")
        self.assertFalse(vd["corroborated"])
        # zero frames survive; the suppression is itself recorded
        self.assertEqual(list(d.glob("*.png")), [])
        ev = json.loads((d / "evidence.json").read_text())
        self.assertTrue(ev["privacy_suppressed"])

    def test_deny_on_hidden_workspace_does_not_suppress(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        clients = [{"class": "keepassxc", "title": "", "mapped": True,
                    "workspace": {"id": 9, "name": "9"}}]
        vd = call(_step(d), clients=clients)
        self.assertEqual(vd["verdict"], "landed")

    def test_config_deny_class_suppresses(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        cfg = {"cua": {"deny": "secretdialog"}}
        clients = [{"class": "SecretDialog", "title": "", "mapped": True,
                    "workspace": {"id": 1}}]
        vd = call(_step(d), clients=clients, cfg=cfg)
        self.assertEqual(vd["verdict"], "suppressed")

    def test_unreadable_window_list_suppresses(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=True)

        def boom():
            raise OSError("compositor socket gone")
        vd = call(_step(d), clients=boom)
        self.assertEqual(vd["verdict"], "suppressed")
        self.assertEqual(list(d.glob("*.png")), [])

    def test_spawned_deny_surface_deletes_the_frames(self):
        # the click raised a credential dialog that post-dates the
        # dispatch: the post-dispatch re-check finds it and the frames
        # it landed in are deleted at the re-check
        d = _turn_dir(self.root)
        self.frames(d, changed=True)
        clients = [{"class": "gcr-prompter", "title": "Password",
                    "mapped": True, "workspace": {"id": 1}}]
        vd = call(_step(d), clients=clients)
        self.assertEqual(vd["verdict"], "suppressed")
        self.assertEqual(list(d.glob("*.png")), [])
        ev = json.loads((d / "evidence.json").read_text())
        self.assertTrue(ev["privacy_suppressed"])
        self.assertIn("gcr-prompter", ev["suppression"]["reason"])
        self.assertEqual(sorted(ev["suppression"]["deleted_frames"]),
                         ["after.png", "before.png"])


@unittest.skipUnless(_HAVE_DIFF, "no PIL or ImageMagick diff backend")
class Terminal(LadderCase):
    def test_terminal_capture_reruns_the_ladder(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=False)
        s = _step(d)
        first = call(s)
        self.assertEqual(first["verdict"], "missed")
        s["verify"] = first

        def cap(path):
            _write_png(path, blocks=[(60, 60, 150, 150)])
            return True
        vd = verify.terminal_verdict(s, cfg={}, capture=cap,
                                     clients=[], monitors=MONS)
        self.assertIsNotNone(vd)
        self.assertEqual(vd["verdict"], "landed")
        self.assertTrue((d / "after_terminal.png").exists())
        evs = [e for e in self.trace_events("verify")
               if e["data"].get("terminal")]
        self.assertTrue(evs)

    def test_terminal_suppression_never_captures(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=False)
        s = _step(d)
        s["verify"] = call(s)
        called = []

        def cap(path):
            called.append(path)
            return True
        clients = [{"class": "pinentry", "title": "", "mapped": True,
                    "workspace": {"id": 1}}]
        vd = verify.terminal_verdict(s, cfg={}, capture=cap,
                                     clients=clients, monitors=MONS)
        self.assertEqual(vd["verdict"], "suppressed")
        self.assertEqual(called, [])
        self.assertEqual(list(d.glob("*.png")), [])

    def test_terminal_capture_failure_keeps_the_verdict(self):
        d = _turn_dir(self.root)
        self.frames(d, changed=False)
        s = _step(d)
        s["verify"] = call(s)
        vd = verify.terminal_verdict(s, cfg={}, capture=lambda p: False,
                                     clients=[], monitors=MONS)
        self.assertIsNone(vd)
        self.assertEqual(s["verify"]["verdict"], "missed")


class Postcondition(unittest.TestCase):
    def test_element_rect_from_target(self):
        tgt = SimpleNamespace(x=50, y=60, rect=(40, 50, 20, 12),
                              label="OK")
        c = verify.postcondition("click", "OK", "50,60@logical", tgt)
        self.assertEqual(c["kind"], "element")
        self.assertEqual(c["rect"], [40, 50, 20, 12])
        self.assertEqual(c["label"], "OK")

    def test_point_region_box(self):
        tgt = SimpleNamespace(x=100, y=100, rect=None, label="")
        c = verify.postcondition("click", "", "100,100@logical", tgt)
        self.assertEqual(c["kind"], "region")
        self.assertEqual(c["rect"], [52, 52, 96, 96])
        self.assertEqual(c["point"], [100, 100])

    def test_arg_coords_when_no_target(self):
        c = verify.postcondition("click", "100,100", "100,100@logical",
                                 None)
        self.assertEqual(c["kind"], "region")
        self.assertEqual(c["rect"], [52, 52, 96, 96])

    def test_no_region_is_an_effect_claim(self):
        c = verify.postcondition("click", "menu icon", "menu icon",
                                 None)
        self.assertEqual(c["kind"], "effect")
        self.assertNotIn("rect", c)


class FakeDriver:
    """`cua-driver call` boundary fake (as in test_record) — records
    argv, answers session/recording control calls; `action()` writes a
    turn dir with action.json AND before/after frames like the real
    writer."""

    def __init__(self, changed=False):
        self.argv = []
        self.rec_dir = None
        self.seq = 0
        self.changed = changed

    def run(self, argv, **kw):
        cancel.check()
        if argv[:2] != ["cua-driver", "call"]:
            raise AssertionError(f"not a cua call: {argv}")
        tool = argv[2]
        args = json.loads(argv[3]) if len(argv) > 3 else {}
        self.argv.append((tool, args))
        if tool == "start_session":
            return self._done({"active": True})
        if tool == "start_recording":
            self.rec_dir = pathlib.Path(args["output_dir"])
            return self._done({"recording": True})
        if tool == "stop_recording":
            return self._done({"recording": False})
        return self._done({"tool": tool})

    @staticmethod
    def _done(result, rc=0):
        import subprocess
        return subprocess.CompletedProcess(
            ["cua-driver"], rc,
            stdout=json.dumps(result).encode(), stderr=b"")

    def action(self, tool, x=None, y=None):
        self.seq += 1
        d = pathlib.Path(self.rec_dir) / f"turn-{self.seq:05d}"
        d.mkdir(parents=True, exist_ok=True)
        args = {"session": "wisp", "scope": "desktop"}
        if x is not None:
            args["x"], args["y"] = x, y
        (d / "action.json").write_text(json.dumps({
            "tool": tool, "args": args,
            "action_truth": {
                "effect": "delivered", "route": "global_input",
                "transport": "linux_wayland_virtual_pointer",
                "refusal": None},
            "ts": time.time()}))
        _write_png(d / "before.png")
        _write_png(d / "after.png",
                   blocks=[(60, 60, 150, 150)] if self.changed else ())
        return d


DRIVE = {"pointer": {"mode": "drive", "backend": "auto"},
         "brain": {"default": "lmstudio:fake"},
         "brain.lmstudio": {"tools": "true", "vision": "false",
                            "kind": "openai_compat",
                            "base_url": "http://127.0.0.1:1"}}


def _msg(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


def _call(name, arg=""):
    return {"id": f"c_{name}_{arg[:8]}", "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"arg": arg})}}


class Loop(LadderCase):
    """End-to-end through run_act_loop: the verdict is suffixed onto
    the tool_result the model sees, lands on the step record, and the
    terminal after-frame re-verifies the turn's final mutation."""

    def setUp(self):
        super().setUp()
        realinput._stop_for_test()
        t = self.root
        self.driver = FakeDriver(changed=False)
        self._patchers = [
            mock.patch("wisp.cancel.run", side_effect=self.driver.run),
            mock.patch.object(record, "REC_DIR", t / "rec"),
            mock.patch.object(act.realinput, "begin",
                              return_value="off"),
            mock.patch.object(act, "_record_traj"),
            mock.patch.object(platform, "_cua_live", return_value=True),
            mock.patch.object(cua_safety, "audit_default_path",
                              return_value=t / "cua.jsonl"),
            mock.patch.object(cua_safety, "kill_default_path",
                              return_value=t / "cua.kill"),
            mock.patch.object(verify, "_clients", return_value=[]),
            mock.patch.object(verify, "_monitors", return_value=MONS),
            # the loop still runs the whole ladder; only the pixel
            # fraction is stubbed — cancel.run is faked for cua argv
            # so a real ImageMagick call can't run here anyway
            mock.patch.object(verify, "_diff_frac",
                              side_effect=_stub_frac),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._unpatch)

    def _unpatch(self):
        for p in reversed(self._patchers):
            p.stop()

    def fake_tools(self):
        def run(name, arg, cfg, harness=None):
            if name == "click":
                x, y = (int(v)
                        for v in arg.split("@")[0].split(",")[:2])
                self.driver.action("click", x, y)
                return f"CLICKED({x},{y})"
            if name == "move":
                return "MOVED(0,0)"
            return "OK"
        return run

    def test_verdict_suffix_step_record_and_terminal_recheck(self):
        replies = [_msg(calls=[_call("click", "100,100@logical")]),
                   _msg(content="done")]
        steps = []
        _trace.set_turn("t-vfy1")

        def cap(path):
            # the terminal after-frame: the effect finally rendered
            _write_png(path, blocks=[(60, 60, 150, 150)])
            return True
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run",
                                  side_effect=self.fake_tools()), \
                mock.patch.object(verify, "_capture",
                                  side_effect=cap):
            out = act.run_act_loop("click the thing", DRIVE,
                                   steps_out=steps)
        self.assertTrue(out.startswith("ACTED"), out)
        click = [s for s in steps if s["tool"] == "click"][0]
        # mid-loop: the driver's after.png was unchanged -> missed,
        # suffixed onto the result the model saw
        self.assertIn('"verdict":"missed"', click["result"])
        # terminal re-check captured once more and the ladder flipped
        # the step's verdict — the freshest evidence wins the record
        self.assertEqual(click["verdict"], "landed")
        self.assertEqual(click["verify"]["verdict"], "landed")
        self.assertTrue(click["verify"]["corroborated"] is False)
        tdir = pathlib.Path(click["turn_dir"])
        self.assertTrue((tdir / "after_terminal.png").exists())
        evs = self.trace_events("verify")
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["data"]["verdict"], "missed")
        self.assertTrue(evs[1]["data"]["terminal"])
        self.assertEqual(evs[1]["data"]["verdict"], "landed")

    def test_unrecorded_mutating_tool_keeps_not_recorded(self):
        replies = [_msg(calls=[_call("type_text", "hi")]),
                   _msg(content="done")]
        steps = []
        _trace.set_turn("t-vfy2")
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run",
                                  side_effect=self.fake_tools()):
            out = act.run_act_loop("type", DRIVE, steps_out=steps)
        self.assertTrue(out.startswith("ACTED"), out)
        self.assertEqual(steps[0]["verdict"], "not_recorded")
        self.assertNotIn("verify", steps[0])
        self.assertNotIn('"verdict"', steps[0]["result"])
