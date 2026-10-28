"""B34: the capped trial and the CLI-backed brain are built, off by default,
and leave the key path unchanged."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "trial_proxy"))
from wisp import brain, clibrain, config, errors_codes, trial  # noqa: E402
import proxy  # noqa: E402

TOKEN = "wt_" + "ab" * 16
MSGS = [{"role": "user", "content": "hi"}]
BODY = {"model": proxy.MODELS[0], "messages": MSGS}
AUTH = {"Authorization": f"Bearer {TOKEN}"}
REAL_KEY = "sk-or-REAL-SECRET"


class Off(unittest.TestCase):
    def test_everything_is_off_in_the_shipped_defaults(self):
        self.assertEqual(trial.url({}), "")
        self.assertEqual(trial.url({"trial": {"enabled": "true", "url": ""}}), "")
        self.assertEqual(trial.url({"trial": {"enabled": "false",
                                              "url": "https://x.example"}}), "")
        self.assertFalse(clibrain.enabled({}))
        self.assertIn('[trial]\n', config.DEFAULT_CONFIG)
        self.assertIn('[clibrain]\n', config.DEFAULT_CONFIG)

    def test_only_https_or_loopback_urls_count(self):
        on = lambda u: trial.url({"trial": {"enabled": "true", "url": u}})
        self.assertEqual(on("https://t.example/"), "https://t.example")
        self.assertEqual(on("http://127.0.0.1:8787"), "http://127.0.0.1:8787")
        self.assertEqual(on("http://t.example"), "")
        self.assertEqual(on("ftp://t.example"), "")

    def test_the_key_path_is_unchanged(self):
        cfg = {"brain": {"default": "openrouter:m/x"}}
        p = brain.provider(cfg)
        self.assertEqual((p["name"], p["base_url"], p["key_env"], p["paid"]),
                         ("openrouter", "https://openrouter.ai/api/v1",
                          "OPENROUTER_API_KEY", True))

    def test_a_trial_brain_while_off_says_so_and_calls_nothing(self):
        cfg = {"brain": {"default": "trial:m/x"}}
        with mock.patch.object(brain, "_post") as post:
            with self.assertRaises(errors_codes.WispError) as cm:
                brain.chat(MSGS, cfg)
        post.assert_not_called()
        self.assertIn("trial' is off", str(cm.exception))


class TrialClient(unittest.TestCase):
    def test_the_token_is_random_private_and_not_a_key(self):
        f = pathlib.Path(tempfile.mkdtemp()) / "t"
        t = trial.token(f)
        self.assertRegex(t, r"\Awt_[0-9a-f]{32}\Z")
        self.assertEqual(trial.token(f), t, "stable per install")
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("sk-", t)

    def test_requests_carry_the_token_and_no_image(self):
        cfg = {"brain": {"default": "trial:m/x"},
               "trial": {"enabled": "true", "url": "https://t.example"}}
        sent = {}

        def post(url, headers, body, timeout=60):
            sent.update(url=url, headers=headers, body=body)
            return {"choices": [{"message": {"content": "ok"}}]}
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "what is this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
        f = pathlib.Path(tempfile.mkdtemp()) / "t"
        with mock.patch.object(brain, "_post", post), \
                mock.patch.object(trial, "TOKEN_FILE", f):
            res = brain.chat(msgs, cfg)
        self.assertEqual(res["content"], "ok")
        self.assertEqual(sent["url"], "https://t.example/chat/completions")
        self.assertTrue(sent["headers"]["Authorization"].startswith("Bearer wt_"))
        self.assertNotIn("image", json.dumps(sent["body"]))
        self.assertNotIn(REAL_KEY, json.dumps(sent))

    def test_a_cap_reply_becomes_the_add_your_keys_line(self):
        import urllib.error
        e = urllib.error.HTTPError("u", 429, "cap", {}, None)
        self.assertTrue(trial.limit_reached(e))
        self.assertIn("Add your own keys",
                      brain._describe({"name": "trial"}, e))


class Proxy(unittest.TestCase):
    def setUp(self):
        self.store = proxy.Store()
        self.calls = []

    def fwd(self, body):
        self.calls.append(body)
        return {"choices": [{"message": {"content": "hi"}}]}

    def call(self, n=1, token=TOKEN, ip="1.1.1.1", now=1_700_000_000.0,
             limits=None, body=BODY, headers=None):
        out = None
        for _ in range(n):
            out = proxy.handle(headers or {"Authorization": f"Bearer {token}"},
                               body, ip, self.store, self.fwd, now=now,
                               limits=limits)
        return out

    def test_the_n_plus_one_call_is_refused_and_never_forwarded(self):
        lim = {"token_day": 3}
        self.assertEqual(self.call(3, limits=lim)[0], 200)
        status, body = self.call(1, limits=lim)
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["code"], "trial_cap")
        self.assertEqual(len(self.calls), 3)

    def test_the_total_cap_outlives_the_day(self):
        lim = {"token_total": 2, "token_day": 10}
        self.call(1, limits=lim, now=1_700_000_000.0)
        self.call(1, limits=lim, now=1_700_100_000.0)
        self.assertEqual(self.call(1, limits=lim, now=1_700_200_000.0)[0], 429)

    def test_the_address_cap_stops_fresh_tokens(self):
        lim = {"ip_day": 2, "token_day": 10}
        self.call(1, token="wt_" + "01" * 16, limits=lim)
        self.call(1, token="wt_" + "02" * 16, limits=lim)
        self.assertEqual(self.call(1, token="wt_" + "03" * 16, limits=lim)[0], 429)

    def test_the_global_dollar_ceiling_is_a_hard_stop(self):
        lim = {"global_day_usd": 0.006, "call_usd": 0.002, "ip_day": 99}
        for i in range(3):
            self.assertEqual(self.call(1, token="wt_" + f"{i:02x}" * 16,
                                       ip=f"9.9.9.{i}", limits=lim)[0], 200)
        self.assertEqual(self.call(1, token="wt_" + "ff" * 16, ip="9.9.9.9",
                                   limits=lim)[0], 429)

    def test_bad_tokens_models_and_the_kill_switch(self):
        self.assertEqual(self.call(token="sk-or-real")[0], 401)
        self.assertEqual(self.call(headers={"X": "1"})[0], 401)
        self.assertEqual(self.call(body={"model": "gpt-x", "messages": []})[0], 400)
        s, _ = proxy.handle(AUTH, BODY, "1.1.1.1", self.store, self.fwd, off=True)
        self.assertEqual(s, 503)
        self.assertEqual(self.calls, [])

    def test_forwarded_requests_are_clamped_and_text_only(self):
        body = {"model": proxy.MODELS[0], "max_tokens": 99999,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "q"},
                    {"type": "image_url", "image_url": {"url": "data:AAAA"}}]}]}
        self.call(body=body)
        sent = self.calls[0]
        self.assertEqual(sent["max_tokens"], proxy.MAX_TOKENS)
        self.assertNotIn("image", json.dumps(sent))

    def test_the_token_reveals_no_real_key(self):
        with mock.patch.dict(os.environ, {"TRIAL_UPSTREAM_KEY": REAL_KEY}):
            self.assertNotIn(REAL_KEY, trial.token(
                pathlib.Path(tempfile.mkdtemp()) / "t"))
        self.assertNotIn(REAL_KEY, json.dumps(self.call()[1]))


class CliBrain(unittest.TestCase):
    CFG = {"clibrain": {"enabled": "true"}}

    def p(self, name="claude"):
        return {"name": "cli", "model": name}

    def run_cli(self, name="claude", cfg=None, stdout="the answer", rc=0,
                which=lambda b: "/usr/bin/" + b, msgs=MSGS):
        seen = {}

        def runner(argv, **kw):
            seen.update(argv=argv, **kw)
            return subprocess.CompletedProcess(argv, rc, stdout, "")
        res = clibrain.chat(self.p(name), msgs, cfg or self.CFG,
                            runner=runner, which=which)
        return res, seen

    def test_it_answers_through_the_users_cli_with_the_prompt_on_stdin(self):
        res, seen = self.run_cli()
        self.assertEqual(res["content"], "the answer")
        self.assertEqual(seen["argv"], ["claude", "-p"])
        self.assertIn("hi", seen["input"])
        self.assertNotIn("hi", " ".join(seen["argv"]), "not in the process list")

    def test_codex_uses_exec(self):
        _r, seen = self.run_cli("codex")
        self.assertEqual(seen["argv"][:2], ["codex", "exec"])

    def test_no_credential_file_is_read(self):
        home = pathlib.Path.home()
        touched = []
        real_open = open

        def spy(file, *a, **k):
            if any(s in str(file) for s in (".claude", ".codex", "auth.json",
                                            ".credentials")):
                touched.append(str(file))
            return real_open(file, *a, **k)
        with mock.patch("builtins.open", spy), \
                mock.patch.object(pathlib.Path, "read_text",
                                  lambda self, *a, **k: touched.append(str(self))
                                  if any(s in str(self) for s in
                                         (".claude", ".codex", "auth.json"))
                                  else ""):
            self.run_cli()
        self.assertEqual(touched, [])
        self.assertTrue(home)

    def test_wisp_held_keys_are_scrubbed_from_the_child(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": REAL_KEY,
                                          "PATH": os.environ.get("PATH", "")}):
            cfg = {"clibrain": {"enabled": "true"}}
            _r, seen = self.run_cli(cfg=cfg)
        self.assertNotIn("OPENROUTER_API_KEY", seen["env"])
        self.assertNotIn(REAL_KEY, json.dumps(seen["env"]))

    def test_a_missing_cli_gives_the_existing_missing_key_error(self):
        with self.assertRaises(errors_codes.WispError) as cm:
            self.run_cli(which=lambda b: None)
        self.assertEqual(cm.exception.code, "key_missing")
        self.assertIn("run wispd onboard", cm.exception.public)

    def test_off_gives_the_same_error_and_runs_nothing(self):
        ran = []
        with self.assertRaises(errors_codes.WispError) as cm:
            clibrain.chat(self.p(), MSGS, {}, runner=lambda *a, **k: ran.append(1))
        self.assertEqual(cm.exception.code, "key_missing")
        self.assertEqual(ran, [])

    def test_unknown_cli_and_failures(self):
        with self.assertRaises(errors_codes.WispError):
            self.run_cli("rm")
        with self.assertRaises(errors_codes.WispError) as cm:
            self.run_cli(rc=1, stdout="")
        self.assertEqual(cm.exception.code, "brain_down")

    def test_images_never_reach_the_cli(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
        _r, seen = self.run_cli(msgs=msgs)
        self.assertNotIn("AAAA", seen["input"])
        self.assertIn("look", seen["input"])

    def test_through_the_brain_chain(self):
        cfg = {"brain": {"default": "cli:claude"}, **self.CFG}

        def runner(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, "via chain", "")
        with mock.patch("wisp.cancel.run", runner), \
                mock.patch("shutil.which", lambda b: "/usr/bin/" + b):
            res = brain.chat(MSGS, cfg)
        self.assertEqual((res["content"], res["provider"]), ("via chain", "cli"))


if __name__ == "__main__":
    unittest.main()
