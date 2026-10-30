"""Transcripts, replies and traces are private to the user."""
import importlib.machinery
import importlib.util
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp import config, private, session, stage_speak, trace  # noqa: E402


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = pathlib.Path(td.name)
        old = os.umask(0o022)         # the permissive default that leaked
        self.addCleanup(os.umask, old)


class TestWriters(Base):
    def test_session_log_is_0600_in_a_0700_folder(self):
        p = self.root / "data" / "session.jsonl"
        session.append_turn("what is my password", "answer", "it is x",
                            path=p)
        self.assertEqual(mode(p), 0o600)
        self.assertEqual(mode(p.parent), 0o700)

    def test_decision_log_is_0600(self):
        p = self.root / "data" / "decisions.jsonl"
        stage_speak.log_decision({"transcript": "private words"},
                                 log_file=p)
        self.assertEqual(mode(p), 0o600)

    def test_trace_is_0600_in_a_0700_folder(self):
        p = self.root / "data" / "trace.jsonl"
        with mock.patch.object(trace, "TRACE_FILE", p), \
                mock.patch.object(trace, "_cfg_flag", lambda: True):
            trace.emit("t1", "transcribe", "stt", {"text": "secret"})
        self.assertEqual(mode(p), 0o600)
        self.assertEqual(mode(p.parent), 0o700)

    def test_an_existing_folder_keeps_its_mode(self):
        d = self.root / "shared"
        d.mkdir(mode=0o755)
        d.chmod(0o755)
        with private.open_append(d / "x.log") as f:
            f.write("x")
        self.assertEqual(mode(d), 0o755)


class TestHarden(Base):
    def test_older_world_readable_files_are_tightened(self):
        data, cfg = self.root / "data", self.root / "cfg"
        for d in (data / "tasks", cfg):
            d.mkdir(parents=True)
        files = [data / "session.jsonl", data / "trace.jsonl",
                 data / "tasks" / "a.log", cfg / ".env"]
        for f in files:
            f.write_text("x")
            f.chmod(0o644)
        data.chmod(0o755)
        (data / "tasks").chmod(0o755)
        link = data / "link"
        link.symlink_to(files[0])
        changed = private.harden([data, cfg])
        self.assertGreaterEqual(changed, 6)
        self.assertEqual(mode(data), 0o700)
        self.assertEqual(mode(data / "tasks"), 0o700)
        for f in files:
            self.assertEqual(mode(f), 0o600, f)

    def test_harden_never_widens_and_skips_missing_folders(self):
        d = self.root / "d"
        d.mkdir()
        f = d / "ro"
        f.write_text("x")
        f.chmod(0o400)
        private.harden([d, self.root / "nope", None])
        self.assertEqual(mode(f), 0o400)

    def test_symlinked_root_is_left_alone(self):
        real = self.root / "real"
        real.mkdir()
        real.chmod(0o755)
        link = self.root / "link"
        link.symlink_to(real)
        private.harden([link])
        self.assertEqual(mode(real), 0o755)


class TestDaemonAndUnit(unittest.TestCase):
    def test_the_unit_sets_a_private_umask(self):
        unit = (ROOT / "scripts" / "units" / "wispd.service").read_text()
        self.assertIn("UMask=0077", unit)

    def test_the_daemon_hardens_before_it_serves(self):
        src = (ROOT / "wispd").read_text()
        a = src.index("def run_daemon")
        body = src[a:src.index("\ndef ", a + 10)]
        self.assertLess(body.index("_apply_private()"),
                        body.index("skills.seed()"))


def load_wispd():
    loader = importlib.machinery.SourceFileLoader("wispd_priv",
                                                  str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_priv", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestApply(Base):
    def setUp(self):
        super().setUp()
        self.data, self.cfg = self.root / "data", self.root / "cfg"

    def test_apply_sets_umask_and_creates_private_folders(self):
        private.apply([self.data, self.cfg])
        self.assertEqual(os.umask(0o077), 0o077)
        self.assertEqual(mode(self.data), 0o700)
        self.assertEqual(mode(self.cfg), 0o700)

    def test_apply_tightens_a_traversable_config_folder(self):
        self.cfg.mkdir()
        self.cfg.chmod(0o755)
        (self.cfg / "utterance.wav").write_bytes(b"x")
        (self.cfg / "utterance.wav").chmod(0o644)
        private.apply([self.data, self.cfg])
        self.assertEqual(mode(self.cfg), 0o700)
        self.assertEqual(mode(self.cfg / "utterance.wav"), 0o600)


class TestNoDaemonTrigger(Base):
    """The trigger fallback records without a daemon; it must run the
    same private setup run_daemon does before any audio is written."""

    def test_fallback_records_privately_under_a_permissive_umask(self):
        w = load_wispd()
        data, cfg = self.root / "data", self.root / "cfg"
        cfg.mkdir()
        cfg.chmod(0o755)                 # traversable, as in the finding
        seen = {}

        def fake_run_listen(_cfg, _st, *a, **k):
            seen["umask"] = os.umask(0)
            os.umask(seen["umask"])
            wav = cfg / "utterance.wav"  # what the recorder creates
            with open(wav, "wb") as f:
                f.write(b"audio")
            seen["wav"] = wav
            return 0

        with mock.patch.object(config, "DATA_DIR", data), \
                mock.patch.object(config, "CFG_DIR", cfg), \
                mock.patch.object(w.ipc, "send",
                                  side_effect=ConnectionError), \
                mock.patch.object(w.state_mod, "StateBus"), \
                mock.patch.object(w.pipeline, "run_listen",
                                  side_effect=fake_run_listen):
            self.assertEqual(w.cmd_trigger({}, ""), 0)
        self.assertEqual(seen["umask"], 0o077)
        self.assertEqual(mode(cfg), 0o700)
        self.assertEqual(mode(seen["wav"]), 0o600)

    def test_fallback_still_runs_when_hardening_fails(self):
        w = load_wispd()
        with mock.patch.object(private, "apply",
                               side_effect=OSError("denied")), \
                mock.patch.object(w, "dlog"), \
                mock.patch.object(w.ipc, "send",
                                  side_effect=ConnectionError), \
                mock.patch.object(w.state_mod, "StateBus"), \
                mock.patch.object(w.pipeline, "run_listen",
                                  return_value=0) as run:
            self.assertEqual(w.cmd_trigger({}, ""), 0)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
