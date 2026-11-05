#!/usr/bin/env python3
"""U1: the offline teaching harness scores recorded planner replies.
No model call, no network."""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import gauntlet as G  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "teach"


def _write_case(root, cid, reply, kind="click", target=None, elements=None,
                with_reply=True):
    d = pathlib.Path(root) / cid
    d.mkdir(parents=True)
    els = elements if elements is not None else [
        {"label": "Save", "rect": [100, 100, 40, 20]},
        {"label": "Open", "rect": [300, 100, 40, 20]}]
    (d / "case.json").write_text(json.dumps({
        "id": cid, "app": "t", "goal": "g", "expected_kind": kind,
        "expected_target": target if target is not None else
        {"label": "Save", "rect": [100, 100, 40, 20]},
        "elements": els}))
    (d / "capture.png").write_bytes(b"\x89PNG")
    if with_reply:
        (d / "reply.json").write_text(json.dumps({"raw": reply}))
    return d


def _reply(label="Save", **extra):
    return json.dumps({"steps": [{"say": "Do it.", "label": label, **extra}]})


class Scoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def verdict(self, reply, **kw):
        d = _write_case(self.tmp, "c", reply, **kw)
        return G.score_teach_case(G.load_teach_case(d))

    def test_right_control_and_kind_is_correct_within_region(self):
        r = self.verdict(_reply(kind="click"))
        self.assertEqual(r["verdict"], G.CORRECT)
        self.assertTrue(G._in_region(r["point"], {"rect": [100, 100, 40, 20]}))

    def test_other_control_is_wrong_target(self):
        r = self.verdict(_reply("Open", kind="click"))
        self.assertEqual(r["verdict"], G.WRONG_TARGET)

    def test_omitted_kind_is_wrong_kind(self):
        r = self.verdict(_reply())
        self.assertEqual(r["verdict"], G.WRONG_KIND)
        self.assertTrue(r["target_ok"])

    def test_explicit_wrong_kind(self):
        self.assertEqual(self.verdict(_reply(kind="hover"))["verdict"],
                         G.WRONG_KIND)

    def test_unknown_label_without_coordinates_is_no_element(self):
        self.assertEqual(self.verdict(_reply("Nope", kind="click"))["verdict"],
                         G.NO_ELEMENT)

    def test_prose_reply_is_no_element(self):
        self.assertEqual(self.verdict("open the thing yourself")["verdict"],
                         G.NO_ELEMENT)

    def test_reply_coordinates_used_when_label_unknown(self):
        r = self.verdict(_reply("", kind="click", x=120, y=110))
        self.assertEqual(r["verdict"], G.CORRECT)

    def test_label_is_matched_before_coordinates(self):
        r = self.verdict(_reply("Open", kind="click", x=120, y=110))
        self.assertEqual(r["verdict"], G.WRONG_TARGET)

    def test_slack_edge(self):
        near = 100 - G.TEACH_REGION_SLACK_PX
        far = near - 1
        ok = self.verdict(_reply("", kind="click", x=near, y=110))
        self.assertEqual(ok["verdict"], G.CORRECT)
        self.tmp2 = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp2, True)
        d = _write_case(self.tmp2, "c", _reply("", kind="click", x=far, y=110))
        self.assertEqual(G.score_teach_case(
            G.load_teach_case(d))["verdict"], G.WRONG_TARGET)

    def test_voice_confirm_needs_no_target(self):
        d = _write_case(self.tmp, "v", json.dumps({"steps": [
            {"say": "Press Super and Space.", "kind": "voice-confirm"}]}),
            kind="voice-confirm", target={})
        # an empty target is allowed only for voice-confirm
        self.assertEqual(G.score_teach_case(
            G.load_teach_case(d))["verdict"], G.CORRECT)

    def test_pointing_kind_requires_a_target(self):
        _write_case(self.tmp, "bad", _reply(), target={})
        with self.assertRaises(G.TeachCaseError):
            G.load_teach_case(pathlib.Path(self.tmp) / "bad")

    def test_missing_reply_fails_loudly_and_calls_no_model(self):
        _write_case(self.tmp, "norep", "", with_reply=False)
        with mock.patch("wisp.brain.chat", side_effect=AssertionError("model")):
            with self.assertRaises(G.TeachCaseError) as cm:
                G.score_teach_cases(self.tmp)
        self.assertIn("no recorded planner reply", str(cm.exception))

    def test_empty_directory_is_an_error(self):
        with self.assertRaises(G.TeachCaseError):
            G.score_teach_cases(self.tmp)

    def test_hooks_default_to_absent(self):
        c = G.load_teach_case(_write_case(self.tmp, "h", _reply()))
        self.assertIsNone(c.ax_tree)
        self.assertIsNone(c.guide)


class SeededFixtures(unittest.TestCase):
    def test_battery_shape(self):
        dirs = [p for p in FIX.iterdir() if p.is_dir()]
        self.assertGreaterEqual(len(dirs), 12)
        self.assertLessEqual(len(dirs), 15)
        apps = {json.loads((p / "case.json").read_text())["app"]
                for p in dirs}
        self.assertTrue({"terminal", "browser", "libreoffice", "gimp",
                         "files", "omarchy"} <= apps)
        self.assertTrue((FIX / "omarchy-no-activities").is_dir())
        self.assertLess(sum(f.stat().st_size for f in FIX.rglob("*")
                            if f.is_file()), 400_000)

    def test_every_case_loads_and_expected_region_is_on_the_capture(self):
        for p in sorted(FIX.iterdir()):
            if not p.is_dir():
                continue
            c = G.load_teach_case(p)
            self.assertIn(c.expected_kind, G.TEACH_KINDS)
            t = c.expected_target
            if t:
                x, y, w, h = t["rect"]
                self.assertTrue(0 <= x and 0 <= y and x + w <= c.size[0]
                                and y + h <= c.size[1], c.id)

    def test_baseline_is_not_perfect_and_covers_every_failure_class(self):
        counts = G.score_teach_cases().counts()
        self.assertLess(counts[G.CORRECT], sum(counts.values()))
        for k in (G.WRONG_TARGET, G.WRONG_KIND, G.NO_ELEMENT):
            self.assertGreater(counts[k], 0, k)

    def test_baseline_numbers(self):
        # Quoted in the PR and docs/ACCURACY.md. Later units change these
        # on purpose and update the doc in the same commit.
        t = G.score_teach_cases()
        self.assertEqual(
            (t.counts()[G.CORRECT], t.counts()[G.WRONG_TARGET],
             t.counts()[G.WRONG_KIND], t.counts()[G.NO_ELEMENT]),
            (0, 2, 11, 2))

    def test_scoring_passes_with_the_network_blocked(self):
        def boom(*a, **k):
            raise AssertionError("network used")
        with mock.patch.object(socket.socket, "connect", boom), \
                mock.patch("socket.getaddrinfo", boom), \
                mock.patch("wisp.brain.chat", side_effect=boom):
            G.score_teach_cases()

    def test_generator_matches_checked_in_case_json(self):
        spec = importlib.util.spec_from_file_location(
            "gen_teach", ROOT / "scripts" / "gen_teach_fixtures.py")
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        g.OUT = tmp
        with contextlib.redirect_stdout(io.StringIO()):
            g.main()
        for p in FIX.iterdir():
            for f in ("case.json", "reply.json"):
                self.assertEqual((p / f).read_text(),
                                 (tmp / p.name / f).read_text(), p.name)


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "gauntlet_script_u1", ROOT / "scripts" / "gauntlet.py")
        cls.S = importlib.util.module_from_spec(spec)
        sys.modules["gauntlet_script_u1"] = cls.S
        spec.loader.exec_module(cls.S)

    def test_flag_prints_the_table(self):
        out = []
        rc = self.S.main(["--teach-offline"], out=out.append)
        self.assertEqual(rc, self.S.EXIT_OK)
        self.assertIn("first-time-correct", out[0])

    def test_flag_on_a_dir_without_reply_exits_usage(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        _write_case(tmp, "x", "", with_reply=False)
        out = []
        rc = self.S.main(["--teach-offline", tmp], out=out.append)
        self.assertEqual(rc, self.S.EXIT_USAGE)
        self.assertIn("no recorded planner reply", out[0])


if __name__ == "__main__":
    unittest.main()
