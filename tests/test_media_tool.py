"""TLY-430: Omarchy-native media tool — native controls before any
pixel click or key press."""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from wisp import delivery, policy, tools  # noqa: E402
from wisp.tools import media  # noqa: E402


class Runner:
    def __init__(self, have=("omarchy-shell", "omarchy-audio-output-volume"),
                 rc=0):
        self.have, self.rc, self.calls = set(have), rc, []

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.have else None

    def run(self, argv):
        self.calls.append(list(argv))
        return self.rc, ""

    def __enter__(self):
        self._p = [mock.patch.object(media, "_which", self.which),
                   mock.patch.object(media, "_run", self.run)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


class TestOmarchyNative(unittest.TestCase):
    def test_command_per_arg(self):
        want = {
            "play_pause": ["omarchy-shell", "media", "playPause"],
            "next": ["omarchy-shell", "media", "next"],
            "previous": ["omarchy-shell", "media", "previous"],
            "volume_up": ["omarchy-audio-output-volume", "raise"],
            "volume_down": ["omarchy-audio-output-volume", "lower"],
            "mute": ["omarchy-audio-output-volume", "mute-toggle"],
        }
        for arg, argv in want.items():
            with self.subTest(arg=arg), Runner() as r:
                out = media.media(arg)
                self.assertTrue(out.startswith("MEDIA"), out)
                self.assertEqual(r.calls, [argv])

    def test_pause_and_play_map_to_toggle_and_say_so(self):
        for arg in ("pause", "play"):
            with self.subTest(arg=arg), Runner() as r:
                out = media.media(arg)
                self.assertEqual(r.calls,
                                 [["omarchy-shell", "media", "playPause"]])
                self.assertIn("toggle", out.lower())

    def test_arg_is_normalised(self):
        with Runner() as r:
            media.media(" Play-Pause ")
            media.media("volume up")
        self.assertEqual(r.calls[0][-1], "playPause")
        self.assertEqual(r.calls[1][-1], "raise")

    def test_unknown_arg_skips(self):
        with Runner() as r:
            out = media.media("rewind")
        self.assertTrue(out.startswith("SKIP"))
        self.assertEqual(r.calls, [])

    def test_nonzero_exit_skips(self):
        with Runner(rc=1):
            self.assertTrue(media.media("next").startswith("SKIP"))


class TestFallback(unittest.TestCase):
    def test_playerctl_when_omarchy_missing(self):
        with Runner(have=("playerctl",)) as r:
            self.assertTrue(media.media("pause").startswith("MEDIA"))
            media.media("next")
        self.assertEqual(r.calls[0], ["playerctl", "pause"])
        self.assertEqual(r.calls[1], ["playerctl", "next"])

    def test_nothing_installed_skips_with_message(self):
        with Runner(have=()) as r:
            out = media.media("play_pause")
        self.assertTrue(out.startswith("SKIP"))
        self.assertIn("omarchy-shell", out)
        self.assertEqual(r.calls, [])

    def test_mute_without_omarchy_skips(self):
        with Runner(have=("playerctl",)) as r:
            self.assertTrue(media.media("mute").startswith("SKIP"))
        self.assertEqual(r.calls, [])


class TestRegistered(unittest.TestCase):
    def test_registered_safe_t0(self):
        e = tools.REGISTRY["media"]
        self.assertIs(e[0], media.media)
        self.assertEqual(e[1], "safe")
        self.assertEqual(tools.meta_of("media")["tier"], "T0")
        self.assertEqual(policy.declared_tier("media"), "T0")

    def test_background_delivery(self):
        self.assertEqual(delivery.planned("media", {}), "background")

    def test_act_prompt_points_at_media(self):
        from wisp import act
        self.assertIn("media tool", act.SYSTEM)


if __name__ == "__main__":
    unittest.main()
