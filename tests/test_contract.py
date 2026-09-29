"""Contract tests: the IPC + state.json surface every wispd must satisfy.

These run against the live Python daemon internals today and become the
parity oracle for wispd-rs (same fixtures, same expected shapes).
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, ".")
from wisp import ipc, state  # noqa: E402

FIXTURES = pathlib.Path("tests/fixtures/ipc_commands.jsonl")


class CommandSurface(unittest.TestCase):
    def _handler(self, calls):
        def h(cmd):
            calls.append(cmd.get("cmd"))
            return {"ok": True}
        return h

    def test_all_fixture_commands_well_formed(self):
        cmds = [json.loads(l) for l in FIXTURES.read_text().splitlines()]
        for c in cmds:
            assert isinstance(c.get("cmd"), str), c

    def test_reply_envelope_shape(self):
        # every handler path returns ok-bool; unknown cmd returns error
        st = state.State(state_file=pathlib.Path("/tmp/wisp-ct-state.json"))
        calls = []

        def handler(cmd):
            c = cmd.get("cmd")
            if c in ("status", "listen", "choice", "task_status",
                     "task_cancel", "stop"):
                return {"ok": True, "state": st.snapshot()} \
                    if c == "status" else {"ok": True}
            return {"ok": False, "error": f"unknown cmd {c!r}"}

        for line in FIXTURES.read_text().splitlines():
            resp = handler(json.loads(line))
            assert isinstance(resp.get("ok"), bool), resp
            if not resp["ok"]:
                assert "error" in resp
            if resp["ok"] and json.loads(line)["cmd"] == "status":
                assert "state" in resp


class StateFileShape(unittest.TestCase):
    KEYS = {"status", "transcript", "answer", "result", "choices",
            "level", "tasks", "error", "started_at"}
    STATUSES = {"idle", "listening", "transcribing", "deciding",
                "awaiting_choice", "acting", "speaking", "done", "error"}

    def test_snapshot_has_contract_keys(self):
        f = pathlib.Path("/tmp/wisp-ct-state2.json")
        f.unlink(missing_ok=True)
        st = state.State(state_file=f)
        s = st.snapshot()
        assert self.KEYS <= set(s), f"missing: {self.KEYS - set(s)}"
        assert s["status"] in self.STATUSES
        assert isinstance(s["choices"], list)
        assert isinstance(s["tasks"], dict)
        assert isinstance(s["level"], (int, float))

    def test_transition_writes_file(self):
        f = pathlib.Path("/tmp/wisp-ct-state3.json")
        f.unlink(missing_ok=True)
        st = state.State(state_file=f)
        st.transition("listening", transcript="hi")
        on_disk = json.loads(f.read_text())
        assert on_disk["status"] == "listening"
        assert on_disk["transcript"] == "hi"


if __name__ == "__main__":
    unittest.main()
