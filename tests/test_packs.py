"""Capture packs (U4): the durable per-turn artifact + `wispd captures`.

The act loop's finally hands the turn off to `packs.write`, which folds
`rec/<turn>/` into `~/.local/share/wisp/packs/<turn>/`: a
`wisp-capture-pack/v1` manifest (schema, transcript-with-timestamps,
actions + verdicts, frame index), the frame PNGs, a contact sheet.
Keyboard args persist only as len + salted HMAC-SHA256; a deny-listed
surface visible at pack-write (or an unreadable window list) deletes
every frame — recorded in the manifest. Retention prunes packs/ by
count AND age, shots/ on its own keys (same policy, same owner), and
rec/ is swept after promotion. `wispd captures` serves metadata over
IPC; transcript lines and AT-SPI state dumps only under --full.

Everything here is faked: temp rec/packs/shots roots, a stub window
list, hand-encoded PNGs — nothing touches a live daemon or compositor.
"""
import json
import os
import pathlib
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import cli_env  # noqa: E402

from wisp import act, packs, record  # noqa: E402
from wisp import trace as _trace  # noqa: E402
import wisp.verify as verify  # noqa: E402


def _png_bytes(w, h, px):
    """Minimal RGB8 PNG encoder — no PIL needed to build fixtures."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    raw = b"".join(
        b"\x00" + b"".join(bytes(px(x, y)) for x in range(w))
        for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


_GRAY = (128, 128, 128)


def _write_png(path, w=200, h=200, blocks=()):
    def px(x, y):
        for x0, y0, x1, y1 in blocks:
            if x0 <= x < x1 and y0 <= y < y1:
                return (240, 240, 240)
        return _GRAY
    pathlib.Path(path).write_bytes(_png_bytes(w, h, px))


def _mode(path) -> int:
    return stat.S_IMODE(pathlib.Path(path).stat().st_mode)


def _turn_dir(rec_dir, seq=1, tool="click", args=None, ts=None,
              pngs=("before.png", "after.png"), evidence=None):
    """A driver-style turn-NNNNN dir inside rec/<turn>/."""
    d = pathlib.Path(rec_dir) / f"turn-{seq:05d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "action.json").write_text(json.dumps({
        "tool": tool,
        "args": {"session": "wisp", "x": 10, "y": 20,
                 **(args or {})},
        "action_truth": {"effect": "delivered", "route": "g",
                         "transport": "t", "refusal": None},
        "ts": time.time() if ts is None else ts,
        "ms": int(time.monotonic() * 1000)}))
    for i, n in enumerate(pngs):
        _write_png(d / n, blocks=[(i * 10, i * 10, 30 + i * 10,
                                   30 + i * 10)])
    (d / "evidence.json").write_text(json.dumps(evidence or {}))
    (d / "before_state.json").write_text(
        json.dumps({"tree": "window text"}))
    return d


def _step(d=None, tool="click", arg="10,20", verdict="landed"):
    s = {"tool": tool, "arg": arg,
         "turn_dir": str(d) if d else None,
         "verdict": verdict,
         "verify": {"verdict": verdict, "source": "rung",
                    "corroborated": verdict == "landed",
                    "evidence": str(d) if d else "",
                    "detail": "test"}}
    return s


NO_CLIENTS = []          # visible_deny: readable list, nothing denied
NO_MONS = []             # visibility unknown -> every mapped client counts


class PackCase(unittest.TestCase):
    """Shared plumbing: rec/, packs/, shots/ and the salt all live in a
    temp dir; trace writes to a temp file."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        t = pathlib.Path(self.td.name)
        self.rec = t / "rec"
        self.store = t / "packs"
        self.shots = t / "shots"
        self.trace_file = t / "trace.jsonl"
        self._patchers = [
            mock.patch.object(record, "REC_DIR", self.rec),
            mock.patch.object(packs, "PACKS_DIR", self.store),
            mock.patch.object(packs, "SHOTS_DIR", self.shots),
            mock.patch.object(_trace, "TRACE_FILE", self.trace_file),
            mock.patch.object(_trace, "_enabled", True),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._unpatch)

    def _unpatch(self):
        for p in reversed(self._patchers):
            p.stop()

    def write(self, turn="t-p1", steps=(), rec_dir=None, cfg=None,
              transcript=None, **kw):
        kw.setdefault("clients", NO_CLIENTS)
        kw.setdefault("monitors", NO_MONS)
        return packs.write(turn, list(steps), cfg or {},
                           rec_dir=rec_dir,
                           recorded=kw.pop("recorded", True),
                           transcript=transcript or
                           [{"role": "user", "text": "do it"}],
                           **kw)

    def manifest(self, turn="t-p1") -> dict:
        return json.loads(
            (self.store / turn / "manifest.json").read_text())


class TestWrite(PackCase):
    def test_manifest_schema_frames_and_verdicts(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        d2 = _turn_dir(rec_dir, 2)
        steps = [_step(d1), _step(d2, verdict="missed")]
        pack = self.write(steps=steps, rec_dir=rec_dir)
        self.assertEqual(pack, self.store / "t-p1")
        m = self.manifest()
        self.assertEqual(m["schema"], "wisp-capture-pack/v1")
        self.assertEqual(m["turn"], "t-p1")
        self.assertEqual(m["session"], "wisp")
        self.assertEqual(len(m["actions"]), 2)
        self.assertEqual(m["verdicts"], {"landed": 1, "missed": 1})
        self.assertEqual(m["frame_count"], 4)
        self.assertEqual(len(m["frames"]), 2)
        self.assertEqual(m["transcript"][0]["role"], "user")
        self.assertEqual(m["transcript"][0]["text"], "do it")
        self.assertIn("ts", m["transcript"][0])
        self.assertFalse(m["privacy_suppressed"])
        # action refs rebase into the pack, never absolute rec paths
        a = m["actions"][0]
        self.assertEqual(a["turn_dir"], "turn-00001")
        self.assertEqual(a["verify"]["evidence"], "turn-00001")
        self.assertIn("ts", a)
        # the four frames + action.json + evidence + state landed
        names = {f["name"] for e in m["frames"] for f in e["files"]}
        self.assertIn("before.png", names)
        self.assertIn("after.png", names)
        self.assertIn("action.json", names)
        self.assertIn("evidence.json", names)
        self.assertIn("before_state.json", names)
        # the rec/ intermediates are gone after promotion
        self.assertFalse((self.rec / "t-p1").exists())
        # step records link back to the pack
        self.assertEqual(steps[0]["pack"], "packs/t-p1")

    def test_frame_files_identical_and_hardlinked(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir, clean_rec=False)
        src = d1 / "before.png"
        dst = self.store / "t-p1" / "turn-00001" / "before.png"
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        # same volume -> the pack shares the rec inode (no byte copy)
        self.assertEqual(src.stat().st_ino, dst.stat().st_ino)

    def test_contact_sheet_or_note(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        m = self.manifest()
        backend = packs._PIL or shutil.which("montage") \
            or shutil.which("magick")
        if backend:
            self.assertEqual(m["contact"]["file"], "contact.png")
            self.assertTrue(
                (self.store / "t-p1" / "contact.png").exists())
        else:
            self.assertIsNone(m["contact"]["file"])
            self.assertIn("no contact backend",
                          m["contact"]["note"])

    def test_missing_contact_backend_never_fails(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        with mock.patch.object(packs, "_PIL", False), \
                mock.patch.object(packs, "_montage_bin",
                                  return_value=None):
            pack = self.write(steps=[_step(d1)], rec_dir=rec_dir)
        m = self.manifest()
        self.assertEqual(pack, self.store / "t-p1")
        self.assertIsNone(m["contact"]["file"])
        self.assertIn("no contact backend", m["contact"]["note"])

    def test_permissions_0700_and_manifest_0600(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        self.assertEqual(_mode(self.store), 0o700)
        self.assertEqual(_mode(self.store / "t-p1"), 0o700)
        self.assertEqual(
            _mode(self.store / "t-p1" / "manifest.json"), 0o600)

    def test_unrecorded_turn_writes_nothing(self):
        self.assertIsNone(self.write(steps=[], rec_dir=self.rec / "t-x",
                                     recorded=False))
        self.assertFalse(self.store.exists())

    def test_sys_turn_is_never_packed(self):
        rec_dir = self.rec / "sys"
        d1 = _turn_dir(rec_dir, 1)
        self.assertIsNone(self.write(turn="sys", steps=[_step(d1)],
                                     rec_dir=rec_dir))
        self.assertFalse(self.store.exists())

    def test_recorded_zero_action_turn_packs_transcript(self):
        rec_dir = self.rec / "t-p1"
        rec_dir.mkdir(parents=True)
        pack = self.write(steps=[], rec_dir=rec_dir)
        m = self.manifest()
        self.assertEqual(pack, self.store / "t-p1")
        self.assertEqual(m["actions"], [])
        self.assertEqual(m["frame_count"], 0)
        self.assertEqual(m["transcript"][0]["text"], "do it")

    def test_transcript_is_sanitized(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir,
                   transcript=[{"role": "user",
                                "text": "a\x00b\x1b[3mc\x7f"}])
        m = self.manifest()
        self.assertNotRegex(m["transcript"][0]["text"], r"[\x00-\x1f]")
        # control bytes become spaces — the ESC leaves literal "[3m"
        self.assertEqual(m["transcript"][0]["text"], "a b [3mc ")

    def test_write_never_raises(self):
        # rec_dir a FILE: _turn_dirs returns [] and a recorded turn
        # still gets its transcript-only pack
        f = self.rec / "t-p1"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("junk")
        self.assertIsNotNone(self.write(steps=[], rec_dir=f))


class TestRedaction(PackCase):
    def test_type_text_args_hash_never_plaintext(self):
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1, tool="type_text",
                  args={"text": "s3cret w0rd"})
        steps = [{"tool": "type_text", "arg": "s3cret w0rd",
                  "turn_dir": str(rec_dir / "turn-00001"),
                  "verdict": "not_recorded"}]
        self.write(steps=steps, rec_dir=rec_dir)
        aj = json.loads((self.store / "t-p1" / "turn-00001"
                         / "action.json").read_text())
        red = aj["args"]["text"]
        self.assertTrue(red["redacted"])
        self.assertEqual(red["len"], len("s3cret w0rd"))
        self.assertRegex(red["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(aj["args"]["session"], "wisp")
        # the manifest step arg is the same redacted form
        m = self.manifest()
        marg = m["actions"][0]["arg"]
        self.assertTrue(marg["redacted"])
        self.assertEqual(marg["len"], len("s3cret w0rd"))
        # plaintext survives NOWHERE durable — not in manifest.json,
        # not in any copied json
        for p in self.store.rglob("*"):
            if p.is_file() and p.suffix != ".png":
                self.assertNotIn(b"s3cret", p.read_bytes(), str(p))

    def test_salted_hash_is_stable_across_packs(self):
        for turn in ("t-a", "t-b"):
            rec_dir = self.rec / turn
            _turn_dir(rec_dir, 1, tool="type_text",
                      args={"text": "same phrase"})
            self.write(turn=turn, steps=[], rec_dir=rec_dir)
        a = json.loads((self.store / "t-a" / "turn-00001"
                        / "action.json").read_text())
        b = json.loads((self.store / "t-b" / "turn-00001"
                        / "action.json").read_text())
        self.assertEqual(a["args"]["text"]["sha256"],
                         b["args"]["text"]["sha256"])

    def test_key_tool_also_redacted(self):
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1, tool="key", args={"key": "a"})
        self.write(steps=[], rec_dir=rec_dir)
        aj = json.loads((self.store / "t-p1" / "turn-00001"
                         / "action.json").read_text())
        self.assertTrue(aj["args"]["key"]["redacted"])

    def test_non_keyboard_args_pass_through(self):
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1, tool="click", args={"x": 5, "y": 6})
        self.write(steps=[], rec_dir=rec_dir)
        aj = json.loads((self.store / "t-p1" / "turn-00001"
                         / "action.json").read_text())
        self.assertEqual(aj["args"]["x"], 5)


class TestSuppression(PackCase):
    DENY = [{"class": "gcr-prompter", "title": "unlock",
             "mapped": True, "workspace": {"id": 1}}]

    def test_visible_deny_deletes_every_frame(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        d2 = _turn_dir(rec_dir, 2)
        self.write(steps=[_step(d1), _step(d2)], rec_dir=rec_dir,
                   clean_rec=False,
                   clients=self.DENY)
        m = self.manifest()
        self.assertTrue(m["privacy_suppressed"])
        self.assertEqual(m["frame_count"], 0)
        self.assertFalse(list(self.store.rglob("*.png")))
        # the deny-interval frames died at the source too (KTD6)
        self.assertEqual(list(d1.glob("*.png")), [])
        self.assertEqual(list(d2.glob("*.png")), [])
        stages = {e["stage"] for e in m["privacy"]["events"]}
        self.assertEqual(stages, {"pack"})
        self.assertTrue(any("gcr-prompter" in e["reason"]
                            for e in m["privacy"]["events"]))
        # the manifest is still valid evidence: actions + event record
        self.assertEqual(len(m["actions"]), 2)
        self.assertTrue(all(e["deleted_frames"]
                            for e in m["privacy"]["events"]))

    def test_unreadable_window_list_suppresses_too(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)

        def boom():
            raise OSError("hyprctl gone")
        self.write(steps=[_step(d1)], rec_dir=rec_dir,
                   clients=boom, monitors=NO_MONS)
        m = self.manifest()
        self.assertTrue(m["privacy_suppressed"])
        self.assertEqual(m["frame_count"], 0)
        self.assertIn("unreadable",
                      m["privacy"]["events"][0]["reason"])

    def test_loop_stage_suppression_deletes_stragglers(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        # mid-loop suppress already ran: evidence.json carries the
        # record, but the driver's late after.png survived
        (d1 / "evidence.json").write_text(json.dumps({
            "privacy_suppressed": True,
            "suppression": {"reason": "deny interval", "ts": 1.0,
                            "deleted_frames": ["before.png"]}}))
        self.write(steps=[_step(d1, verdict="suppressed")],
                   rec_dir=rec_dir, clean_rec=False)
        m = self.manifest()
        self.assertTrue(m["privacy_suppressed"])
        self.assertEqual(list(d1.glob("*.png")), [])
        self.assertEqual(m["privacy"]["events"][0]["stage"], "loop")
        # the copied evidence.json still records the suppression
        ev = json.loads((self.store / "t-p1" / "turn-00001"
                         / "evidence.json").read_text())
        self.assertTrue(ev["privacy_suppressed"])


class TestRetention(PackCase):
    def _pack(self, turn, ts=None):
        p = self.store / turn
        p.mkdir(parents=True, exist_ok=True)
        (p / "manifest.json").write_text(json.dumps(
            {"schema": packs.SCHEMA, "turn": turn,
             "ts": ts if ts is not None else time.time(),
             "actions": [], "transcript": [], "frames": []}))
        return p

    def test_prune_by_count(self):
        cfg = {"packs": {"keep": "2", "keep_days": "0"}}
        t0 = time.time()
        for i, turn in enumerate(("t-1", "t-2", "t-3")):
            self._pack(turn, ts=t0 + i)
        r = packs.maintenance(cfg)["packs"]
        self.assertEqual(r["removed"], ["t-1"])
        self.assertTrue((self.store / "t-2").exists())
        self.assertTrue((self.store / "t-3").exists())

    def test_prune_by_age(self):
        cfg = {"packs": {"keep": "0", "keep_days": "7"}}
        now = time.time()
        self._pack("t-old", ts=now - 9 * 86400)
        self._pack("t-new", ts=now)
        r = packs.maintenance(cfg, now=now)["packs"]
        self.assertEqual(r["removed"], ["t-old"])
        self.assertTrue((self.store / "t-new").exists())

    def test_evicted_pack_drops_its_rec_intermediates(self):
        cfg = {"packs": {"keep": "1", "keep_days": "0"}}
        t0 = time.time()
        self._pack("t-1", ts=t0)
        self._pack("t-2", ts=t0 + 1)
        stale = self.rec / "t-1"
        stale.mkdir(parents=True)
        (stale / "turn-00001").mkdir()
        r = packs.maintenance(cfg)["packs"]
        self.assertEqual(r["removed"], ["t-1"])
        self.assertFalse(stale.exists())

    def test_shots_pruning_is_owned_but_explicit(self):
        self.shots.mkdir(parents=True)
        for i in range(3):
            f = self.shots / f"shot-{i}.png"
            f.write_bytes(b"x")
            os.utime(f, (time.time() + i, time.time() + i))
        cfg = {"packs": {"shots_keep": "2", "shots_keep_days": "0"}}
        r = packs.maintenance(cfg)["shots"]
        self.assertEqual(len(r["removed"]), 1)
        self.assertEqual(len(list(self.shots.iterdir())), 2)
        # zero disables: nothing is ever silently deleted
        r = packs.maintenance(
            {"packs": {"shots_keep": "0", "shots_keep_days": "0"}},
            )["shots"]
        self.assertEqual(r["removed"], [])

    def test_maintenance_runs_both_stores(self):
        cfg = {"packs": {"keep": "0", "keep_days": "7",
                         "shots_keep": "0", "shots_keep_days": "7"}}
        now = time.time()
        self._pack("t-old", ts=now - 9 * 86400)
        self.shots.mkdir(parents=True)
        old = self.shots / "old.png"
        old.write_bytes(b"x")
        os.utime(old, (now - 9 * 86400,) * 2)
        r = packs.maintenance(cfg, now=now)
        self.assertEqual(r["packs"]["removed"], ["t-old"])
        self.assertEqual(r["shots"]["removed"], ["old.png"])


class TestCaptures(PackCase):
    def test_list_rows_are_metadata_only(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        r = packs.captures_response({"cmd": "captures"})
        self.assertTrue(r["ok"])
        row = r["packs"][0]
        self.assertEqual(row["turn"], "t-p1")
        self.assertEqual(row["actions"], 1)
        self.assertEqual(row["verdicts"], {"landed": 1})
        self.assertEqual(row["frames"], 2)
        self.assertFalse(row["suppressed"])
        self.assertIn("path", row)
        self.assertNotIn("transcript", row)

    def test_manifest_gates_transcript_and_state_dumps(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        r = packs.captures_response({"cmd": "captures", "turn": "t-p1"})
        self.assertTrue(r["ok"])
        m = r["manifest"]
        self.assertEqual(m["transcript"], [])
        self.assertGreater(m["transcript_lines"], 0)
        kinds = {f["kind"] for e in m["frames"] for f in e["files"]}
        self.assertNotIn("state", kinds)
        self.assertEqual(m["state_dumps_gated"], "--full")
        r = packs.captures_response(
            {"cmd": "captures", "turn": "t-p1", "full": True})
        m = r["manifest"]
        self.assertEqual(m["transcript"][0]["text"], "do it")
        kinds = {f["kind"] for e in m["frames"] for f in e["files"]}
        self.assertIn("state", kinds)

    def test_no_such_pack_and_bad_turn(self):
        r = packs.captures_response({"cmd": "captures", "turn": "t-zz"})
        self.assertEqual(r, {"ok": False, "error": "no_such_pack"})
        r = packs.captures_response(
            {"cmd": "captures", "turn": "../etc"})
        self.assertEqual(r, {"ok": False, "error": "bad_turn"})

    def test_empty_store_lists_nothing(self):
        r = packs.captures_response({"cmd": "captures"})
        self.assertEqual(r, {"ok": True, "packs": []})

    def test_cli_over_ipc(self):
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        store = self.store
        with cli_env.CliEnv() as env:
            env.start_daemon(
                handler=lambda c: packs.captures_response(c, root=store))
            code, out, err = env.run(["captures", "--json"])
            self.assertEqual(code, 0, err)
            env_data = json.loads(out)["data"]
            self.assertEqual(len(env_data["packs"]), 1)
            self.assertEqual(env_data["packs"][0]["turn"], "t-p1")
            self.assertNotIn("transcript",
                             env_data["packs"][0])
            code, out, err = env.run(["captures", "t-p1", "--json"])
            self.assertEqual(code, 0, err)
            m = json.loads(out)["data"]["manifest"]
            self.assertEqual(m["transcript"], [])
            self.assertGreater(m["transcript_lines"], 0)
            code, out, err = env.run(
                ["captures", "t-p1", "--full", "--json"])
            self.assertEqual(code, 0, err)
            m = json.loads(out)["data"]["manifest"]
            self.assertEqual(m["transcript"][0]["text"], "do it")
            # the wire carried turn + full
            self.assertIn({"cmd": "captures", "turn": "t-p1",
                           "full": True}, env.ipc)

    def test_cli_empty_store_exits_zero(self):
        with cli_env.CliEnv() as env:
            env.start_daemon(
                handler=lambda c: packs.captures_response(
                    c, root=self.store))
            code, out, err = env.run(["captures"])
            self.assertEqual(code, 0, err)
            self.assertIn("[]", out)


class TestKeyboardRedaction(PackCase):
    """F2: fill/post_send carry typed content — same privacy class as
    type_text; args and result echoes must never reach the pack."""

    def test_fill_value_with_equals_never_leaks_plaintext(self):
        rec_dir = self.rec / "t-eq"
        steps = [{"tool": "fill", "arg": "login-pw abc=def",
                  "result": "FILLED login-pw=abc=def",
                  "turn_dir": str(rec_dir / "turn-00001"),
                  "verdict": "not_recorded"}]
        _turn_dir(rec_dir, 1, tool="fill", args={"text": "abc=def"})
        self.write(steps=steps, rec_dir=rec_dir, turn="t-eq")
        a = self.manifest("t-eq")["actions"][0]
        self.assertEqual(a["arg"]["target"], "login-pw")
        self.assertTrue(a["arg"]["value"]["redacted"])
        for p in self.store.rglob("*"):
            if p.is_file() and p.suffix != ".png":
                body = p.read_bytes()
                self.assertNotIn(b"abc", body, str(p))

    def test_fill_arg_and_result_redact(self):
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1, tool="fill",
                  args={"text": "s3cret p@ssphrase"})
        steps = [{"tool": "fill", "arg": "login-pw s3cret p@ssphrase",
                  "result": "FILLED login-pw=s3cret p@ssphrase",
                  "turn_dir": str(rec_dir / "turn-00001"),
                  "verdict": "not_recorded"}]
        self.write(steps=steps, rec_dir=rec_dir)
        a = self.manifest()["actions"][0]
        # the field id stays (routing metadata); the value is hashed
        self.assertEqual(a["arg"]["target"], "login-pw")
        self.assertTrue(a["arg"]["value"]["redacted"])
        self.assertEqual(a["arg"]["value"]["len"],
                         len("s3cret p@ssphrase"))
        # the FILLED echo keeps the tool prefix, never the value
        self.assertEqual(a["result"], "FILLED login-pw")
        for p in self.store.rglob("*"):
            if p.is_file() and p.suffix != ".png":
                self.assertNotIn(b"s3cret", p.read_bytes(), str(p))
                self.assertNotIn(b"p@ssphrase", p.read_bytes(), str(p))

    def test_post_send_arg_fully_redacted(self):
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1, tool="post_send",
                  args={"text": "my hot take draft"})
        steps = [{"tool": "post_send", "arg": "my hot take draft",
                  "result": "OPENED compose via xdg-open — press Post",
                  "turn_dir": str(rec_dir / "turn-00001"),
                  "verdict": "not_recorded"}]
        self.write(steps=steps, rec_dir=rec_dir)
        a = self.manifest()["actions"][0]
        self.assertTrue(a["arg"]["redacted"])
        self.assertEqual(a["arg"]["len"], len("my hot take draft"))
        # the result has no typed payload to strip — passes through
        self.assertIn("OPENED compose", a["result"])
        for p in self.store.rglob("*"):
            if p.is_file() and p.suffix != ".png":
                self.assertNotIn(b"hot take", p.read_bytes(), str(p))


class TestSuppressionFiles(PackCase):
    """F10/F23: suppression deletes the JSON evidence too, and the
    pack never promotes it — even when it lands after the re-check."""

    def _suppressed_dir(self, rec_dir, seq=1):
        d = _turn_dir(rec_dir, seq)
        (d / "before_state.json").write_text(
            json.dumps({"atspi": "window text dump"}))
        (d / "control_before.json").write_text(
            json.dumps({"inspect": {"window": "text"}}))
        (d / "control_after.json").write_text(
            json.dumps({"inspect": {"window": "more text"}}))
        (d / "evidence.json").write_text(json.dumps({
            "privacy_suppressed": True,
            "suppression": {"reason": "deny interval",
                            "ts": 1.0, "deleted_frames": []}}))
        return d

    def test_suppressed_dir_drops_state_and_control_json(self):
        rec_dir = self.rec / "t-p1"
        d1 = self._suppressed_dir(rec_dir)
        self.write(steps=[_step(d1, verdict="suppressed")],
                   rec_dir=rec_dir, clean_rec=False)
        pack_d = self.store / "t-p1" / "turn-00001"
        # images, state dumps and channel snapshots never promote —
        # action.json + evidence.json do (they carry the record)
        names = {p.name for p in pack_d.iterdir()}
        self.assertEqual(names, {"action.json", "evidence.json"})
        # the rec/ source was re-swept too (F23 straggler close)
        self.assertFalse(list(d1.glob("*.png")))
        self.assertFalse((d1 / "control_before.json").exists())
        self.assertFalse((d1 / "before_state.json").exists())

    def test_straggler_in_suppressed_dir_still_dropped(self):
        rec_dir = self.rec / "t-p1"
        d1 = self._suppressed_dir(rec_dir)
        self.write(steps=[_step(d1, verdict="suppressed")],
                   rec_dir=rec_dir, clean_rec=False)
        m = self.manifest()
        # the frame index records no promoted evidence files
        entry = m["frames"][0]
        self.assertEqual(
            {f["name"] for f in entry["files"]},
            {"action.json", "evidence.json"})

    def test_pack_write_failure_signals_not_silent(self):
        # F20: a failed write returns None like an empty turn but must
        # leave a pack_unavailable trace row — the evidence gap is real
        rec_dir = self.rec / "t-p1"
        _turn_dir(rec_dir, 1)
        with mock.patch.object(packs, "_write",
                               side_effect=OSError("disk full")):
            out = self.write(steps=[], rec_dir=rec_dir)
        self.assertIsNone(out)
        evs = [e for e in _trace.read(path=self.trace_file, tail=50)
               if e["step"] == "pack_unavailable"]
        self.assertTrue(evs)
        self.assertIn("disk full", evs[0]["data"]["detail"])

    def test_full_gate_is_strict_bool(self):
        # F24: full:"false"/full:1 from a wire client never opens the
        # gated transcript — only JSON true does
        rec_dir = self.rec / "t-p1"
        d1 = _turn_dir(rec_dir, 1)
        self.write(steps=[_step(d1)], rec_dir=rec_dir)
        for bad in ("false", "true", 1, "yes"):
            r = packs.captures_response(
                {"cmd": "captures", "turn": "t-p1", "full": bad})
            self.assertEqual(r["manifest"]["transcript"], [], bad)
        r = packs.captures_response(
            {"cmd": "captures", "turn": "t-p1", "full": True})
        self.assertEqual(r["manifest"]["transcript"][0]["text"],
                         "do it")


class TestActLoopPack(PackCase):
    """End-to-end: run_act_loop -> finally -> packs.write lands a real
    pack from the fake driver's rec dir."""

    def setUp(self):
        super().setUp()
        from wisp import platform, realinput, cua_safety, tools
        self.driver = _LoopDriver(self.rec)
        t = pathlib.Path(self.td.name)
        self._more = [
            mock.patch("wisp.cancel.run",
                       side_effect=self.driver.run),
            mock.patch.object(act.realinput, "begin",
                              return_value="off"),
            mock.patch.object(act, "_record_traj"),
            mock.patch.object(platform, "_cua_live",
                              return_value=True),
            mock.patch.object(cua_safety, "audit_default_path",
                              return_value=t / "cua.jsonl"),
            mock.patch.object(cua_safety, "kill_default_path",
                              return_value=t / "cua.kill"),
            mock.patch.object(verify, "_clients", return_value=[]),
            mock.patch.object(verify, "_monitors", return_value=[]),
        ]
        for p in self._more:
            p.start()
        self.addCleanup(self._unpatch_more)
        self._tools = tools

    def _unpatch_more(self):
        for p in reversed(self._more):
            p.stop()

    def test_loop_writes_pack(self):
        from wisp import tools
        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "click",
                                          "arguments":
                                          '{"arg":"10,20@logical"}'}}]},
            {"role": "assistant", "content": "done"},
        ]
        cfg = {"pointer": {"mode": "drive"},
               "brain": {"default": "lmstudio:fake"},
               "brain.lmstudio": {"tools": "true", "vision": "false",
                                  "kind": "openai_compat",
                                  "base_url": "http://127.0.0.1:1"}}

        def fake_run(name, arg, cfg, harness=None):
            if name == "click":
                x, y = (int(v)
                        for v in arg.split("@")[0].split(",")[:2])
                self.driver.action("click", x, y)
                return f"CLICKED({x},{y})"
            return "OK"

        steps = []
        _trace.set_turn("t-loop1")
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run",
                                  side_effect=fake_run):
            out = act.run_act_loop("do it", cfg, steps_out=steps)
        self.assertTrue(out.startswith("ACTED"), out)
        pack = self.store / "t-loop1"
        m = json.loads((pack / "manifest.json").read_text())
        self.assertEqual(m["schema"], packs.SCHEMA)
        self.assertEqual(m["turn"], "t-loop1")
        self.assertEqual(len(m["actions"]), 1)
        self.assertEqual(m["actions"][0]["turn_dir"], "turn-00001")
        self.assertEqual(m["frame_count"], 2)
        self.assertEqual(m["transcript"][0]["text"], "do it")
        self.assertEqual(m["transcript"][-1]["text"], out)
        # the turn's intermediates are gone
        self.assertFalse((self.rec / "t-loop1").exists())
        # and the pack event went to the trace
        evs = [e for e in _trace.read(path=self.trace_file, tail=100)
               if e.get("step") == "pack"]
        self.assertEqual(len(evs), 1)


class _LoopDriver:
    """`cua-driver call` boundary fake (same contract as
    test_record.FakeDriver) that also writes frame PNGs so the pack has
    something to promote."""

    def __init__(self, rec_root):
        self.rec_root = rec_root
        self.rec_dir = None
        self.seq = 0

    def run(self, argv, **kw):
        from wisp import cancel
        cancel.check()
        assert argv[:2] == ["cua-driver", "call"], argv
        tool = argv[2]
        args = json.loads(argv[3]) if len(argv) > 3 else {}
        if tool == "start_session":
            return self._done({"active": True})
        if tool == "start_recording":
            self.rec_dir = pathlib.Path(args["output_dir"])
            return self._done({"recording": True})
        if tool == "stop_recording":
            return self._done({"recording": False})
        return self._done({"tool": tool})

    @staticmethod
    def _done(result, rc=0):
        return subprocess.CompletedProcess(
            ["cua-driver"], rc,
            stdout=json.dumps(result).encode(), stderr=b"")

    def action(self, tool, x=None, y=None):
        self.seq += 1
        d = pathlib.Path(self.rec_dir) / f"turn-{self.seq:05d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "action.json").write_text(json.dumps({
            "tool": tool,
            "args": {"session": "wisp", "x": x, "y": y},
            "action_truth": {"effect": "delivered",
                             "route": "global_input",
                             "transport": "wayland", "refusal": None},
            "ts": time.time(),
            "ms": int(time.monotonic() * 1000)}))
        _write_png(d / "before.png")
        _write_png(d / "after.png", blocks=[(60, 60, 120, 120)])
        (d / "evidence.json").write_text("{}")
        return d


if __name__ == "__main__":
    unittest.main()
