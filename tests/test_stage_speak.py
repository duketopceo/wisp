"""Points timed to speech: stage_speak._answer grows `points` as each
sentence starts playing (voice on), and publishes them all at once when
voice is off."""
import pathlib
import stat
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import cancel, pipeline, points, speech, state, stage_speak  # noqa: E402

MON = [{"x": 0, "y": 0, "width": 2000, "height": 1200, "scale": 1}]
P1 = {"x": 10, "y": 20, "label": "Settings"}
P2 = {"x": 30, "y": 40, "label": "Display"}
REPLY = ("Open Settings [POINT:10,20:Settings]. "
         "Then click Display [POINT:30,40:Display].")
DRAW_REPLY = ("Look here [RING:100,200,30]. "
              "Then drag [ARROW:1,2,300,400] to Display [POINT:30,40:Display].")
RING1 = {"kind": "ring", "x": 100, "y": 200, "r": 30}
ARROW1 = {"kind": "arrow", "x1": 1, "y1": 2, "x2": 300, "y2": 400}


class FakeSpeaker:
    """Stands in for SentenceSpeaker: records what the stage hands it and
    lets a test fire `on_sentence` by hand."""
    enabled = True
    started = False

    def __init__(self, cfg, token=None, on_sentence=None, on_audio=None):
        self.on_sentence = on_sentence
        self.feeds = []
        self.finishes = []

    def feed(self, text, marks=()):
        self.feeds.append((text, list(marks)))

    def finish(self, full, on_done=None, marks=()):
        self.finishes.append((full, on_done, list(marks)))


class StageBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bus = state.StateBus(
            state.State(state_file=pathlib.Path(self.dir.name) / "s.json",
                        write_initial=False), autostart=False)
        self.addCleanup(self.bus.stop) if hasattr(self.bus, "stop") else None
        self.turn = self.bus.current_turn()
        self.ts = self.bus.turn(self.turn)
        self.token = cancel.CancelToken()
        self.pubs = []      # points-only publishes + spoken lines then
        self.spoken = lambda: []
        real = self.bus.publish

        def spy(turn_id, **kw):
            if set(kw) == {"points", "drawings"}:
                self.pubs.append((dict(kw), list(self.spoken())))
            return real(turn_id, **kw)
        self.bus.publish = spy
        self.mons = mock.Mock(return_value=MON)
        self.emit = mock.Mock()
        for p in (mock.patch.object(points, "monitors", self.mons),
                  mock.patch.object(points, "img_space_is_logical",
                                    return_value=True),
                  mock.patch("wisp.trace.emit", self.emit)):
            p.start()
            self.addCleanup(p.stop)

    def ctx(self, cfg):
        return SimpleNamespace(
            state=self.ts, cfg=cfg, sp=mock.MagicMock(), token=self.token,
            text="where", result="ANSWERED", turn=self.turn,
            session_text="", shot_b64="x", reply="", speaker=None)

    def run_answer(self, cfg, reply, chunks=None):
        def ask(text, cfg_, session_text="", image_b64=None,
                on_delta=None, meta=None):
            acc = ""
            for c in chunks or ():
                acc += c
                on_delta(acc)
            return reply
        ctx = self.ctx(cfg)
        with mock.patch.object(pipeline, "ask_chat", side_effect=ask), \
             mock.patch.object(pipeline.speech, "speak", return_value=None):
            stage_speak._answer(ctx)
        return ctx

    def shown(self):
        return list(self.bus.state.points)


class VoiceOnTimingTests(StageBase):
    def setUp(self):
        super().setUp()
        speech.stop()
        self.addCleanup(speech.stop)
        d = pathlib.Path(self.dir.name)
        self.log = d / "spoken.txt"
        script = d / "tts.sh"
        script.write_text(f'#!/bin/sh\necho "$1" >> {self.log}\nsleep 0.3\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.cfg = {"voice": {"enabled": "true", "cmd": str(script)},
                    "agent": {}}
        self.spoken = lambda: (self.log.read_text().splitlines()
                               if self.log.exists() else [])

    def wait_done(self):
        for _ in range(200):
            if self.bus.state.status == "done":
                return
            time.sleep(0.05)
        self.fail("turn never reached done")

    def test_streamed_points_fire_one_sentence_at_a_time(self):
        chunks = ["Open Settings [POINT:10,20:Sett", "ings]. Then click ",
                  "Display [POINT:30,40:Display]."]
        self.run_answer(self.cfg, REPLY, chunks)
        self.wait_done()
        lists = [p[0]["points"] for p in self.pubs]
        # grows monotonically, one point per fire, never a 2-point jump
        self.assertEqual([len(x) for x in lists], [1, 2])
        self.assertEqual(lists[-1], [P1, P2])
        # point 2 arrived only after sentence 1 was already speaking
        self.assertEqual(len(self.pubs[0][1]) <= 1, True)
        self.assertGreaterEqual(len(self.pubs[1][1]), 1)
        self.assertEqual(self.shown(), [])  # cleared when done

    def test_single_chunk_reply_still_paces_points(self):
        # voice on, whole reply in one go: still one publish per sentence,
        # and point 2 only after sentence 1 was already speaking
        self.run_answer(self.cfg, REPLY)
        self.wait_done()
        lists = [p[0]["points"] for p in self.pubs]
        self.assertEqual([len(x) for x in lists], [1, 2])
        self.assertEqual(lists[-1], [P1, P2])
        self.assertGreaterEqual(len(self.pubs[1][1]), 1)

    def test_drawings_grow_with_sentences(self):
        self.run_answer(self.cfg, DRAW_REPLY)
        self.wait_done()
        pubs = [p[0] for p in self.pubs]
        self.assertEqual([len(x["drawings"]) for x in pubs], [1, 2])
        shown = pubs[-1]["drawings"]
        # each mark carries the spoken time of its own sentence (the
        # pen's pace); the geometry is untouched
        self.assertEqual([{k: v for k, v in d.items() if k != "ms"}
                          for d in shown], [RING1, ARROW1])
        self.assertTrue(all(isinstance(d["ms"], int) and d["ms"] > 0
                            for d in shown))
        self.assertEqual([len(x["points"]) for x in pubs], [0, 1])
        self.assertGreaterEqual(len(self.pubs[1][1]), 1)
        self.assertEqual(self.bus.state.drawings, [])
        for line in self.spoken():
            self.assertNotIn("[", line)

    def test_monitors_looked_up_once_per_turn(self):
        self.run_answer(self.cfg, REPLY,
                        ["Open Settings [POINT:10,20:Settings]. ", REPLY])
        self.wait_done()
        self.assertEqual(self.mons.call_count, 1)

    def test_full_points_trace_once(self):
        self.run_answer(self.cfg, REPLY)
        self.wait_done()
        evs = [c for c in self.emit.call_args_list if c.args[1] == "points"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].args[3], {"points": [P1, P2], "drawings": []})


class VoiceOffTests(StageBase):
    def test_all_points_publish_at_once(self):
        cfg = {"voice": {"enabled": "false"}, "agent": {}}
        seen = []
        real = self.ts.transition
        with mock.patch.object(
                self.ts, "transition",
                side_effect=lambda s, **kw: (seen.append((s, kw)),
                                             real(s, **kw))):
            self.run_answer(cfg, REPLY, [REPLY[:30], REPLY])
        self.assertEqual(self.pubs, [])  # no points-only publishes
        speaking = [kw for s, kw in seen if s == "speaking"]
        self.assertEqual(speaking[-1]["points"], [P1, P2])
        self.assertNotIn("[POINT", speaking[-1]["answer"])

    def test_drawings_ride_the_speaking_transition_and_clear_at_done(self):
        cfg = {"voice": {"enabled": "false"}, "agent": {}}
        seen = []
        real = self.ts.transition
        with mock.patch.object(
                self.ts, "transition",
                side_effect=lambda s, **kw: (seen.append((s, kw)),
                                             real(s, **kw))):
            self.run_answer(cfg, DRAW_REPLY)
        speaking = [kw for s, kw in seen if s == "speaking"][-1]
        self.assertEqual(speaking["drawings"], [RING1, ARROW1])
        self.assertEqual(speaking["points"], [P2])
        self.assertNotIn("[", speaking["answer"])
        self.assertEqual(self.bus.state.drawings, [])
        self.assertEqual(self.bus.state.points, [])

    def test_tag_only_reply_still_reaches_done(self):
        cfg = {"voice": {"enabled": "false"}, "agent": {}}
        self.run_answer(cfg, "[RING:100,200,30]")
        self.assertEqual(self.bus.state.status, "done")
        self.assertEqual(self.bus.state.drawings, [])


class PaperAndActResultTests(StageBase):
    NOTE = ("::tiles\n- a [RING:1,2,3]\n- b [POINT:1,2:x]\n::\n"
            "see [ARROW:1,2,3,4] and [HL:1,2,3,4]")

    def test_paper_never_gets_tags(self):
        cfg = {"voice": {"enabled": "false"}, "agent": {}}
        with mock.patch.object(stage_speak, "_publish_paper") as pp:
            self.run_answer(cfg, self.NOTE)
        text = pp.call_args.args[1]
        for t in ("[RING", "[ARROW", "[HL", "[POINT"):
            self.assertNotIn(t, text)
        self.assertIn("::tiles", text)

    def test_act_result_speaks_clean_and_draws_nothing(self):
        cfg = {"voice": {"enabled": "false"}, "agent": {}}
        ctx = self.ctx(cfg)
        ctx.result = "ACTED: ok"
        spoken = []
        with mock.patch.object(stage_speak, "_publish_paper") as pp, \
             mock.patch.object(speech, "speak",
                               side_effect=lambda t, c: spoken.append(t)):
            stage_speak._speak_result(
                ctx, "Done [RING:1,2,3] and [ARROW:1,2,3,4] ok")
        self.assertEqual(spoken, ["Done  and  ok"])
        self.assertEqual(self.bus.state.drawings, [])
        for t in ("[RING", "[ARROW"):
            self.assertNotIn(t, pp.call_args.args[1])

    def test_direct_tool_results_have_spoken_payload(self):
        self.assertEqual(
            stage_speak._spoken_payload(
                "SWITCHED tab 'Inbox — Personal' -> mail.google.com"),
            "Switched to Inbox — Personal.")
        self.assertEqual(
            stage_speak._spoken_payload(
                "OPENED https://dashboard.stripe.com -> xdg-open"),
            "Opened dashboard.stripe.com.")
        self.assertEqual(
            stage_speak._spoken_payload("LAUNCHED Discord -> gtk-launch"),
            "Opened Discord.")
        self.assertEqual(
            stage_speak._spoken_payload("FOCUSED firefox -> address:0x1"),
            "Focused firefox.")
        self.assertEqual(
            stage_speak._spoken_payload("WORKSPACE 3 -> ok"),
            "Switched to workspace 3.")


class GuardTests(StageBase):
    """Stage-side guards, driven through a fake speaker."""

    def setUp(self):
        super().setUp()
        self.cfg = {"voice": {"enabled": "true"}, "agent": {}}
        self.spk = None

        def make(cfg, token=None, on_sentence=None, on_audio=None):
            self.spk = FakeSpeaker(cfg, token, on_sentence, on_audio)
            return self.spk
        p = mock.patch.object(speech, "SentenceSpeaker", make)
        p.start()
        self.addCleanup(p.stop)

    def test_voice_on_routes_through_finish_with_marks(self):
        ctx = self.run_answer(self.cfg, REPLY)
        (full, on_done, marks), = self.spk.finishes
        self.assertEqual(full, "Open Settings . Then click Display .")
        self.assertEqual([p for _, p in marks], [P1, P2])
        self.assertTrue(callable(on_done))
        self.assertEqual(ctx.reply, full)

    def test_stream_feeds_clean_text_and_hides_partial_tags(self):
        chunks = ["Open Settings [POINT:10,20:Settings]. Then [POI",
                  "NTS:[{\"x\":1,\"y\":2}"]
        pubs = []
        real = self.ts._bus.publish
        self.bus.publish = lambda t, **kw: (pubs.append(kw), real(t, **kw))[1]
        self.run_answer(self.cfg, REPLY, chunks)
        for text, _ in self.spk.feeds:
            self.assertNotIn("[", text)
        for kw in pubs:
            self.assertNotIn("[POINT", kw.get("answer", ""))
        self.assertEqual([p for _, p in self.spk.feeds[0][1]], [P1])

    def fire(self, pts):
        self.spk.on_sentence(pts)

    def armed(self):
        self.run_answer(self.cfg, REPLY)
        self.pubs.clear()

    def test_fire_publishes_points_only_in_order(self):
        self.armed()
        self.fire([P1])
        self.fire([P2])
        self.assertEqual([p[0]["points"] for p in self.pubs],
                         [[P1], [P1, P2]])
        self.assertEqual(self.shown(), [P1, P2])

    def test_fire_publishes_point_and_drawing_in_one_publish(self):
        self.armed()
        self.fire([ARROW1, P2])
        (kw, _), = self.pubs
        self.assertEqual(kw["drawings"], [ARROW1])
        self.assertEqual(kw["points"], [P2])

    def test_trailing_tag_fires_with_tail(self):
        self.armed()
        self.fire([RING1])
        self.assertEqual(self.shown(), [])
        self.assertEqual(list(self.bus.state.drawings), [RING1])

    def test_drawing_mapping_scale_2_on_screen_edge(self):
        mons = [{"x": 0, "y": 0, "width": 2000, "height": 1200, "scale": 2}]
        self.mons.return_value = mons
        with mock.patch.object(points, "img_space_is_logical",
                               return_value=False):
            self.armed()
            self.fire([{"kind": "hl", "x": 1000, "y": 600,
                        "w": 1000, "h": 600}, RING1])
        d = self.bus.state.drawings
        self.assertEqual(d[0], {"kind": "hl", "x": 500, "y": 300,
                                "w": 500, "h": 300})
        self.assertEqual(d[1], {"kind": "ring", "x": 50, "y": 100, "r": 15})

    def test_no_drawings_after_cancel_stale_or_done(self):
        self.armed()
        self.token.cancel()
        self.fire([RING1])
        self.assertEqual(self.pubs, [])

    def test_image_prompt_mentions_drawing_tags(self):
        from wisp import brain
        for img, want in (("abc", True), (None, False)):
            seen = []
            with mock.patch.object(brain, "supports_vision",
                                   return_value=True), \
                 mock.patch.object(
                     brain, "chat",
                     side_effect=lambda m, *a, **k: (
                         seen.append(m), {"content": "ok"})[1]):
                stage_speak.ask_chat("where", {}, "", image_b64=img)
            sysmsg = seen[0][0]["content"]
            for tag in ("RING", "ARROW", "HL"):
                self.assertEqual(tag in sysmsg, want, tag)

    def test_no_publish_after_cancel(self):
        self.armed()
        self.token.cancel()
        self.fire([P1])
        self.assertEqual(self.pubs, [])

    def test_no_publish_for_stale_turn(self):
        self.armed()
        self.bus.begin_turn()
        self.fire([P1])
        self.assertEqual(self.pubs, [])

    def test_no_publish_once_status_left_speaking(self):
        self.armed()
        self.ts.transition("done")
        self.fire([P1])
        self.assertEqual(self.pubs, [])
        self.assertEqual(self.shown(), [])

    def test_concurrent_fires_never_shrink_the_list(self):
        self.armed()
        ts = [threading.Thread(target=self.fire, args=([dict(P1, x=i)],))
              for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        sizes = [len(p[0]["points"]) for p in self.pubs]
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(sizes[-1], 20)


if __name__ == "__main__":
    unittest.main()
