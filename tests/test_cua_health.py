"""W10: CuaProbe state table, doctor lines, CLI registry entries."""
import contextlib
import io
import json
import pathlib
import socket
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from wisp import health, probes_cua  # noqa: E402
from wisp.cli import registry  # noqa: E402
from cli_env import CliEnv  # noqa: E402
import shorttmp  # noqa: E402

PIN = "0.33.1"


class Rig:
    """Everything the probe touches, injected."""

    def __init__(self, **cua):
        self.td = shorttmp.TemporaryDirectory()
        self.dir = pathlib.Path(self.td.name)
        self.sock = self.dir / "cua.sock"
        self.kill = self.dir / "cua.kill"
        self.binary = "/fake/cua-driver"
        self.version = f"cua-driver {PIN}"
        self.connect_ok = True
        self.cfg = {"cua": {k: str(v) for k, v in cua.items()}}
        self.version_calls = 0

    def probe(self, pin=PIN):
        def ver(path):
            self.version_calls += 1
            return self.version
        return probes_cua.CuaProbe(
            self.cfg, pin=pin, which=lambda n: self.binary,
            socket_path=self.sock, kill_path=self.kill, version_fn=ver,
            connect_fn=lambda p: self.connect_ok)

    def up(self):
        self.sock.write_text("")

    def close(self):
        self.td.cleanup()


class States(unittest.TestCase):
    def setUp(self):
        self.r = Rig()
        self.addCleanup(self.r.close)

    def state(self, **kw):
        return self.r.probe(**kw).check()

    def test_absent(self):
        self.r.binary = None
        s = self.state()
        self.assertEqual(s["state"], "absent")
        self.assertFalse(s["ok"])
        self.assertEqual(s["code"], "cua_absent")
        self.assertIn("install", s["fix"])

    def test_installed_not_running(self):
        s = self.state()   # no socket file
        self.assertEqual(s["state"], "installed_not_running")
        self.assertFalse(s["ok"])
        self.assertEqual(s["code"], "cua_down")
        self.assertIn("systemctl --user start", s["fix"])

    def test_running(self):
        self.r.up()
        s = self.state()
        self.assertEqual((s["state"], s["ok"], s["code"]),
                         ("running", True, None))
        self.assertEqual(s["version"], PIN)

    def test_version_mismatch(self):
        self.r.up()
        self.r.version = "cua-driver 0.40.0"
        s = self.state()
        self.assertEqual(s["state"], "version_mismatch")
        self.assertFalse(s["ok"])
        self.assertEqual(s["code"], "cua_version")
        self.assertEqual((s["version"], s["pin"]), ("0.40.0", PIN))

    def test_unknown_version_is_not_a_mismatch(self):
        self.r.up()
        self.r.version = None
        self.assertEqual(self.state()["state"], "running")

    def test_no_pin_skips_version_check(self):
        self.r.up()
        self.r.version = "cua-driver 9.9.9"
        self.assertEqual(self.state(pin=None)["state"], "running")

    def test_socket_unresponsive(self):
        self.r.up()
        self.r.connect_ok = False
        s = self.state()
        self.assertEqual(s["state"], "socket_unresponsive")
        self.assertFalse(s["ok"])
        self.assertEqual(s["code"], "cua_unresponsive")

    def test_kill_switch_file(self):
        self.r.up()
        self.r.kill.write_text("")
        s = self.state()
        self.assertEqual(s["state"], "kill_switch_on")
        self.assertTrue(s["ok"])    # intentional, not a fault
        self.assertTrue(s["kill"])

    def test_kill_switch_config(self):
        self.r.cfg = {"cua": {"kill_switch": "true"}}
        self.r.up()
        self.assertEqual(self.state()["state"], "kill_switch_on")

    def test_dry_run(self):
        self.r.cfg = {"cua": {"dry_run": "true"}}
        self.r.up()
        s = self.state()
        self.assertEqual((s["state"], s["ok"]), ("dry_run", True))

    def test_kill_beats_dry_run(self):
        self.r.cfg = {"cua": {"dry_run": "true", "kill_switch": "true"}}
        self.r.up()
        self.assertEqual(self.state()["state"], "kill_switch_on")

    def test_driver_fault_beats_modes(self):
        self.r.cfg = {"cua": {"kill_switch": "true"}}
        self.r.connect_ok = False
        self.r.up()
        self.assertEqual(self.state()["state"], "socket_unresponsive")

    def test_never_raises(self):
        p = probes_cua.CuaProbe(
            {}, pin=PIN, which=lambda n: 1 / 0, socket_path=self.r.sock)
        self.assertEqual(p.check()["state"], "absent")

    def test_version_cached_per_binary(self):
        self.r.up()
        p = self.r.probe()
        p.check()
        p.check()
        self.assertEqual(self.r.version_calls, 1)

    def test_real_unix_socket_connect(self):
        self.r.up()
        self.r.sock.unlink()
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(self.r.sock))
        srv.listen(1)
        self.addCleanup(srv.close)
        p = probes_cua.CuaProbe(
            {}, pin=PIN, which=lambda n: "/x", socket_path=self.r.sock,
            kill_path=self.r.kill, version_fn=lambda p: f"v {PIN}")
        self.assertEqual(p.check()["state"], "running")


class Registration(unittest.TestCase):
    def test_hook_shape_for_health_registry(self):
        r = Rig()
        self.addCleanup(r.close)
        r.up()
        reg = health.HealthRegistry({})
        probes_cua.register(reg, r.cfg, probe=r.probe(), force=True)
        row = reg.probe("cua")
        self.assertTrue(row["ok"])
        r.connect_ok = False
        self.assertEqual(reg.probe("cua")["code"], "cua_unresponsive")

    def test_not_registered_when_absent_and_not_selected(self):
        reg = health.HealthRegistry({})
        r = Rig()
        self.addCleanup(r.close)
        r.binary = None
        probes_cua.register(reg, {"pointer": {"backend": "auto"}},
                            probe=r.probe())
        self.assertEqual(reg.probe("cua"), {})

    def test_registered_when_backend_cua_even_if_absent(self):
        reg = health.HealthRegistry({})
        r = Rig()
        self.addCleanup(r.close)
        r.binary = None
        probes_cua.register(reg, {"pointer": {"backend": "cua"}},
                            probe=r.probe())
        self.assertEqual(reg.probe("cua")["code"], "cua_absent")


class DoctorLines(unittest.TestCase):
    def rows(self, r, cfg=None):
        from wisp.cli import diagnose
        c = {"pointer": {"backend": "auto"}}
        c.update(cfg or {})
        c.setdefault("cua", r.cfg["cua"])
        secs = diagnose.doctor_sections(
            c, cua_probe=r.probe())
        return {x["name"]: x for x in
                next(s for s in secs if s["name"] == "pointer")["rows"]
                for x in [x]}

    def test_running_lines(self):
        r = Rig()
        self.addCleanup(r.close)
        r.up()
        rows = self.rows(r)
        self.assertIn("running", rows["cua driver"]["value"])
        self.assertTrue(rows["cua driver"]["ok"])
        self.assertIn(PIN, rows["cua version"]["value"])
        self.assertIn("kill off", rows["cua safety"]["value"])
        self.assertIn("cua.jsonl", rows["cua audit log"]["value"])

    def test_kill_and_dry_run_visible(self):
        r = Rig(dry_run="true")
        self.addCleanup(r.close)
        r.up()
        r.kill.write_text("")
        v = self.rows(r)["cua safety"]["value"]
        self.assertIn("KILL SWITCH ON", v)
        self.assertIn("dry-run on", v)

    def test_absent_ok_unless_backend_cua(self):
        r = Rig()
        self.addCleanup(r.close)
        r.binary = None
        self.assertTrue(self.rows(r)["cua driver"]["ok"])
        row = self.rows(r, {"pointer": {"backend": "cua"}})["cua driver"]
        self.assertFalse(row["ok"])
        self.assertIn("install --cua", row["value"])

    def test_version_mismatch_row_fails(self):
        r = Rig()
        self.addCleanup(r.close)
        r.up()
        r.version = "cua-driver 1.0.0"
        rows = self.rows(r)
        self.assertFalse(rows["cua version"]["ok"])
        self.assertIn("1.0.0", rows["cua version"]["value"])


class CliEntries(unittest.TestCase):
    def test_registered_and_help_budget(self):
        cmds = registry.commands()
        for p in ("cua kill", "cua resume", "cua log"):
            self.assertIn(p, cmds)
        import subprocess
        out = subprocess.run([sys.executable, str(HERE.parent / "wispd"),
                              "--help"], capture_output=True, text=True,
                             env={"COLUMNS": "80", "PATH": "/usr/bin"})
        self.assertLess(len(out.stdout.splitlines()), 60)

    def test_daemon_install_has_cua_flag(self):
        with CliEnv() as env:
            code, out, err = env.run(["daemon", "install", "--help"])
            self.assertIn("--cua", out)
            self.assertIn("--dry-run", out)

    def test_kill_resume_roundtrip(self):
        with CliEnv() as env:
            kf = env.home / "run" / "wisp" / "cua.kill"
            code, out, err = env.run(["cua", "kill", "--json"])
            self.assertEqual(code, 0, err)
            self.assertTrue(kf.exists())
            self.assertTrue(json.loads(out)["data"]["armed"])
            code, out, err = env.run(["cua", "resume", "--json"])
            self.assertEqual(code, 0, err)
            self.assertFalse(kf.exists())
            self.assertFalse(json.loads(out)["data"]["armed"])

    def test_resume_warns_when_config_kill_set(self):
        with CliEnv() as env:
            cfg = env.home / ".config" / "wisp" / "config.toml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text('[cua]\nkill_switch = "true"\n')
            code, out, err = env.run(["cua", "resume", "--json"])
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["data"]["config_kill"])

    def test_log_audit_reads_jsonl_not_journal(self):
        with CliEnv() as env:
            env.shim("journalctl")
            f = env.home / ".local" / "state" / "wisp" / "cua.jsonl"
            f.parent.mkdir(parents=True)
            f.write_text("".join(
                json.dumps({"n": i, "tool": "click"}) + "\n"
                for i in range(5)))
            code, out, err = env.run(["cua", "log", "--audit", "-n", "2",
                                      "--json"])
            self.assertEqual(code, 0, err)
            lines = json.loads(out)["data"]["lines"]
            self.assertEqual(len(lines), 2)
            self.assertIn('"n": 4', lines[-1])
            self.assertEqual(env.shim_calls(), [])

    def test_log_audit_missing_file_is_empty(self):
        with CliEnv() as env:
            code, out, err = env.run(["cua", "log", "--audit", "--json"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["data"]["lines"], [])

    def test_cua_status_includes_probe_state(self):
        with CliEnv() as env:
            code, out, err = env.run(["cua", "status", "--json"])
            self.assertEqual(json.loads(out)["data"]["state"], "absent")


if __name__ == "__main__":
    unittest.main()
