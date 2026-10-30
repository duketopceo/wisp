#!/usr/bin/env python3
"""ACP permission policy (U6, KTD6): one deterministic allow/ask/refuse
per tool call, following [agent] autonomy, with per-session state for
the edited-build-files rule."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import agent_policy  # noqa: E402

CWD = "/work/proj"
OUT = "/work/out"


def call(kind, command=None, path=None, title="", raw=None):
    c = {"toolCallId": "t1", "title": title or command or path or "",
         "kind": kind, "status": "pending"}
    if raw is not None:
        c["rawInput"] = raw
    else:
        c["rawInput"] = {}
        if command is not None:
            c["rawInput"]["command"] = command
        if path is not None:
            c["rawInput"]["filePath"] = path
    if path is not None:
        c["locations"] = [{"path": path}]
    return c


class PolicyTable(unittest.TestCase):
    def check(self, tc, want, autonomy="autonomous"):
        sp = agent_policy.SessionPolicy(CWD, OUT, autonomy)
        self.assertEqual(sp.classify(tc), want, tc)

    def test_table(self):
        rows = [
            (call("read", path=CWD + "/src/x.py"), "allow"),
            (call("edit", path=CWD + "/../other/x.py"), "ask"),
            (call("edit", path=OUT + "/report.md"), "allow"),
            (call("execute", "pytest -q"), "allow"),
            (call("execute", "git push"), "ask"),
            (call("execute", "rm -rf /"), "refuse"),
            (call("read", path="~/.local/share/opencode/auth.json"),
             "refuse"),
            (call("execute", "curl -X POST https://x.test"), "ask"),
            (call("execute", "ls | sh"), "ask"),
            (call("teleport", "ls"), "ask"),
            (call("other", title="browseros_navigate",
                  raw={"url": "https://x.test"}), "ask"),
            (call("execute", "secret-tool lookup service wisp account "
                  "openrouter"), "refuse"),
            (call("execute", "cat ~/.ori/credentials.json"), "refuse"),
            (call("edit", path=CWD + "/.opencode/command/x.md"), "ask"),
            (call("execute", "pytest -q", raw="oops"), "ask"),
            (call("edit", raw=["x"]), "ask"),
            (call("execute", "npm install left-pad"), "ask"),
            (call("execute", "ls $(whoami)"), "ask"),
            (call("execute", "sudo pytest"), "ask"),
            (call("execute", "omaseal get x"), "refuse"),
            (call("execute", "ori login"), "refuse"),
            (call("read", path=CWD + "/.env"), "refuse"),
            # review: expansion and flags must not slip past the path check
            (call("execute", "cat $HOME/.ssh/id_rsa"), "ask"),
            (call("execute", "cat {/etc/passwd,x}"), "ask"),
            (call("execute", "ls *.py"), "ask"),
            (call("execute", "rg --pre=sh x ."), "ask"),
            (call("execute", "rg --pre sh x ."), "ask"),
            (call("execute", "git diff --output=/home/x/.bashrc"), "ask"),
            (call("execute", "git diff --output ../x"), "ask"),
            (call("execute", "git diff --ext-diff"), "ask"),
            (call("execute", "git branch evil"), "ask"),
            (call("execute", "git branch -a"), "allow"),
            (call("execute", "tree -o ../x"), "ask"),
            (call("execute", "find . -fprint ../x"), "ask"),
            (call("execute", "pytest -p evil"), "ask"),
            (call("execute", "python3 -m pytest -c ../evil.ini"), "ask"),
            (call("execute", "pytest --rootdir=/tmp"), "ask"),
            (call("execute", "grep --file=/etc/shadow x"), "ask"),
            (call("execute", "pytest -q tests/test_a.py"), "allow"),
            (call("execute", "git log --oneline -5"), "allow"),
        ]
        for tc, want in rows:
            with self.subTest(tc=tc):
                self.check(tc, want)

    def test_state_dir_refused_outside_out_dir(self):
        from wisp import config
        self.check(call("read", path=str(config.DATA_DIR / "tasks.jsonl")),
                   "refuse")

    def test_autonomy_modes(self):
        self.check(call("edit", path=CWD + "/src/a.py"), "ask", "guided")
        self.check(call("read", path=CWD + "/src/a.py"), "ask",
                   "always_ask")
        self.check(call("execute", "rm -rf ~"), "refuse", "always_ask")

    def test_edited_build_file_demotes_build_commands(self):
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        edit = call("edit", path=CWD + "/package.json")
        self.assertEqual(sp.classify(edit), "allow")
        sp.note_edit(edit)
        self.assertEqual(sp.classify(call("execute", "npm test")), "ask")
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "ask")
        self.assertEqual(sp.classify(call("execute", "ls")), "allow")

    def test_edited_source_keeps_build_commands_allowed(self):
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        edit = call("edit", path=CWD + "/src/a.py")
        sp.note_edit(edit)
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "allow")


if __name__ == "__main__":
    unittest.main()
