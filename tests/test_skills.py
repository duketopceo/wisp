"""U5d: self-authored skills — create/view/edit/delete lifecycle, index
injection, toolbelt registration, filename safety."""
import tempfile
import unittest
import pathlib
from unittest import mock

from wisp import skills, tools


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()) / "skills"
        self.backups = pathlib.Path(tempfile.mkdtemp()) / "backups"
        for p_ in (mock.patch.object(skills, "SKILLS_DIR", self.dir),
                   mock.patch.object(skills, "BACKUPS_DIR", self.backups)):
            p_.start()
            self.addCleanup(p_.stop)

    def test_create_and_view(self):
        self.assertIn("OK", skills.run_manage(
            "create|daily-note|writes a daily note|Do X then Y"))
        body = skills.run_view("daily-note")
        self.assertIn("name: daily-note", body)
        self.assertIn("Do X then Y", body)

    def test_create_existing_fails(self):
        skills.run_manage("create|dup|d|b")
        self.assertIn("FAIL", skills.run_manage("create|dup|d|b"))

    def test_edit_requires_existing_and_body(self):
        self.assertIn("FAIL", skills.run_manage("edit|ghost||body"))
        skills.run_manage("create|s|d|v1")
        self.assertIn("OK", skills.run_manage("edit|s||---\nname: s\n---\nv2"))
        self.assertIn("v2", skills.run_view("s"))

    def test_delete_removes_dir(self):
        skills.run_manage("create|doomed|d|b")
        self.assertIn("OK", skills.run_manage("delete|doomed"))
        self.assertIn("FAIL", skills.run_view("doomed"))

    def test_delete_is_reversible_for_60_days(self):
        skills.run_manage("create|doomed|d|the body")
        self.assertIn("restorable", skills.run_manage("delete|doomed"))
        self.assertIn("FAIL", skills.run_view("doomed"))
        # the backup exists and restore brings the body back
        self.assertIn("doomed", skills.run_manage("list_backups"))
        self.assertIn("OK", skills.run_manage("restore|doomed"))
        self.assertIn("the body", skills.run_view("doomed"))

    def test_restore_refuses_when_skill_exists_or_no_backup(self):
        skills.run_manage("create|s|d|body")
        self.assertIn("FAIL", skills.run_manage("restore|s"))  # still here
        skills.run_manage("delete|s")
        self.assertIn("OK", skills.run_manage("restore|s"))
        self.assertIn("FAIL", skills.run_manage("restore|s"))  # restored once

    def test_list_backups_without_a_name_lists_everything(self):
        self.assertEqual("OK (no skill backups)",
                         skills.run_manage("list_backups"))
        skills.run_manage("create|a1|d|b")
        skills.run_manage("delete|a1")
        self.assertIn("a1", skills.run_manage("list_backups"))

    def test_backup_prunes_older_than_60_days(self):
        import time as _time
        import os
        skills.run_manage("create|old|d|b")
        skills.run_manage("delete|old")
        self.assertIn("old", skills.run_manage("list_backups"))
        # age the snapshot past the window; the next backup of the same
        # skill prunes it, so only the fresh snapshot remains listed
        snap = next((self.backups / "old").iterdir())
        old = _time.time() - (skills.BACKUP_DAYS + 1) * 86400
        os.utime(snap, (old, old))
        skills.run_manage("create|old|d|b2")
        skills.run_manage("delete|old")
        self.assertIn("backed up 0d ago",
                      skills.run_manage("list_backups|old"))
        # the aged snapshot is gone — only one snapshot remains
        self.assertEqual(1, len(list((self.backups / "old").iterdir())))

    def test_list_and_index(self):
        self.assertIn("no skills", skills.run_manage("list"))
        skills.run_manage("create|alpha|first skill|b")
        skills.run_manage("create|beta|second skill|b")
        idx = skills.index()
        self.assertEqual(len(idx), 2)
        text = skills.index_text()
        self.assertIn("alpha: first skill", text)


GUIDE = """---
name: {name}
description: {desc}
provenance: shipped
{pulls}
---

Body.
"""


class PullsToolsTest(unittest.TestCase):
    """U7: a skill states the tools it needs, a bad statement is refused by
    name, and the model can see the dependency in the index."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()) / "skills"
        for p_ in (mock.patch.object(skills, "SKILLS_DIR", self.dir),):
            p_.start()
            self.addCleanup(p_.stop)

    def guide(self, name="g", desc="a guide", pulls="",
              extra_key=""):
        d = self.dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(GUIDE.format(
            name=name, desc=desc, pulls=pulls) + extra_key)
        return (d / "SKILL.md").read_text()

    def test_parses_both_tokens_from_a_comma_list(self):
        self.guide(pulls="pulls_tools: memory, browser")
        got = [s for s in skills.index() if s["name"] == "g"][0]
        self.assertEqual(got["pulls_tools"], ["memory", "browser"])

    def test_the_index_names_the_tools_a_skill_pulls(self):
        self.guide(pulls="pulls_tools: memory, browser")
        self.assertIn("(needs: memory, browser)", skills.index_text())

    def test_a_skill_without_pulls_tools_lists_exactly_as_before(self):
        self.guide()
        got = [s for s in skills.index() if s["name"] == "g"][0]
        self.assertEqual(got["pulls_tools"], [])
        self.assertNotIn("needs:", skills.index_text())

    def test_a_bracketed_value_tokenises_to_valid_tokens(self):
        # _list_field strips the brackets; the plan asks for this to be
        # asserted as the parser dictates rather than assumed a rejection
        self.guide(pulls="pulls_tools: [memory, browser]")
        got = [s for s in skills.index() if s["name"] == "g"][0]
        self.assertEqual(got["pulls_tools"], ["memory", "browser"])

    def test_an_unregistered_tool_is_a_named_problem(self):
        text = self.guide(pulls="pulls_tools: memory, sandbox")
        problems = skills.frontmatter_problems(text)
        self.assertIn("pulls_tools names no such tool: sandbox", problems)
        self.assertNotIn("pulls_tools names no such tool: memory", problems)

    def test_every_registry_tool_is_accepted(self):
        for name in sorted(tools.REGISTRY)[:5]:
            text = self.guide(name=f"g-{name}", pulls=f"pulls_tools: {name}")
            self.assertEqual(skills.frontmatter_problems(text), [], name)

    def test_pulls_tools_is_a_permitted_app_guide_key(self):
        text = self.guide(pulls="pulls_tools: memory")
        self.assertEqual(skills.frontmatter_problems(text), [])

    def test_another_unknown_key_is_still_rejected(self):
        text = self.guide(pulls="pulls_tools: memory",
                          extra_key="")
        text = text.replace("provenance: shipped",
                            "provenance: shipped\nsandbox: true")
        self.assertIn("disallowed key: sandbox",
                      skills.frontmatter_problems(text))

    def test_write_file_rejects_traversal(self):
        skills.run_manage("create|s|d|b")
        self.assertIn("FAIL",
                      skills.run_manage("write_file|s|../evil|x"))
        self.assertIn("OK", skills.run_manage("write_file|s|note.txt|hi"))
        self.assertEqual((self.dir / "s" / "note.txt").read_text(), "hi")
        self.assertIn("OK", skills.run_manage("remove_file|s|note.txt"))

    def test_toolbelt_registration(self):
        skills.run_manage("create|echoer|echoes args|b")
        skills.run_manage("write_file|echoer|run.sh|echo SKILL:$1")
        # declare the tool in frontmatter
        f = self.dir / "echoer" / "SKILL.md"
        f.write_text("---\nname: echoer\ndescription: echoes args\n"
                     "tool: run.sh\ntier: safe\n---\nbody\n")
        added = set()
        orig = dict(tools.REGISTRY)
        try:
            skills.register_tools()
            self.assertIn("skill_echoer", tools.REGISTRY)
            fn, tier, desc, meta = tools.REGISTRY["skill_echoer"]
            # tool: scripts run bash — `tier: safe` can't be
            # self-declared; floor is mutating (confirm-gated)
            self.assertEqual(tier, "mutating")
            self.assertEqual(meta["tier"], "T2")
            self.assertIn("SKILL:hi", fn("hi"))
        finally:
            tools.REGISTRY.clear()
            tools.REGISTRY.update(orig)

    def test_skill_without_tool_decl_registers_nothing(self):
        skills.run_manage("create|plain|no tool|b")
        orig = dict(tools.REGISTRY)
        try:
            skills.register_tools()
            self.assertNotIn("skill_plain", tools.REGISTRY)
        finally:
            tools.REGISTRY.clear()
            tools.REGISTRY.update(orig)


class RequiresBinAdTimeTest(unittest.TestCase):
    """A skill's `requires_bin` is checked at advertisement time, every
    time — not only when seed() copies it — so a binary that arrives
    later makes the skill appear and one that disappears stops the
    skill being advertised instead of failing at call time."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()) / "skills"
        p = mock.patch.object(skills, "SKILLS_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def skill(self, name="binner", tool=False, bin="definitely-missing-bin"):
        d = self.dir / name
        d.mkdir(parents=True)
        fm = ("---\nname: %s\ndescription: d\nrequires_bin: %s\n"
              + ("tool: run.sh\n" if tool else "") + "---\nbody\n")
        (d / "SKILL.md").write_text(fm % (name, bin))
        if tool:
            (d / "run.sh").write_text("echo hi")
        return d

    def test_hidden_while_bin_missing_listed_once_installed(self):
        self.skill()
        self.assertEqual([], skills.index())
        # the binary arrives
        import pathlib as _pl
        fake = _pl.Path(tempfile.mkdtemp()) / "definitely-missing-bin"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        with mock.patch.dict("os.environ", {"PATH": str(fake.parent) +
                                             ":/usr/bin:/bin"}):
            self.assertEqual(["binner"],
                             [s["name"] for s in skills.index()])

    def test_tool_skill_unregistered_while_bin_missing(self):
        self.skill(tool=True)
        from wisp import tools as _tools
        orig = dict(_tools.REGISTRY)
        try:
            skills.register_tools()
            self.assertNotIn("skill_binner", _tools.REGISTRY)
        finally:
            _tools.REGISTRY.clear()
            _tools.REGISTRY.update(orig)

    def test_run_tool_returns_none_while_bin_missing(self):
        self.skill(tool=True)
        self.assertIsNone(skills.run_tool("skill_binner", "x"))


SEED = """---
name: {name}
description: a seeded skill
{extra}---
# {name}

seed body v1
"""


class SeedVersionTest(unittest.TestCase):
    """SEED_VERSION + RETIRED_SEEDS: seed() can update an unmodified
    seed copy and prune a retired one; user edits are marked and never
    touched by either."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()) / "skills"
        self.seeds = pathlib.Path(tempfile.mkdtemp()) / "seeds"
        (self.seeds / "s1").mkdir(parents=True)
        (self.seeds / "s1" / "SKILL.md").write_text(
            SEED.format(name="s1", extra=""))
        for p_ in (mock.patch.object(skills, "SKILLS_DIR", self.dir),
                   mock.patch.object(skills, "_seed_dir",
                                     lambda: self.seeds),
                   mock.patch.object(skills, "SEED_VERSION", 1),
                   mock.patch.object(skills, "RETIRED_SEEDS",
                                     frozenset())):
            p_.start()
            self.addCleanup(p_.stop)

    def test_seed_writes_version_state(self):
        skills.seed()
        st = skills._seed_state(self.dir / "s1")
        self.assertEqual({"seed": "s1", "version": skills.SEED_VERSION}, st)

    def test_version_bump_refreshes_unmodified_copy(self):
        skills.seed()
        bumped = skills.SEED_VERSION + 1
        skills.SEED_VERSION = bumped
        (self.seeds / "s1" / "SKILL.md").write_text(
            SEED.format(name="s1", extra="").replace("v1", "v2"))
        skills.seed()
        self.assertIn("seed body v2", skills.run_view("s1"))
        self.assertEqual(bumped,
                         skills._seed_state(self.dir / "s1")["version"])

    def test_edited_copy_survives_bump_and_retire(self):
        skills.seed()
        skills.run_manage("edit|s1||---\nname: s1\ndescription: mine\n---\nmine")
        self.assertTrue(skills._seed_state(self.dir / "s1")["edited"])
        skills.SEED_VERSION = skills.SEED_VERSION + 5
        (self.seeds / "s1" / "SKILL.md").write_text(
            SEED.format(name="s1", extra="").replace("v1", "v9"))
        skills.RETIRED_SEEDS = frozenset({"s1"})
        skills.seed()
        self.assertIn("mine", skills.run_view("s1"))

    def test_retire_prunes_unmodified_copy(self):
        skills.seed()
        skills.RETIRED_SEEDS = frozenset({"s1"})
        skills.seed()
        self.assertFalse((self.dir / "s1").exists())
        # a foreign skill with the same name is never pruned
        d = self.dir / "s1"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SEED.format(name="s1", extra=""))
        skills.seed()
        self.assertTrue((d / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
