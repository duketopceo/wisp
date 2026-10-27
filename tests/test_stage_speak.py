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


class FakeSpeaker:
    """Stands in for SentenceSpeaker: records what the stage hands it and
    lets a test fire `on_sentence` by hand."""
    enabled = True
    started = False

    def __init__(self, cfg, token=None, on_sentence=None):
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
            if set(kw) == {"points"}:
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
        self.run_answer(self.cfg, REPLY)
        # voice on: the first sentence's point is the most that can have
        # landed before the second sentence starts playing
        first = self.bus.state.points
        self.assertLessEqual(len(first), 1)
        self.wait_done()
        seen = [x for p in self.pubs for x in p[0]["points"]]
        self.assertIn(P2, seen)

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
        self.assertEqual(evs[0].args[3], {"points": [P1, P2]})


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


class GuardTests(StageBase):
    """Stage-side guards, driven through a fake speaker."""

    def setUp(self):
        super().setUp()
        self.cfg = {"voice": {"enabled": "true"}, "agent": {}}
        self.spk = None

        def make(cfg, token=None, on_sentence=None):
            self.spk = FakeSpeaker(cfg, token, on_sentence)
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
