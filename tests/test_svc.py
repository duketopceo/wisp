#!/usr/bin/env python3
"""W29: service hygiene. Unit-file lint, `wispd install` units under a fake
HOME with a stub systemctl, sd_notify against a fake NOTIFY_SOCKET, and
`wispd doctor` service rows against fake systemctl/journalctl/ps. Nothing
here touches the live user manager."""
import configparser
import json
import os
import pathlib
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import svc  # noqa: E402

UNITS = ROOT / "scripts" / "units"
LLAMAS = ["llama-local", "llama-jev", "llama-uitars"]
ALL = LLAMAS + ["jev-shim", "wispd"]


def parse(path: pathlib.Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=True, interpolation=None,
                                   delimiters=("=",))
    cp.optionxform = str
    cp.read_string(path.read_text())
    return cp


class TestUnitLint(unittest.TestCase):
    def test_templates_exist(self):
        for n in ALL:
            self.assertTrue((UNITS / f"{n}.service").is_file(), n)

    def test_required_keys(self):
        for n in ALL:
            cp = parse(UNITS / f"{n}.service")
            self.assertTrue({"Unit", "Service", "Install"} <=
                            set(cp.sections()), n)
            self.assertTrue(cp["Unit"]["Description"], n)
            self.assertTrue(cp["Service"]["ExecStart"], n)
            self.assertEqual(cp["Service"]["Restart"], "on-failure", n)
            self.assertEqual(cp["Install"]["WantedBy"], "default.target")
            self.assertEqual(svc.lint_unit((UNITS / f"{n}.service")
                                           .read_text(), n), [], n)

    def test_llama_units_leave_oomd_reach(self):
        for n in LLAMAS + ["jev-shim"]:
            s = parse(UNITS / f"{n}.service")["Service"]
            self.assertEqual(s["Slice"], "session.slice", n)
            self.assertEqual(s["ManagedOOMPreference"], "omit", n)

    def test_start_limit_relaxed_with_backoff(self):
        for n in ALL:
            cp = parse(UNITS / f"{n}.service")
            self.assertEqual(cp["Unit"]["StartLimitIntervalSec"], "900", n)
            self.assertGreaterEqual(int(cp["Unit"]["StartLimitBurst"]), 20)
            s = cp["Service"]
            self.assertGreaterEqual(int(s["RestartSec"]), 2, n)
            self.assertEqual(s["RestartSteps"], "5", n)
            self.assertEqual(s["RestartMaxDelaySec"], "60", n)

    def test_wispd_notify_watchdog(self):
        s = parse(UNITS / "wispd.service")["Service"]
        self.assertEqual(s["Type"], "notify")
        self.assertEqual(s["NotifyAccess"], "main")
        self.assertEqual(s["WatchdogSec"], "60")
        self.assertIn("wispd daemon", s["ExecStart"])
        self.assertEqual(s["Slice"], "session.slice")

    def test_lint_flags_problems(self):
        bad = ("[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n"
               "Slice=app.slice\nWatchdogSec=60\n[Install]\n"
               "WantedBy=default.target\n")
        probs = " ".join(svc.lint_unit(bad, "x"))
        self.assertIn("Slice", probs)
        self.assertIn("Type=notify", probs)
        self.assertIn("StartLimit", probs)
        self.assertTrue(svc.lint_unit("[Service]\nbogus line\n", "y"))

    @unittest.skipUnless(__import__("shutil").which("systemd-analyze"),
                         "systemd-analyze missing")
    def test_systemd_analyze_verify_exit_recorded(self):
        # read-only; the exit code is logged for the PR, only crashes fail
        r = subprocess.run(
            ["systemd-analyze", "--user", "verify",
             *map(str, sorted(UNITS.glob("*.service")))],
            capture_output=True, text=True, timeout=60)
        print("systemd-analyze --user verify exit", r.returncode,
              r.stderr.strip()[:400], file=sys.stderr)
        self.assertLess(r.returncode, 127)


def stub_systemctl(bindir: pathlib.Path, show: dict | None = None):
    """Executable stub: records argv, answers `show` from JSON."""
    log = bindir / "systemctl.log"
    cfg = bindir / "systemctl.json"
    cfg.write_text(json.dumps(show or {}))
    p = bindir / "systemctl"
    p.write_text(f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
open({str(log)!r}, "a").write(json.dumps(argv) + "\\n")
cfg = json.load(open({str(cfg)!r}))
if "show" in argv:
    unit = argv[-1]
    props = cfg.get(unit)
    if props is None:
        print("LoadState=not-found"); sys.exit(0)
    for k, v in props.items():
        print(f"{{k}}={{v}}")
sys.exit(0)
""")
    p.chmod(0o755)
    return log


class Env:
    def __enter__(self):
        self._td = shorttmp.TemporaryDirectory()
        self.root = pathlib.Path(self._td.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.unit_dir = self.home / ".config" / "systemd" / "user"
        self.patch = mock.patch.dict(os.environ, {
            "PATH": str(self.bin) + os.pathsep + "/usr/bin:/bin"})
        self.patch.start()
        return self

    def __exit__(self, *a):
        self.patch.stop()
        self._td.cleanup()

    def calls(self):
        p = self.bin / "systemctl.log"
        return [json.loads(l) for l in p.read_text().splitlines()] \
            if p.exists() else []

    def fake_exes(self):
        """llama wrappers present so their units are installable."""
        d = self.home / ".local" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        for n in ("llama-local", "llama-jev", "llama-uitars"):
            (d / n).write_text("#!/bin/sh\n")
            (d / n).chmod(0o755)
        b = self.home / "bin"
        b.mkdir(exist_ok=True)
        (b / "jev-shim").write_text("#!/bin/sh\n")


class TestInstall(unittest.TestCase):
    def test_fresh_install_idempotent(self):
        with Env() as e:
            stub_systemctl(e.bin)
            e.fake_exes()
            acts = svc.install_units(e.home)
            self.assertEqual({a["name"] for a in acts}, set(ALL))
            self.assertTrue(all(a["action"] == "new" for a in acts), acts)
            for n in ALL:
                self.assertEqual(
                    (e.unit_dir / f"{n}.service").read_text(),
                    svc.render(n, e.home))
            self.assertIn(["--user", "daemon-reload"], e.calls())
            e.calls().clear()
            before = {p.name for p in e.unit_dir.iterdir()}
            n_calls = len(e.calls())
            acts = svc.install_units(e.home)
            self.assertTrue(all(a["action"] == "unchanged" for a in acts))
            self.assertEqual({p.name for p in e.unit_dir.iterdir()}, before)
            self.assertEqual(len(e.calls()), n_calls)   # no reload

    def test_modified_unit_backed_up(self):
        with Env() as e:
            stub_systemctl(e.bin)
            e.fake_exes()
            e.unit_dir.mkdir(parents=True)
            live = e.unit_dir / "llama-local.service"
            live.write_text("[Service]\nExecStart=/mine\n")
            acts = {a["name"]: a for a in svc.install_units(e.home)}
            a = acts["llama-local"]
            self.assertEqual(a["action"], "update")
            bak = pathlib.Path(a["backup"])
            self.assertEqual(bak.read_text(),
                             "[Service]\nExecStart=/mine\n")
            self.assertEqual(live.read_text(),
                             svc.render("llama-local", e.home))
            # second run: nothing to back up again
            again = {a["name"]: a for a in svc.install_units(e.home)}
            self.assertEqual(again["llama-local"]["action"], "unchanged")
            self.assertEqual(len(list(e.unit_dir.glob(
                "llama-local.service.bak-*"))), 1)

    def test_dry_run_writes_nothing(self):
        with Env() as e:
            stub_systemctl(e.bin)
            e.fake_exes()
            e.unit_dir.mkdir(parents=True)
            live = e.unit_dir / "wispd.service"
            live.write_text("old\n")
            acts = svc.install_units(e.home, dry_run=True)
            self.assertEqual({a["name"]: a["action"] for a in acts}[
                "wispd"], "update")
            self.assertEqual(live.read_text(), "old\n")
            self.assertEqual([p.name for p in e.unit_dir.iterdir()],
                             ["wispd.service"])
            self.assertEqual(e.calls(), [])

    def test_skips_units_whose_program_is_missing(self):
        with Env() as e:
            stub_systemctl(e.bin)
            acts = {a["name"]: a for a in svc.install_units(e.home)}
            self.assertEqual(acts["llama-local"]["action"], "skip")
            self.assertEqual(acts["wispd"]["action"], "new")
            self.assertFalse((e.unit_dir / "llama-local.service").exists())

    def test_never_enables_or_restarts(self):
        with Env() as e:
            stub_systemctl(e.bin)
            e.fake_exes()
            svc.install_units(e.home)
            verbs = {c[1] for c in e.calls() if len(c) > 1}
            self.assertEqual(verbs, {"daemon-reload"})


class TestNotify(unittest.TestCase):
    def sock(self, td):
        path = os.path.join(td, "notify.sock")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(path)
        s.settimeout(3)
        self.addCleanup(s.close)
        return s, path

    def test_noop_when_unset(self):
        self.assertFalse(svc.notify("READY=1", environ={}))

    def test_ready_and_watchdog_cadence(self):
        with shorttmp.TemporaryDirectory() as td:
            s, path = self.sock(td)
            env = {"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "600000"}
            self.assertTrue(svc.notify("READY=1", environ=env))
            self.assertEqual(s.recv(256), b"READY=1")
            self.assertLess(svc.watchdog_interval(env), 0.3)   # < 0.6s/2
            stop = threading.Event()
            wd = svc.Watchdog(stop, lambda: True, environ=env)
            wd.start()
            t0, stamps = time.monotonic(), []
            while len(stamps) < 3:
                self.assertEqual(s.recv(256), b"WATCHDOG=1")
                stamps.append(time.monotonic())
            stop.set()
            wd.join()
            gaps = [b - a for a, b in zip(stamps, stamps[1:])]
            self.assertTrue(all(g < 0.3 for g in gaps), gaps)

    def test_no_ping_when_unhealthy(self):
        with shorttmp.TemporaryDirectory() as td:
            s, path = self.sock(td)
            s.settimeout(0.5)
            env = {"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "300000"}
            stop = threading.Event()
            wd = svc.Watchdog(stop, lambda: False, environ=env)
            wd.start()
            with self.assertRaises(socket.timeout):
                s.recv(256)
            stop.set()
            wd.join()

    def test_abstract_socket(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        name = f"\0wisp-test-{os.getpid()}"
        s.bind(name)
        s.settimeout(2)
        self.addCleanup(s.close)
        env = {"NOTIFY_SOCKET": "@" + name[1:]}
        self.assertTrue(svc.notify("READY=1", environ=env))
        self.assertEqual(s.recv(64), b"READY=1")

    def test_default_interval_without_env(self):
        self.assertEqual(svc.watchdog_interval({}), None)


class DoctorEnv(Env):
    def __enter__(self):
        super().__enter__()
        self.show = {}
        return self

    def setup(self, show, journal="", ps=""):
        stub_systemctl(self.bin, show)
        (self.bin / "journalctl").write_text(
            f"#!/bin/sh\ncat <<'EOF'\n{journal}\nEOF\n")
        (self.bin / "ps").write_text(f"#!/bin/sh\ncat <<'EOF'\n{ps}\nEOF\n")
        for n in ("journalctl", "ps"):
            (self.bin / n).chmod(0o755)


def rows(res):
    return {r["name"]: r for r in res}


def ok_unit(slice_="session.slice"):
    return {"LoadState": "loaded", "ActiveState": "active",
            "SubState": "running", "Result": "success",
            "UnitFileState": "enabled", "Slice": slice_,
            "ManagedOOMPreference": "omit", "NRestarts": "0"}


class TestDoctor(unittest.TestCase):
    def test_healthy(self):
        with DoctorEnv() as e:
            e.setup({"llama-local.service": ok_unit()})
            r = rows(svc.doctor_rows())
            row = r["llama-local"]
            self.assertTrue(row["ok"], row)
            self.assertIn("active", row["value"])
            self.assertIn("session.slice", row["value"])
            self.assertIn("oomd=omit", row["value"])
            self.assertTrue(r["voxtype alsa"]["ok"])
            self.assertNotIn("llama-jev", r)    # not-found: not reported

    def test_oomd_killed(self):
        with DoctorEnv() as e:
            u = ok_unit("app.slice")
            u.update(ActiveState="failed", SubState="failed",
                     Result="oom-kill", ManagedOOMPreference="none")
            e.setup({"llama-local.service": u})
            row = rows(svc.doctor_rows())["llama-local"]
            self.assertFalse(row["ok"])
            self.assertIn("killed by systemd-oomd", row["value"])
            self.assertIn("app.slice", row["value"])
            self.assertIn("wispd install", row["value"])

    def test_dead_enabled_and_start_limit(self):
        with DoctorEnv() as e:
            a = ok_unit()
            a.update(ActiveState="inactive", SubState="dead")
            b = ok_unit()
            b.update(ActiveState="failed", SubState="failed",
                     Result="start-limit-hit")
            e.setup({"llama-jev.service": a, "llama-uitars.service": b})
            r = rows(svc.doctor_rows())
            self.assertFalse(r["llama-jev"]["ok"])
            self.assertIn("enabled but dead", r["llama-jev"]["value"])
            self.assertIn("reset-failed", r["llama-uitars"]["value"])

    def test_disabled_dead_is_fine(self):
        with DoctorEnv() as e:
            a = ok_unit()
            a.update(ActiveState="inactive", SubState="dead",
                     UnitFileState="disabled")
            e.setup({"llama-uitars.service": a})
            self.assertTrue(rows(svc.doctor_rows())["llama-uitars"]["ok"])

    def test_voxtype_spin_by_journal(self):
        with DoctorEnv() as e:
            line = "voxtype[1]: alsa::poll() returned POLLERR"
            e.setup({}, journal="\n".join([line] * 150))
            row = rows(svc.doctor_rows())["voxtype alsa"]
            self.assertFalse(row["ok"])
            self.assertIn("POLLERR", row["value"])
            self.assertIn("systemctl --user restart voxtype", row["value"])

    def test_voxtype_spin_by_cpu(self):
        with DoctorEnv() as e:
            e.setup({}, ps=" 99.5 cpal_alsa_out\n  0.1 voxtype\n")
            row = rows(svc.doctor_rows())["voxtype alsa"]
            self.assertFalse(row["ok"])
            self.assertIn("restart voxtype", row["value"])

    def test_voxtype_quiet(self):
        with DoctorEnv() as e:
            e.setup({}, journal="started\nready", ps=" 0.2 voxtype\n")
            self.assertTrue(rows(svc.doctor_rows())["voxtype alsa"]["ok"])

    def test_no_systemctl_no_rows(self):
        with DoctorEnv() as e:
            with mock.patch.dict(os.environ, {"PATH": str(e.root)}):
                self.assertEqual(svc.doctor_rows(), [])


class TestCli(unittest.TestCase):
    def test_install_units_dry_run_cli(self):
        from cli_env import CliEnv
        with CliEnv() as env:
            code, out, err = env.run(["install", "--units", "--dry-run",
                                      "--json"])
            self.assertEqual(code, 0, err)
            d = json.loads(out)["data"]
            self.assertFalse(d["installed"])
            self.assertEqual({a["name"]: a["action"]
                              for a in d["units"]}["wispd"], "new")
            self.assertFalse((env.home / ".config" / "systemd").exists())

    def test_dry_run_alone_prints_the_plan(self):
        # W27 made plain `install --dry-run` a valid plan-only run
        from cli_env import CliEnv
        with CliEnv() as env:
            code, out, err = env.run(["install", "--dry-run"])
            self.assertEqual(code, 0, err)

    def test_doctor_services_section(self):
        from cli_env import CliEnv
        with CliEnv() as env:
            stub_systemctl(env.home / "bin", {
                "llama-local.service": dict(
                    ok_unit("app.slice"), ActiveState="failed",
                    SubState="failed", Result="oom-kill")})
            code, out, err = env.run(["doctor", "--json"])
            j = json.loads(out)
            self.assertEqual(code, 4)
            sec = {s["name"]: s for s in j["data"]["sections"]}["services"]
            self.assertIn("killed by systemd-oomd",
                          sec["rows"][0]["value"])


if __name__ == "__main__":
    unittest.main()
