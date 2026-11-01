"""B8b voice polish: captions toggle, mic failover, a muted speaker keeps
the answer on the clipboard, and quiet on calls. Every probe is a fake: no
audio stack, window manager or clipboard is touched."""
import json
import pathlib
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import config, cua_safety, notify, platform, voice_polish  # noqa: E402
from wisp import stage_route, stage_execute, voice_settings  # noqa: E402
from wisp import settings_schema, pipeline, stage_speak  # noqa: E402

import test_notify  # noqa: E402
import test_stage_speak  # noqa: E402


def runner(table):
    """argv[0] -> (rc, out); anything else (1, "")."""
    calls = []

    def run(argv, timeout=1.5, data=None):
        calls.append((list(argv), data))
        return table.get(argv[0], (1, ""))
    run.calls = calls
    return run


class MutedSpeaker(unittest.TestCase):
    def test_wpctl_muted_flag_and_zero_volume(self):
        self.assertTrue(voice_polish.speaker_muted(
            runner({"wpctl": (0, "Volume: 0.40 [MUTED]\n")})))
        self.assertTrue(voice_polish.speaker_muted(
            runner({"wpctl": (0, "Volume: 0.00\n")})))
        self.assertFalse(voice_polish.speaker_muted(
            runner({"wpctl": (0, "Volume: 0.40\n")})))

    def test_pactl_when_wpctl_cannot_answer(self):
        self.assertTrue(voice_polish.speaker_muted(
            runner({"pactl": (0, "Mute: yes\n")})))
        self.assertFalse(voice_polish.speaker_muted(
            runner({"pactl": (0, "Mute: no\n")})))

    def test_an_unreadable_answer_is_not_muted(self):
        self.assertFalse(voice_polish.speaker_muted(runner({})))

    def test_clipboard_copy_sends_the_text(self):
        run = runner({"wl-copy": (0, "")})
        self.assertTrue(voice_polish.copy_to_clipboard("hi there", run))
        self.assertEqual(run.calls[0], (["wl-copy"], b"hi there"))
        self.assertFalse(voice_polish.copy_to_clipboard(
            "x", runner({"wl-copy": (1, "")})))
        self.assertFalse(voice_polish.copy_to_clipboard("", run))


class DeliveryPlan(unittest.TestCase):
    VOICE = {"voice": {"enabled": "true"}}

    def test_voice_off_probes_nothing_and_shows_the_answer(self):
        run = mock.Mock()
        d = voice_polish.begin({"voice": {"enabled": "false"}}, run)
        run.assert_not_called()
        self.assertEqual(d.shown("hello"), "hello")

    def test_captions_default_on(self):
        d = voice_polish.begin(self.VOICE, runner({}))
        self.assertEqual(d.shown("hello"), "hello")

    def test_captions_off_hides_the_spoken_text(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"}}
        with mock.patch.object(voice_polish, "voice_usable",
                               return_value=True):
            d = voice_polish.begin(cfg, runner({}))
        self.assertEqual(d.shown("hello"), "")
        self.assertEqual(d.cfg["voice"]["enabled"], "true")

    def test_captions_stay_on_when_there_is_no_voice_to_speak_with(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"}}
        with mock.patch.object(voice_polish, "voice_usable",
                               return_value=False):
            d = voice_polish.begin(cfg, runner({}))
        self.assertEqual(d.shown("hello"), "hello")

    def test_voice_usable_checks_the_tts_program(self):
        # Groq is a separate path; a host with a Groq key and a player
        # would make every "nothing can speak" case True.
        from wisp import speech, tts_groq
        with mock.patch.object(tts_groq, "available", lambda cfg: False), \
                mock.patch.object(speech.shutil, "which",
                                  lambda n: "/bin/x" if n == "mytts"
                                  else None):
            self.assertTrue(voice_polish.voice_usable(
                {"voice": {"cmd": "mytts --fast {text}"}}))
            self.assertFalse(voice_polish.voice_usable(
                {"voice": {"cmd": "nothere {text}"}}))
            with mock.patch.object(platform, "tts_binary", lambda: None):
                self.assertFalse(voice_polish.voice_usable({"voice": {}}))
            with mock.patch.object(platform, "tts_binary", lambda: "espeak"):
                self.assertTrue(voice_polish.voice_usable({"voice": {}}))
        with mock.patch.object(tts_groq, "available", lambda cfg: True):
            self.assertTrue(voice_polish.voice_usable({"voice": {}}))

    def test_revealed_shows_the_text_when_nothing_was_spoken(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"}}
        with mock.patch.object(voice_polish, "voice_usable",
                               return_value=True):
            d = voice_polish.begin(cfg, runner({}))
        self.assertEqual(d.shown("hi"), "")
        self.assertEqual(d.revealed("hi"), "hi")

    def test_muted_speaker_stops_speech_and_shows_text_with_hint(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"}}
        run = runner({"wpctl": (0, "Volume: 0.5 [MUTED]"),
                      "wl-copy": (0, "")})
        d = voice_polish.begin(cfg, run)
        self.assertTrue(d.muted)
        self.assertEqual(d.cfg["voice"]["enabled"], "false")
        self.assertEqual(cfg["voice"]["enabled"], "true")   # not mutated
        d.finish("the answer", run)
        self.assertEqual(run.calls[-1], (["wl-copy"], b"the answer"))
        out = d.shown("the answer")      # captions off, still shown
        self.assertTrue(out.startswith("the answer"))
        self.assertIn(voice_polish.HINT_MUTED, out)

    def test_muted_without_a_clipboard_tool_says_so(self):
        d = voice_polish.begin(self.VOICE,
                               runner({"wpctl": (0, "Volume: 0 [MUTED]")}))
        d.finish("the answer", runner({}))
        self.assertIn(voice_polish.HINT_MUTED_NOCOPY, d.shown("the answer"))


class MutedTurn(test_stage_speak.StageBase):
    """Through stage_speak._answer: what lands in state.json."""

    def test_muted_turn_shows_hint_copies_and_does_not_speak(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"},
               "agent": {}}
        with mock.patch.object(voice_polish, "speaker_muted",
                               return_value=True), \
             mock.patch.object(voice_polish, "copy_to_clipboard",
                               return_value=True) as cp:
            ctx = self.run_answer(cfg, "Open Settings.")
        cp.assert_called_once_with("Open Settings.", None)
        self.assertEqual(ctx.reply, "Open Settings.")   # history is clean
        ans = self.bus.state.answer
        self.assertIn("Open Settings.", ans)
        self.assertIn(voice_polish.HINT_MUTED, ans)
        self.assertEqual(self.bus.state.status, "done")

    def test_captions_off_keeps_the_bubble_empty_while_speaking(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"},
               "agent": {}}
        speaker = mock.patch("wisp.speech.SentenceSpeaker",
                             test_stage_speak.FakeSpeaker)
        with mock.patch.object(voice_polish, "speaker_muted",
                               return_value=False), \
             mock.patch.object(voice_polish, "voice_usable",
                               return_value=True), speaker:
            self.run_answer(cfg, "Open Settings.", ["Open ", "Open Settings."])
        self.assertEqual(self.bus.state.answer, "")

    def test_clipboard_gets_the_text_without_point_tags(self):
        cfg = {"voice": {"enabled": "true"}, "agent": {}}
        with mock.patch.object(voice_polish, "speaker_muted",
                               return_value=True), \
             mock.patch.object(voice_polish, "copy_to_clipboard",
                               return_value=True) as cp:
            self.run_answer(cfg, test_stage_speak.REPLY)
        copied = cp.call_args[0][0]
        self.assertNotIn("[POINT", copied)
        self.assertIn("Open Settings", copied)

    def test_captions_off_still_shows_the_text_when_speech_never_starts(self):
        cfg = {"voice": {"enabled": "true", "captions": "false"}}
        ctx = self.ctx(cfg)
        with mock.patch.object(voice_polish, "speaker_muted",
                               return_value=False), \
             mock.patch.object(voice_polish, "voice_usable",
                               return_value=True), \
             mock.patch.object(pipeline.speech, "speak", return_value=None):
            stage_speak._speak_result(ctx, "All done.")
        self.assertEqual(self.bus.state.answer, "All done.")
        self.assertEqual(self.bus.state.status, "done")


class MicFailover(unittest.TestCase):
    class Proc:
        def __init__(self, dead):
            self.dead = dead

        def poll(self):
            return 1 if self.dead else None

    def spawn_with(self, first_dead):
        spawned = []

        def spawn(argv):
            spawned.append(argv)
            return self.Proc(first_dead and len(spawned) == 1)
        return spawned, spawn

    def cmd(self, d):
        return ["rec", "--target", d] if d else ["rec"]

    def test_default_device_is_one_spawn_and_no_wait(self):
        spawned, spawn = self.spawn_with(True)
        sleeps = []
        proc, over = voice_polish.spawn_recorder(
            self.cmd, spawn, device="", sleep=sleeps.append)
        self.assertEqual((len(spawned), over, sleeps), (1, False, []))

    def test_a_live_named_mic_is_kept(self):
        spawned, spawn = self.spawn_with(False)
        _, over = voice_polish.spawn_recorder(
            self.cmd, spawn, device="usb", sleep=lambda s: None)
        self.assertEqual((spawned, over), ([["rec", "--target", "usb"]],
                                           False))

    def test_a_dead_named_mic_falls_over_to_the_default_once(self):
        spawned, spawn = self.spawn_with(True)
        _, over = voice_polish.spawn_recorder(
            self.cmd, spawn, device="usb", sleep=lambda s: None)
        self.assertTrue(over)
        self.assertEqual(spawned, [["rec", "--target", "usb"], ["rec"]])

    def test_the_dead_attempt_is_cleared_before_the_retry(self):
        spawned, spawn = self.spawn_with(True)
        order = []
        voice_polish.spawn_recorder(
            self.cmd, lambda a: (order.append("spawn"), spawn(a))[1],
            device="usb", sleep=lambda s: None,
            before_retry=lambda: order.append("clear"))
        self.assertEqual(order, ["spawn", "clear", "spawn"])
        order.clear()
        s2, sp2 = self.spawn_with(False)
        voice_polish.spawn_recorder(
            self.cmd, sp2, device="usb", sleep=lambda s: None,
            before_retry=lambda: order.append("clear"))
        self.assertEqual(order, [])

    def test_a_named_mic_never_falls_back_inside_pipewire(self):
        with mock.patch.object(platform, "_which",
                               lambda n: n == "pw-record"):
            cmd = platform.record_cmd(pathlib.Path("/tmp/a.wav"), None, "usb")
            self.assertIn("node.dont-fallback=true", " ".join(cmd))

    def test_the_failover_toast_is_not_held_on_a_call(self):
        from wisp import stage_capture
        with mock.patch.object(pipeline, "notify") as n:
            stage_capture._note_mic_failover(None, "usb")
        self.assertEqual(n.call_args.kwargs["hold"], False)

    def test_record_cmd_targets_the_device(self):
        with mock.patch.object(platform, "_which",
                               lambda n: n == "pw-record"):
            cmd = platform.record_cmd(pathlib.Path("/tmp/a.wav"), None, "usb")
            self.assertEqual(cmd[cmd.index("--target") + 1], "usb")
            self.assertNotIn("--target", platform.record_cmd(
                pathlib.Path("/tmp/a.wav"), None))

    def test_device_setting_is_read_from_audio(self):
        self.assertEqual(voice_polish.mic_device({"audio": {"device": " usb "}}),
                         "usb")
        self.assertEqual(voice_polish.mic_device({}), "")


CLIENTS = [{"class": "firefox", "title": "Meet - abc-defg-hij — Firefox"},
           {"class": "kitty", "title": "zsh"}]


class QuietOnCalls(unittest.TestCase):
    def hc(self, clients):
        return runner({"hyprctl": (0, json.dumps(clients))})

    def test_call_and_share_windows_are_found(self):
        st = voice_polish.call_state(self.hc(CLIENTS))
        self.assertEqual(st, {"in_call": True, "screen_sharing": False})
        st = voice_polish.call_state(self.hc(
            [{"class": "zoom", "title": "Zoom Meeting"},
             {"class": "x", "title": "You are sharing your screen"}]))
        self.assertEqual(st, {"in_call": True, "screen_sharing": True})
        self.assertEqual(voice_polish.call_state(self.hc(
            [{"class": "kitty", "title": "meeting notes"}])),
            {"in_call": False, "screen_sharing": False})

    def test_hyprctl_failure_means_no_call(self):
        self.assertEqual(voice_polish.call_state(runner({})),
                         {"in_call": False, "screen_sharing": False})
        self.assertEqual(voice_polish.call_state(
            runner({"hyprctl": (0, "not json")}))["in_call"], False)

    def test_hold_reason_uses_the_suggestion_gate(self):
        self.assertEqual(voice_polish.hold_reason({}, self.hc(CLIENTS)),
                         "in_call")
        self.assertEqual(voice_polish.hold_reason(
            {}, self.hc([{"class": "k", "title": "stop sharing"}])),
            "screen_sharing")
        self.assertEqual(voice_polish.hold_reason({}, self.hc([])), "")

    def test_setting_off_never_holds(self):
        cfg = {"quiet": {"on_calls": "false"}}
        self.assertEqual(voice_polish.hold_reason(cfg, self.hc(CLIENTS)), "")

    def test_hold_cache_probes_once_per_ttl(self):
        t = [0.0]
        run = self.hc(CLIENTS)
        c = voice_polish.HoldCache(ttl=5, clock=lambda: t[0])
        for _ in range(3):
            c.get({}, run)
        self.assertEqual(len(run.calls), 1)
        t[0] = 6
        c.get({}, run)
        self.assertEqual(len(run.calls), 2)


class HeldToasts(unittest.TestCase):
    def mk(self, state):
        return test_notify.mk(hold=lambda cfg: state["why"])

    def test_announcement_waits_for_the_call_to_end(self):
        state = {"why": "in_call"}
        n, bus, _ = self.mk(state)
        self.assertEqual(n.send("agent done", "success"), "held")
        self.assertEqual(bus.notifies(), [])
        state["why"] = ""
        self.assertEqual(n.flush_held(), 1)
        self.assertEqual(len(bus.notifies()), 1)
        self.assertEqual(n.flush_held(), 0)

    def test_still_in_a_call_keeps_it_held(self):
        n, bus, _ = self.mk({"why": "screen_sharing"})
        n.send("agent done", "success")
        self.assertEqual(n.flush_held(), 0)
        self.assertEqual(bus.notifies(), [])

    def test_a_later_toast_after_the_call_delivers_the_held_one_first(self):
        state = {"why": "in_call"}
        n, bus, _ = self.mk(state)
        n.send("agent done", "success")
        state["why"] = ""
        self.assertEqual(n.send("next", "info"), "sent")
        self.assertEqual(len(bus.notifies()), 2)

    def test_errors_and_turn_toasts_are_never_held(self):
        n, bus, _ = self.mk({"why": "in_call"})
        self.assertEqual(n.send("boom", "error"), "sent")
        self.assertEqual(n.send("turn done", "success", turn="t1"), "sent")
        self.assertEqual(len(bus.notifies()), 2)

    def test_a_repeat_is_held_once_and_cannot_crowd_out_a_new_one(self):
        n, bus, _ = self.mk({"why": "in_call"})
        for _ in range(notify.HELD_MAX + 5):
            n.send("same", "info")
        n.send("different", "info")
        self.assertEqual(sorted(h[0] for h in n._held), ["different", "same"])

    def test_the_hold_cache_follows_the_setting(self):
        t = [0.0]
        run = runner({"hyprctl": (0, json.dumps(CLIENTS))})
        c = voice_polish.HoldCache(ttl=60, clock=lambda: t[0])
        self.assertEqual(c.get({}, run), "in_call")
        off = {"quiet": {"on_calls": "false"}}
        self.assertEqual(c.get(off, run), "")          # no waiting for ttl
        self.assertEqual(c.get({}, run), "in_call")

    def test_the_held_list_is_bounded(self):
        n, _bus, _ = self.mk({"why": "in_call"})
        for i in range(notify.HELD_MAX + 5):
            n.send(f"m{i}", "info")
        self.assertEqual(len(n._held), notify.HELD_MAX)


class CaptionsByVoice(unittest.TestCase):
    def test_intents(self):
        for said, kind in (("turn off captions", "off"),
                           ("hide the captions", "off"),
                           ("no captions", "off"),
                           ("turn the captions on", "on"),
                           ("show captions", "on"),
                           ("hey wisp, captions on please", "on")):
            self.assertEqual(voice_settings.captions_intent(said), kind, said)
        for said in ("what are captions", "add captions to this video",
                     "open the captions file", ""):
            self.assertIsNone(voice_settings.captions_intent(said), said)

    def test_routes_before_any_model(self):
        self.assertEqual(stage_route.fixed_route("turn off captions", "act"),
                         ("setting", "voice-captions:off"))

    def test_apply_goes_through_set_config_and_the_audit_log(self):
        saved, events = [], []
        with mock.patch.object(config, "set_config",
                               lambda s, k, v: saved.append((s, k, v))), \
             mock.patch.object(cua_safety, "audit_event",
                               lambda *a, **k: events.append((a, k))):
            c = {"voice": {"enabled": "true"}}
            out = voice_settings.apply_captions("off", c, turn="t9")
        self.assertEqual(saved, [("voice", "captions", "false")])
        self.assertEqual(c["voice"]["captions"], "false")
        self.assertEqual(events[0][1]["setting"], "voice.captions")
        self.assertTrue(out.startswith("ACTED"))

    def test_execute_runs_it(self):
        c = {"voice": {"enabled": "true"}}
        with mock.patch.object(config, "set_config"), \
             mock.patch.object(cua_safety, "audit_event"):
            out = stage_execute.execute(
                {"route": {"choice": "setting"}}, c,
                detail="voice-captions:off", initial_image=None,
                interrupted=lambda: False)
        self.assertEqual(out, "ACTED (0 steps): okay, hiding captions "
                              "while I talk.")

    def test_schema_knows_the_new_keys(self):
        for key in ("voice.captions", "quiet.on_calls"):
            self.assertEqual(settings_schema.problem(key, "true"), "", key)
            self.assertNotEqual(settings_schema.problem(key, "maybe"), "", key)


if __name__ == "__main__":
    unittest.main()
