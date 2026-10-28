"""B16: the Omarchy tutor reads this machine, never a manual, never runs a
package command, and is absent without the CLI."""
import contextlib
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import omarchy_tutor as ot  # noqa: E402
from wisp import skills, stage_capture, stage_ctx, stage_speak  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEFAULTS = '''\
o.bind("SUPER + SPACE", "Omarchy menu", "omarchy-menu toggle")
o.bind("SUPER + ALT + SPACE", "Apps menu", "omarchy-menu toggle apps")
o.bind("SUPER + K", "Keybindings", "omarchy-menu-keybindings")
o.bind("SUPER + J", "Toggle window split", hl.dsp.layout("togglesplit"))
o.bind("SUPER + T", "Toggle window floating/tiling", hl.dsp.window.float({ action = "toggle" }))
'''

USER = '''\
-- personal overrides
hl.unbind("SUPER + K")
o.bind("SUPER + F1", "Keybindings", "omarchy-menu-keybindings")
o.bind("SUPER + B", "BrowserOS", { launch = "/x/browseros" })
'''

COMMANDS = {"ok": True, "commands": [
    {"route": "omarchy theme set", "group": "theme", "name": "set",
     "summary": "Apply an Omarchy theme", "args": "<theme-name>",
     "hidden": False},
    {"route": "omarchy theme list", "group": "theme", "name": "list",
     "summary": "List available themes", "args": "", "hidden": False},
    {"route": "omarchy pkg aur install", "group": "pkg", "name": "install",
     "summary": "Pick new AUR packages to install", "args": "",
     "hidden": False},
    {"route": "omarchy secret", "group": "dev", "name": "secret",
     "summary": "theme internals", "args": "", "hidden": True},
]}

SHIM = """#!/bin/sh
echo "$@" >> "$OMARCHY_LOG"
case "$1 $2" in
  "commands --json") cat "$OMARCHY_COMMANDS" ;;
  "version ") echo "9.9.9-fixture" ;;
  "theme current") echo "Fixture Night" ;;
  *) echo "UNEXPECTED $@" >> "$OMARCHY_LOG.bad"; exit 9 ;;
esac
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.defaults = self.tmp / "defaults"
        self.defaults.mkdir()
        (self.defaults / "tiling.lua").write_text(DEFAULTS)
        self.user = self.tmp / "bindings.lua"
        self.user.write_text(USER)
        self.log = self.tmp / "calls.log"
        (self.tmp / "commands.json").write_text(json.dumps(COMMANDS))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shim = self.bin / "omarchy"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        env = {"PATH": str(self.bin) + os.pathsep + "/usr/bin:/bin",
               "OMARCHY_LOG": str(self.log),
               "OMARCHY_COMMANDS": str(self.tmp / "commands.json")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def text(self, q):
        return ot.context_for(q, defaults_dir=self.defaults,
                              user_file=self.user)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class FromTheMachine(Fixture):
    def test_a_rebound_key_is_named_not_the_default(self):
        t = self.text("how do I see every keybinding in omarchy")
        self.assertIn("Super+F1 opens the list of every key binding", t)
        self.assertNotIn("Super+K ", t)

    def test_an_unrebound_key_is_the_default(self):
        self.user.write_text("")
        t = self.text("show me the keybindings")
        self.assertIn("Super+K opens the list of every key binding", t)

    def test_a_dropped_binding_is_not_claimed(self):
        self.user.write_text('hl.unbind("SUPER + K")\n')
        t = self.text("show me the keybindings")
        self.assertNotIn("Super+K", t)
        self.assertIn("not bound here", t)

    def test_menu_split_and_float_keys_and_the_users_own_bindings(self):
        t = self.text("how do I split a window in omarchy")
        self.assertIn("Super+Alt+Space opens the apps menu", t)
        self.assertIn("Super+J toggles the window split", t)
        self.assertIn("Super+T toggles floating and tiling", t)
        self.assertIn("Super+B BrowserOS", t)

    def test_version_and_theme_come_from_the_cli(self):
        t = self.text("change the theme in omarchy")
        self.assertIn("Omarchy 9.9.9-fixture", t)
        self.assertIn("theme Fixture Night", t)

    def test_matching_commands_come_from_the_command_list(self):
        t = self.text("how do I change the theme")
        self.assertIn("omarchy theme set <theme-name>: Apply an Omarchy "
                      "theme", t)
        self.assertIn("omarchy theme list", t)
        self.assertNotIn("omarchy secret", t)          # hidden

    def test_pointing_hint_and_the_budget(self):
        t = self.text("keybindings theme install package aur menu")
        self.assertIn("visible label", t)
        self.assertLessEqual(len(t), ot.BUDGET)


class NeverRunsAPackageCommand(Fixture):
    def test_an_aur_question_gets_the_pkgbuild_line_and_no_install_call(self):
        t = self.text("how do I install an app from the AUR")
        self.assertIn("read the PKGBUILD before any `omarchy pkg aur "
                      "install`", t)
        self.assertIn("Never run a package command", t)
        for call in self.calls():
            self.assertNotIn("pkg", call)
            self.assertNotIn("install", call.replace("commands", ""))
        self.assertFalse(pathlib.Path(str(self.log) + ".bad").exists())

    def test_only_read_only_calls_are_ever_made(self):
        self.text("keybindings theme packages")
        allowed = {"commands --json", "version", "theme current"}
        self.assertTrue(self.calls())
        self.assertLessEqual({c.strip() for c in self.calls()}, allowed)

    def test_the_runner_refuses_anything_else(self):
        for bad in (("pkg", "install"), ("theme", "set", "x"),
                    ("update",), ("pkg", "aur", "add", "evil")):
            with self.assertRaises(ValueError):
                ot._run(bad)
        self.assertEqual(self.calls(), [])


class Absent(Fixture):
    def test_without_the_cli_there_is_no_tutor_text(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertFalse(ot.available())
            self.assertEqual(self.text("change the omarchy theme"), "")

    def test_off_topic_questions_add_nothing_and_call_nothing(self):
        self.assertEqual(self.text("what is the capital of france"), "")
        self.assertEqual(self.calls(), [])

    def test_a_failing_cli_degrades_to_the_bindings_alone(self):
        (self.bin / "omarchy").write_text("#!/bin/sh\nexit 3\n")
        t = self.text("show me the keybindings")
        self.assertIn("Super+F1", t)
        self.assertNotIn("Installed Omarchy", t)


class Seed(unittest.TestCase):
    def test_seed_is_small_and_has_no_manual_text(self):
        body = (ROOT / "wisp/skills_seed/omarchy/SKILL.md").read_text()
        self.assertLess(len(body), 1500)
        # headings of the published Omarchy manual: none may appear
        for h in ("Getting Started", "Making Omarchy Yours", "Hotkeys",
                  "Learn Omarchy", "The Omarchy Manual", "Keyboard Shortcuts",
                  "Advanced"):
            self.assertNotIn(h, body)
        self.assertFalse(re.search(r"\bSuper\s*\+\s*\w", body),
                         "no default key is hard-coded in the seed")
        self.assertEqual(sorted(p.name for p in
                                (ROOT / "wisp/skills_seed/omarchy").iterdir()),
                         ["SKILL.md"])

    def seeded(self, path):
        with tempfile.TemporaryDirectory() as td:
            dst = pathlib.Path(td) / "skills"
            with mock.patch.object(skills, "SKILLS_DIR", dst), \
                    mock.patch.dict(os.environ, {"PATH": path}):
                skills.seed()
            return (dst / "omarchy" / "SKILL.md").exists()

    def test_the_skill_is_installed_only_with_the_cli(self):
        with tempfile.TemporaryDirectory() as td:
            b = pathlib.Path(td)
            (b / "omarchy").write_text("#!/bin/sh\n")
            (b / "omarchy").chmod(0o755)
            self.assertTrue(self.seeded(str(b)))
        self.assertFalse(self.seeded("/nonexistent"))


class IntoTheTurn(Fixture):
    def test_context_stage_adds_it_and_ask_chat_carries_it(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": "Press Super+F1."}
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False), \
                mock.patch("wisp.memory.context_block", return_value=""):
            stage_speak.ask_chat("show keybindings", {},
                                 tutor_text="[omarchy] Super+F1 opens it")
        sys_msgs = [m["content"] for m in seen["m"] if m["role"] == "system"]
        self.assertIn("[omarchy] Super+F1 opens it", sys_msgs)

    def test_without_tutor_text_the_prompt_is_unchanged(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": "x"}
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False), \
                mock.patch("wisp.memory.context_block", return_value=""):
            stage_speak.ask_chat("hi", {})
        self.assertEqual(len([m for m in seen["m"]
                              if m["role"] == "system"]), 1)

    def test_context_stage_puts_the_text_in_the_turn_context(self):
        sp = mock.MagicMock()
        sp.timed.side_effect = lambda *_a, **_k: contextlib.nullcontext()
        c = stage_ctx.TurnCtx({"agent": {"screenshots": "false"}},
                              mock.MagicMock(), None, None, None, sp, "t1",
                              None, None, 1.0, "m")
        c.text = "how do I change the omarchy theme"
        pl = mock.MagicMock()
        pl.active_window.return_value = {"class": "foot", "title": "t"}
        with mock.patch.object(stage_capture, "_pl", lambda: pl), \
                mock.patch("wisp.tools.adapters.best_catalog",
                           return_value={}), \
                mock.patch("wisp.tools.adapters.context", return_value=""), \
                mock.patch("wisp.goals.join_or_new",
                           return_value=({"text": "g"}, False)), \
                mock.patch("wisp.goals.context_text", return_value=""), \
                mock.patch("wisp.session.tail", return_value=[]), \
                mock.patch("wisp.session.as_text", return_value=""), \
                mock.patch("wisp.memory.context_block", return_value=""), \
                mock.patch("wisp.learn.correction_context",
                           return_value=None), \
                mock.patch("wisp.docread.context_for", return_value=""), \
                mock.patch.object(ot, "DEFAULTS_DIR", str(self.defaults)), \
                mock.patch.object(ot.config, "HOME", self.tmp):
            (self.tmp / ".config" / "hypr").mkdir(parents=True)
            (self.tmp / ".config" / "hypr" / "bindings.lua").write_text(USER)
            stage_capture.context_stage(c)
        self.assertIn("[omarchy]", c.tutor_text)
        self.assertIn("[omarchy]", c.context)


if __name__ == "__main__":
    unittest.main()
