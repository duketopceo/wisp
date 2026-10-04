"""Arena hygiene (W32): matrix policy, orch gate, page tokens, copy."""
import os
import pathlib
import re
import subprocess
import sys
import unittest

import copylint

ROOT = pathlib.Path(__file__).resolve().parent.parent
CL = ROOT / "scripts" / "clicklab"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CL))

import arena  # noqa: E402
import arena_policy as ap  # noqa: E402

HTML = (CL / "arena.html").read_text()
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
GROUND = ROOT / "tests" / "fixtures" / "ground" / "recorded.json"


class TestMatrixPolicy(unittest.TestCase):
    CASES = [
        (["ollama:ornith:latest"], True),
        (["mlx:ornith", "uitars:ui-tars-7b", "ollama:qwen3"], True),
        (["openrouter:x-ai/grok-4.7"], True),
        (["ollama:a", "openrouter:google/gemini-2.5-flash"], True),
        (["openrouter:anthropic/claude-sonnet-4.6"], False),
        (["openrouter:anthropic/claude-haiku"], False),
        (["openrouter:openai/gpt-5"], False),
        (["openrouter:google/gemini-2.5-pro"], False),
        (["openrouter:unknown/model"], False),
        (["openrouter:x-ai/grok-4.7",
          "openrouter:google/gemini-2.5-flash"], False),
        (["anthropic:claude-opus"], False),
        (["nocolon"], False),
        ([], False),
    ]

    def test_policy_table(self):
        for specs, ok in self.CASES:
            with self.subTest(specs=specs):
                if ok:
                    ap.validate_matrix(specs)
                else:
                    with self.assertRaises(ap.PolicyError):
                        ap.validate_matrix(specs)

    def test_prices_respect_ceiling(self):
        for spec, (i, o) in ap.HOSTED_PRICES.items():
            self.assertLessEqual(i, ap.CEILING_IN, spec)
            self.assertLessEqual(o, ap.CEILING_OUT, spec)
            self.assertEqual(ap.classify(spec), "hosted")

    def test_priced_but_premium_name_rejected(self):
        old = dict(ap.HOSTED_PRICES)
        ap.HOSTED_PRICES["openrouter:anthropic/claude-x"] = (0.1, 0.1)
        try:
            with self.assertRaises(ap.PolicyError):
                ap.classify("openrouter:anthropic/claude-x")
        finally:
            ap.HOSTED_PRICES.clear()
            ap.HOSTED_PRICES.update(old)

    def test_over_ceiling_rejected(self):
        ap.HOSTED_PRICES["openrouter:big/model"] = (3.0, 15.0)
        try:
            with self.assertRaises(ap.PolicyError):
                ap.classify("openrouter:big/model")
        finally:
            del ap.HOSTED_PRICES["openrouter:big/model"]


class TestOrchGate(unittest.TestCase):
    def test_hosted_refused_without_orch(self):
        with self.assertRaises(ap.PolicyError) as cm:
            ap.gate(["openrouter:x-ai/grok-4.7"], env={})
        self.assertIn("orch", str(cm.exception))

    def test_marker_must_be_exactly_one(self):
        with self.assertRaises(ap.PolicyError):
            ap.gate(["openrouter:x-ai/grok-4.7"],
                    env={ap.ORCH_MARKER: "true"})

    def test_hosted_allowed_with_marker(self):
        self.assertEqual(
            ap.gate(["openrouter:x-ai/grok-4.7"],
                    env={ap.ORCH_MARKER: "1"}),
            ["openrouter:x-ai/grok-4.7"])

    def test_local_allowed_without_orch(self):
        self.assertEqual(ap.gate(["ollama:ornith"], env={}), [])

    def test_premium_refused_even_via_orch(self):
        with self.assertRaises(ap.PolicyError):
            ap.gate(["openrouter:anthropic/claude-sonnet-4.6"],
                    env={ap.ORCH_MARKER: "1"})

    def test_orch_argv_needs_orch(self):
        old = os.environ.get("PATH")
        os.environ["PATH"] = "/nonexistent"
        try:
            with self.assertRaises(ap.PolicyError):
                ap.orch_argv(["python3", "x"])
        finally:
            os.environ["PATH"] = old
        self.assertEqual(ap.orch_argv(["a"], "/bin/orch"),
                         ["/bin/orch", "a"])

    def _cli(self, *args):
        env = {k: v for k, v in os.environ.items()
               if k != ap.ORCH_MARKER}
        return subprocess.run(
            [sys.executable, str(CL / "arena.py"), "--run", *args],
            env=env, capture_output=True, text=True, timeout=30)

    def test_cli_refuses_hosted_without_via_orch(self):
        r = self._cli("--models", "openrouter:x-ai/grok-4.7")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--via-orch", r.stdout)

    def test_cli_refuses_two_hosted(self):
        r = self._cli("--via-orch", "--models",
                      "openrouter:x-ai/grok-4.7,"
                      "openrouter:google/gemini-2.5-flash")
        self.assertEqual(r.returncode, 2)

    def test_cli_refuses_premium(self):
        r = self._cli("--models", "openrouter:anthropic/claude-opus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("premium", r.stdout)


class TestPage(unittest.TestCase):
    def _outside_block(self, html):
        return arena._BLOCK.sub("", html)

    def test_no_hex_outside_generated_block(self):
        self.assertEqual(HEX.findall(self._outside_block(HTML)), [])

    def test_block_is_fresh(self):
        self.assertIn(arena.token_css(), HTML)

    def test_light_dark_and_reduced_motion(self):
        self.assertIn("prefers-color-scheme: light", HTML)
        self.assertIn("prefers-reduced-motion: reduce", HTML)
        from wisp import theme
        for k in theme.TOKENS:
            self.assertIn(theme._css_name(k) + ":", HTML)

    def test_swap_tokens_replaces_block(self):
        out = arena.swap_tokens(HTML, f"{arena.BEGIN}\nX\n{arena.END}")
        self.assertNotIn("--wisp-canvas:", out)
        self.assertIn("X", out)

    def test_copy_lint(self):
        body = self._outside_block(HTML)
        text = re.sub(r"<(script|style)\b.*?</\1>", "", body, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        strings = [text] + copylint.qml_strings(
            re.search(r"<script>(.*?)</script>", HTML, re.S).group(1))
        strings += re.findall(r"<title>(.*?)</title>", HTML)
        self.assertEqual(copylint.violations(strings), [])

    def test_python_strings_copy_lint(self):
        for f in ("arena.py", "arena_policy.py"):
            src = (CL / f).read_text()
            self.assertEqual(
                copylint.violations(copylint.python_strings(src)), [], f)


class TestGroundOffline(unittest.TestCase):
    @unittest.skipUnless(GROUND.exists(), "ground fixtures not on this base")
    def test_ground_offline_exit_zero(self):
        r = subprocess.run(
            [sys.executable, str(CL / "arena.py"), "--ground-offline"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
