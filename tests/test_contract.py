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

    def test_snapshot_carries_stamps(self):
        f = pathlib.Path("/tmp/wisp-ct-state4.json")
        f.unlink(missing_ok=True)
        st = state.State(state_file=f)
        s = st.snapshot()
        assert s["contract_version"] == state.CONTRACT_VERSION == 1
        assert isinstance(s["seq"], int)
        assert "turn_id" in s and "updated_at" in s


class BusWriterOutput(unittest.TestCase):
    """What the single publisher writes must satisfy the contract."""
    STATUSES = StateFileShape.STATUSES

    def test_bus_file_matches_contract(self):
        import tempfile
        f = pathlib.Path(tempfile.mkdtemp()) / "state.json"
        bus = state.StateBus(state_file=f)
        try:
            t = bus.begin_turn()
            bus.publish(t, status="listening", transcript="hi")
            bus.publish(t, level=0.4)
            bus.publish(t, status="done", result="ok")
            d = json.loads(f.read_text())
        finally:
            bus.close()
        assert StateFileShape.KEYS <= set(d), StateFileShape.KEYS - set(d)
        assert d["status"] in self.STATUSES
        assert d["contract_version"] == 1
        assert d["turn_id"] == t
        assert isinstance(d["seq"], int) and d["seq"] >= 3
        assert d["updated_at"].endswith("+00:00")
        # additive only: nothing from the v1 document is renamed away
        for k in ("points", "steps", "guide", "focus", "goal",
                  "transcript", "answer", "choices"):
            assert k in d, k

    def test_seq_is_strictly_increasing_across_writes(self):
        import tempfile
        f = pathlib.Path(tempfile.mkdtemp()) / "state.json"
        bus = state.StateBus(state_file=f)
        try:
            t = bus.begin_turn()
            seen = []
            for s in ("listening", "transcribing", "deciding", "done"):
                bus.publish(t, status=s)
                seen.append(json.loads(f.read_text())["seq"])
        finally:
            bus.close()
        assert seen == sorted(set(seen)) and len(seen) == 4


if __name__ == "__main__":
    unittest.main()


class PushStreamContract(unittest.TestCase):
    """The `subscribe` framing every core must honour (W3)."""

    def test_hello_snapshot_diff_framing_and_seq(self):
        import tempfile
        td = pathlib.Path(tempfile.mkdtemp())
        bus = state.StateBus(state_file=td / "state.json")
        srv = ipc.Daemon(lambda c: {"ok": True}, sock_file=td / "s.sock",
                         bus=bus)
        srv.start()
        try:
            it = ipc.subscribe(sock_file=td / "s.sock", timeout=3)
            hello, snap = next(it), next(it)
            assert hello["type"] == "hello" and hello["ok"] is True
            assert hello["contract_version"] == state.CONTRACT_VERSION
            assert snap["type"] == "snapshot"
            assert snap["seq"] == snap["state"]["seq"]
            assert StateFileShape.KEYS <= set(snap["state"])
            t = bus.begin_turn()
            bus.publish(t, status="listening")
            ev = next(it)
            assert ev["type"] == "state" and ev["seq"] == snap["seq"] + 1
            assert ev["diff"]["status"] == "listening"
            it.close()
        finally:
            srv.stop()
            bus.close()
