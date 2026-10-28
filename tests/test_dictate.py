#!/usr/bin/env python3
"""U6 dictation: raw/cleanup/compose modes, per-app profiles, the
terminal newline guard, personal corrections and the insert fallback
chain."""
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import cua_safety, dictate, tools  # noqa: E402
from wisp.tools import system as _sys  # noqa: E402


def _state(cls="", title=""):
    s = mock.Mock()
    s.focus = {"app": cls, "title": title}
    return s


class RunTest(unittest.TestCase):
    """dictate.run against a stub insert + stub brain."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.f = pathlib.Path(self.td) / "dictation.json"
        self.inserted = []
        self.keys = []                    # tools.run("key", ...) calls
        self.tail = ""                    # session tail stub

    def _keyspy(self, name, arg, cfg):
        self.keys.append((name, arg))
        return "KEY"

    def go(self, text, cfg=None, cls="", title="", confirm=None,
           mode=None, chat=None):
        """run() with insert/brain/FILE hermetic. `chat` is the canned
        brain reply (str) or an exception instance to raise."""
        cfg = cfg or {}
        self.inserted.clear()
        self.keys.clear()

        def fake_insert(t, c, guard=None):
            self.inserted.append(t)
            return "typed", ""

        # a real Guard over hermetic inputs — the dictation route's
        # key/type calls go through the same gate the act loop uses
        guard = cua_safety.Guard(
            cfg, state=_state(cls, title),
            window=lambda: {"app": cls, "title": title},
            audit_path=pathlib.Path(self.td) / "cua.jsonl",
            kill_path=pathlib.Path(self.td) / "cua.kill")

        if isinstance(chat, Exception):
            chat_fn = mock.Mock(side_effect=chat)
        else:
            chat_fn = mock.Mock(
                return_value={"content": chat or "stub reply"})
        self.chat = chat_fn
        with mock.patch.object(dictate, "FILE", self.f), \
             mock.patch.object(dictate, "insert", fake_insert), \
             mock.patch.object(dictate, "_session_tail",
                               return_value=self.tail), \
             mock.patch.object(dictate, "_chat", chat_fn), \
             mock.patch.object(tools, "run",
                               side_effect=self._keyspy):
            return dictate.run(text, cfg, state=_state(cls, title),
                               confirm=confirm, mode=mode, guard=guard)

    # -- modes ----------------------------------------------------------

    def test_raw_is_verbatim_and_never_calls_the_brain(self):
        out = self.go("hello   world", {"dictation": {"mode": "raw"}},
                      cls="chromium")
        self.assertEqual(self.inserted, ["hello   world"])
        self.assertEqual(out, "INSERTED: hello   world")
        self.chat.assert_not_called()

    def test_cleanup_rewrites_through_the_brain(self):
        out = self.go("hello   world",
                      {"dictation": {"mode": "cleanup"}},
                      cls="chromium", chat="Hello world.")
        self.assertEqual(self.inserted, ["Hello world."])
        self.assertEqual(out, "INSERTED: Hello world.")
        msgs = self.chat.call_args[0][0]
        self.assertEqual(msgs[1]["content"], "hello   world")
        self.assertIn("Preserve the user", msgs[0]["content"])

    def test_compose_prompt_carries_focused_app(self):
        self.go("i want to tell sam the deploy went fine",
                {"dictation": {"mode": "compose"}},
                cls="chromium", title="Gmail - Compose",
                chat="Hi Sam, the deploy went fine.")
        msgs = self.chat.call_args[0][0]
        self.assertIn("composer", msgs[0]["content"])
        self.assertIn("chromium", msgs[0]["content"])
        self.assertIn("Gmail - Compose", msgs[0]["content"])
        self.assertEqual(self.inserted, ["Hi Sam, the deploy went fine."])

    def test_compose_intent_promotes_cleanup_default(self):
        self.go("write an email to sam about the deploy",
                {"dictation": {"mode": "cleanup"}}, cls="chromium",
                chat="Hi Sam, ...")
        self.assertIn("composer", self.chat.call_args[0][0][0]["content"])

    def test_compose_prompt_carries_session_tail(self):
        self.tail = "user: deploy finished\nwisp: noted"
        self.go("tell sam it went fine",
                {"dictation": {"mode": "compose"}}, cls="chromium",
                chat="Dear Sam,")
        user = self.chat.call_args[0][0][1]["content"]
        self.assertIn("deploy finished", user)

    def test_spoken_mode_token_overrides_default(self):
        out = self.go("raw keep   the   spacing",
                      {"dictation": {"mode": "cleanup"}}, cls="x")
        self.chat.assert_not_called()              # cleaned mode -> raw
        self.assertEqual(self.inserted, ["keep   the   spacing"])
        self.assertTrue(out.startswith("INSERTED"), out)

    def test_explicit_mode_arg_beats_everything(self):
        out = self.go("anything",
                      {"dictation": {"mode": "compose"},
                       "dictation.profiles.chromium": {"mode": "raw"}},
                      cls="chromium", mode="raw")
        self.chat.assert_not_called()
        self.assertEqual(self.inserted, ["anything"])
        self.assertTrue(out.startswith("INSERTED"), out)

    def test_brain_failure_degrades_to_raw_transcript(self):
        out = self.go("the literal words",
                      {"dictation": {"mode": "cleanup"}}, cls="chromium",
                      chat=RuntimeError("down"))
        self.assertEqual(self.inserted, ["the literal words"])
        self.assertTrue(out.startswith("INSERTED"), out)

    # -- profiles -------------------------------------------------------

    def test_profile_picks_mode_and_style(self):
        cfg = {"dictation": {"mode": "raw"},
               "dictation.profiles.chromium": {
                   "mode": "compose", "style": "professional email"}}
        self.go("tell sam the deploy went fine", cfg, cls="chromium",
                chat="Dear Sam,")
        sys_p = self.chat.call_args[0][0][0]["content"]
        self.assertIn("composer", sys_p)
        self.assertIn("professional email", sys_p)

    def test_profile_pattern_matches_suffix_classes(self):
        cfg = {"dictation.profiles.chromium": {"style": "chat tone"}}
        prof = dictate.profile_for("chromium-beta", cfg)
        self.assertEqual(prof.get("style"), "chat tone")

    def test_unknown_app_uses_global_defaults(self):
        cfg = {"dictation": {"mode": "raw"},
               "dictation.profiles.chromium": {"mode": "compose"}}
        out = self.go("plain text", cfg, cls="nautilus")
        self.chat.assert_not_called()
        self.assertEqual(self.inserted, ["plain text"])
        self.assertTrue(out.startswith("INSERTED"), out)

    # -- terminal guard ---------------------------------------------------

    def test_terminal_collapses_newlines_for_every_mode(self):
        cfg = {"dictation": {"mode": "cleanup"}}
        out = self.go("line one line two line three", cfg, cls="foot",
                      chat="line one\nline two\nline three")
        self.assertEqual(self.inserted, ["line one line two line three"])
        self.assertNotIn("\n", out)

    def test_terminal_list_extends_via_config(self):
        cfg = {"dictation": {"mode": "raw",
                             "terminal_classes": "coolretro"}}
        self.go("a\nb", cfg, cls="coolretro")
        self.assertEqual(self.inserted, ["a b"])

    def test_non_terminal_keeps_newlines(self):
        self.go("line one line two", {"dictation": {"mode": "cleanup"}},
                cls="chromium", chat="line one\nline two")
        self.assertEqual(self.inserted, ["line one\nline two"])

    def test_auto_send_asks_then_presses_enter(self):
        cfg = {"dictation": {"mode": "compose"},
               "dictation.profiles.foot": {"auto_send": "true"}}
        calls = []

        def confirm(prompt):
            calls.append(prompt)
            return True
        out = self.go("update the readme", cfg, cls="foot",
                      confirm=confirm, chat="first line\nsecond")
        self.assertEqual(len(calls), 1)
        self.assertIn("foot", calls[0])
        self.assertEqual(self.inserted, ["first line\nsecond"])  # armed
        self.assertIn(("key", "enter"), self.keys)
        self.assertTrue(out.startswith("INSERTED +sent:"), out)

    def test_auto_send_denied_keeps_draft_and_guard(self):
        cfg = {"dictation": {"mode": "compose"},
               "dictation.profiles.foot": {"auto_send": "true"}}
        out = self.go("update the readme", cfg, cls="foot",
                      confirm=lambda _p: False, chat="one\ntwo")
        self.assertEqual(self.inserted, ["one two"])   # guard back on
        self.assertEqual(self.keys, [])

    def test_no_confirm_channel_means_draft_only(self):
        cfg = {"dictation": {"mode": "compose"},
               "dictation.profiles.foot": {"auto_send": "true"}}
        self.go("update the readme", cfg, cls="foot", confirm=None,
                chat="one\ntwo")
        self.assertEqual(self.inserted, ["one two"])
        self.assertEqual(self.keys, [])

    # -- corrections ------------------------------------------------------

    def test_correction_record_apply_persist(self):
        res = dictate.add_correction("wisp dot ai", "wisp.ai",
                                     path=self.f)
        self.assertTrue(res.startswith("CORRECTED"), res)
        data = json.loads(self.f.read_text())
        self.assertEqual(data["corrections"]["wisp dot ai"], "wisp.ai")
        # post-LLM swap, case-insensitive exact phrase
        self.go("go to wisp dot ai today",
                {"dictation": {"mode": "cleanup"}},
                cls="chromium", chat="go to Wisp dot ai today")
        self.assertEqual(self.inserted, ["go to wisp.ai today"])

    def test_corrections_ride_the_prompt(self):
        dictate.add_correction("wisp dot ai", "wisp.ai", path=self.f)
        self.go("x", {"dictation": {"mode": "cleanup"}}, cls="chromium",
                chat="ok")
        sys_p = self.chat.call_args[0][0][0]["content"]
        self.assertIn("wisp dot ai -> wisp.ai", sys_p)

    def test_correction_args_required(self):
        res = dictate.add_correction("", "x", path=self.f)
        self.assertTrue(res.startswith("SKIP"), res)

    def test_voice_correct_path_records_without_inserting(self):
        out = self.go('/correct "wisp dot ai" "wisp.ai"',
                      {"dictation": {"mode": "raw"}}, cls="chromium")
        self.assertTrue(out.startswith("CORRECTED"), out)
        self.assertEqual(self.inserted, [])
        self.assertEqual(dictate.corrections(self.f)["wisp dot ai"],
                         "wisp.ai")

    def test_voice_correct_malformed_skips(self):
        out = self.go("/correct just words",
                      {"dictation": {"mode": "raw"}}, cls="chromium")
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertEqual(self.inserted, [])

    def test_profiles_seen_records_the_app(self):
        self.go("hi", {"dictation": {"mode": "raw"}}, cls="chromium")
        data = json.loads(self.f.read_text())
        self.assertEqual(data["profiles_seen"]["chromium"]["n"], 1)
        self.go("hi", {"dictation": {"mode": "raw"}}, cls="chromium")
        data = json.loads(self.f.read_text())
        self.assertEqual(data["profiles_seen"]["chromium"]["n"], 2)


class InsertChainTest(unittest.TestCase):
    """insert(): wordink -> type_text -> wl-copy + ctrl+v."""

    def setUp(self):
        self.td = tempfile.mkdtemp()

    def test_wordink_first_when_importable(self):
        fake = types.ModuleType("wordink")

        class Inserter:
            def insert_text(self, t):
                self.t = t
                return True
        fake.TextInserter = Inserter
        with mock.patch.dict("sys.modules", {"wordink": fake}):
            via, err = dictate.insert("hi", {})
        self.assertEqual(via, "wordink")
        self.assertEqual(err, "")

    def test_type_text_when_wordink_absent(self):
        with mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run",
                               return_value="TYPED") as r:
            via, _ = dictate.insert("hi", {"c": 1})
        self.assertEqual(via, "typed")
        r.assert_called_once_with("type_text", "hi", {"c": 1})

    def test_clipboard_paste_is_the_last_fallback(self):
        with mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run",
                               return_value="SKIP (no typer)") as r, \
             mock.patch.object(dictate, "_paste",
                               return_value=True) as p:
            via, _ = dictate.insert("hi", {})
        self.assertEqual(via, "paste")
        p.assert_called_once_with("hi", {}, None)

    def test_paste_chords_ctrl_v_and_restores_the_clip(self):
        runs = []

        class R:
            def __init__(self, out=b""):
                self.returncode, self.stdout = 0, out
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
             mock.patch.object(dictate._cancel, "run",
                               side_effect=lambda a, **k:
                               (runs.append(a), R(b"old clip"))[1]), \
             mock.patch.object(tools, "run", return_value="KEY") as kr, \
             mock.patch.object(dictate.time, "sleep"):
            self.assertTrue(dictate._paste("hello", {}))
        # the clip is captured BEFORE wl-copy overwrites it — reading
        # after the write would "restore" the dictated text itself
        self.assertEqual(runs[0], ["wl-paste", "--no-newline"])
        self.assertEqual(runs[1], ["wl-copy"])
        kr.assert_called_once_with("key", "ctrl+v", {})
        self.assertEqual(runs[-1], ["wl-copy"])      # clip restored

    def test_paste_fails_without_wl_copy(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(dictate._paste("hi", {}))

    def test_guard_refusal_stops_typed_and_paste(self):
        # the CUA kill switch gates dictation's keystrokes too — a
        # refused type never falls through to the paste path
        g = cua_safety.Guard({"cua": {"kill_switch": "true"}},
                             window=lambda: {"app": "chromium",
                                             "title": ""},
                             audit_path=pathlib.Path(self.td) / "c.jsonl",
                             kill_path=pathlib.Path(self.td) / "c.kill")
        with mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run") as r, \
             mock.patch.object(dictate, "_paste") as p:
            via, err = dictate.insert("hi", {}, g)
        self.assertEqual(via, "")
        self.assertIn("REFUSED", err)
        r.assert_not_called()
        p.assert_not_called()

    def test_nothing_landed_reports_the_typer_reason(self):
        with mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run",
                               return_value="SKIP (no typer)"), \
             mock.patch.object(dictate, "_paste", return_value=False):
            via, err = dictate.insert("hi", {})
        self.assertEqual(via, "")
        self.assertEqual(err, "SKIP (no typer)")


class ChordTest(unittest.TestCase):
    """key() modifier chords: 'ctrl+v' through ydotool, never DOM."""

    def test_ctrl_v_sequence(self):
        calls = []

        class R:
            returncode = 0
        with mock.patch.object(_sys._cancel, "run",
                               side_effect=lambda a, **k:
                               (calls.append(a), R())[1]):
            self.assertEqual(_sys.key("ctrl+v", {}), "KEY")
        self.assertEqual(calls[0],
                         ["ydotool", "key",
                          "29:1", "47:1", "47:0", "29:0"])

    def test_unknown_chord_skips(self):
        self.assertTrue(_sys.key("ctrl+frobnicate", {})
                        .startswith("SKIP"))

    def test_chord_never_goes_dom(self):
        out = _sys.key("ctrl+v", {"screen": {"dom_page": "p1"}})
        self.assertTrue(out.startswith("SKIP"), out)


if __name__ == "__main__":
    unittest.main()
