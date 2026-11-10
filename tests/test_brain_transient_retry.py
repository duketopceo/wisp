"""One retry on a transient 502/503/504 from the provider (gauntlet
20261110-032017: a lone OpenRouter 503 ended a turn). Fully faked."""
import unittest
import urllib.error
from unittest import mock

from wisp import brain


def http(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


class TransientRetry(unittest.TestCase):
    def run_attempt(self, errors):
        calls = []

        def fn(p):
            calls.append(1)
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return "ok"
        with mock.patch.object(brain.time, "sleep"):
            try:
                return brain._attempt({"name": "openrouter"}, fn), calls
            except Exception as e:
                return e, calls

    def test_503_is_retried_once(self):
        out, calls = self.run_attempt([http(503)])
        self.assertEqual((out, len(calls)), ("ok", 2))

    def test_second_503_surfaces(self):
        out, calls = self.run_attempt([http(503), http(503)])
        self.assertIsInstance(out, urllib.error.HTTPError)
        self.assertEqual(len(calls), 2)

    def test_auth_and_rate_limit_are_not_retried(self):
        for code in (401, 402, 429):
            out, calls = self.run_attempt([http(code)])
            self.assertIsInstance(out, urllib.error.HTTPError)
            self.assertEqual(len(calls), 1)

    def test_committed_stream_is_not_retried(self):
        e = http(503)
        e.committed = True
        out, calls = self.run_attempt([e])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
