"""Gap-closure U1: note.md file, `::` parser, note_changed bus events."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wisp import note, state as state_mod


SAMPLE = """\
{now} Checking calendar
{pick} Which calendar?
{needs} Google account

::tiles
- Inbox
- Sent
::

:::letter
Thursday works for me.
:::

::ticket[status=open]
Book the room
::

::ask
Shall I send it?
::
"""


class TestParse(unittest.TestCase):
    def test_tiles_letter_and_plan(self):
        parsed = note.parse(SAMPLE)
        markers = [p["marker"] for p in parsed["plan"]]
        self.assertEqual(markers, ["now", "pick", "needs"])
        self.assertEqual(parsed["plan"][0]["text"], "Checking calendar")
        kinds = [o["kind"] for o in parsed["objects"]]
        self.assertEqual(kinds, ["tiles", "letter", "ticket", "ask"])
        tiles = parsed["objects"][0]
        self.assertEqual(tiles["items"], ["Inbox", "Sent"])
        self.assertEqual(parsed["objects"][1]["body"],
                         "Thursday works for me.")
        self.assertEqual(parsed["objects"][2]["attrs"]["status"], "open")

    def test_garbage_degrades_to_letter(self):
        parsed = note.parse("::bogus\nhello\n::\n:::chart\nunclosed")
        kinds = [o["kind"] for o in parsed["objects"]]
        self.assertTrue(kinds)  # something landed
        self.assertTrue(all(k in ("letter", "chart") for k in kinds))
        # never raises
        note.parse(":::letter\nno close")
        note.parse("{now}")
        note.parse("")

    def test_rewrite_plan_marker(self):
        a = note.parse("{now} Doing it\n:::letter\nok\n:::")
        b = note.parse("{needs} Waiting\n:::letter\nok\n:::")
        self.assertEqual(a["plan"][0]["marker"], "now")
        self.assertEqual(b["plan"][0]["marker"], "needs")


class TestNotePad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_set_writes_file_and_emits_event(self):
        bus = state_mod.StateBus(
            state_mod.State(state_file=self.root / "state.json",
                            write_initial=False),
            autostart=False)
        sub = bus.subscribe(topics=["events", "state"])
        pad = note.NotePad("conv1", bus=bus, turn_id=bus.current_turn(),
                           root=self.root)
        payload = pad.set(SAMPLE)
        self.assertTrue(pad.path.exists())
        self.assertIn("::tiles", pad.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["conv_id"], "conv1")
        kinds = [o["kind"] for o in payload["objects"]]
        self.assertIn("tiles", kinds)
        self.assertIn("letter", kinds)
        self.assertTrue(payload["plan"])
        self.assertIn("[now]", payload["rendered"])

        events = []
        while (ev := sub.get(0.05)) is not None:
            events.append(ev)
        note_evs = [e for e in events
                    if e.get("type") == "event"
                    and e.get("name") == "note_changed"]
        self.assertEqual(len(note_evs), 1)
        self.assertEqual(note_evs[0]["data"]["conv_id"], "conv1")
        self.assertEqual(bus.snapshot()["note"]["conv_id"], "conv1")

    def test_rewrite_emits_ordered_events(self):
        bus = state_mod.StateBus(
            state_mod.State(state_file=self.root / "state.json",
                            write_initial=False),
            autostart=False)
        sub = bus.subscribe(topics=["events"])
        pad = note.NotePad("t", bus=bus, turn_id=bus.current_turn(),
                           root=self.root)
        pad.set("{now} A\n:::letter\none\n:::")
        pad.set("{needs} B\n:::letter\ntwo\n:::")
        markers = []
        while (ev := sub.get(0.05)) is not None:
            if ev.get("name") == "note_changed":
                plan = ev["data"].get("plan") or []
                markers.append(plan[0]["marker"] if plan else None)
        self.assertEqual(markers, ["now", "needs"])

    def test_close_clears_plan_in_payload(self):
        bus = state_mod.StateBus(
            state_mod.State(state_file=self.root / "state.json",
                            write_initial=False),
            autostart=False)
        pad = note.NotePad("t", bus=bus, turn_id=bus.current_turn(),
                           root=self.root)
        pad.set("{now} Working\n:::letter\nhi\n:::")
        closed = pad.close()
        self.assertTrue(closed["closed"])
        self.assertEqual(closed["plan"], [])
        self.assertNotIn("[now]", closed["rendered"])
        # file still has the markers
        self.assertIn("{now}", pad.read())


class TestHelpers(unittest.TestCase):
    def test_looks_like_paper(self):
        self.assertTrue(note.looks_like_paper("::tiles\n- a\n::"))
        self.assertTrue(note.looks_like_paper("{now} x"))
        self.assertFalse(note.looks_like_paper("just a sentence"))

    def test_spoken_text_prefers_letter(self):
        parsed = note.parse(
            "{now} X\n::tiles\n- a\n::\n:::letter\nHello there.\n:::")
        self.assertEqual(note.spoken_text(parsed), "Hello there.")


if __name__ == "__main__":
    unittest.main()
