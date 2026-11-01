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
    ("brain.router", "act", ""),
    ("pointer.mode", "drive", ""),
    ("pointer.mode", "fly", "choice"),
    ("cua.dry_run", "true", ""),
    ("cua.dry_run", "yes", "choice"),
    ("cua.confirm", "always", ""),
    ("cua.delivery", "pointer", ""),
    ("cua.delivery", "sneaky", "choice"),
    ("cua.max_per_turn", "12", ""),
    ("cua.max_per_turn", "0", "range"),
    ("cua.max_per_turn", "900", "range"),
    ("cua.max_clicks_per_min", "x", "number"),
    ("cua.max_clicks_per_min", "601", "range"),
    ("cua.max_clicks_per_min", "600", ""),
    ("agent.autonomy", "guided", ""),
    ("agent.autonomy", "always_ask", ""),
    ("agent.autonomy", "yolo", "choice"),
    ("hotkey.mod", "SUPER", ""),
    ("hotkey.mod", "SUPER ALT", "format"),
    ("hotkey.key", "D", ""),
    ("hotkey.key", "D E", "format"),
    ("brain.default", "ollama:lfm2-vl", ""),
    ("brain.default", "openrouter:meta-llama/llama-4-maverick", ""),
    ("brain.default", "just-a-name", "format"),
    ("brain.default", "a:b,trailing", "format"),
    ("brain.default", "a:b c", "format"),
    ("brain.default", 'a:b"c', "chars"),
    ("brain.default", "a:b#c", "chars"),
    ("brain.default", "a:b\\c", "chars"),
    ("brain.default", "a:b\nc", "chars"),
    ("brain.fallback", "", ""),
    ("brain.fallback", "mlx:ornith, ollama:ornith", ""),
    ("brain.fallback", "mlx:ornith,", "format"),
    ("brain.first_token_s", "3", ""),
    ("brain.first_token_s", "0", "range"),
    ("brain.first_token_s", "61", "range"),
    ("brain.agent_runtime", "codex", ""),
    ("brain.agent_runtime", "emacs", "choice"),
    ("keys.submap", "x", "choice"),
    ("cua.kill_switch", 'tr"ue', "chars"),
    ("cua.kill_switch", "a\nb", "chars"),
    ("cua.kill_switch", "a\\b", "chars"),
    # not in the schema: writable (provider sections), but the Panel
    # cannot edit it
    ("whisper_cpp.model", "x", ""),
]


class TestSchemaShape(unittest.TestCase):
    def test_unconfigured_pointer_selection_does_not_impersonate_explicit_guide(self):
        self.assertEqual(S.field("pointer.mode").default, "auto")

    def test_router_schema_does_not_offer_retired_decision_lane(self):
        self.assertEqual(S.problem("brain.router", "jev"), "choice")
        field = next(f for f in S.FIELDS if f.key == "brain.router")
        self.assertEqual(field.choices, ("act", "chat", "off"))

    def test_private_weekly_recap_is_declared_and_off_by_default(self):
        field = next((f for f in S.FIELDS if f.key == "growth.weekly_recap"), None)
        self.assertIsNotNone(field)
        self.assertEqual((field.kind, field.default, field.section, field.quick),
                         ("bool", "false", "growth", False))
        self.assertEqual(config._default_cfg_dict()["growth"]["weekly_recap"],
                         "false")
        self.assertIn('[growth]\nweekly_recap = "false"', config.DEFAULT_CONFIG)

    def test_keys_unique_and_sectioned(self):
        keys = [f.key for f in S.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        for f in S.FIELDS:
            self.assertEqual(f.key.split(".")[0], f.section, f.key)
            self.assertTrue(f.description, f.key)
            self.assertIn(f.kind, S.KINDS, f.key)
            self.assertIn(f.widget, ("number", "toggle", "choice", "text",
                                     "status"), f.key)

    def test_router_accepts_act_and_rejects_unknown(self):
        self.assertEqual(S.problem("brain.router", "act"), "")
        self.assertEqual(S.problem("brain.router", "bogus"), "choice")

    def test_local_enabled_is_a_validated_bool(self):
        self.assertEqual(S.field("local.enabled").default, "false")
        self.assertEqual(S.problem("local.enabled", "true"), "")
        self.assertEqual(S.problem("local.enabled", "tru"), "choice")

    def test_keys_submap_is_a_daemon_only_bool(self):
        f = S.field("keys.submap")
        self.assertFalse(f.quick)
        self.assertEqual(S.problem("keys.submap", "false"), "")
        self.assertEqual(S.problem("keys.submap", "x"), "choice")

    def test_defaults_pass_their_own_validator(self):
        for f in S.FIELDS:
            self.assertEqual(S.problem(f.key, f.default), "", f.key)

    def test_defaults_match_default_config(self):
        import re
        import tomllib
        parsed = tomllib.loads(config.DEFAULT_CONFIG)
        # These documented fallbacks must remain absent from persisted defaults:
        # budget preserves its legacy alias, pointer preserves explicit choice.
        inherited = {"budget.daily_usd", "pointer.mode"}
        for f in S.FIELDS:
            sec, _, name = f.key.partition(".")
            self.assertEqual(name in parsed.get(sec, {}), f.key not in inherited,
                             f.key)
            m = re.search(r"(?ms)^\[%s\]\n(.*?)(?=^\[|\Z)" % re.escape(sec),
                          config.DEFAULT_CONFIG)
            self.assertIsNotNone(m, f.key)
            lead = "(?:# )?"
            mm = re.search(r'(?m)^' + lead + r'%s\s*=\s*"?([^"\n#]*?)"?\s*(?:#.*)?$'
                           % re.escape(name), m.group(1))
            self.assertIsNotNone(mm, f.key)
            self.assertEqual(mm.group(1).strip(), f.default, f.key)

    def test_quick_fields_are_the_w22_set(self):
        self.assertEqual(
            [f.key for f in S.FIELDS if f.quick],
            ["budget.daily_usd", "budget.monthly_usd", "pointer.mode",
             "cua.dry_run", "cua.kill_switch", "cua.confirm",
             "cua.delivery", "cua.max_clicks_per_min",
             "cua.max_per_turn", "agent.autonomy", "dictation.mode",
             "voice.captions", "voice.enabled", "voice.tts_voice"])


class TestUiMetadata(unittest.TestCase):
    """Category, label, help and unit on every key, shared by the
    settings window, `config keys` and the Panel."""

    def test_every_field_has_a_known_category(self):
        for f in S.FIELDS:
            self.assertIn(f.category, S.CATEGORIES, f.key)
        self.assertEqual(set(S._CATEGORY), set(S.KEYS))
        # every category has at least one key, so no empty sidebar page
        self.assertEqual({f.category for f in S.FIELDS}, set(S.CATEGORIES))

    def test_every_field_has_label_and_help_copy(self):
        from wisp import copy as wcopy
        for f in S.FIELDS:
            self.assertIn(f.label_key, wcopy.STRINGS, f.key)
            self.assertIn(f.help_key, wcopy.STRINGS, f.key)
            self.assertTrue(wcopy.STRINGS[f.help_key].endswith("."), f.key)
        for c in S.CATEGORIES:
            self.assertIn(f"set.cat.{c}", wcopy.STRINGS)

    def test_number_fields_carry_a_unit_where_one_applies(self):
        self.assertEqual(S.field("budget.daily_usd").unit, "USD")
        self.assertEqual(S.field("cua.timeout_ms").unit, "ms")
        self.assertEqual(S.field("pointer.mode").unit, "")

    def test_quick_replaces_panel(self):
        self.assertFalse(hasattr(S.Field, "panel"))
        self.assertFalse(hasattr(S, "panel_fields"))

    def test_unit_and_category_tables_name_real_keys(self):
        self.assertLessEqual(set(S._UNIT), set(S.KEYS))
        self.assertEqual(set(S._CATEGORY), set(S.KEYS))

    def test_hybrid_model_keys_are_declared_with_no_new_daemon_keys(self):
        """The keys the daemon already reads for the answer model chain
        (hosted OpenRouter default, local models optional) are editable."""
        for key in ("brain.default", "brain.fallback", "brain.allow_paid",
                    "brain.first_token_s", "brain.agent_runtime",
                    "local.enabled", "brain.router"):
            self.assertEqual(S.field(key).category, "models"
                             if key != "brain.agent_runtime" else "agents")
        self.assertEqual(S.field("brain.default").default,
                         "openrouter:meta-llama/llama-4-maverick")
        self.assertEqual(S.field("local.enabled").default, "false")

    def test_text_field_accepts_a_model_id_and_refuses_toml_breakers(self):
        for ok in ("ollama:lfm2-vl", "lmstudio:liquid/lfm2-vl-1.6b"):
            self.assertEqual(S.problem("brain.default", ok), "", ok)
        for ch in ('"', "\\", "#", "\n"):
            self.assertEqual(S.problem("brain.default", f"a:b{ch}c"),
                             "chars", repr(ch))

    def test_secret_field_has_no_value_and_refuses_writes(self):
        sec = S.Field("keys.example_secret", "secret", "hunter2",
                      "A stored credential", category="models")
        self.assertEqual(sec.widget, "status")
        d = sec.as_dict()
        self.assertEqual(d["default"], "")
        self.assertNotIn("hunter2", json.dumps(d))
        js = sec.js_dict()
        self.assertNotIn("default", js)
        self.assertNotIn("hunter2", json.dumps(js))
        with mock.patch.dict(S._BY_KEY, {sec.key: sec}):
            self.assertEqual(S.problem(sec.key, "anything"), "unknown")
            self.assertIn("secret", S.message(sec.key, "anything"))

    def test_config_keys_groups_by_category_in_sidebar_order(self):
        order = [f.category for f in S.ordered()]
        rank = [S.CATEGORIES.index(c) for c in order]
        self.assertEqual(rank, sorted(rank))
        self.assertEqual(sorted(f.key for f in S.ordered()),
                         sorted(S.KEYS))
        heads = [ln[:-1] for ln in S.help_table().splitlines()
                 if not ln.startswith(" ") and ln.endswith(":")][1:]
        self.assertEqual(heads, list(S.CATEGORIES))


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
                # the rejected cua.max_per_turn value; other keys may default to 900
                self.assertNotRegex(bad, r"(?m)^max_per_turn\s*=\s*\"?900")

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
                             [f.key for f in S.ordered()])
            self.assertEqual(rows[0], S.ordered()[0].as_dict())
            self.assertEqual(json.loads(out)["data"]["categories"],
                             list(S.CATEGORIES))
            self.assertTrue(all(r["category"] and r["label"] and r["help"]
                                for r in rows))


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
        want = [f.js_dict() for f in S.FIELDS]
        self.assertEqual(fields, want)
        self.assertEqual(
            jsnode.call("Sch.CATEGORIES", Sch="settings_schema"),
            list(S.CATEGORIES))
        allkeys = jsnode.call("Sch.KEYS", Sch="settings_schema")
        self.assertEqual(allkeys, [f.key for f in S.FIELDS])

    def test_js_validate_agrees_with_python(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        for key, val, code in TABLE:
            want = "" if code == "" else "ui.err." + code
            if key not in S.KEYS and code == "":
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
            self.assertIn(f.label_key, wcopy.STRINGS, f.key)

    def test_js_validate_accepts_every_schema_key_and_refuses_unknown(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        for f in S.FIELDS:
            got = jsnode.call(
                f"Sch.validate({json.dumps(f.key)}, {json.dumps(f.default)})",
                Sch="settings_schema")
            self.assertEqual(got, "", f.key)
        self.assertEqual(jsnode.call("Sch.validate('made.up_key', 'x')",
                                     Sch="settings_schema"),
                         "ui.err.unknown")
        # the Settings model the surfaces import answers the same way
        self.assertEqual(jsnode.call("S.validate('hotkey.mod', 'SUPER')",
                                     S="settings"), "")
        self.assertEqual(jsnode.call("S.validate('made.up_key', 'x')",
                                     S="settings"), "ui.err.unknown")

    def test_js_quick_group_is_only_quick_fields(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        got = jsnode.call("S.group('budget').map(function (f) { return f.key })",
                          S="settings")
        self.assertEqual(got, ["budget.daily_usd", "budget.monthly_usd"])
        self.assertEqual(jsnode.call("S.group('hotkey')", S="settings"), [])


if __name__ == "__main__":
    unittest.main()
