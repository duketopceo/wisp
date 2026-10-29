"""spike/lfm-local: the lfm brain provider + lfm_eval gate scoring."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from wisp import brain, svc  # noqa: E402
import lfm_eval  # noqa: E402


class LfmProviderTest(unittest.TestCase):
    def test_lfm_builtin_defaults(self):
        cfg = {"brain": {"default": "lfm:lfm25-vl-1.6b"}}
        p = brain.provider(cfg)
        self.assertEqual(p["kind"], "openai_compat")
        self.assertEqual(p["base_url"], "http://127.0.0.1:8082/v1")
        self.assertEqual(p["model"], "lfm25-vl-1.6b")
        self.assertEqual(p["vision"], "true")
        self.assertEqual(p["tools"], "false")
        self.assertFalse(p["paid"])  # loopback is never a paid call

    def test_lfm_section_overrides(self):
        cfg = {"brain": {"default": "lfm:x"},
               "brain.lfm": {"base_url": "http://10.0.0.2:9/v1",
                             "tools": "true"}}
        p = brain.provider(cfg)
        self.assertEqual(p["base_url"], "http://10.0.0.2:9/v1")
        self.assertEqual(p["tools"], "true")

    def test_lfm_unit_is_local_gated(self):
        self.assertIn("llama-lfm", svc.LLAMA)
        home = pathlib.Path(tempfile.mkdtemp())
        acts = svc.install_units(home, local=False)
        lfm = next(a for a in acts if a["name"] == "llama-lfm")
        self.assertEqual(lfm["action"], "skip")
        self.assertIn("local", lfm["reason"])
        # local on but no launcher -> still skipped, by missing ExecStart
        acts = svc.install_units(home, local=True)
        lfm = next(a for a in acts if a["name"] == "llama-lfm")
        self.assertEqual(lfm["action"], "skip")
        self.assertIn("not found", lfm["reason"])


class LfmEvalTest(unittest.TestCase):
    def _rows(self):
        return [{"name": "t1", "prompt": "say hi",
                 "expect_any": ["hi"], "_dir": ROOT},
                {"name": "t2", "prompt": "2+2?",
                 "expect": ["4"], "_dir": ROOT}]

    def test_score_all_and_any(self):
        self.assertTrue(lfm_eval.score(
            {"expect": ["a", "B"]}, "ABb..."))
        self.assertFalse(lfm_eval.score(
            {"expect": ["a", "z"]}, "abc"))
        self.assertTrue(lfm_eval.score(
            {"expect_any": ["nope", "yep"]}, "YEP."))
        self.assertFalse(lfm_eval.score(
            {"expect_any": ["nope"]}, "nah"))
        self.assertTrue(lfm_eval.score({}, "anything"))
        self.assertFalse(lfm_eval.score({}, ""))

    def test_run_provider_reports_errors_not_raises(self):
        rows = self._rows()
        with mock.patch.object(
                brain, "chat",
                side_effect=urllib_err()) as mc:
            res = lfm_eval.run_provider("lfm:x", rows, 1)
        self.assertEqual(len(res), 2)
        self.assertTrue(all(r["error"] for r in res))
        self.assertTrue(all(not r["ok"] for r in res))
        self.assertEqual(mc.call_count, 2)

    def test_summarize_and_gates(self):
        res = [{"ms": 100, "ok": True, "error": ""},
               {"ms": 200, "ok": False, "error": ""}]
        s = lfm_eval.summarize(res)
        self.assertEqual((s["accuracy"], s["p50_ms"]), (0.5, 150))
        g = lfm_eval.gates(s, {"accuracy": 0.6}, 400, 0.10, 0.5)
        self.assertTrue(all(ok for _, _, ok in g))
        g = lfm_eval.gates(s, {"accuracy": 0.9}, 100, 0.10, 0.9)
        self.assertFalse(any(ok for _, _, ok in g))

    def test_load_rows_and_fixture_file_shape(self):
        rows = lfm_eval.load_rows(
            ROOT / "tests" / "fixtures" / "lfm_gate.jsonl")
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(r.get("name") and r.get("prompt")
                            for r in rows))
        # every referenced image resolves fixture-relative
        for img in (r for r in rows if r.get("image")):
            self.assertTrue((img["_dir"] / img["image"]).exists(),
                            img["image"])

    def test_main_offline_errors_cleanly(self):
        # a dead lfm endpoint must be a gate failure (exit 1/2), not a
        # traceback
        with mock.patch.object(brain, "chat",
                               side_effect=urllib_err()):
            rc = lfm_eval.main([
                str(ROOT / "tests" / "fixtures" / "lfm_gate.jsonl"),
                "--lfm", "lfm:dead"])
        self.assertIn(rc, (1, 2))


def urllib_err():
    import urllib.error
    return urllib.error.URLError("connection refused")


if __name__ == "__main__":
    unittest.main()
