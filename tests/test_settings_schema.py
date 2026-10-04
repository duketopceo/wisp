#!/usr/bin/env python3
"""W28: wisp/settings_schema.py is the one settings table.

It generates the CLI `config` help and validation, the daemon-side check
in config.set_config, and shell-plugin/lib/settings_schema.js (the Panel
field table and validators). These tests pin each consumer to the schema
so they cannot drift.
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "assets"))

import jsnode  # noqa: E402
from cli_env import CliEnv  # noqa: E402

from wisp import config, settings_schema as S  # noqa: E402
import gen_settings  # noqa: E402

HELP_DIR = HERE / "golden" / "cli_help"

# (key, value, code): the daemon, CLI and Panel must all agree
TABLE = [
    ("budget.daily_usd", "2.50", ""),
    ("budget.daily_usd", "", ""),
    ("budget.daily_usd", " 3 ", ""),
    ("budget.daily_usd", "two", "number"),
    ("budget.daily_usd", "-1", "number"),
    ("budget.daily_usd", "1e3", "number"),
    ("budget.daily_usd", "999999", "range"),
    ("budget.monthly_usd", "5#", "chars"),
    ("pointer.mode", "drive", ""),
    ("pointer.mode", "fly", "choice"),
    ("cua.dry_run", "true", ""),
    ("cua.dry_run", "yes", "choice"),
    ("cua.confirm", "always", ""),
    ("cua.max_per_turn", "12", ""),
    ("cua.max_per_turn", "0", "range"),
    ("cua.max_per_turn", "900", "range"),
    ("cua.max_clicks_per_min", "x", "number"),
    ("cua.max_clicks_per_min", "601", "range"),
    ("cua.max_clicks_per_min", "600", ""),
    ("cua.kill_switch", 'tr"ue', "chars"),
    ("cua.kill_switch", "a\nb", "chars"),
    ("cua.kill_switch", "a\\b", "chars"),
    # not in the schema: writable (provider sections), but the Panel
    # cannot edit it
    ("keys.submap", "x", ""),
]


class TestSchemaShape(unittest.TestCase):
    def test_keys_unique_and_sectioned(self):
        keys = [f.key for f in S.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        for f in S.FIELDS:
            self.assertEqual(f.key.split(".")[0], f.section, f.key)
            self.assertTrue(f.description, f.key)
            self.assertIn(f.kind, ("usd", "int", "bool", "choice"), f.key)
            self.assertIn(f.widget, ("number", "toggle", "choice"), f.key)

    def test_defaults_pass_their_own_validator(self):
        for f in S.FIELDS:
            self.assertEqual(S.problem(f.key, f.default), "", f.key)

    def test_defaults_match_default_config(self):
        import re
        for f in S.FIELDS:
            sec, _, name = f.key.partition(".")
            m = re.search(r"(?ms)^\[%s\]\n(.*?)(?=^\[|\Z)" % re.escape(sec),
                          config.DEFAULT_CONFIG)
            self.assertIsNotNone(m, f.key)
            mm = re.search(r'(?m)^%s\s*=\s*"?([^"\n#]*?)"?\s*(?:#.*)?$'
                           % re.escape(name), m.group(1))
            self.assertIsNotNone(mm, f.key)
            self.assertEqual(mm.group(1).strip(), f.default, f.key)

    def test_panel_fields_are_the_w22_set(self):
        self.assertEqual(
            [f.key for f in S.FIELDS if f.panel],
            ["budget.daily_usd", "budget.monthly_usd", "pointer.mode",
             "cua.dry_run", "cua.kill_switch", "cua.confirm",
             "cua.max_clicks_per_min", "cua.max_per_turn"])


class TestValidation(unittest.TestCase):
    def test_problem_table(self):
        for key, val, code in TABLE:
            self.assertEqual(S.problem(key, val), code, (key, val))

    def test_messages_are_sentences_naming_the_key(self):
        for key, val, code in TABLE:
            if not code or code == "unknown":
                continue
            msg = S.message(key, val)
            self.assertTrue(msg.endswith("."), msg)
            self.assertIn(key, msg)
        self.assertIn("between 1 and 200",
                      S.message("cua.max_per_turn", "900"))
        self.assertIn("guide, drive, auto",
                      S.message("pointer.mode", "fly"))

    def test_set_config_validates_in_the_daemon_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = pathlib.Path(d)
            with mock.patch.object(config, "CFG_DIR", cfg), \
                    mock.patch.object(config, "CFG_FILE", cfg / "c.toml"):
                for key, val, code in TABLE:
                    sec, _, name = key.rpartition(".")
                    if code in ("", "unknown"):
                        # unknown keys stay writable (provider sections)
                        config.set_config(sec, name, val.strip())
                        continue
                    with self.assertRaises(ValueError, msg=(key, val)):
                        config.set_config(sec, name, val)
                bad = (cfg / "c.toml").read_text()
                self.assertNotIn("fly", bad)
                self.assertNotIn("900", bad)

    def test_cli_rejects_with_e_bad_config(self):
        with CliEnv() as env:
            for key, val, code in TABLE:
                if code in ("", "unknown"):
                    continue
                c, out, err = env.run(["config", "set", key, val])
                self.assertEqual(c, 1, (key, val, err))
                self.assertTrue(err.startswith("E_BAD_CONFIG: "), err)
            self.assertFalse((env.home / ".config" / "wisp"
                              / "config.toml").exists())
            c, out, err = env.run(["config", "set", "cua.max_per_turn", "7"])
            self.assertEqual(c, 0, err)

    def test_cli_rejects_before_the_daemon_hears_it(self):
        with CliEnv(daemon=True) as env:
            c, out, err = env.run(["config", "set", "pointer.mode", "fly"])
            self.assertEqual(c, 1)
            self.assertIn("E_BAD_CONFIG", err)
            self.assertEqual(env.ipc, [])


class TestCliHelp(unittest.TestCase):
    def test_help_table_lists_every_key(self):
        text = S.help_table()
        for f in S.FIELDS:
            self.assertIn(f.key, text)
        self.assertIn("default", text)

    def test_config_set_help_carries_the_table(self):
        with CliEnv() as env:
            c, out, err = env.run(["config", "set", "--help"])
            self.assertEqual(c, 0, err)
            for f in S.FIELDS:
                self.assertIn(f.key, out)

    def test_config_keys_matches_golden_and_json(self):
        with CliEnv() as env:
            c, out, err = env.run(["config", "keys"])
            self.assertEqual(c, 0, err)
            self.assertEqual(out.rstrip("\n"), S.help_table())
            c, out, err = env.run(["config", "keys", "--json"])
            rows = json.loads(out)["data"]["keys"]
            self.assertEqual([r["key"] for r in rows],
                             [f.key for f in S.FIELDS])
            self.assertEqual(rows[0], S.FIELDS[0].as_dict())


class TestGeneratedJs(unittest.TestCase):
    def test_generated_file_is_current(self):
        self.assertEqual(gen_settings.main(["--check"]), 0)

    def test_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "settings_schema.js"
            with mock.patch.object(gen_settings, "OUT", out), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gen_settings.main(["--check"]), 1)
                gen_settings.main([])
                self.assertEqual(gen_settings.main(["--check"]), 0)
                out.write_text(out.read_text().replace("guide", "gxide", 1))
                self.assertEqual(gen_settings.main(["--check"]), 1)

    def test_js_table_matches_schema(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        fields = jsnode.call("Sch.FIELDS", Sch="settings_schema")
        want = [f.panel_dict() for f in S.FIELDS if f.panel]
        self.assertEqual(fields, want)
        allkeys = jsnode.call("Sch.KEYS", Sch="settings_schema")
        self.assertEqual(allkeys, [f.key for f in S.FIELDS])

    def test_js_validate_agrees_with_python(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        for key, val, code in TABLE:
            want = "" if code == "" else "ui.err." + code
            if key not in {f.key for f in S.FIELDS if f.panel} \
                    and code == "":
                want = "ui.err.unknown"
            got = jsnode.call(
                f"Sch.validate({json.dumps(key)}, {json.dumps(val)})",
                Sch="settings_schema")
            self.assertEqual(got, want, (key, val))

    def test_every_error_code_has_a_copy_string(self):
        from wisp import copy as wcopy
        for code in S.ERROR_CODES:
            self.assertIn("ui.err." + code, wcopy.STRINGS)
        for f in S.FIELDS:
            if f.panel:
                self.assertIn(f.label, wcopy.STRINGS, f.key)


if __name__ == "__main__":
    unittest.main()
