"""Offline regressions for verified release-grounding review feedback."""
import types
import tomllib
import unittest
from unittest import mock

from wisp import grounding as g
from wisp import brain


class ResizeFallback(unittest.TestCase):
    def test_unmodified_bytes_keep_original_dimensions_on_resize_fallback(self):
        shot = g.Shot("synthetic-full-resolution-bytes", 1920, 1080)
        broken_image = types.SimpleNamespace(
            open=mock.Mock(side_effect=ValueError("synthetic decoder failure")))
        for pillow_available in (False, True):
            with self.subTest(pillow_available=pillow_available), \
                    mock.patch.object(g, "_PIL_AVAILABLE", pillow_available), \
                    mock.patch.object(g, "Image", broken_image, create=True):
                self.assertEqual(shot.letterboxed(),
                                 g.Letterbox.stretched(shot.b64, 1920, 1080,
                                                       1920, 1080))


def context(cfg=None):
    cfg = cfg or {"ground": {"providers": "jev"}}
    return g._Ctx(target="Save", region_hint="", cfg=cfg, st=g.settings(cfg),
                  shot=g.Shot("synthetic-pixels", 1920, 1080), timeout=5.0)


class FallbackBudget(unittest.TestCase):
    def test_jev_fallback_only_gets_unspent_absolute_budget(self):
        for spent in (3.0, 5.0, 6.0):
            for down in (False, True):
                clock = types.SimpleNamespace(now=0.0)

                def vlm(*_args):
                    clock.now += spent
                    if down:
                        raise g.ProviderDown("synthetic timeout")
                    return None

                with self.subTest(spent=spent, down=down), \
                        mock.patch.object(g.time, "monotonic",
                                          side_effect=lambda: clock.now), \
                        mock.patch.object(g, "_vlm_locate", side_effect=vlm), \
                        mock.patch.object(g, "_jev_locate",
                                          return_value=None) as jev:
                    self.assertIsNone(g._jev(context()))
                if spent < 5.0:
                    self.assertAlmostEqual(jev.call_args.args[-1], 5.0 - spent)
                else:
                    jev.assert_not_called()

    def test_compatibility_jev_vlm_result_retains_actual_provider_source(self):
        with mock.patch.object(g, "_vlm_locate", return_value=(100, 120, 0.9)), \
                mock.patch.object(g, "_jev_locate") as patches:
            target = g._jev(context())
        self.assertEqual(target.source, "vlm")
        patches.assert_not_called()

    def test_unsupported_compatibility_vlm_point_can_fall_through_to_jev(self):
        with mock.patch.object(g, "_vlm_locate", return_value=(100, 120, 0.0)), \
                mock.patch.object(g, "_jev_locate",
                                  return_value=(110, 130, 0.8)) as patches:
            candidate = g._jev(context())
        self.assertEqual((candidate.x, candidate.y, candidate.source),
                         (110, 130, "jev"))
        patches.assert_called_once()

    def test_vlm_result_arriving_after_jev_deadline_is_not_accepted(self):
        clock = types.SimpleNamespace(now=0.0)

        def late_vlm(*_args):
            clock.now += 6.0
            return 100, 120, 0.9

        with mock.patch.object(g.time, "monotonic",
                               side_effect=lambda: clock.now), \
                mock.patch.object(g, "_vlm_locate", side_effect=late_vlm), \
                mock.patch.object(g, "_jev_locate") as patches:
            result = g._jev(context())
        self.assertIsNone(result)
        patches.assert_not_called()

    def test_vlm_preprocessing_spends_budget_without_a_one_second_floor(self):
        for spent in (0.3, 0.6):
            clock = types.SimpleNamespace(now=0.0)
            shot = context().shot

            def resize():
                clock.now += spent
                return g.Letterbox.stretched("synthetic", 1280, 800,
                                             1920, 1080)

            with self.subTest(spent=spent), \
                    mock.patch.object(g.time, "monotonic",
                                      side_effect=lambda: clock.now), \
                    mock.patch.object(shot, "letterboxed",
                                      side_effect=resize), \
                    mock.patch.object(brain, "chat",
                                      return_value={"content": "NONE"}) as chat:
                self.assertIsNone(g._vlm_locate(shot, "Save", timeout=0.5))
                if spent < 0.5:
                    self.assertAlmostEqual(chat.call_args.kwargs["timeout"],
                                           0.5 - spent)
                else:
                    chat.assert_not_called()

    def test_jev_patch_preprocessing_uses_the_same_remaining_deadline(self):
        clock = types.SimpleNamespace(now=0.0)

        class FakeImage:
            size = (36, 36)

            def crop(self, _box):
                return self

            def save(self, buffer, **_kwargs):
                clock.now += 3.0
                buffer.write(b"synthetic-crop")

        image = types.SimpleNamespace(open=lambda _buffer: FakeImage())
        with mock.patch.object(g, "_PIL_AVAILABLE", True), \
                mock.patch.object(g, "Image", image, create=True), \
                mock.patch.object(g.time, "monotonic",
                                  side_effect=lambda: clock.now), \
                mock.patch.object(g.config, "load_api_key", return_value=""), \
                mock.patch.object(g, "_post_json", return_value=None) as post:
            self.assertIsNone(g._jev_locate(
                "eA==", "Save", "", 6.0, None, {}, 5.0))
        self.assertAlmostEqual(post.call_args.args[2], 2.0)


class ProviderOrder(unittest.TestCase):
    def test_first_install_config_uses_the_same_provider_order(self):
        from wisp import config
        self.assertEqual(
            g.settings(tomllib.loads(config.DEFAULT_CONFIG))["providers"],
            ["control", "a11y", "vlm", "jev"])

    def test_default_keeps_real_elements_first_then_vlm_before_local_pixels(self):
        self.assertEqual(g.settings({})["providers"],
                         ["control", "a11y", "vlm", "jev"])
        self.assertEqual(g.settings({"local": {"enabled": "true"}})["providers"],
                         ["control", "a11y", "vlm", "uitars", "jev"])

    def test_explicit_vlm_provider_is_not_repeated_inside_jev(self):
        cfg = {"ground": {"providers": "control,a11y,vlm,uitars,jev"}}
        with mock.patch.object(g, "_vlm_locate", return_value=None) as vlm, \
                mock.patch.object(g, "_jev_locate",
                                  return_value=(100, 120, 0.8)) as patches:
            candidate = g._jev(context(cfg))
        self.assertEqual(candidate.source, "jev")
        patches.assert_called_once()
        vlm.assert_not_called()


SAME = g.Letterbox.stretched("synthetic", 1920, 1080, 1920, 1080)


class VlmTargetSupport(unittest.TestCase):
    def test_prompt_does_not_request_the_unsupported_bare_coordinate_form(self):
        shot = context().shot
        with mock.patch.object(shot, "letterboxed",
                               return_value=SAME), \
                mock.patch.object(brain, "chat", return_value={
                    "content": "NONE"}) as chat:
            self.assertIsNone(g._vlm_locate(shot, "Save"))
        prompt = chat.call_args.args[0][0]["content"][0]["text"]
        # one POINT tag naming the target, with explicit <x>,<y> slots
        # (never the bare literal template, which models echo back)
        self.assertIn("[POINT:<x>,<y>:Save]", prompt)
        self.assertNotIn("[POINT:x,y:Save]", prompt)
        self.assertNotIn("or `(x,y)`", prompt)
        self.assertIn("ambiguous", prompt)

    def test_in_bounds_coordinates_without_unique_target_support_stay_low(self):
        replies = ("(100,120)", "[POINT:100,120:Other button]",
                   "Maybe Save is here: [POINT:100,120:Save]",
                   "[POINT:100,120:Save] [POINT:200,240:Save]")
        for text in replies:
            shot = context().shot
            with self.subTest(reply=text), \
                    mock.patch.object(shot, "letterboxed",
                                      return_value=SAME), \
                    mock.patch.object(brain, "chat", return_value={"content": text}):
                result = g._vlm_locate(shot, "Save")
            self.assertIsNotNone(result)
            self.assertEqual(result[:2], (100, 120))
            self.assertLess(result[2], g.settings({})["min_conf"])

    def test_single_exact_target_mark_keeps_scaled_point_and_support(self):
        shot = context().shot
        with mock.patch.object(shot, "letterboxed",
                               return_value=g.Letterbox.stretched(
                                   "synthetic", 960, 540, 1920, 1080)), \
                mock.patch.object(brain, "chat", return_value={
                    "content": "[POINT:100,120:Save]"}):
            result = g._vlm_locate(shot, "Save")
        self.assertEqual(result[:2], (200, 240))
        self.assertGreaterEqual(result[2], g.settings({})["min_conf"])
