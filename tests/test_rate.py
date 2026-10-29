#!/usr/bin/env python3
"""U2: one-tap rating. shell-plugin/lib/rate.js (pure, run under node) plus
the static wiring of the answer-card buttons, the Now-tab note, the
service members and the bind. Daemon-side rate_prompt tests live in
test_wispd.py / test_contract.py; the install bind in test_clean_box.py."""
import pathlib
import re
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
COMP = PLUGIN / "components"
UI = {"ui.rate.good": "rated good", "ui.rate.wrong": "rated wrong",
      "ui.rate.not_found": "nothing to rate",
      "ui.rate.not_ratable": "that turn did not finish"}


def js(expr):
    return jsnode.call(expr, R="rate")


def ack(**kw):
    base = {"verb": "label", "pending": False, "ok": True, "message": "ok",
            "status": "ok", "turn": "t1", "verdict": "correct", "at": 1}
    base.update(kw)
    return base


def receipt(last, turn="t1", verdict="correct"):
    return js("R.receipt(%s, %r, %r, function(k){return %r[k]||k})"
              % (jsnode.json.dumps(last), turn, verdict, UI))


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestRateLib(unittest.TestCase):
    def test_rateable_only_for_a_finished_answer(self):
        f = "R.rateable(%r, %r, %r, %r)"
        self.assertTrue(js(f % ("done", "hi", "ANSWERED x", "")))
        self.assertFalse(js(f % ("done", "", "ANSWERED x", "")))
        self.assertFalse(js(f % ("speaking", "hi", "", "")))
        self.assertFalse(js(f % ("error", "hi", "ERROR (x)", "internal")))
        self.assertFalse(js(f % ("done", "hi", "CANCELLED (user)", "")))
        self.assertFalse(js(f % ("done", "hi", "ERROR (boom)", "")))
        self.assertFalse(js(f % ("done", "hi", "ANSWERED x", "cancelled")))

    def test_label_command_names_the_turn_and_guards_the_note(self):
        cmd = js('R.labelCommand("wispd", "incorrect", "b2", "wrong app")')
        self.assertEqual(cmd, ["wispd", "label", "set", "--json", "--turn",
                               "b2", "--", "incorrect", "wrong app"])
        cmd = js('R.labelCommand("wispd", "correct", "", "")')
        self.assertEqual(cmd, ["wispd", "label", "set", "--json", "--",
                               "correct"])
        self.assertEqual(
            js('R.skipCommand("wispd")'),
            ["wispd", "label", "set", "--json", "--", "skip"])

    def test_receipt_for_this_cards_turn(self):
        r = receipt(ack())
        self.assertEqual((r["kind"], r["text"]), ("receipt", "rated good"))
        r = receipt(ack(verdict="incorrect"), verdict="incorrect")
        self.assertEqual(r["text"], "rated wrong")

    def test_pending_shows_the_receipt_at_once(self):
        r = receipt(ack(pending=True, ok=False, status=""))
        self.assertEqual(r["kind"], "receipt")

    def test_another_turns_or_verbs_ack_is_not_this_cards(self):
        self.assertEqual(receipt(ack(turn="t0"))["kind"], "none")
        self.assertEqual(receipt(ack(verb="choice"))["kind"], "none")
        self.assertEqual(receipt(None)["kind"], "none")

    def test_unratable_replies_are_a_muted_line_not_a_receipt(self):
        for st, text in (("not_found", "nothing to rate"),
                         ("not_ratable", "that turn did not finish")):
            r = receipt(ack(ok=False, status=st))
            self.assertEqual((r["kind"], r["text"]), ("muted", text))

    def test_other_failure_is_muted_with_its_message(self):
        r = receipt(ack(ok=False, status="", message="wisp is busy"))
        self.assertEqual((r["kind"], r["text"]), ("muted", "wisp is busy"))


class TestWiring(unittest.TestCase):
    def read(self, *p):
        return pathlib.Path(ROOT, *p).read_text()

    def test_answer_card_uses_rate_row_and_not_the_old_chips(self):
        src = self.read("shell-plugin/components/OverlayLayer.qml")
        self.assertIn("RateRow {", src)
        self.assertNotIn("ui.label.good", src)
        self.assertNotIn('verdict("correct")', src)

    def test_overlay_never_takes_keyboard_focus(self):
        src = self.read("shell-plugin/Companion.qml")
        self.assertIn("WlrKeyboardFocus.None", src)
        self.assertNotIn("WlrKeyboardFocus.OnDemand", src)
        self.assertNotIn("WlrKeyboardFocus.Exclusive", src)

    def test_rate_row_has_thumbs_and_accessible_names(self):
        src = self.read("shell-plugin/components/RateRow.qml")
        self.assertIn('"thumb-up"', src)
        self.assertIn('"thumb-down"', src)
        # both buttons are one inline Btn, named by its `word`
        self.assertIn("Accessible.name: word", src)
        self.assertEqual(src.count("Btn {"), 2)
        self.assertIn("Accessible.role: Accessible.Button", src)

    def test_rate_note_enter_saves_escape_skips(self):
        src = self.read("shell-plugin/components/RateNote.qml")
        self.assertRegex(src, r"Keys\.onReturnPressed")
        self.assertRegex(src, r"Keys\.onEscapePressed")
        self.assertIn("forceActiveFocus", src)

    def test_now_tab_shows_the_note_while_a_prompt_is_open(self):
        src = self.read("shell-plugin/components/NowTab.qml")
        self.assertIn("RateNote {", src)
        self.assertIn("service.ratePrompt", src)

    def test_service_members_on_real_and_fixture_service(self):
        for p in ("shell-plugin/WispService.qml",
                  "tests/qml/harness/FixtureService.qml"):
            src = self.read(p)
            self.assertRegex(src, r"property var ratePrompt", p)
            self.assertRegex(src, r"function label\(verdict, turn, note\)", p)
            self.assertRegex(src, r"function skipRatePrompt\(\)", p)

    def test_bar_and_panel_open_the_note_on_the_now_tab(self):
        bar = self.read("shell-plugin/BarWidget.qml")
        self.assertIn("onRatePromptChanged", bar)
        panel = self.read("shell-plugin/Panel.qml")
        self.assertIn("onRatePromptChanged", panel)
        self.assertIn("skipRatePrompt", panel)

    def test_state_contract_documents_rate_prompt(self):
        doc = self.read("docs/IPC_CONTRACT.md")
        self.assertRegex(doc, r'"rate_prompt":')

    def test_copy_keys_exist(self):
        copy = self.read("wisp/copy.py")
        for k in list(UI) + ["ui.rate.note"]:
            self.assertIn(f'"{k}"', copy)

    def test_thumb_sources_exist(self):
        for n in ("thumb-up", "thumb-down"):
            self.assertTrue((ROOT / "assets/icons/src" / f"{n}.svg").exists())


if __name__ == "__main__":
    unittest.main()
