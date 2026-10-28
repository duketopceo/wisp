"""B5: image objects in the paper, fetched only from allowed hosts."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from PIL import Image  # noqa: E402
from wisp import config, note, pipeline, stage_speak  # noqa: E402
from wisp.tools import imagefetch  # noqa: E402
from test_stage_speak import StageBase  # noqa: E402

URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Cat.png"


def png(w=40, h=30, color=(200, 80, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, data):
        self.buf = io.BytesIO(data)

    def read(self, n=-1):
        return self.buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Env(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        patches = [
            mock.patch.object(config, "DATA_DIR", self.tmp / "data"),
            mock.patch.object(config, "load_config", lambda: {}),
            mock.patch.dict(os.environ,
                            {"WISP_NOTES_DIR": str(self.tmp / "notes")}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.calls = []

    def opener(self, data):
        def op(url, timeout):
            self.calls.append(url)
            return FakeResponse(data)
        return op

    def public(self, host):
        return None


class Allow(Env):
    def test_default_allow_list_is_the_wikimedia_image_host(self):
        self.assertEqual(imagefetch.check_url(URL), "upload.wikimedia.org")

    def test_other_hosts_are_refused_with_a_speakable_reason(self):
        with self.assertRaises(imagefetch.ImageRefused) as c:
            imagefetch.check_url("https://evil.example.com/a.png")
        self.assertIn("evil.example.com isn't on my list", str(c.exception))

    def test_subdomains_of_an_allowed_host_pass_and_lookalikes_do_not(self):
        cfg = {"images": {"allow": "example.org, cdn.test"}}
        self.assertEqual(imagefetch.check_url("https://img.example.org/a",
                                              cfg), "img.example.org")
        for bad in ("https://example.org.evil.com/a",
                    "https://notexample.org/a",
                    "https://upload.wikimedia.org/a"):
            with self.assertRaises(imagefetch.ImageRefused, msg=bad):
                imagefetch.check_url(bad, cfg)

    def test_only_https_and_no_logins_in_the_address(self):
        for bad in ("http://upload.wikimedia.org/a.png",
                    "ftp://upload.wikimedia.org/a.png",
                    "file:///etc/passwd", "",
                    "https://user:pw@upload.wikimedia.org/a.png"):
            with self.assertRaises(imagefetch.ImageRefused, msg=bad):
                imagefetch.check_url(bad)

    def test_a_refused_host_is_never_connected_to(self):
        def boom(*a, **k):
            raise AssertionError("network touched")
        with self.assertRaises(imagefetch.ImageRefused):
            imagefetch.fetch("https://evil.example.com/a.png",
                             opener=boom, resolve=boom)

    def test_every_redirect_hop_is_checked(self):
        h = imagefetch._Hops({}, lambda host: None)
        req = mock.Mock(full_url=URL, headers={}, origin_req_host="x",
                        unverifiable=False, get_method=lambda: "GET",
                        data=None)
        with self.assertRaises(imagefetch.ImageRefused):
            h.redirect_request(req, None, 302, "Found", {},
                               "https://evil.example.com/b.png")

    def test_a_host_that_resolves_to_a_private_address_is_refused(self):
        with mock.patch("socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("10.0.0.5", 443))]):
            with self.assertRaises(imagefetch.ImageRefused):
                imagefetch._public("upload.wikimedia.org")
        with mock.patch("socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(imagefetch.ImageRefused):
                imagefetch._public("upload.wikimedia.org")
        with mock.patch("socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("93.184.216.34", 443))]):
            imagefetch._public("upload.wikimedia.org")


class Fetch(Env):
    def test_a_good_picture_is_stored_with_its_source(self):
        rec = imagefetch.fetch(URL, opener=self.opener(png()),
                               resolve=self.public)
        p = pathlib.Path(rec["path"])
        self.assertTrue(p.is_file())
        self.assertEqual(p.suffix, ".png")
        self.assertEqual((rec["w"], rec["h"]), (40, 30))
        self.assertEqual(rec["source"], URL)
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        side = json.loads(p.with_suffix(".json").read_text())
        self.assertEqual(side["source"], URL)

    def test_a_second_request_for_the_same_url_costs_nothing(self):
        imagefetch.fetch(URL, opener=self.opener(png()), resolve=self.public)
        again = imagefetch.fetch(URL, opener=self.opener(b"x"),
                                 resolve=self.public)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(again["source"], URL)

    def test_an_oversized_download_is_stopped(self):
        cfg = {"images": {"max_kb": "1"}}
        with self.assertRaises(imagefetch.ImageFailed) as c:
            imagefetch.fetch(URL, cfg, opener=self.opener(b"\0" * 5000),
                             resolve=self.public)
        self.assertIn("too large", str(c.exception))
        self.assertIsNone(imagefetch.lookup(URL))

    def test_something_that_is_not_a_picture_is_not_stored(self):
        with self.assertRaises(imagefetch.ImageFailed):
            imagefetch.fetch(URL, opener=self.opener(b"<html>hi</html>"),
                             resolve=self.public)
        self.assertIsNone(imagefetch.lookup(URL))
        self.assertFalse(list((config.DATA_DIR / "images").glob("*.png")))

    def test_a_huge_picture_by_pixels_is_refused(self):
        with mock.patch.object(imagefetch, "MAX_PIXELS", 100):
            with self.assertRaises(imagefetch.ImageFailed):
                imagefetch.fetch(URL, opener=self.opener(png(40, 30)),
                                 resolve=self.public)

    def test_a_network_error_is_a_speakable_failure(self):
        def bad(url, timeout):
            raise OSError("down")
        with self.assertRaises(imagefetch.ImageFailed) as c:
            imagefetch.fetch(URL, opener=bad, resolve=self.public)
        self.assertIn("upload.wikimedia.org", str(c.exception))


class Grammar(Env):
    TEXT = ("Here is the cat.\n::image[url=" + URL + ",alt=A cat]\n"
            "Seen from the front.\n::\nDone.")

    def test_image_objects_parse_with_url_and_alt(self):
        objs = note.parse(self.TEXT)["objects"]
        img = [o for o in objs if o["kind"] == "image"][0]
        self.assertEqual(img["attrs"]["url"], URL)
        self.assertEqual(img["attrs"]["alt"], "A cat")
        self.assertEqual(img["body"], "Seen from the front.")

    def test_unknown_objects_still_degrade_to_letter_text(self):
        objs = note.parse("::imagine[url=x]\nhi")["objects"]
        self.assertEqual([o["kind"] for o in objs], ["letter"])

    def test_payload_state_is_loading_ready_or_refused(self):
        p = note._payload("c", self.tmp / "n.md", note.parse(self.TEXT),
                          closed=False, cfg={})
        img = [o for o in p["objects"] if o["kind"] == "image"][0]["image"]
        self.assertEqual((img["status"], img["local"]), ("loading", ""))
        imagefetch.fetch(URL, opener=self.opener(png()), resolve=self.public)
        p = note._payload("c", self.tmp / "n.md", note.parse(self.TEXT),
                          closed=False, cfg={})
        img = [o for o in p["objects"] if o["kind"] == "image"][0]["image"]
        self.assertEqual(img["status"], "ready")
        self.assertTrue(img["local"].endswith(".png"))
        self.assertEqual(img["source"], URL)
        bad = note.parse("::image[url=https://evil.example.com/a.png]\n::")
        p = note._payload("c", self.tmp / "n.md", bad, closed=False, cfg={})
        img = p["objects"][0]["image"]
        self.assertEqual(img["status"], "refused")
        self.assertIn("evil.example.com", img["reason"])
        self.assertEqual(note.refusals(p), [img["reason"]])

    def test_the_rendered_text_names_the_source(self):
        p = note._payload("c", self.tmp / "n.md", note.parse(self.TEXT),
                          closed=False, cfg={})
        self.assertIn("(image) A cat - " + URL, p["rendered"])

    def test_image_lines_never_reach_speech(self):
        out = note.strip_image_lines(self.TEXT)
        self.assertNotIn("::image", out)
        self.assertIn("Here is the cat.", out)
        part = "Look. \n::image[url=https://upload.wiki"
        self.assertEqual(note.strip_image_lines(part, partial=True), "Look.")
        self.assertEqual(note.strip_image_lines("std::vector is fine"),
                         "std::vector is fine")


class Pad(Env):
    def test_the_card_publishes_loading_then_the_local_copy(self):
        events = []
        bus = mock.Mock()
        bus.emit_event = lambda name, **kw: events.append((name, kw))
        bus.publish = lambda tid, **kw: None
        bus.current_turn = lambda: "t"
        jobs = []
        pad = note.NotePad("c", bus=bus, turn_id="t",
                           root=self.tmp / "notes", cfg={},
                           fetch=lambda u, cfg: imagefetch.fetch(
                               u, cfg, opener=self.opener(png()),
                               resolve=self.public),
                           spawn=jobs.append)
        first = pad.set(Grammar.TEXT)
        st = [o for o in first["objects"] if o["kind"] == "image"][0]
        self.assertEqual(st["image"]["status"], "loading")
        self.assertEqual(len(jobs), 1)
        jobs[0]()
        again = [kw for n, kw in events if n == "note_changed"][-1]
        st = [o for o in again["objects"] if o["kind"] == "image"][0]
        self.assertEqual(st["image"]["status"], "ready")
        self.assertEqual(st["image"]["source"], URL)

    def test_a_refused_picture_starts_no_download(self):
        jobs = []
        pad = note.NotePad("c", root=self.tmp / "notes", cfg={},
                           spawn=jobs.append)
        pad.set("::image[url=https://evil.example.com/a.png]\n::")
        self.assertEqual(jobs, [])

    def test_a_download_that_lands_after_the_turn_closed_does_not_reopen(self):
        events = []
        bus = mock.Mock()
        bus.emit_event = lambda name, **kw: events.append(kw)
        bus.publish = lambda tid, **kw: None
        jobs = []
        pad = note.NotePad("c", bus=bus, root=self.tmp / "notes", cfg={},
                           fetch=lambda u, cfg: imagefetch.fetch(
                               u, cfg, opener=self.opener(png()),
                               resolve=self.public),
                           spawn=jobs.append)
        pad.set("{now} look\n" + Grammar.TEXT)
        with mock.patch.object(note, "_note_snap", return_value={
                "conv_id": "c", "closed": True}):
            jobs[0]()
        self.assertTrue(events[-1]["closed"])
        self.assertEqual(events[-1]["plan"], [])


class InATurn(StageBase):
    def setUp(self):
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        for p in (mock.patch.object(config, "DATA_DIR",
                                    pathlib.Path(td.name) / "d"),
                  mock.patch.object(config, "load_config", lambda: {}),
                  mock.patch.dict(os.environ, {
                      "WISP_NOTES_DIR": td.name + "/notes"})):
            p.start()
            self.addCleanup(p.stop)

    def answer(self, reply):
        ctx = self.ctx({"agent": {}})
        started = []
        real = note.NotePad._start_fetches
        with mock.patch.object(pipeline, "ask_chat", return_value=reply), \
                mock.patch.object(pipeline.speech, "speak",
                                  return_value=None), \
                mock.patch.object(note.NotePad, "_start_fetches",
                                  lambda s, parsed, payload: started.append(
                                      payload)), \
                mock.patch.object(imagefetch, "fetch",
                                  side_effect=AssertionError("fetched")):
            stage_speak._answer(ctx)
        del real
        return ctx, started

    def test_an_image_object_becomes_a_card_with_its_source(self):
        ctx, started = self.answer(
            "This is a cat.\n::image[url=" + URL + ",alt=A cat]\n::")
        img = [o for o in started[0]["objects"]
               if o["kind"] == "image"][0]["image"]
        self.assertEqual((img["status"], img["source"]), ("loading", URL))
        self.assertNotIn("::image", ctx.reply)
        self.assertEqual(ctx.reply, "This is a cat.")

    def test_a_host_off_the_list_is_refused_aloud_and_never_fetched(self):
        ctx, started = self.answer(
            "Here you go.\n::image[url=https://evil.example.com/x.png]\n::")
        self.assertIn("evil.example.com isn't on my list", ctx.reply)
        self.assertNotIn("::image", ctx.reply)
        self.assertEqual(len(started), 1)
        img = [o for o in started[0]["objects"]
               if o["kind"] == "image"][0]["image"]
        self.assertEqual(img["status"], "refused")


if __name__ == "__main__":
    unittest.main()
