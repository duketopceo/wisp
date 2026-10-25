"""Gap-closure U2: paper rendering — text form, CLI, plan strip lifecycle."""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from wisp import note, state as state_mod
from wisp.cli import note as note_cli
from wisp.cli.registry import Flags


class _Ctx:
    def __init__(self, *, json=False, quiet=False, send=None):
        self.json = json
        self.flags = Flags(json=json, quiet=quiet)
        self._send = send or (lambda msg: {"ok": False})

    def send(self, msg):
        return self._send(msg)

    def emit(self, data, text=None):
        return 0


class TestRenderText(unittest.TestCase):
    def test_tiles_and_plan_while_open(self):
        parsed = note.parse(
            "{now} Searching\n::tiles\n- A\n- B\n::\n:::letter\nDone.\n:::")
        text = note.render_text(parsed)
        self.assertIn("[now] Searching", text)
        self.assertIn("• A", text)
        self.assertIn("• B", text)
        self.assertIn("Done.", text)

    def test_plan_dropped_when_closed(self):
        parsed = note.parse("{now} Searching\n:::letter\nDone.\n:::")
        open_text = note.render_text(parsed, closed=False)
        closed_text = note.render_text(parsed, closed=True)
        self.assertIn("[now]", open_text)
        self.assertNotIn("[now]", closed_text)
        self.assertIn("Done.", closed_text)

    def test_letter_only_matches_spoken(self):
        body = "Thursday works for me."
        parsed = note.parse(f":::letter\n{body}\n:::")
        self.assertEqual(note.render_text(parsed), body)
        self.assertEqual(note.spoken_text(parsed), body)


class TestTurnLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_acting_shows_plan_done_clears_it(self):
        bus = state_mod.StateBus(
            state_mod.State(state_file=self.root / "state.json",
                            write_initial=False),
            autostart=False)
        turn = bus.current_turn()
        bus.publish(turn, status="acting")
        payload = note.publish_from_text(
            "{now} Clicking send\n::tiles\n- Send\n::\n:::letter\nok\n:::",
            bus=bus, turn_id=turn, conv_id=turn, root=self.root)
        self.assertIsNotNone(payload)
        live = bus.snapshot()["note"]
        self.assertFalse(live["closed"])
        self.assertEqual(live["plan"][0]["marker"], "now")
        self.assertIn("[now]", live["rendered"])
        self.assertIn("• Send", live["rendered"])

        closed = note.close_live(bus, turn_id=turn, root=self.root,
                                 state=bus)
        self.assertTrue(closed["closed"])
        self.assertEqual(bus.snapshot()["note"]["plan"], [])
        self.assertNotIn("[now]", bus.snapshot()["note"]["rendered"])


class TestCliNote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_show_rendered_and_raw(self):
        pad = note.NotePad("c1", root=self.root)
        pad.set("{now} X\n:::letter\nHello paper.\n:::")

        def send(msg):
            return {"ok": True, "state": {"note": None}}

        ctx = _Ctx(send=send)
        with mock.patch.object(note, "notes_dir", return_value=self.root), \
             mock.patch.object(note, "current_note",
                               return_value=note.current_note(
                                   conv_id="c1", root=self.root)):
            a = mock.Mock(conv="c1", raw=False, tail=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = note_cli.note_cmd(ctx, a)
            self.assertEqual(rc, 0)
            self.assertIn("Hello paper.", buf.getvalue())
            self.assertIn("[now]", buf.getvalue())

            a.raw = True
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = note_cli.note_cmd(ctx, a)
            self.assertEqual(rc, 0)
            self.assertIn(":::letter", buf.getvalue())
            self.assertIn("{now}", buf.getvalue())

    def test_show_from_daemon_state(self):
        payload = {
            "conv_id": "current",
            "path": "/tmp/x.md",
            "raw": ":::letter\nHi\n:::",
            "objects": [{"kind": "letter", "body": "Hi", "attrs": {}}],
            "plan": [],
            "closed": True,
            "rendered": "Hi",
        }
        ctx = _Ctx(send=lambda msg: {"ok": True, "state": {"note": payload}})
        a = mock.Mock(conv="", raw=False, tail=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = note_cli.note_cmd(ctx, a)
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "Hi")


if __name__ == "__main__":
    unittest.main()
