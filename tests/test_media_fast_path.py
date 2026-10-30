"""U14 media lane: exact intent -> canonical detail -> real registry -> honest
talkback. Backend executables, model calls, speech and state I/O are faked."""
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import pipeline, route, stage_route, stage_speak, tools
from wisp.tools import media


class MediaFastPath(unittest.TestCase):
    def setUp(self):
        for target in ("wisp.act.run_act_loop", "subprocess.Popen",
                       "subprocess.run"):
            patch = mock.patch(target, side_effect=AssertionError(
                "model/system process forbidden"))
            patch.start()
            self.addCleanup(patch.stop)
        for target in ("wisp.trace.emit", "wisp.stage_speak._finish",
                       "wisp.stage_speak._publish_paper",
                       "wisp.stage_speak._close_paper"):
            patch = mock.patch(target)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(pipeline.speech, "speak", return_value=None)
        self.speech = patch.start()
        self.addCleanup(patch.stop)

    def context(self, text, fast_path="true"):
        return SimpleNamespace(
            text=text, cfg={"brain": {"router": "act", "fast_path": fast_path},
                            "voice": {"enabled": "false"}},
            detail=text, state=mock.Mock(), sp=mock.MagicMock(),
            turn="media-test", token=mock.Mock(), model="never-called",
            harness={"apps": {}}, context="", wait_for_choice=None,
            answers={}, result="", reply="", app="none")

    def route_context(self, ctx):
        # Fixed, unrelated lesson/settings/routine intents are out of scope.
        # Keep the actual route_stage -> fast_route -> media_fast_arg chain.
        with mock.patch.object(stage_route, "fixed_route",
                               return_value=("act", None)), \
             mock.patch.object(route, "decide",
                               side_effect=AssertionError("model forbidden")):
            self.assertTrue(pipeline.route_stage(ctx))

    def test_exact_controls_produce_canonical_registered_arguments(self):
        for text, action in (
                ("pause YouTube", "pause"), ("next track", "next"),
                ("volume down", "volume_down"), ("Please PAUSE Spotify!", "pause"),
                ("resume the music", "play"), ("unpause video", "play"),
                ("play the music", "play"), ("skip", "next"),
                ("previous track", "previous"), ("prev song", "previous"),
                ("mute the speakers", "mute"), ("unmute", "mute"),
                ("turn it up", "volume_up"), ("turn the volume down", "volume_down"),
                ("louder.", "volume_up"), ("quieter", "volume_down")):
            with self.subTest(text=text):
                ctx = self.context(text)
                self.route_context(ctx)
                self.assertEqual(ctx.route_lane, "fast_path")
                self.assertEqual(ctx.answers["route"]["choice"], "tool")
                self.assertEqual(ctx.answers["tool"]["choice"], "media")
                self.assertEqual(ctx.answers["action"]["choice"], "media")
                self.assertEqual(ctx.detail, action)
                self.assertIn(ctx.detail, media.ARGS)
                self.assertIs(tools.REGISTRY["media"][0], media.media)

    def test_modifiers_named_targets_and_negation_keep_normal_routing(self):
        for text in (
                "pause YouTube then open mail", "pause YouTube and open mail",
                "pause YouTube, then open mail", "pause YouTube in Firefox",
                "pause YouTube on the other screen", "pause in five minutes",
                "next track on Spotify", "volume down by 20 percent",
                "volume down to 10", "play Miles Davis", "play Kind of Blue",
                "play YouTube", "play Spotify", "don't pause YouTube",
                "do not mute", "do not unmute", "do not skip track",
                "do not resume", "do not turn the volume down",
                "can you lower the volume", "never turn it down", "not next track",
                "can you pause YouTube", "what happens if I pause YouTube",
                "pause YouTubee", "muted", "", "  "):
            with self.subTest(text=text):
                self.assertIsNone(stage_route.media_fast_arg(text))
                ctx = self.context(text)
                self.route_context(ctx)
                self.assertEqual(ctx.answers["route"]["choice"], "act")
                self.assertEqual(ctx.detail, text)
                self.assertFalse(hasattr(ctx, "route_lane"))

    def test_disabled_fast_path_keeps_act_route_with_original_detail(self):
        ctx = self.context("pause YouTube", fast_path="false")
        self.route_context(ctx)
        self.assertEqual(ctx.answers["route"]["choice"], "act")
        self.assertEqual(ctx.detail, "pause YouTube")
        self.assertFalse(hasattr(ctx, "route_lane"))

    def test_non_media_turn_question_keeps_existing_fast_answer(self):
        result = stage_route.fast_route("what is a turn in a game", {}, {})
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["route"]["choice"], "answer")

    def test_canonical_route_dispatches_through_registry_then_speaks(self):
        for text, argv, spoken in (
                ("pause YouTube", ["omarchy-shell", "media", "playPause"],
                 "Sent the play/pause toggle."),
                ("next track", ["omarchy-shell", "media", "next"], "Media next."),
                ("volume down", ["omarchy-audio-output-volume", "lower"],
                 "Media volume down."),
                ("unmute", ["omarchy-audio-output-volume", "mute-toggle"],
                 "Sent the mute toggle.")):
            with self.subTest(text=text):
                ctx = self.context(text)
                self.route_context(ctx)
                self.speech.reset_mock()
                with mock.patch.object(media, "_which",
                                       return_value="/fake/control"), \
                     mock.patch.object(media, "_run",
                                       return_value=(0, "")) as run:
                    ctx.result = pipeline.execute(
                        ctx.answers, ctx.cfg, ctx.harness, detail=ctx.detail)
                run.assert_called_once_with(argv)
                self.assertTrue(ctx.result.startswith("MEDIA "))
                stage_speak.speak_stage(ctx)
                self.assertEqual(ctx.reply, spoken)
                self.speech.assert_called_once_with(spoken, ctx.cfg)
                self.assertEqual(ctx.state.transition.call_args,
                                 mock.call("done", result=ctx.result, answer=spoken))

    def test_failed_or_absent_backend_preserves_skip_explanation(self):
        for have, rc, reason in ((True, 1, "fake backend failure"),
                                  (False, 0, "not found")):
            with self.subTest(have=have, rc=rc):
                ctx = self.context("next track")
                self.route_context(ctx)
                self.speech.reset_mock()
                with mock.patch.object(
                        media, "_which", return_value="/fake/control" if have
                        else None), mock.patch.object(
                            media, "_run", return_value=(rc, "fake backend failure")) as run:
                    ctx.result = pipeline.execute(
                        ctx.answers, ctx.cfg, ctx.harness, detail=ctx.detail)
                self.assertTrue(ctx.result.startswith("SKIP "), ctx.result)
                self.assertIn(reason, ctx.result)
                self.assertEqual(stage_speak._spoken_payload(ctx.result), "")
                stage_speak.speak_stage(ctx)
                self.speech.assert_not_called()
                ctx.state.transition.assert_called_once_with(
                    "done", result=ctx.result)
                if not have:
                    run.assert_not_called()

    def test_playerctl_pause_is_not_described_as_a_toggle(self):
        with mock.patch.object(media, "_which", side_effect=lambda name:
                               "/fake/playerctl" if name == "playerctl" else None), \
             mock.patch.object(media, "_run", return_value=(0, "")) as run:
            result = media.media("pause")
        run.assert_called_once_with(["playerctl", "pause"])
        self.assertEqual(result, "MEDIA pause via playerctl")
        self.assertNotIn("toggle", stage_speak._spoken_payload(result).lower())

    def test_omarchy_playback_talkback_preserves_toggle_semantics(self):
        for action in ("play", "pause", "play_pause"):
            with self.subTest(action=action), \
                 mock.patch.object(media, "_which",
                                   return_value="/fake/control"), \
                 mock.patch.object(media, "_run", return_value=(0, "")):
                result = media.media(action)
                payload = stage_speak._spoken_payload(result).lower()
                self.assertIn("toggle", payload)
                self.assertNotIn("paused", payload)
                self.assertNotIn("resumed", payload)

    def test_mute_toggle_talkback_does_not_claim_a_known_state(self):
        with mock.patch.object(media, "_which", return_value="/fake/control"), \
             mock.patch.object(media, "_run", return_value=(0, "")):
            result = media.media("unmute")
        payload = stage_speak._spoken_payload(result)
        self.assertIn("toggle", payload.lower())
        self.assertNotIn("unmuted", payload.lower())
        self.assertNotEqual(payload, "Media mute.")


if __name__ == "__main__":
    unittest.main()
