"""Telemetry digest, focus context, action stats."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wisp import action_stats, context, telemetry


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class TelemetryTest(unittest.TestCase):

    def _dec(self, route="act", result="ACTED", timing=None, ts=None):
        return {"ts": ts or "2030-01-01T00:00:00+00:00",
                "answers": {"route": {"choice": route}},
                "result": result,
                "timing_ms": timing or {"jev_ms": 100}}

    def test_digest_counts_routes_and_latency(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "dec.jsonl"
            _write(f, [self._dec(), self._dec("answer", "ANSWERED"),
                       self._dec("act", "BLOCKED (x)")])
            out = telemetry.digest(decisions_file=f, trace_file=f)
            self.assertEqual(out["turns"], 3)
            self.assertEqual(out["routes"]["act"], 2)
            self.assertEqual(out["avg_ms"]["jev_ms"], 100)
            self.assertEqual(out["outcomes"]["fail"], 1)

    def test_digest_empty(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "none.jsonl"
            self.assertEqual(telemetry.digest(decisions_file=f,
                                              trace_file=f)["turns"], 0)


class ActionStatsTest(unittest.TestCase):

    def _traj(self, app, tool, result, n=1):
        return [{"app": app, "task": "t",
                 "steps": [{"tool": tool, "arg": "", "result": result}] * n,
                 "outcome": "ACTED"}]

    def test_block_for_rates_and_suspects(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "traj.jsonl"
            _write(f, self._traj("godot", "click", "ok", 4)
                    + self._traj("godot", "click", "FAIL", 1)
                    + self._traj("godot", "shell", "SKIPPED", 4))
            blk = action_stats.block_for("godot", path=f)
            self.assertIn("godot", blk)
            self.assertIn("click 4/5", blk)
            self.assertIn("suspect: shell 0/4", blk)

    def test_block_for_unknown_app_empty(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "traj.jsonl"
            _write(f, self._traj("godot", "click", "ok"))
            self.assertEqual(action_stats.block_for("blender", path=f), "")


class ContextTest(unittest.TestCase):

    def test_snapshot_focus_fields(self):
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "Godot",
                                      "title": "MyGame - editor"}), \
             mock.patch("wisp.context._last_dayflow",
                        return_value="editing player scene"), \
             mock.patch("wisp.context.app_skills",
                        return_value=["godot-help"]):
            blk = context.snapshot({"act": {"context": "full"}})
            self.assertIn("app=Godot", blk)
            self.assertIn("doing=", blk)
            self.assertIn("skills=godot-help", blk)

    def test_snapshot_off_and_minimal(self):
        self.assertEqual(
            context.snapshot({"act": {"context": "off"}}), "")
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "Godot",
                                      "title": "secret title"}):
            blk = context.snapshot({"act": {"context": "minimal"}})
            self.assertIn("app=Godot", blk)
            self.assertNotIn("title", blk)

    def test_app_skills_matches(self):
        fake = [{"name": "godot-tools", "description": "godot editor"},
                {"name": "rust-fmt", "description": "format rust"}]
        with mock.patch("wisp.skills.index", return_value=fake):
            self.assertEqual(context.app_skills("godot"), ["godot-tools"])


if __name__ == "__main__":
    unittest.main()
