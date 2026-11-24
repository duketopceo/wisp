#!/usr/bin/env python3
"""U6: the embed contract other shells read (docs/EMBED.md).

Pins the shapes a host depends on: `wispd status --json` words, the
offline data on exit 3, `wispd status --table --json`, the `view` object
on watched state lines, and that every verb, flag and field EMBED.md
names exists in the CLI and the IPC contract.
"""
import contextlib
import io
import json
import pathlib
import re
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from cli_env import CliEnv  # noqa: E402

from wisp import cli, copy, status  # noqa: E402
from wisp.cli import registry  # noqa: E402

EMBED = (ROOT / "docs" / "EMBED.md").read_text()
IPC = (ROOT / "docs" / "IPC_CONTRACT.md").read_text()

# the closed tone set a host maps to its own colours
TONES = {"muted", "ember", "needsYou", "ok", "fail"}


def run_inproc(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv), host=None)
    return code, out.getvalue(), err.getvalue()


def status_json(state):
    reply = {"ok": True, "state": state}
    with mock.patch("wisp.ipc.send", return_value=reply):
        code, out, err = run_inproc(["status", "--json"])
    return code, json.loads(out)


class TestStatusWords(unittest.TestCase):
    def test_word_and_tone_follow_word_view(self):
        cases = [
            {"status": "idle"},
            {"status": "acting"},
            {"status": "transcribing"},
            {"status": "error", "error_code": "jev_down"},
            {"status": "done", "result": "BLOCKED: no target"},
            {"status": "no_such_status"},
        ]
        for st in cases:
            with self.subTest(st):
                code, j = status_json(st)
                self.assertEqual(code, 0)
                self.assertTrue(j["ok"])
                want = copy.word_view(st["status"], st.get("result", ""),
                                      st.get("error_code", ""))
                self.assertEqual((j["data"]["word"], j["data"]["tone"]),
                                 want)
                self.assertEqual(j["data"]["state"], st)
                self.assertIn("deploy", j["data"])
                self.assertIn(j["data"]["tone"], TONES)

    def test_blocked_and_error_code_differ_from_plain_rows(self):
        _, blocked = status_json({"status": "done", "result": "BLOCKED: x"})
        _, done = status_json({"status": "done"})
        self.assertNotEqual(blocked["data"]["word"], done["data"]["word"])
        self.assertEqual(blocked["data"]["tone"], "needsYou")
        _, err = status_json({"status": "error", "error_code": "jev_down"})
        self.assertEqual(err["data"]["word"], copy.error_message("jev_down"))

    def test_daemon_down_prints_offline_data_and_exits_3(self):
        with CliEnv() as env:
            code, out, err = env.run(["status", "--json"])
            self.assertEqual(code, 3, err)
            j = json.loads(out)
            self.assertFalse(j["ok"])
            self.assertEqual(j["error"]["code"], "E_DAEMON_DOWN")
            word, tone = copy.word_view("offline")
            self.assertEqual(j["data"], {"status": "offline", "word": word,
                                         "tone": tone})
            # plain output keeps the one-line error on stderr
            code, out, err = env.run(["status"])
            self.assertEqual(code, 3)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("E_DAEMON_DOWN: "), err)


class TestTable(unittest.TestCase):
    def table(self):
        with CliEnv() as env:  # no daemon: the table must not need one
            code, out, err = env.run(["status", "--table", "--json"])
            self.assertEqual(code, 0, err)
            return json.loads(out)["data"], env.ipc

    def test_table_lists_every_row_in_order_without_daemon(self):
        data, sent = self.table()
        self.assertEqual(sent, [])
        self.assertEqual(data["embed_version"], 1)
        keys = [r["key"] for r in data["rows"]]
        self.assertEqual(keys, list(status.STATUSES) + list(status.DERIVED))
        for r in data["rows"]:
            with self.subTest(r["key"]):
                self.assertEqual(set(r), {"key", "derived", "word", "short",
                                          "tone"})
                row = status.ROWS[r["key"]]
                self.assertEqual(r["derived"], r["key"] in status.DERIVED)
                self.assertEqual(r["word"], copy.STRINGS[row["word"]])
                self.assertEqual(r["short"], copy.STRINGS[row["short"]])
                self.assertTrue(r["word"].startswith(r["short"]))
                self.assertIn(r["tone"], TONES)

    def test_table_carries_every_error_cause(self):
        data, _ = self.table()
        self.assertEqual(data["causes"], {
            code: copy.STRINGS[key] for code, key in status.CAUSES.items()})

    def test_plain_table_prints_one_line_per_row(self):
        with CliEnv() as env:
            code, out, err = env.run(["status", "--table"])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        for key in list(status.STATUSES) + list(status.DERIVED):
            self.assertTrue(any(l.split()[:1] == [key] for l in lines), key)


class TestWatchView(unittest.TestCase):
    def watch(self, evs):
        with mock.patch("wisp.ipc.watch", return_value=iter(evs)):
            code, out, _ = run_inproc(["watch", "state", "tasks"])
        self.assertEqual(code, 0)
        return [json.loads(l) for l in out.splitlines()]

    def test_view_follows_merged_state(self):
        evs = [
            {"type": "hello", "ok": True, "contract_version": 2,
             "topics": ["state", "tasks"]},
            {"type": "snapshot", "seq": 1, "state": {"status": "idle"}},
            {"type": "state", "seq": 2, "diff": {"status": "acting"}},
            {"type": "state", "seq": 3, "diff": {"heartbeat_at": "t"}},
            {"type": "event", "name": "task_finished", "data": {}},
            {"type": "state", "seq": 4,
             "diff": {"status": "error", "error_code": "jev_down"}},
            {"type": "state", "seq": 5,
             "diff": {"status": "done", "result": "BLOCKED: x",
                      "error_code": ""}},
            {"type": "ping"},
        ]
        got = self.watch([dict(e) for e in evs])
        want_views = [
            None, copy.word_view("idle"), copy.word_view("acting"),
            copy.word_view("acting"), None,
            copy.word_view("error", code="jev_down"),
            copy.word_view("done", result="BLOCKED: x"), None,
        ]
        for line, ev, view in zip(got, evs, want_views):
            with self.subTest(ev):
                if view is None:
                    self.assertEqual(line, ev)
                else:
                    self.assertEqual(line["view"],
                                     {"word": view[0], "tone": view[1]})
                    # the daemon's own payload is passed through untouched
                    self.assertEqual({k: v for k, v in line.items()
                                      if k != "view"}, ev)

    def test_new_snapshot_resets_merged_state(self):
        evs = [
            {"type": "snapshot", "seq": 1,
             "state": {"status": "done", "result": "BLOCKED: x"}},
            {"type": "snapshot", "seq": 9, "state": {"status": "idle"}},
            {"type": "state", "seq": 10, "diff": {"status": "done"}},
        ]
        got = self.watch(evs)
        self.assertEqual(got[2]["view"]["word"], copy.word_view("done")[0])


class TestEmbedDoc(unittest.TestCase):
    def test_every_documented_command_parses(self):
        cmds = re.findall(r"^\s*(?:\$ )?wispd ([^\n#|`]+?)\s*$", EMBED,
                          re.M)
        self.assertGreaterEqual(len(cmds), 8, cmds)
        for line in cmds:
            argv = [a for a in line.split()
                    if a not in ("--json", "--quiet", "--no-color")]
            argv = [re.sub(r"<[^>]+>", "x", a) for a in argv]
            with self.subTest(line):
                cmd, _ = registry.parse(argv)
                self.assertIn(cmd.path, registry.commands())

    def test_documented_actions_and_flags_exist(self):
        for argv in (["trigger", "start"], ["trigger", "stop"],
                     ["interrupt"], ["choice", "x", "--prompt-id", "p"],
                     ["settings", "--category", "budget"],
                     ["status", "--table"], ["watch", "state", "tasks"]):
            with self.subTest(argv):
                registry.parse(argv)
                self.assertIn(" ".join(argv[:1]), EMBED.replace("`", " "))

    def test_documented_fields_and_lines(self):
        for field in ("data.word", "data.tone", "data.state",
                      "data.embed_version", "data.rows", "data.causes",
                      "E_DAEMON_DOWN", "contract_version", '"view"',
                      "heartbeat_at"):
            with self.subTest(field):
                self.assertIn(field, EMBED)
        for tone in TONES:
            self.assertIn(f"`{tone}`", EMBED)
        # the stream lines EMBED.md relies on are in the IPC contract
        for line in ('"type":"hello"', '"type":"snapshot"',
                     '"type":"state"', '"type":"ping"', "contract_version"):
            with self.subTest(line):
                self.assertIn(line, IPC)
        self.assertIn("EMBED.md", IPC)

    def test_exit_codes_match_registry(self):
        self.assertEqual(registry.EXIT_DOWN, 3)
        self.assertEqual(registry.EXIT_USAGE, 2)
        self.assertIn("exit 3", EMBED)
        self.assertIn("exit 2", EMBED)

    def test_worked_example_is_valid_python_on_the_contract(self):
        import ast
        blocks = re.findall(r"```python\n(.*?)```", EMBED, re.S)
        self.assertEqual(len(blocks), 1)
        ast.parse(blocks[0])
        for name in ('"view"', '"rows"', '"stale"', "returncode == 3",
                     '["wispd", "watch", "state", "tasks"]'):
            self.assertIn(name, blocks[0])

    def test_tone_set_is_the_table_tone_set(self):
        self.assertEqual({r["tone"] for r in status.ROWS.values()}, TONES)


if __name__ == "__main__":
    unittest.main()
