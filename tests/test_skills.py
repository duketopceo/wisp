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
        p = mock.patch.object(skills, "SKILLS_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)

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


if __name__ == "__main__":
    unittest.main()
