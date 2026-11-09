"""Window-text collector (companion core U2): sources, caps, privacy,
time budgets and the press-time prefetch. Hermetic: fake tree, fake cua,
fake OCR, injected clock."""
import sys
import unittest

sys.path.insert(0, ".")
from wisp import context, elementtree as et, window_text  # noqa: E402

WIN = {"class": "editor", "title": "notes.txt", "at": [0, 0],
       "size": [800, 600]}


class FakeTextTree(et.ElementTree):
    def __init__(self, texts=(), state=(et.OK, ""), tick=None):
        self._texts_in, self._state, self._tick = list(texts), state, tick

    def state(self):
        return self._state

    def texts(self):
        if self._tick:
            self._tick()
        return list(self._texts_in)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def collect(**kw):
    kw.setdefault("window", WIN)
    kw.setdefault("cfg", {})
    kw.setdefault("tree", lambda: FakeTextTree())
    kw.setdefault("cua", lambda win: "")
    kw.setdefault("which", lambda name: None)
    return window_text.collect(**kw)


class Sources(unittest.TestCase):
    def test_document_text_capped_and_deduplicated(self):
        body = "alpha line\nalpha line\n" + "x" * 9000
        r = collect(tree=lambda: FakeTextTree(["alpha line", body]))
        self.assertEqual(r.source, "atspi")
        self.assertEqual(r.text.count("alpha line"), 1)
        self.assertLessEqual(len(r.text), window_text.MAX_CHARS)

    def test_buttons_only_yields_no_atspi_text(self):
        r = collect(tree=lambda: FakeTextTree([]))
        self.assertEqual((r.source, r.text), ("none", ""))

    def test_unavailable_and_unbound_are_none(self):
        for st in (et.UNAVAILABLE, et.UNBOUND):
            r = collect(tree=lambda st=st: FakeTextTree(
                ["would be text"], state=(st, "x")))
            self.assertEqual((r.source, r.text), ("none", ""), st)

    def test_cua_used_when_atspi_empty(self):
        r = collect(cua=lambda win: "from the cua tree")
        self.assertEqual((r.source, r.text), ("cua", "from the cua tree"))

    def test_ocr_of_window_crop(self):
        seen = []
        r = collect(capture=lambda: "/fixture/shot.png",
                    ocr=lambda path: seen.append(path) or "read by ocr")
        self.assertEqual((r.source, r.text), ("ocr", "read by ocr"))
        self.assertEqual(seen, ["/fixture/shot.png"])

    def test_missing_ocr_binary_is_none(self):
        shots = []
        r = collect(capture=lambda: shots.append(1) or "/fixture/s.png")
        self.assertEqual((r.source, r.text), ("none", ""))
        self.assertEqual(shots, [])


class Guards(unittest.TestCase):
    def test_sensitive_window_is_none(self):
        called = []
        r = collect(window={"class": "1password", "title": "Vault"},
                    tree=lambda: called.append(1) or FakeTextTree(["secret"]))
        self.assertEqual((r.source, r.text), ("none", ""))
        self.assertEqual(called, [])

    def test_read_past_budget_is_none(self):
        clk = Clock()
        r = collect(clock=clk,
                    tree=lambda: FakeTextTree(
                        ["late text"], tick=lambda: setattr(clk, "t", 0.5)),
                    cua=lambda win: "must not be used")
        self.assertEqual((r.source, r.text), ("none", ""))
        self.assertGreaterEqual(r.elapsed, 0.5)

    def test_ocr_past_budget_is_none(self):
        clk = Clock()
        r = collect(clock=clk, capture=lambda: "/f.png",
                    ocr=lambda p: setattr(clk, "t", 0.9) or "late")
        self.assertEqual(r.source, "none")


class Prefetch(unittest.TestCase):
    def test_prefetched_result_reused_within_ttl(self):
        clk, calls = Clock(), []

        def gather():
            calls.append(1)
            return window_text.Result("hello", "atspi", 0.01)
        spec = context.Speculative({"window_text": gather}, ttl=5.0,
                                   clock=clk).start()
        spec._done["window_text"].wait(2)
        clk.t = 3.0
        got = spec.take("window_text", consume=False)
        self.assertEqual(got.text, "hello")
        self.assertEqual(spec.take("window_text").text, "hello")
        self.assertEqual(len(calls), 1)

    def test_gatherer_is_the_collector(self):
        g = context.window_text_gatherer({})
        self.assertTrue(callable(g))


if __name__ == "__main__":
    unittest.main()
