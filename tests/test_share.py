"""B27: share a lesson, skill or helper as one file, and import it safely."""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import agent_home, cli, config, lessons, routines, share, skills  # noqa: E402

HOME = os.path.expanduser("~")
KEY = "sk-test-SENTINEL-share-77"
MEMORY = "SENTINELMEMORY the user's mother-in-law dislikes cilantro"
INBOX = "SENTINELINBOX call the bank"
OUTPUT = "SENTINELOUTPUT quarterly numbers"


class Sandbox(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.d = pathlib.Path(td.name)
        self.lessons = self.d / "lessons"
        self.skills = self.d / "skills"
        self.agents = self.d / "agents"
        self.manifest = self.d / "imports.json"
        self.store = routines.RoutineStore(self.d / "routines.json")
        self.out = self.d / "out"
        self.out.mkdir()

    # fixtures
    def lesson(self, title="Set up a git remote", step="Open the terminal"):
        dump = {"goal": title, "steps": [
            {"text": step, "label": "terminal",
             "point": {"x": 10, "y": 20, "label": "terminal"}},
            {"text": f"Edit {HOME}/project/config", "label": "",
             "point": None}]}
        return lessons.save(title, dump, root=self.lessons)

    def skill(self, name="git-tips", extra=""):
        d = self.skills / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Git tips\n{extra}---\n"
            f"# {name}\n\nUse `git status` first.\n")
        (d / "notes.md").write_text("A note.\n")
        (d / "run.sh").write_text("#!/bin/sh\necho hi\n")
        return d

    def helper(self, name="Scout"):
        agent_home.create(name, "research helper", root=self.agents)
        h = agent_home.home(name, self.agents)
        (h / "AGENTS.md").write_text(
            f"# {name}\n\nRole: research helper\n\nKeep files in "
            f"{HOME}/Documents/research.\n")
        (h / "notes").mkdir(exist_ok=True)
        (h / "notes" / "2026-10-01.md").write_text(MEMORY + "\n")
        (h / "inbox.md").write_text(INBOX + "\n")
        (h / "output").mkdir(exist_ok=True)
        (h / "output" / "report.md").write_text(OUTPUT + "\n")
        return h

    def apply(self, v, **kw):
        return share.apply(v, lessons_dir=self.lessons,
                           skills_dir=self.skills, agents_root=self.agents,
                           store=self.store, manifest=self.manifest, **kw)


class Export(Sandbox):
    def test_lesson_bundle_has_the_steps_and_no_home_path(self):
        self.lesson()
        b = share.export_lesson("set up a git remote", root=self.lessons)
        self.assertEqual(b["kind"], "lesson")
        self.assertEqual(len(b["payload"]["steps"]), 2)
        text = json.dumps(b)
        if HOME not in ("/", ""):
            self.assertNotIn(HOME, text)
        self.assertIn("~/project/config", text)
        self.assertEqual(b["hash"], share.digest(
            "lesson", b["name"], b["payload"]))
        self.assertTrue(b["hash"].startswith("sha256:"))

    def test_the_hash_ignores_the_date_so_equal_content_is_equal(self):
        self.lesson()
        a = share.export_lesson("set up a git remote", root=self.lessons)
        b = share.make("lesson", a["name"], a["payload"], now=0)
        self.assertEqual(a["hash"], b["hash"])
        self.assertNotEqual(a["created"], b["created"])

    def test_a_key_in_a_lesson_is_refused_naming_where(self):
        self.lesson(step=f"export OPENROUTER_API_KEY={KEY}")
        with self.assertRaises(share.ShareError) as cm:
            share.export_lesson("set up a git remote", root=self.lessons)
        self.assertIn("lesson step 1", str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))

    def test_an_env_secret_value_is_refused(self):
        self.lesson(step="the token is hunter2hunter2")
        with mock.patch.dict(os.environ, {"MY_API_TOKEN": "hunter2hunter2"}):
            with self.assertRaises(share.ShareError) as cm:
                share.export_lesson("set up a git remote",
                                    root=self.lessons)
        self.assertIn("MY_API_TOKEN", str(cm.exception))

    def test_unknown_names_say_so(self):
        for fn, arg in ((share.export_lesson, "nope"),
                        (share.export_skill, "nope"),
                        (share.export_helper, "nope")):
            with self.assertRaises(share.ShareError):
                if fn is share.export_lesson:
                    fn(arg, root=self.lessons)
                elif fn is share.export_skill:
                    fn(arg, base=self.skills)
                else:
                    fn(arg, root=self.agents)

    def test_skill_drops_tool_and_scripts_and_says_so(self):
        self.skill(extra="tool: run.sh\ntier: safe\n")
        b, notes = share.export_skill("git-tips", base=self.skills)
        body = b["payload"]["skill"]
        self.assertNotIn("tool:", body)
        self.assertNotIn("tier:", body)
        self.assertEqual(list(b["payload"]["files"]), ["notes.md"])
        joined = " ".join(notes)
        self.assertIn("`tool:`", joined)
        self.assertIn("run.sh", joined)
        share.check(json.loads(json.dumps(b)))     # and it imports

    def test_helper_has_no_memory_no_inbox_no_output_no_home_path(self):
        self.helper()
        b, notes = share.export_helper("Scout", root=self.agents,
                                       store=self.store)
        text = json.dumps(b)
        for bad in ("SENTINELMEMORY", "SENTINELINBOX", "SENTINELOUTPUT",
                    "cilantro"):
            self.assertNotIn(bad, text)
        if HOME not in ("/", ""):
            self.assertNotIn(HOME, text)
        self.assertIn("~/Documents/research", text)
        self.assertEqual(b["payload"]["routines"], [])
        self.assertIn("notes", " ".join(notes))

    def test_helper_routines_are_only_the_ones_named(self):
        self.helper()
        self.store.save(routines.Routine(id="digest", name="Weekly digest",
                                         task="summarise my week",
                                         schedule="weekly"))
        self.store.save(routines.Routine(id="other", name="Other",
                                         task="private task"))
        b, _ = share.export_helper("Scout", ["digest"], root=self.agents,
                                   store=self.store)
        self.assertEqual([r["name"] for r in b["payload"]["routines"]],
                         ["Weekly digest"])
        self.assertNotIn("private task", json.dumps(b))
        with self.assertRaises(share.ShareError):
            share.export_helper("Scout", ["missing"], root=self.agents,
                                store=self.store)


class Check(Sandbox):
    def bundle(self, kind="skill", **over):
        if kind == "skill":
            self.skill()
            b, _ = share.export_skill("git-tips", base=self.skills)
        elif kind == "lesson":
            self.lesson()
            b = share.export_lesson("set up a git remote",
                                    root=self.lessons)
        else:
            self.helper()
            b, _ = share.export_helper("Scout", root=self.agents,
                                       store=self.store)
        b = json.loads(json.dumps(b))
        b.update(over)
        return b

    def forge(self, b, edit):
        edit(b["payload"])
        b["hash"] = share.digest(b["kind"], b["name"], b["payload"])
        return b

    def test_each_kind_checks_and_returns_its_hash(self):
        for kind in share.KINDS:
            v = share.check(self.bundle(kind))
            self.assertEqual(v["kind"], kind)
            self.assertTrue(v["hash"].startswith("sha256:"))

    def test_a_changed_file_fails_the_hash(self):
        b = self.bundle("lesson")
        b["payload"]["steps"][0]["text"] = "Run something else"
        with self.assertRaises(share.ShareError) as cm:
            share.check(b)
        self.assertIn("hash does not match", str(cm.exception))

    def test_tier_safe_is_rejected_with_the_reason(self):
        b = self.forge(self.bundle(), lambda p: p.update(
            skill="---\nname: x\ndescription: d\ntier: safe\n---\nbody\n"))
        with self.assertRaises(share.ShareError) as cm:
            share.check(b)
        self.assertIn("tier: safe", str(cm.exception))
        self.assertIn("lower", str(cm.exception))

    def test_tier_mutating_is_rejected_but_the_default_tier_is_not(self):
        b = self.forge(self.bundle(), lambda p: p.update(
            skill="---\nname: x\ndescription: d\ntier: mutating\n---\nb\n"))
        with self.assertRaises(share.ShareError):
            share.check(b)
        ok = self.forge(self.bundle(), lambda p: p.update(
            skill="---\nname: x\ndescription: d\ntier: shell\n---\nb\n"))
        share.check(ok)

    def test_a_tool_or_policy_key_is_rejected(self):
        for key in ("tool: run.sh", "confirm: never", "allow_shell: true",
                    "autonomy: autonomous", "policy: open"):
            b = self.forge(self.bundle(), lambda p, key=key: p.update(
                skill=f"---\nname: x\ndescription: d\n{key}\n---\nb\n"))
            with self.assertRaises(share.ShareError, msg=key) as cm:
                share.check(b)
            self.assertIn(key.split(":")[0], str(cm.exception))

    def test_script_and_path_files_never_come_in(self):
        for fn in ("run.sh", "x.py", "../escape.md", "a/b.md", ".hidden.md",
                   "bin"):
            b = self.forge(self.bundle(), lambda p, fn=fn: p.update(
                files={fn: "echo hi"}))
            with self.assertRaises(share.ShareError, msg=fn):
                share.check(b)

    def test_sizes_and_control_characters(self):
        b = self.forge(self.bundle("lesson"), lambda p: p["steps"][0]
                       .update(text="x" * 601))
        with self.assertRaises(share.ShareError):
            share.check(b)
        b = self.forge(self.bundle("lesson"), lambda p: p["steps"][0]
                       .update(text="bell\x07"))
        with self.assertRaises(share.ShareError):
            share.check(b)
        b = self.forge(self.bundle("lesson"), lambda p: p.update(
            steps=[{"text": "a", "label": "", "point": None}] * 41))
        with self.assertRaises(share.ShareError):
            share.check(b)

    def test_bad_points_and_kinds_and_versions(self):
        b = self.forge(self.bundle("lesson"), lambda p: p["steps"][0]
                       .update(point={"x": "no", "y": 1}))
        with self.assertRaises(share.ShareError):
            share.check(b)
        for bad in ({"wisp_bundle": 2}, {"wisp_bundle": 1, "kind": "tool"},
                    [], "x", None):
            with self.assertRaises(share.ShareError):
                share.check(bad)

    def test_too_many_helper_routines(self):
        b = self.forge(self.bundle("helper"), lambda p: p.update(
            routines=[{"name": f"r{i}", "task": "t", "schedule": "daily"}
                      for i in range(6)]))
        with self.assertRaises(share.ShareError):
            share.check(b)

    def test_describe_shows_everything_and_what_it_asks_for(self):
        self.helper()
        self.store.save(routines.Routine(id="digest", name="Weekly digest",
                                         task="summarise my week",
                                         schedule="weekly"))
        b, _ = share.export_helper("Scout", ["digest"], root=self.agents,
                                   store=self.store)
        v = share.check(json.loads(json.dumps(b)))
        text = share.describe(v)
        self.assertIn(v["hash"], text)
        self.assertIn("research helper", text)
        self.assertIn("summarise my week", text)
        self.assertIn("PAUSED", text)
        self.assertIn("runs nothing on import", text)
        self.assertIn("does not change your confirm settings", text)


class Apply(Sandbox):
    def v(self, kind):
        return Check.bundle(self, kind)

    def test_lesson_imports_and_twice_changes_nothing(self):
        v = share.check(self.v("lesson"))
        # export from a different store than the one we import into
        self.lessons = self.d / "lessons2"
        first = self.apply(v)
        self.assertEqual(first["status"], "imported")
        f = pathlib.Path(first["stored"])
        before = (f.read_text(), f.stat().st_mtime_ns)
        second = self.apply(v)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual((f.read_text(), f.stat().st_mtime_ns), before)
        self.assertEqual(len(list(self.lessons.glob("*.json"))), 1)
        self.assertEqual(json.loads(f.read_text())["imported"], v["hash"])

    def test_a_taken_lesson_name_keeps_the_users_own(self):
        b = self.v("lesson")                       # saved in self.lessons
        mine = (self.lessons / (b["name"] + ".json"))
        mine_before = mine.read_text()
        b["payload"]["steps"][0]["text"] = "A different first step"
        b["hash"] = share.digest("lesson", b["name"], b["payload"])
        r = self.apply(share.check(b))
        self.assertEqual(r["status"], "imported")
        self.assertTrue(r["name"].endswith("-imported"))
        self.assertIn("kept yours", r["note"])
        self.assertEqual(mine.read_text(), mine_before)

    def test_skill_imports_with_a_marker_and_never_overwrites(self):
        b = self.v("skill")
        mine = self.skills / "git-tips" / "SKILL.md"
        mine_before = mine.read_text()
        r = self.apply(share.check(b))
        self.assertEqual(r["name"], "git-tips-imported")
        self.assertEqual(mine.read_text(), mine_before)
        new = pathlib.Path(r["stored"])
        self.assertIn(b["hash"], (new / "SKILL.md").read_text())
        self.assertEqual((new / "notes.md").read_text(), "A note.\n")
        self.assertFalse((new / "run.sh").exists())
        again = self.apply(share.check(b))
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(sorted(p.name for p in self.skills.iterdir()),
                         ["git-tips", "git-tips-imported"])

    def test_helper_arrives_with_paused_routines_and_no_timer(self):
        self.helper()
        self.store.save(routines.Routine(id="digest", name="Weekly digest",
                                         task="summarise my week",
                                         schedule="weekly"))
        b, _ = share.export_helper("Scout", ["digest"], root=self.agents,
                                   store=self.store)
        b = json.loads(json.dumps(b))
        other_agents = self.d / "agents2"
        other_store = routines.RoutineStore(self.d / "routines2.json")
        with mock.patch.object(routines, "install_systemd_units") as units, \
                mock.patch("subprocess.run") as run:
            r = share.apply(share.check(b), agents_root=other_agents,
                            store=other_store, manifest=self.manifest)
        units.assert_not_called()
        run.assert_not_called()
        self.assertEqual(r["status"], "imported")
        self.assertTrue((other_agents / "scout" / "AGENTS.md").is_file())
        self.assertIn(b["hash"], (other_agents / "scout" / "AGENTS.md")
                      .read_text())
        self.assertEqual(os.listdir(other_agents / "scout" / "notes"), [])
        rt = other_store.list()
        self.assertEqual(len(rt), 1)
        self.assertTrue(rt[0].paused)
        self.assertFalse(rt[0].enabled)
        self.assertIn("paused", r["note"])
        again = share.apply(share.check(b), agents_root=other_agents,
                            store=other_store, manifest=self.manifest)
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(len(other_store.list()), 1)

    def test_a_taken_helper_name_is_not_overwritten(self):
        b = self.v("helper")
        mine = (agent_home.home("Scout", self.agents) / "AGENTS.md")
        before = mine.read_text()
        r = self.apply(share.check(b))
        self.assertEqual(r["name"], "scout-imported")
        self.assertEqual(mine.read_text(), before)
        self.assertIn("(imported)", (pathlib.Path(r["stored"]) /
                                     "AGENTS.md").read_text())

    def test_nothing_is_executed_on_import(self):
        b = self.v("skill")
        with mock.patch("subprocess.run") as run, \
                mock.patch("subprocess.Popen") as popen, \
                mock.patch("os.system") as system:
            self.apply(share.check(b))
        run.assert_not_called()
        popen.assert_not_called()
        system.assert_not_called()

    def test_a_rejected_bundle_writes_nothing(self):
        b = Check.forge(self, self.v("skill"), lambda p: p.update(
            skill="---\nname: x\ndescription: d\ntier: safe\n---\nb\n"))
        before = sorted(p.name for p in self.skills.iterdir())
        with self.assertRaises(share.ShareError):
            share.check(b)
        self.assertEqual(sorted(p.name for p in self.skills.iterdir()),
                         before)
        self.assertFalse(self.manifest.exists())


class Fetch(unittest.TestCase):
    class _Resp:
        def __init__(self, data):
            self.data = data

        def read(self, n=-1):
            return self.data[:n] if n >= 0 else self.data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def __init__(self, data):
            self.data, self.urls = data, []

        def open(self, req, timeout=None):
            self.urls.append(req.full_url)
            return Fetch._Resp(self.data)

    def test_only_https(self):
        for url in ("http://example.com/x.json", "ftp://x/y",
                    "file:///etc/passwd"):
            with self.assertRaises(share.ShareError):
                share.fetch(url)

    def test_fetch_and_size_cap(self):
        op = self._Opener(b'{"a":1}')
        self.assertEqual(share.fetch("https://example.com/x.json", op),
                         '{"a":1}')
        self.assertEqual(op.urls, ["https://example.com/x.json"])
        with self.assertRaises(share.ShareError):
            share.fetch("https://example.com/big",
                        self._Opener(b"x" * (share.MAX_FETCH + 5)))

    def test_load_from_a_url_and_a_file_and_garbage(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "b.json"
            p.write_text("not json")
            with self.assertRaises(share.ShareError):
                share.load(str(p))
            with self.assertRaises(share.ShareError):
                share.load(str(pathlib.Path(td) / "missing.json"))
        with self.assertRaises(share.ShareError):
            share.load("https://example.com/x", self._Opener(b"[1]"))


class Cli(Sandbox):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(config, "DATA_DIR", self.d),
                  mock.patch.object(skills, "SKILLS_DIR", self.skills),
                  mock.patch.object(share, "IMPORTS", self.manifest),
                  mock.patch.object(routines, "DEFAULT_ROUTINES_FILE",
                                    self.d / "routines.json"),
                  mock.patch.object(lessons, "_dir", lambda: self.lessons)):
            p.start()
            self.addCleanup(p.stop)
        self.cwd = pathlib.Path.cwd()
        os.chdir(self.out)
        self.addCleanup(os.chdir, self.cwd)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(
                err), mock.patch("sys.stdin", io.StringIO("")):
            code = cli.main(list(argv), host=None)
        return code, out.getvalue(), err.getvalue()

    def exported(self, kind="lesson"):
        if kind == "lesson":
            self.lesson()
            code, out, err = self.run_cmd("export", "lesson",
                                          "set up a git remote", "--out",
                                          str(self.out / "l.json"))
        else:
            self.skill()
            code, out, err = self.run_cmd("export", "skill", "git-tips",
                                          "--out", str(self.out / "s.json"))
        self.assertEqual(code, 0, err)
        return json.loads(out and (self.out / (
            "l.json" if kind == "lesson" else "s.json")).read_text())

    def test_export_writes_a_file_and_never_overwrites(self):
        b = self.exported()
        self.assertEqual(b["kind"], "lesson")
        code, out, err = self.run_cmd("export", "lesson",
                                      "set up a git remote", "--out",
                                      str(self.out / "l.json"))
        self.assertEqual(code, 2)
        self.assertIn("exists already", err)

    def test_import_without_a_yes_shows_the_text_and_writes_nothing(self):
        self.exported()
        self.lessons = self.d / "fresh"
        code, out, err = self.run_cmd("import", str(self.out / "l.json"))
        self.assertEqual(code, 0, err)
        self.assertIn("Open the terminal", out)
        self.assertIn("nothing imported", out)
        self.assertIn("--yes --hash sha256:", out)
        self.assertFalse(self.lessons.exists())
        self.assertFalse(self.manifest.exists())
        code, out, _ = self.run_cmd("import", str(self.out / "l.json"),
                                    "--json")
        d = json.loads(out)["data"]
        self.assertEqual(d["status"], "needs_yes")
        self.assertFalse(d["imported"])
        self.assertTrue(d["permissions"])
        self.assertFalse(self.lessons.exists())

    def test_yes_needs_the_hash_of_what_was_read(self):
        self.exported()
        self.lessons = self.d / "fresh"
        code, out, err = self.run_cmd("import", str(self.out / "l.json"),
                                      "--yes")
        self.assertEqual(code, 2)
        self.assertIn("--hash", err)
        code, out, err = self.run_cmd("import", str(self.out / "l.json"),
                                      "--yes", "--hash", "sha256:00")
        self.assertEqual(code, 2)
        self.assertFalse(self.lessons.exists())

    def test_yes_with_the_hash_imports_and_a_repeat_changes_nothing(self):
        b = self.exported()
        self.lessons = self.d / "fresh"
        code, out, err = self.run_cmd("import", str(self.out / "l.json"),
                                      "--yes", "--hash", b["hash"])
        self.assertEqual(code, 0, err)
        self.assertIn("imported lesson", out)
        files = list(self.lessons.glob("*.json"))
        self.assertEqual(len(files), 1)
        before = files[0].read_text()
        code, out, err = self.run_cmd("import", str(self.out / "l.json"),
                                      "--yes", "--hash", b["hash"])
        self.assertEqual(code, 0, err)
        self.assertIn("already imported", out)
        self.assertEqual(files[0].read_text(), before)
        self.assertEqual(len(list(self.lessons.glob("*.json"))), 1)

    def test_a_widening_bundle_is_rejected_with_the_reason(self):
        b = self.exported("skill")
        b["payload"]["skill"] = ("---\nname: x\ndescription: d\n"
                                 "tier: safe\n---\nbody\n")
        b["hash"] = share.digest("skill", b["name"], b["payload"])
        (self.out / "bad.json").write_text(json.dumps(b))
        before = sorted(p.name for p in self.skills.iterdir())
        code, out, err = self.run_cmd("import", str(self.out / "bad.json"),
                                      "--yes", "--hash", b["hash"])
        self.assertEqual(code, 1)
        self.assertIn("tier: safe", err)
        self.assertEqual(sorted(p.name for p in self.skills.iterdir()),
                         before)

    def test_routine_list_pause_resume(self):
        self.store = routines.RoutineStore(self.d / "routines.json")
        self.store.save(routines.Routine(id="r1", name="Digest",
                                         task="t", schedule="daily",
                                         paused=True))
        code, out, _ = self.run_cmd("routine", "list", "--json")
        rows = json.loads(out)["data"]["routines"]
        self.assertEqual(rows[0]["state"], "paused")
        with mock.patch.object(routines, "install_systemd_units",
                               return_value={"scheduled": True}) as u:
            code, out, err = self.run_cmd("routine", "resume", "r1")
        self.assertEqual(code, 0, err)
        u.assert_called_once()
        self.assertFalse(self.store.get("r1").paused)
        code, out, _ = self.run_cmd("routine", "pause", "r1")
        self.assertTrue(self.store.get("r1").paused)
        code, out, err = self.run_cmd("routine", "resume", "missing")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
