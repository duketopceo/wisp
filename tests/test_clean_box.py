"""A box with nothing on it: `wispd install` works, no local-model units
appear, keys read as missing, and a turn says so (hosted-install U4).

Every run is a subprocess in the hermetic temp HOME from cli_env.py with
PATH cut to shims plus a real `git` — no API keys, no omaseal, and
hyprctl/systemctl stubbed. Nothing touches the real home.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cli_env  # noqa: E402

BIND_HEAD = ('-- Wisp push-to-talk (Super + D)\n'
             'o.bind("SUPER + D", "Wisp push-to-talk (hold)", '
             '{ launch = "/x/wisp-trigger start" })\n'
             'o.bind("SUPER + D", "Wisp push-to-talk (release)", '
             '{ launch = "/x/wisp-trigger stop" }, { release = true })\n')


class CleanBoxTest(unittest.TestCase):
    def box(self, hypr=True):
        e = cli_env.CliEnv()
        e.__enter__()
        self.addCleanup(e.__exit__, None, None, None)
        for name in ("systemctl", "hyprctl"):
            e.shim(name)
        os.symlink(shutil.which("git"), e.home / "bin" / "git")
        e.env["WISP_OS"] = "linux"
        e.env["XDG_CURRENT_DESKTOP"] = "Hyprland"
        e.env["HYPRLAND_INSTANCE_SIGNATURE"] = "test"
        if hypr:
            (e.home / ".config" / "hypr").mkdir(parents=True)
        return e

    def test_clean_install_hosted_no_local_units_keys_todo(self):
        e = self.box(hypr=False)
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        udir = e.home / ".config" / "systemd" / "user"
        names = sorted(p.name for p in udir.glob("*"))
        self.assertTrue(names, "no units installed")
        self.assertFalse([n for n in names
                          if n.startswith(("llama", "jev-shim"))], names)
        code, out, err = e.run(["onboard", "--status", "--json"])
        keys = next(s for s in json.loads(out)["data"]["steps"]
                    if s["id"] == "keys")
        self.assertEqual(keys["state"], "todo")
        self.assertIn("GROQ_API_KEY", keys["detail"])

    def test_clean_install_without_hypr_dir_skips_the_bind(self):
        e = self.box(hypr=False)
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertIn("no ~/.config/hypr", out)
        self.assertFalse((e.home / ".config" / "hypr").exists())

    def test_stt_turn_without_a_key_is_key_missing(self):
        e = self.box()
        self.assertEqual(e.run(["install"])[0], 0)
        wav = e.home / "t.wav"
        wav.write_bytes(b"RIFFfake")
        code_src = ("import sys, pathlib\n"
                    f"sys.path.insert(0, {str(cli_env.ROOT)!r})\n"
                    "from wisp import config, pipeline, errors_codes\n"
                    "try:\n"
                    f"    pipeline.transcribe(pathlib.Path({str(wav)!r}), "
                    "config.load_config())\n"
                    "except errors_codes.WispError as x:\n"
                    "    print(x.code, x.public)\n")
        p = subprocess.run([sys.executable, "-c", code_src], env=e.env,
                           capture_output=True, text=True, timeout=60)
        self.assertIn("key_missing", p.stdout, p.stderr)
        self.assertIn("GROQ_API_KEY", p.stdout)

    def test_comment_and_own_binds_do_not_warn(self):
        e = self.box()
        (e.home / ".config" / "hypr" / "bindings.lua").write_text(BIND_HEAD)
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("already in use", out)

    def rate_lines(self, e):
        text = (e.home / ".config" / "hypr" / "bindings.lua").read_text()
        return [l for l in text.splitlines()
                if "label set incorrect" in l]

    def test_install_writes_the_rate_bind_once(self):
        e = self.box()
        self.assertEqual(e.run(["install"])[0], 0)
        lines = self.rate_lines(e)
        self.assertEqual(len(lines), 1, lines)
        # Super+Shift+D is Omarchy's Docker bind
        self.assertIn('"SUPER + ALT + D"', lines[0])
        self.assertIn("/.local/bin/wispd label set incorrect", lines[0])
        # idempotent: a second install adds nothing
        self.assertEqual(e.run(["install"])[0], 0)
        self.assertEqual(len(self.rate_lines(e)), 1)
        self.assertEqual(
            (e.home / ".config" / "hypr" / "bindings.lua")
            .read_text().count("wisp-trigger start"), 1)

    def test_rate_bind_lands_beside_an_existing_push_to_talk_bind(self):
        e = self.box()
        (e.home / ".config" / "hypr" / "bindings.lua").write_text(BIND_HEAD)
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.rate_lines(e)), 1)

    def test_rate_bind_follows_the_hotkey_config(self):
        e = self.box()
        cfg = e.home / ".config" / "wisp"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.toml").write_text(
            '[hotkey]\nmod = "ALT"\nkey = "f"\n')
        self.assertEqual(e.run(["install"])[0], 0)
        # a mod that already holds ALT takes CTRL
        self.assertIn('"ALT + CTRL + F"', self.rate_lines(e)[0])

    def test_unrelated_super_d_bind_still_warns(self):
        e = self.box()
        (e.home / ".config" / "hypr" / "bindings.lua").write_text(
            BIND_HEAD + 'o.bind("SUPER + D", "Launcher", '
            '{ launch = "rofi" })\n')
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertIn("already in use", out)
        self.assertIn("rofi", out)


if __name__ == "__main__":
    unittest.main()
