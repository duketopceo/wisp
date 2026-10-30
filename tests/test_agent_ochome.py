"""U4: the private OpenCode home and the ACP launch line (KTD1, KTD4)."""
import json
import pathlib
import tempfile
import unittest

from wisp import agent_home, agent_ochome


class OcHomeTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = pathlib.Path(td.name)
        self.home = self.root / "home"
        self.runtime = self.root / "runtime"
        self.cfg = {"agents": {"ask_timeout_s": "120"}}

    def written(self):
        path = agent_ochome.write_config(self.cfg, home=self.home)
        return path, json.loads(path.read_text())

    def test_config_lives_in_the_private_xdg_config_home(self):
        path, _ = self.written()
        self.assertEqual(path, self.home / "config" / "opencode" / "opencode.json")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_config_defines_the_wisp_agent_as_default(self):
        _, conf = self.written()
        self.assertEqual(conf["default_agent"], "wisp")
        wisp = conf["agents"]["wisp"]
        self.assertEqual(wisp["mode"], "primary")
        self.assertIn("PROGRESS:", wisp["system"])
        self.assertNotIn("{today}", wisp["system"])
        self.assertNotIn("tools", wisp)
        self.assertNotIn("model", wisp)  # the model is set per session (KTD5)

    def test_permissions_ask_by_default_and_deny_env_files(self):
        _, conf = self.written()
        rules = conf["agents"]["wisp"]["permissions"]
        self.assertEqual(rules[0], {"action": "*", "resource": "*", "effect": "ask"})
        self.assertIn({"action": "read", "resource": "*.env", "effect": "deny"}, rules)
        self.assertIn({"action": "wisp_*", "resource": "*", "effect": "allow"}, rules)
        self.assertNotIn("allow", {r["effect"] for r in rules if r["action"] in
                                   ("shell", "edit", "external_directory")})

    def test_rewrite_is_idempotent(self):
        p1, c1 = self.written()
        p2, c2 = self.written()
        self.assertEqual((p1, c1), (p2, c2))

    def test_launch_argv_is_ori_opencode_acp_with_no_model_flag(self):
        argv, _ = agent_ochome.launch(self.cfg, {"PATH": "/usr/bin"}, home=self.home,
                                      runtime_root=self.runtime)
        ori = self.runtime / "ori" / "current" / "ori"
        self.assertEqual(argv, [str(ori), "opencode", "acp"])
        self.assertNotIn("--model", argv)
        self.assertNotIn("--standalone", argv)  # breaks ACP framing (spike)

    def test_launch_env_is_private_scrubbed_and_quiet(self):
        base = {"PATH": "/usr/bin", "HOME": "/home/u", "OPENROUTER_API_KEY": "sk-or-v1-x",
                "XDG_CONFIG_HOME": "/home/u/.config", "OPENCODE_CONFIG_CONTENT": "{}"}
        _, env = agent_ochome.launch(self.cfg, base, home=self.home,
                                     runtime_root=self.runtime)
        for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                         ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
            self.assertEqual(env[var], str(self.home / sub))
        self.assertEqual(env["HOME"], "/home/u")
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertNotIn("OPENCODE_CONFIG_CONTENT", env)
        for flag in ("ORI_NO_UPDATE_CHECK", "OPENCODE_DISABLE_PROJECT_CONFIG",
                     "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_AUTOUPDATE"):
            self.assertEqual(env[flag], "1", flag)
        oc_dir = str(self.runtime / "opencode" / "current")
        self.assertEqual(env["PATH"].split(":")[0], oc_dir)

    def test_contract_matches_agent_home(self):
        _, conf = self.written()
        self.assertTrue(conf["agents"]["wisp"]["system"].startswith(
            agent_home.CONTRACT.split("\n")[0]))


if __name__ == "__main__":
    unittest.main()
