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
            fn, tier, desc = tools.REGISTRY["skill_echoer"]
            self.assertEqual(tier, "safe")
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
