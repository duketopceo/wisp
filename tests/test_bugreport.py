"""B26: `wispd bugreport` carries what a maintainer needs and nothing the
user said, saw or keeps secret; and the typed-error log behind it."""
import contextlib
import io
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import bugreport as br, cli, config, deploy, errlog, trace  # noqa: E402

KEY = "sk-test-SENTINEL-bugreport-91"
WORDS = "SENTINELWORDS wire the money to account 4471"
TITLE = "SENTINELTITLE Chase - Online Banking"
FILE = "SENTINELFILE-tax-return-2025.pdf"
HOME = os.path.expanduser("~")


def events():
    return [
        {"ts": "t", "turn": "t1", "step": "transcribe", "kind": "stt",
         "ms": 3, "data": {"text": WORDS}},
        {"ts": "t", "turn": "t1", "step": "context", "kind": "thought",
         "ms": 3, "data": {"window": TITLE, "file": FILE}},
        {"ts": "t", "turn": "t1", "step": "brain_call", "kind": "brain",
         "ms": 9, "data": {"endpoint": "https://x", "key": KEY}},
        {"ts": "t", "turn": "t1", "step": WORDS, "kind": "act",
         "ms": 1, "data": {}},
    ]


def cfg():
    c = config._default_cfg_dict()
    c["stt"] = dict(c.get("stt", {}), key_env=KEY,
                    prompt=f"{WORDS} {FILE}")
    c["report"] = {"dsn": f"https://{KEY}@host/1"}
    c["selection"] = {"enabled": "false"}
    c["hotkey"] = {"mod": "SUPER", "key": "D"}
    return c


class Sandbox(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.errors = self.dir / "errors.jsonl"
        for p in (mock.patch.object(errlog, "FILE", self.errors),
                  mock.patch.object(deploy, "record_path",
                                    lambda: self.dir / "deploy.json"),
                  mock.patch("wisp.update.installed_version",
                             lambda: "v1.2.3")):
            p.start()
            self.addCleanup(p.stop)
        (self.dir / "deploy.json").write_text(json.dumps(
            {"commit": "0123456789abcdef", "ref": "v1.2.3",
             "time": "2026-10-28T01:02:03-0600"}))


class Report(Sandbox):
    def build(self, **kw):
        probe = kw.pop("probe", lambda c: {
            "jev": {"ok": True, "latency_ms": 12},
            "ollama": {"ok": False, "code": "brain_down"}})
        return br.build(cfg(), probe=probe, events=events(), **kw)

    def test_what_a_maintainer_needs_is_there(self):
        errlog.record("brain_down", RuntimeError("boom"))
        text = self.build()
        for want in ("wisp: v1.2.3", "deployed commit: 0123456789ab",
                     "jev: ok (12 ms)", "ollama: DOWN (brain_down)",
                     "brain_down (RuntimeError)", "stt/transcribe: 1",
                     "brain/brain_call: 1", "## What happened",
                     "[hotkey] key = default"):
            self.assertIn(want, text)

    def test_no_sentinel_transcript_title_file_key_or_home_path(self):
        errlog.record("internal", RuntimeError(
            f"{KEY} {WORDS} {TITLE} {FILE} {HOME}/secret"))
        text = self.build()
        for bad in (KEY, "SENTINEL", "account 4471", "Chase", "tax-return",
                    "4471"):
            self.assertNotIn(bad, text, bad)
        if HOME not in ("/", ""):
            self.assertNotIn(HOME + "/", text)

    def test_the_config_is_masked(self):
        text = self.build()
        self.assertIn("[stt] key_env = hidden", text)
        self.assertIn("[report] dsn = hidden", text)
        self.assertRegex(text, r"\[stt\] prompt = set \(\d+ chars\)")
        self.assertIn("[selection] enabled = false", text)
        self.assertIn("[agent] model = default", text)

    def test_trace_free_text_steps_are_not_listed(self):
        text = self.build()
        self.assertIn("act/other: 1", text)

    def test_a_failing_probe_does_not_fail_the_report(self):
        def boom(c):
            raise OSError("socket says " + WORDS)
        text = self.build(probe=boom)
        self.assertIn("probe: DOWN (OSError)", text)
        self.assertNotIn("SENTINEL", text)

    def test_error_count_is_bounded(self):
        for i in range(15):
            errlog.record("timeout")
        text = self.build(n_errors=3)
        self.assertEqual(len(re.findall(r"^- 20\S+ timeout", text, re.M)), 3)

    def test_long_reports_are_not_cut_off(self):
        # scrub_text caps a string at 500 characters; the report is more
        text = self.build()
        self.assertGreater(len(text), 1500)
        self.assertIn("## What happened", text)


class ErrLog(Sandbox):
    def test_entries_hold_a_code_and_a_type_never_the_message(self):
        errlog.record("brain_down", ValueError(f"{KEY} {WORDS}"))
        raw = self.errors.read_text()
        self.assertNotIn("SENTINEL", raw)
        self.assertNotIn("sk-test", raw)
        row = json.loads(raw)
        self.assertEqual((row["code"], row["exc"]),
                         ("brain_down", "ValueError"))

    def test_the_file_is_private(self):
        errlog.record("timeout")
        self.assertEqual(stat.S_IMODE(os.stat(self.errors).st_mode), 0o600)

    def test_it_is_bounded(self):
        for i in range(errlog.KEEP * 2 + 50):
            errlog.record("timeout", RuntimeError)
        n = len(self.errors.read_text().splitlines())
        self.assertLessEqual(n, errlog.KEEP * 2)
        self.assertEqual(len(errlog.recent(10)), 10)

    def test_corrupt_lines_and_missing_files_are_fine(self):
        self.assertEqual(errlog.recent(5), [])
        self.errors.write_text('{"code":"timeout"}\nnot json\n[]\n')
        self.assertEqual([e["code"] for e in errlog.recent(5)],
                         ["timeout"])
        self.assertEqual(errlog.recent(0), [])

    def test_a_pipeline_error_is_recorded(self):
        from wisp import errors_codes, pipeline
        state = mock.Mock()
        with mock.patch("wisp.report.capture"):
            pipeline._publish_error(state, TimeoutError("x"))
        rows = errlog.recent(3)
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["code"], errors_codes.CODES)


class Command(Sandbox):
    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(config, "load_config", cfg), \
                mock.patch("wisp.bugreport._probe",
                           lambda c: {}), \
                mock.patch.object(trace, "read", lambda **k: events()), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = cli.main(list(argv), host=None)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_writes_nothing_and_says_what_it_would(self):
        target = self.dir / "r.md"
        code, out, err = self.run_cmd("bugreport", "--dry-run", "--out",
                                      str(target))
        self.assertEqual(code, 0, err)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.glob("*.md")), [])
        self.assertIn("would write", out)
        self.assertRegex(out, r"\(\d+ bytes\)")
        self.assertIn("sections: version, health, errors, trace, config, "
                      "what happened", out)
        self.assertIn("nothing was written", out)

    def test_dry_run_json(self):
        code, out, _ = self.run_cmd("bugreport", "--dry-run", "--json",
                                    "--out", str(self.dir / "r.md"))
        d = json.loads(out)["data"]
        self.assertFalse(d["written"])
        self.assertGreater(d["bytes"], 500)
        self.assertEqual(d["sections"][0], "version")

    def test_it_writes_a_private_file_and_never_overwrites(self):
        target = self.dir / "r.md"
        code, out, err = self.run_cmd("bugreport", "--out", str(target))
        self.assertEqual(code, 0, err)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        text = target.read_text()
        self.assertIn("## What happened", text)
        self.assertNotIn("SENTINEL", text)
        self.assertIn("Nothing was sent", out)
        code, out, err = self.run_cmd("bugreport", "--out", str(target))
        self.assertEqual(code, 2)
        self.assertIn("exists already", err)

    def test_errors_flag_is_bounded(self):
        code, out, err = self.run_cmd("bugreport", "--errors", "999",
                                      "--dry-run")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
