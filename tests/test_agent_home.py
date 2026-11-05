"""B10: named agents with a folder, a contract, and routing by name."""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import agent_home, agents, stage_execute, stage_route  # noqa: E402
from wisp import tools  # noqa: E402,F401  (import before Popen is patched)


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.root = self.dir / "agents"
        self.tasks = self.dir / "tasks.jsonl"
        self.logs = self.dir / "logs"
        p = mock.patch.object(agent_home, "_root", lambda root=None: root or self.root)
        p.start()
        self.addCleanup(p.stop)
        self.popen = []
        self.stdins = []

        class P:
            pid = 5000

            def poll(self):
                return None

        def fake_popen(cmd, **kw):
            fin = kw.get("stdin")
            self.stdins.append(fin.read().decode()
                               if hasattr(fin, "read") else "")
            self.popen.append((cmd, kw))
            P.pid += 1
            return P()

        alive = mock.patch.object(agents, "_alive", return_value=False)
        self.alive = alive.start()
        self.addCleanup(alive.stop)
        for target, val in (
                ("_runtime_cmd", lambda cfg, model: ["agent", "run"]),
                ("_pinned_state", lambda: {"state": "absent"}),
                ("_systemd_scope_enabled", lambda cfg: False),
                ("_pstart", lambda pid: "1"),
                ("_PROCS", [])):
            q = mock.patch.object(agents, target, val)
            q.start()
            self.addCleanup(q.stop)
        q = mock.patch.object(agents.subprocess, "Popen", fake_popen)
        q.start()
        self.addCleanup(q.stop)
        q = mock.patch.object(agents.config, "TASK_LOGS", self.logs)
        q.start()
        self.addCleanup(q.stop)

    def prompt_of(self, i):
        """The prompt the i-th spawned agent was given. It is stdin, not
        argv: other local accounts can read argv while it runs."""
        self.assertNotIn("Task: ", " ".join(self.popen[i][0]))
        return self.stdins[i]

    def run_named(self, detail, **kw):
        return agents.run_named(detail, {}, self.tasks, log_dir=self.logs,
                                **kw)


class Folder(Base):
    def test_create_makes_the_folder_with_an_identity(self):
        self.assertTrue(agent_home.create("Scout", "research helper"))
        h = self.root / "scout"
        self.assertIn("# Scout", (h / "AGENTS.md").read_text())
        self.assertIn("research helper", (h / "AGENTS.md").read_text())
        for sub in ("notes", "output", "tmp"):
            self.assertTrue((h / sub).is_dir(), sub)
        self.assertEqual(agent_home.known(), ["Scout"])

    def test_create_never_overwrites_an_edited_identity(self):
        agent_home.create("Scout", "research helper")
        f = self.root / "scout" / "AGENTS.md"
        f.write_text("# Scout\nmy own words\n")
        self.assertFalse(agent_home.create("Scout", "something else"))
        self.assertEqual(f.read_text(), "# Scout\nmy own words\n")

    def test_prompt_has_identity_contract_notes_and_task(self):
        agent_home.create("Scout", "research helper")
        notes = self.root / "scout" / "notes"
        (notes / "2026-10-01.md").write_text("found the old API docs")
        text = agent_home.prompt(
            "Scout", "look into rust async",
            now=datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertIn("# Scout", text)
        self.assertIn("PROGRESS:", text)
        self.assertIn("first sentence", text)
        self.assertIn("\"drafted\"", text)
        self.assertIn("notes/2026-10-02.md", text)
        self.assertIn("found the old API docs", text)
        self.assertTrue(text.endswith("Task: look into rust async"))

    def test_notes_are_bounded(self):
        agent_home.create("Scout")
        (self.root / "scout" / "notes" / "2026-10-01.md").write_text(
            "x" * 10000)
        text = agent_home.prompt("Scout", "t")
        self.assertLess(len(text), agent_home.NOTES_BUDGET + 2500)

    def test_inbox_is_read_once(self):
        agent_home.create("Scout")
        agent_home.leave_message("Scout", "also check the changelog")
        self.assertIn("also check the changelog",
                      agent_home.prompt("Scout", "t"))
        self.assertNotIn("also check the changelog",
                         agent_home.prompt("Scout", "t"))


class Speech(unittest.TestCase):
    def test_create_phrases(self):
        c = agent_home.parse_create("make me a research helper called Scout")
        self.assertEqual((c["name"], c["role"], c["task"]),
                         ("Scout", "research helper", ""))
        c = agent_home.parse_create(
            "create an agent called Pilot to watch my inbox")
        self.assertEqual((c["name"], c["task"]), ("Pilot", "watch my inbox"))
        self.assertIsNone(agent_home.parse_create("make me a sandwich"))
        self.assertIsNone(agent_home.parse_create("open firefox"))

    def test_tell_needs_a_known_agent(self):
        self.assertEqual(
            agent_home.parse_tell("tell Scout to check rust async",
                                  ["Scout"]),
            ("Scout", "check rust async"))
        self.assertEqual(
            agent_home.parse_tell("Tell scout that the deadline moved",
                                  ["Scout"]),
            ("Scout", "the deadline moved"))
        self.assertIsNone(agent_home.parse_tell("tell Bob hi", ["Scout"]))
        self.assertIsNone(agent_home.parse_tell("open firefox", ["Scout"]))

    def test_status_phrases(self):
        for said in ("what's running", "what are my agents doing",
                     "agent status"):
            self.assertTrue(agent_home.is_status(said), said)
        self.assertFalse(agent_home.is_status("what time is it"))


class Routing(Base):
    def test_create_routes_by_name(self):
        route, detail = stage_route.fixed_route(
            "make me a research helper called Scout", "act")
        self.assertEqual(route, "agent")
        self.assertEqual(agent_home.decode(detail)["name"], "Scout")

    def test_tell_routes_to_the_known_agent_not_a_new_one(self):
        agent_home.create("Scout")
        route, detail = stage_route.fixed_route(
            "tell Scout to look at tokio", "act")
        self.assertEqual(route, "agent")
        self.assertEqual(agent_home.decode(detail),
                         {"kind": "tell", "name": "Scout",
                          "message": "look at tokio"})

    def test_an_unknown_name_is_ordinary_speech(self):
        self.assertEqual(stage_route.fixed_route("tell Bob hi", "act"),
                         ("act", None))

    def test_execute_hands_the_route_to_run_named(self):
        with mock.patch.object(agents, "run_named",
                               return_value="ACTED (0 steps): x") as rn:
            out = stage_execute.execute(
                {"route": {"choice": "agent"}}, {},
                detail=agent_home.encode("status"), initial_image=None,
                interrupted=lambda: False)
        self.assertEqual(out, "ACTED (0 steps): x")
        rn.assert_called_once()


class Runs(Base):
    def test_spawning_a_helper_creates_its_folder(self):
        out = self.run_named(agent_home.encode(
            "create", name="Scout", role="research helper", task=""))
        self.assertIn("Scout is ready", out)
        self.assertTrue((self.root / "scout" / "AGENTS.md").is_file())
        self.assertEqual(self.popen, [])       # no task, nothing to run

    def test_a_task_starts_the_first_run_in_the_folder(self):
        out = self.run_named(agent_home.encode(
            "create", name="Scout", role="research helper",
            task="find the docs"))
        self.assertEqual(out, "ACTED (0 steps): Scout is on it.")
        cmd, kw = self.popen[0]
        self.assertEqual(kw["cwd"], str(self.root / "scout"))
        self.assertEqual(kw["env"]["WISP_OUT_DIR"],
                         str(self.root / "scout" / "output"))
        self.assertTrue(self.prompt_of(0).endswith("Task: find the docs"))
        rec = json.loads(self.tasks.read_text().splitlines()[0])
        self.assertEqual((rec["agent"], rec["task"]),
                         ("scout", "find the docs"))

    def test_a_second_run_reads_the_notes_and_makes_no_second_agent(self):
        self.run_named(agent_home.encode(
            "create", name="Scout", role="r", task="first job"))
        (self.root / "scout" / "notes" / "2026-10-01.md").write_text(
            "tokio is the runtime to look at")
        out = self.run_named(agent_home.encode(
            "tell", name="Scout", message="now compare with async-std"))
        self.assertEqual(out, "ACTED (0 steps): Scout is on it.")
        self.assertIn("tokio is the runtime to look at", self.prompt_of(1))
        self.assertIn("Task: now compare with async-std", self.prompt_of(1))
        self.assertEqual(agent_home.known(), ["Scout"])      # one agent
        names = [json.loads(l)["agent"] for l in
                 self.tasks.read_text().splitlines()]
        self.assertEqual(names, ["scout", "scout"])

    def test_telling_a_busy_agent_leaves_a_message(self):
        self.run_named(agent_home.encode(
            "create", name="Scout", role="r", task="long job"))
        self.alive.return_value = True            # still running
        out = self.run_named(agent_home.encode(
            "tell", name="Scout", message="also check tokio"))
        self.assertIn("still working", out)
        self.assertEqual(len(self.popen), 1)       # no second process
        self.alive.return_value = False
        self.run_named(agent_home.encode(
            "tell", name="Scout", message="and then summarize"))
        self.assertIn("also check tokio", self.prompt_of(1))

    def test_status_lists_what_is_running(self):
        self.assertEqual(self.run_named(agent_home.encode("status")),
                         "ACTED (0 steps): nothing is running.")
        self.run_named(agent_home.encode(
            "create", name="Scout", role="r", task="long job"))
        self.alive.return_value = True
        out = self.run_named(agent_home.encode("status"))
        self.assertIn("1 running", out)
        self.assertIn("scout: long job", out)

    def test_a_helpers_environment_still_has_no_wisp_credentials(self):
        with mock.patch.dict(agents.os.environ,
                             {"OPENROUTER_API_KEY": "sk", "PATH": "/bin"},
                             clear=True):
            self.run_named(agent_home.encode(
                "create", name="Scout", role="r", task="job"))
        env = self.popen[0][1]["env"]
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertIn("WISP_TASK_ID", env)

    def test_a_tell_with_no_live_session_still_uses_the_inbox(self):
        # no ACP manager running: the one-shot inbox path is unchanged
        self.run_named(agent_home.encode(
            "create", name="Scout", role="r", task="long job"))
        self.alive.return_value = True
        out = self.run_named(agent_home.encode(
            "tell", name="Scout", message="also B"))
        self.assertIn("left it your message", out)
        self.assertIn("also B", (self.root / "scout" / "inbox.md").read_text())

    def test_unknown_request(self):
        self.assertTrue(self.run_named(agent_home.PREFIX + "{}")
                        .startswith("SKIP"))


class Continue(unittest.TestCase):
    def test_plain_continue_only_counts_when_something_is_interrupted(self):
        self.assertIsNone(agent_home.parse_continue("continue", []))
        self.assertEqual(agent_home.parse_continue("continue", ["Scout"]), "")
        self.assertEqual(
            agent_home.parse_continue("wisp, continue scout.", ["Scout"]),
            "scout")
        self.assertIsNone(
            agent_home.parse_continue("continue ghost", ["Scout"]))
        self.assertIsNone(
            agent_home.parse_continue("continue the report", ["Scout"]))

    def test_route_for_continue_and_run_named_without_one(self):
        with mock.patch.object(agents, "interrupted",
                               return_value=[{"name": "scout",
                                              "agent": "scout"}]):
            route, detail = agent_home.route_for("continue")
        self.assertEqual(route, "agent")
        self.assertEqual(agent_home.decode(detail),
                         {"kind": "continue", "name": ""})
        with tempfile.TemporaryDirectory() as td:
            out = agents.run_named(detail, {}, pathlib.Path(td) / "t.jsonl")
        self.assertIn("nothing is waiting", out)


if __name__ == "__main__":
    unittest.main()
