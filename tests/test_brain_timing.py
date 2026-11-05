"""Measured first-token time must not be inferred from a complete response."""
import io
import unittest
from unittest import mock

from wisp import brain


class TimingTruth(unittest.TestCase):
    def provider(self, kind="openai_compat"):
        return {"name": "fixture", "kind": kind, "model": "fixture",
                "base_url": "http://fixture.invalid", "key_env": ""}

    def test_complete_responses_have_latency_but_no_measured_ttft(self):
        for kind, payload in (
            ("openai_compat", {"choices": [{"message": {"content": "ok"}}]}),
            ("ollama", {"message": {"content": "ok"}}),
        ):
            with self.subTest(kind=kind), \
                 mock.patch.object(brain, "_post", return_value=payload), \
                 mock.patch.object(brain.time, "monotonic", side_effect=[10, 13]):
                result = brain._chat_one(self.provider(kind), [], None, 60)
                self.assertIsNone(result["ttft_ms"])
                self.assertEqual(result["latency_ms"], 3000)

    def test_total_latency_includes_empty_response_retry(self):
        clock = [10.0]
        responses = iter([{}, {"choices": [{"message": {"content": "ok"}}]}])

        def post(*args):
            payload = next(responses)
            clock[0] += 3 if payload else 1
            return payload

        with mock.patch.object(brain, "_post", side_effect=post), \
             mock.patch.object(brain.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(brain.time, "sleep",
                               side_effect=lambda duration: clock.__setitem__(0, clock[0] + duration)):
            result = brain._chat_one(self.provider(), [], None, 60)
        self.assertEqual(result["latency_ms"], 4050)
        self.assertIsNone(result["ttft_ms"])

    def test_empty_stream_has_no_first_token_measurement(self):
        with mock.patch.object(brain.cancel, "urlopen",
                               return_value=io.BytesIO(b"data: [DONE]\n")), \
             mock.patch.object(brain.time, "monotonic", side_effect=[10, 13]):
            result = brain._stream_one(self.provider(), [], None, 60, 5)
        self.assertIsNone(result["ttft_ms"])
        self.assertEqual(result["latency_ms"], 3000)

    def test_stream_measures_first_content_separately_from_completion(self):
        data = (b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
                b'data: [DONE]\n')
        with mock.patch.object(brain.cancel, "urlopen", return_value=io.BytesIO(data)), \
             mock.patch.object(brain.time, "monotonic", side_effect=[10, 11, 13]):
            result = brain._stream_one(self.provider(), [], None, 60, 5)
        self.assertEqual(result["ttft_ms"], 1000)
        self.assertEqual(result["latency_ms"], 3000)
