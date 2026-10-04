"""Shadow decider: record a second model's answers on every routed turn.

The shadow exists so two decision models can be scored against human
labels, not against each other. What these tests pin is the safety
contract: a shadow never changes the answer the turn acts on, never
blocks, and never turns its own failure into a turn failure.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import wisp.session  # noqa: F401  (patched by name below; must be imported)
from wisp import config, pipeline


def _resp(payload):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()
    return R()


class ShadowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = pathlib.Path(self.tmp.name) / "shadow.jsonl"
        p = mock.patch.object(config, "SHADOW", self.file)
        p.start()
        self.addCleanup(p.stop)

    def _inline(self):
        """Run the shadow on the calling thread.

        A real daemon thread would race the assertions; the production
        code still uses one, this only makes the test deterministic.
        """
        class Inline:
            def __init__(self, target=None, args=(), daemon=None, **kw):
                self.target, self.args = target, args

            def start(self):
                assert self.target is not None
                self.target(*self.args)
        return mock.patch.object(pipeline.threading, "Thread", Inline)

    # --- gating -------------------------------------------------------
    def test_off_by_default(self):
        with mock.patch.object(pipeline, "_shadow_worker") as w:
            pipeline._shadow_decision("t", "s", {}, {}, {"answers": {}}, "m")
        w.assert_not_called()
        self.assertFalse(self.file.exists())

    def test_unknown_provider_is_ignored(self):
        with mock.patch.object(pipeline, "_shadow_worker") as w:
            pipeline._shadow_decision("t", "s", {},
                                      {"jev": {"shadow": "nope"}},
                                      {"answers": {}}, "m")
        w.assert_not_called()

    def test_no_key_means_no_call(self):
        with mock.patch.object(config, "load_env_key", return_value=""), \
             mock.patch.object(pipeline, "_shadow_worker") as w:
            pipeline._shadow_decision("t", "s", {},
                                      {"jev": {"shadow": "pplx"}},
                                      {"answers": {}}, "m")
        w.assert_not_called()

    # --- the record ---------------------------------------------------
    def test_logs_both_answers_and_agreement(self):
        primary = {"answers": {"route": {"choice": "launch"},
                               "risk": {"score": 1.0}}}
        shadow = {"answers": {"route": {"choice": "launch"},
                              "risk": {"score": 1.4}},
                  "usage": {"input_tokens": 2500}}
        with mock.patch.object(config, "load_env_key", return_value="k"), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=_resp(shadow)), \
             self._inline():
            pipeline._shadow_decision("open spotify", "state", {},
                                      {"jev": {"shadow": "pplx"}},
                                      primary, "typesafe/jev-1.13")

        rec = json.loads(self.file.read_text().splitlines()[0])
        self.assertEqual(rec["transcript"], "open spotify")
        self.assertEqual(rec["primary"]["model"], "typesafe/jev-1.13")
        self.assertEqual(rec["primary"]["answers"]["route"]["choice"], "launch")
        self.assertEqual(rec["shadow"]["provider"], "pplx")
        self.assertEqual(rec["shadow"]["answers"]["route"]["choice"], "launch")
        self.assertEqual(rec["shadow"]["input_tokens"], 2500)
        self.assertTrue(rec["agree"]["route"])
        # 1.0 and 1.4 are the same level on a 3-level rubric
        self.assertTrue(rec["agree"]["risk"])

    def test_appends_rather_than_overwrites(self):
        shadow = {"answers": {"route": {"choice": "answer"}}}
        with mock.patch.object(config, "load_env_key", return_value="k"), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=_resp(shadow)), \
             self._inline():
            for tr in ("one", "two"):
                pipeline._shadow_decision(tr, "s", {},
                                          {"jev": {"shadow": "pplx"}},
                                          shadow, "m")
        rows = self.file.read_text().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertEqual([json.loads(r)["transcript"] for r in rows],
                         ["one", "two"])

    # --- never harmful ------------------------------------------------
    def test_shadow_failure_writes_nothing_and_does_not_raise(self):
        with mock.patch.object(config, "load_env_key", return_value="k"), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               side_effect=OSError("network down")), \
             self._inline():
            pipeline._shadow_decision("t", "s", {},
                                      {"jev": {"shadow": "pplx"}},
                                      {"answers": {}}, "m")
        self.assertFalse(self.file.exists())

    def test_unwritable_shadow_path_does_not_raise(self):
        shadow = {"answers": {"route": {"choice": "launch"}}}
        with mock.patch.object(config, "load_env_key", return_value="k"), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=_resp(shadow)), \
             mock.patch.object(config, "SHADOW",
                               pathlib.Path("/proc/nope/shadow.jsonl")), \
             self._inline():
            pipeline._shadow_decision("t", "s", {},
                                      {"jev": {"shadow": "pplx"}},
                                      shadow, "m")   # must not raise

    def test_worker_stamps_the_turn_it_is_given(self):
        shadow = {"answers": {"route": {"choice": "launch"}}}
        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=_resp(shadow)):
            pipeline._shadow_worker("pplx", config.SHADOW_PROVIDERS["pplx"],
                                    "k", "t", "s", {}, shadow, "m", "t1a2b3c4")
        rec = json.loads(self.file.read_text().splitlines()[0])
        self.assertEqual(rec["turn"], "t1a2b3c4")

    def test_decision_record_carries_the_same_turn_id(self):
        """Scoring pairs a shadow record with the decision a human labels,
        and that pairing must key on the turn id — matching on transcript
        plus timestamp mis-pairs a repeated utterance."""
        logged = {}
        with mock.patch.object(pipeline, "record",
                               return_value=pathlib.Path("/tmp/x.wav")), \
             mock.patch.object(pipeline, "transcribe", return_value="hi"), \
             mock.patch.object(pipeline, "ask_jev",
                               return_value={"answers":
                                             {"route": {"choice": "answer"}}}), \
             mock.patch.object(pipeline, "ask_chat", return_value="hello"), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(pipeline, "log_decision",
                               side_effect=lambda r: logged.update(r)), \
             mock.patch.object(sys.modules["wisp.session"],
                               "append_turn"), \
             mock.patch.object(sys.modules["wisp.session"], "tail",
                               return_value=[]), \
             mock.patch.object(sys.modules["wisp.session"], "as_text",
                               return_value=""):
            st = mock.Mock()
            st.state = {}
            st.transition = lambda s, **kw: st.state.update(status=s, **kw)
            rc = pipeline.run_listen(
                {"audio": {"seconds": "0"}, "agent": {}, "jev": {},
                 "brain": {"router": "jev"}}, st)
        self.assertEqual(rc, 0)
        self.assertRegex(logged.get("turn", ""), r"^t[0-9a-f]{8}$")

    def test_ask_jev_returns_the_primary_untouched(self):
        primary = {"answers": {"route": {"choice": "answer"}}}
        # Pin the key too. Without this the test only passed on a host
        # that happens to have OPENROUTER_API_KEY set, and raised on a
        # clean runner instead of exercising the shadow at all.
        with mock.patch.object(config, "load_api_key", return_value="k"), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=_resp(primary)), \
             mock.patch.object(pipeline, "_shadow_decision") as sd:
            out = pipeline.ask_jev("hi", "m", {},
                                   cfg={"jev": {"shadow": "pplx"}})
        # equal, not identical: the test double round-trips through JSON.
        # What matters is that ask_jev returns the primary answer as-is
        # rather than a shadow-influenced one.
        self.assertEqual(out, primary)
        sd.assert_called_once()

    def test_shadow_is_skipped_entirely_for_non_jev_routers(self):
        """The chat/off routers synthesise an answer and never call
        ask_jev, so there is nothing to shadow."""
        with mock.patch.object(pipeline, "_shadow_decision") as sd, \
             mock.patch.object(pipeline, "record",
                               return_value=pathlib.Path("/tmp/x.wav")), \
             mock.patch.object(pipeline, "transcribe", return_value="hi"), \
             mock.patch.object(pipeline, "ask_chat", return_value="hello"), \
             mock.patch.object(pipeline, "notify"):
            st = mock.Mock()
            st.state = {}
            st.transition = lambda s, **kw: st.state.update(status=s, **kw)
            rc = pipeline.run_listen(
                {"audio": {"seconds": "0"}, "agent": {},
                 "brain": {"router": "chat"},
                 "jev": {"shadow": "pplx"}}, st)
        self.assertEqual(rc, 0)
        sd.assert_not_called()


class ShadowAgreeTest(unittest.TestCase):
    def test_choice_matches_on_the_pick(self):
        a = {"answers": {"q": {"choice": "launch"}}}
        self.assertTrue(pipeline._shadow_agree(a,
                        {"answers": {"q": {"choice": "launch"}}})["q"])
        self.assertFalse(pipeline._shadow_agree(a,
                         {"answers": {"q": {"choice": "tool"}}})["q"])

    def test_noul_is_a_probability_not_a_label(self):
        f = lambda v: {"answers": {"n": {"noul": v}}}     # noqa: E731
        self.assertTrue(pipeline._shadow_agree(f(0.82), f(0.90))["n"])
        self.assertFalse(pipeline._shadow_agree(f(0.82), f(0.20))["n"])

    def test_score_compares_rounded_level(self):
        f = lambda v: {"answers": {"r": {"score": v}}}    # noqa: E731
        self.assertTrue(pipeline._shadow_agree(f(1.0), f(1.4))["r"])
        self.assertFalse(pipeline._shadow_agree(f(1.0), f(2.0))["r"])

    def test_missing_question_reports_none(self):
        out = pipeline._shadow_agree({"answers": {"a": {"choice": "x"}}},
                                     {"answers": {}})
        self.assertIsNone(out["a"])


class ShadowConfigTest(unittest.TestCase):
    def test_default_config_ships_the_jev_section_off(self):
        self.assertIn("[jev]", config.DEFAULT_CONFIG)
        self.assertIn('shadow = ""', config.DEFAULT_CONFIG)

    def test_pplx_spec_is_complete(self):
        spec = config.SHADOW_PROVIDERS["pplx"]
        self.assertEqual(spec["model"], "pplx-decider-v1-27b")
        self.assertTrue(spec["endpoint"].startswith("https://"))
        self.assertEqual(spec["key_env"], "PERPLEXITY_API_KEY")


if __name__ == "__main__":
    unittest.main()