#!/usr/bin/env python3
"""R4/KTD9: the `keyring://svc/acct` key source in config.load_env_key.

A fake `secret-tool` shell script on a private PATH stands in for the
desktop Secret Service; nothing here touches a real keyring."""
import pathlib
import sys
import tomllib
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import shorttmp  # noqa: E402

from wisp import config  # noqa: E402


class TestKeyringSource(unittest.TestCase):
    def setUp(self):
        self._td = shorttmp.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = pathlib.Path(self._td.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.argv_log = self.tmp / "argv.log"
        p = mock.patch.object(config, "ENV_FILE", self.tmp / "none.env")
        p.start()
        self.addCleanup(p.stop)

    def _fake(self, body: str):
        f = self.bin / "secret-tool"
        f.write_text(f'#!/bin/sh\necho "$@" >> "{self.argv_log}"\n{body}\n')
        f.chmod(0o755)

    def _env(self, **extra):
        return mock.patch.dict(
            "os.environ", {"PATH": f"{self.bin}:/usr/bin:/bin", **extra},
            clear=True)

    def test_keyring_ref_resolves_and_strips_the_newline(self):
        self._fake("echo sk-or-v1-x")
        with self._env():
            self.assertEqual(
                config.load_env_key("keyring://wisp/openrouter"),
                "sk-or-v1-x")
        self.assertEqual(self.argv_log.read_text().strip(),
                         "lookup service wisp account openrouter")

    def test_absent_secret_tool_falls_through_to_the_env_var(self):
        with mock.patch.dict("os.environ", {
                "PATH": str(self.bin), "OPENROUTER_API_KEY": "sk-env"},
                clear=True):
            self.assertEqual(config.load_env_key(
                "keyring://wisp/openrouter,OPENROUTER_API_KEY"), "sk-env")

    def test_locked_keyring_exit_1_falls_through_without_raising(self):
        self._fake("exit 1")
        with self._env(OPENROUTER_API_KEY="sk-env"):
            self.assertEqual(config.load_env_key(
                "keyring://wisp/openrouter,OPENROUTER_API_KEY"), "sk-env")
            self.assertEqual(
                config.load_env_key("keyring://wisp/openrouter"), "")

    def test_key_label_skips_keyring_refs(self):
        self.assertEqual(config.key_label(
            "keyring://wisp/openrouter,OPENROUTER_API_KEY"),
            "OPENROUTER_API_KEY")

    def test_default_openrouter_key_env_lists_keyring_first(self):
        self.assertEqual(
            tomllib.loads(config.DEFAULT_CONFIG)["brain"]["openrouter"]["key_env"],
            "keyring://wisp/openrouter,OPENROUTER_API_KEY")


if __name__ == "__main__":
    unittest.main()
