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

    def test_edited_source_demotes_build_commands(self):
        # a runner executes agent-written source too
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        sp.note_edit(call("edit", path=CWD + "/src/a.py"))
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "ask")

    def test_inert_edit_keeps_build_commands_allowed(self):
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        for f in ("README.md", "notes.txt", "docs/a.rst", "logo.png"):
            sp.note_edit(call("edit", path=CWD + "/" + f))
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "allow")

    def test_written_test_file_demotes_every_runner(self):
        """The reviewed attack: write test_payload.py, then run it."""
        runners = ["python3 -m unittest test_payload",
                   "python -m pytest test_payload.py", "pytest -q",
                   "python3 -m unittest discover", "npm test",
                   "npm run test", "pnpm test", "yarn test", "make test",
                   "make", "cargo test", "go test"]
        for f in ("test_payload.py", "payload_test.py", "tests/test_x.py",
                  "payload.test.js", "payload.spec.ts", "run_tests",
                  "Makefile", "build.rs", "go.mod", "x.pth",
                  "sitecustomize.py", "package.json", "conftest.py"):
            for cmd in runners:
                with self.subTest(file=f, cmd=cmd):
                    sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
                    w = call("edit", path=CWD + "/" + f)
                    self.assertEqual(sp.classify(w), "allow")
                    sp.note_edit(w)
                    self.assertEqual(sp.classify(call("execute", cmd)),
                                     "ask")

    def test_other_tool_kinds_and_move_taint(self):
        for kind in ("edit", "delete", "move"):
            sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
            sp.note_edit(call(kind, path=CWD + "/test_payload.py"))
            self.assertEqual(
                sp.classify(call("execute", "python3 -m unittest t")), "ask")

    def test_approved_command_taints_session(self):
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        cmd = call("execute", "sh gen.sh")
        self.assertEqual(sp.classify(cmd), "ask")
        sp.note_edit(cmd)
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "ask")
        self.assertEqual(sp.classify(call("execute", "ls")), "allow")

    def test_approved_pathless_or_unknown_call_taints_session(self):
        for c in (call("other", title="run generator"),
                  call("edit", raw={"target": CWD + "/gen.py"}),
                  call("edit", raw={"files": [CWD + "/a.py"]})):
            sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
            sp.note_edit(c)
            self.assertEqual(
                sp.classify(call("execute", "python3 -m unittest t")), "ask",
                c)

    def test_approved_read_class_call_does_not_taint(self):
        for kind in ("read", "search", "think", "fetch"):
            sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
            sp.note_edit(call(kind, title="look"))
            self.assertNotIn(agent_policy._EXEC_MARK, sp.edited, kind)

    def test_symlink_and_dotdot_paths_resolve(self):
        sp = agent_policy.SessionPolicy(CWD, OUT, "autonomous")
        sp.note_edit(call("edit", path="src/../test_payload.py"))
        self.assertEqual(sp.classify(call("execute", "pytest -q")), "ask")


if __name__ == "__main__":
    unittest.main()
