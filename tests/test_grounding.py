#!/usr/bin/env python3
"""Tests for Decision-Agent UI Grounding and WordInk integration."""
import base64
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import grounding, pipeline, tools, config  # noqa: E402
from PIL import Image  # noqa: E402


class TestGrounding(unittest.TestCase):
    def setUp(self):
        # Create a small dummy image for testing
        img = Image.new("RGB", (200, 100), color=(30, 30, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self.img_b64 = base64.b64encode(buf.getvalue()).decode()

    @mock.patch("wisp.config.load_api_key", return_value="sk-test-key")
    @mock.patch("urllib.request.urlopen")
    def test_ground_element_probabilistic_centering(self, mock_urlopen, mock_key):
        # Simulate Clef/Jev returning high noul probability on patch 2 and lower on others
        mock_resp = mock.MagicMock()
        answers = {
            "p_0": {"noul": 0.15},
            "p_1": {"noul": 0.30},
            "p_2": {"noul": 0.95},
            "p_3": {"noul": 0.20},
        }
        mock_resp.read.return_value = json.dumps({"answers": answers}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        coords = grounding.ground_element(
            self.img_b64,
            target_description="monitor icon",
            region_hint="menu bar",
            power=6.0
        )
        self.assertIsNotNone(coords)
        self.assertIsInstance(coords, tuple)
        self.assertEqual(len(coords), 2)
        # Verify valid screen coordinate integers
        self.assertGreaterEqual(coords[0], 0)
        self.assertGreaterEqual(coords[1], 0)

    @mock.patch("wisp.config.load_api_key", return_value="sk-test-key")
    @mock.patch("urllib.request.urlopen")
    def test_ground_element_low_confidence_returns_none(self, mock_urlopen, mock_key):
        # All probabilities are very low (element not present)
        mock_resp = mock.MagicMock()
        answers = {
            "p_0": {"noul": 0.05},
            "p_1": {"noul": 0.10},
        }
        mock_resp.read.return_value = json.dumps({"answers": answers}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        coords = grounding.ground_element(
            self.img_b64,
            target_description="nonexistent button",
            region_hint="menu bar"
        )
        self.assertIsNone(coords)

    def test_tools_ground_registry(self):
        self.assertIn("ground", tools.REGISTRY)
        self.assertEqual(tools.risk_of("ground"), "safe")

    @mock.patch("wordink.transcribe", return_value="hello from wordink")
    def test_wordink_stt_provider(self, mock_wordink_stt):
        dummy_wav = pathlib.Path("dummy.wav")
        cfg = {"stt": {"provider": "wordink"}}
        result = pipeline.transcribe(dummy_wav, cfg)
        self.assertEqual(result, "hello from wordink")


if __name__ == "__main__":
    unittest.main()
