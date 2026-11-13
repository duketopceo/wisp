"""U5b: curated memory — add/replace/remove round-trips, bound
enforcement, frozen-snapshot injection."""
import io
import contextlib
import tempfile
import unittest
import pathlib
import re
from unittest import mock

from wisp import memory
from wisp import skills
from wisp.cli import settings as settings_cli
from wisp.cli.registry import Ctx, Flags


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.mf = self.tmp / "MEMORY.md"
        self.uf = self.tmp / "USER.md"
        p1 = mock.patch.object(memory, "MEMORY_FILE", self.mf)
        p2 = mock.patch.object(memory, "USER_FILE", self.uf)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_add_creates_and_appends(self):
        self.assertTrue(memory.run("memory|add|user likes coffee")
                        .startswith("OK"))
        self.assertIn("- user likes coffee", self.mf.read_text())

    def test_replace_rewrites_matching_line(self):
        memory.run("memory|add|theme is dark")
        memory.run("memory|replace|theme|theme is tokyo-night")
        text = self.mf.read_text()
        self.assertIn("tokyo-night", text)
        self.assertNotIn("is dark", text)

    def test_remove_drops_matching_line(self):
        memory.run("memory|add|temp note")
        memory.run("memory|remove|temp note")
        self.assertNotIn("temp note", self.mf.read_text())

    def test_missing_match_fails_cleanly(self):
        self.assertIn("FAIL", memory.run("memory|remove|nonexistent"))

    def test_user_file_is_separate(self):
        memory.run("user|add|name is Luke")
        self.assertIn("name is Luke", self.uf.read_text())
        self.assertFalse(self.mf.exists() and
                         "name is Luke" in self.mf.read_text())

    def test_bad_target_and_op_fail(self):
        self.assertIn("FAIL", memory.run("bogus|add|x"))
        self.assertIn("FAIL", memory.run("memory|frob|x"))

    def test_budget_enforced(self):
        big = "x" * (memory.MEMORY_BUDGET + 100)
        self.assertIn("FAIL", memory.run(f"memory|add|{big}"))
        self.assertNotIn(big, self.mf.read_text() if self.mf.exists() else "")

    def test_write_replaces_body_keeps_head(self):
        memory.run("memory|add|old fact")
        # GUI path — body arg carries the full post-header text
        out = memory.edit("memory", "write", "", "- a\n- b\n")
        self.assertTrue(out.startswith("OK"))
        text = self.mf.read_text()
        self.assertIn("- a\n- b", text)
        self.assertNotIn("old fact", text)
        self.assertTrue(text.lstrip().startswith("#"))

    def test_write_bounded(self):
        big = "x" * (memory.MEMORY_BUDGET + 100)
        self.assertIn("FAIL", memory.edit("memory", "write", "", big))

    def test_snapshot_empty_when_no_content(self):
        self.assertEqual(memory.snapshot(), "")

    def test_snapshot_includes_both_files(self):
        memory.run("memory|add|prefers vim")
        memory.run("user|add|uses omarchy")
        snap = memory.snapshot()
        self.assertIn("[memory]", snap)
        self.assertIn("prefers vim", snap)
        self.assertIn("[user]", snap)
        self.assertIn("uses omarchy", snap)

    def test_sync_unconfigured_leaves_existing_bytes(self):
        original = b"# Memory\n\n- keep this\n"
        self.mf.write_bytes(original)
        for path in (None, ""):
            out = memory.sync_constitution(path)
            self.assertIn("not configured", out)
            self.assertEqual(self.mf.read_bytes(), original)

    def test_sync_unconfigured_does_not_create_memory(self):
        self.assertFalse(self.mf.exists())
        out = memory.sync_constitution(None)
        self.assertIn("not configured", out)
        self.assertFalse(self.mf.exists())
        out = memory.sync_constitution("")
        self.assertIn("not configured", out)
        self.assertFalse(self.mf.exists())

    def test_sync_configured_writes_file_lines_once(self):
        const = self.tmp / "constitution.md"
        const.write_text("speaks plainly\n\nkeeps notes\n")
        first = memory.sync_constitution(str(const))
        self.assertTrue(first.startswith("OK"))
        text = self.mf.read_text()
        self.assertIn("## constitution\n", text)
        self.assertIn("## /constitution\n", text)
        self.assertIn("- speaks plainly\n", text)
        self.assertIn("- keeps notes\n", text)
        self.assertNotIn("luke-agents", text)
        second = memory.sync_constitution(str(const))
        self.assertTrue(second.startswith("OK"))
        again = self.mf.read_text()
        self.assertEqual(again.count("## constitution"), 1)
        self.assertEqual(again.count("- speaks plainly"), 1)
        self.assertEqual(again.count("- keeps notes"), 1)

    def test_sync_replaces_luke_agents_block(self):
        self.mf.write_text(
            "# Memory\n\n"
            "## luke-agents\n"
            "- old private fact\n"
            "## /luke-agents\n"
        )
        const = self.tmp / "constitution.md"
        const.write_text("one public fact\n")
        out = memory.sync_constitution(str(const))
        self.assertTrue(out.startswith("OK"))
        text = self.mf.read_text()
        self.assertNotIn("luke-agents", text)
        self.assertNotIn("old private fact", text)
        self.assertEqual(text.count("## constitution"), 1)
        self.assertIn("- one public fact", text)
        self.assertIn("## /constitution", text)

    def test_sync_keeps_unrelated_bullet(self):
        self.mf.write_text("# Memory\n\n- user likes tea\n")
        const = self.tmp / "constitution.md"
        const.write_text("uses a fountain pen\n")
        out = memory.sync_constitution(str(const))
        self.assertTrue(out.startswith("OK"))
        text = self.mf.read_text()
        self.assertIn("- user likes tea", text)
        self.assertIn("- uses a fountain pen", text)

    def test_sync_missing_constitution_names_path_and_does_not_write(self):
        missing = self.tmp / "no-such-constitution.md"
        original = b"# Memory\n\n- stay\n"
        self.mf.write_bytes(original)
        out = memory.sync_constitution(str(missing))
        self.assertIn("FAIL", out)
        self.assertIn(str(missing), out)
        self.assertEqual(self.mf.read_bytes(), original)
        self.mf.unlink()
        out = memory.sync_constitution(str(missing))
        self.assertIn("FAIL", out)
        self.assertIn(str(missing), out)
        self.assertFalse(self.mf.exists())

    def test_sync_unreadable_memory_fails_without_writing(self):
        self.mf.mkdir()
        const = self.tmp / "constitution.md"
        const.write_text("a fact\n")
        out = memory.sync_constitution(str(const))
        self.assertIn("FAIL", out)
        self.assertIn(str(self.mf), out)
        self.assertEqual(list(self.mf.iterdir()), [])

    def test_sync_unterminated_region_fails_without_writing(self):
        # A begin marker with no end would swallow every line after it; the
        # sync must refuse rather than persist that loss.
        original = "# Memory\n\n- keep me\n- also keep\n" + memory._SYNC_BEGIN + "\n- managed\n"
        self.mf.write_text(original, encoding="utf-8")
        const = self.tmp / "constitution.md"
        const.write_text("a fact\n")
        out = memory.sync_constitution(str(const))
        self.assertIn("FAIL", out)
        self.assertEqual(self.mf.read_text(encoding="utf-8"), original)

    def test_sync_over_budget_does_not_write(self):
        original = b"# Memory\n\n- keep me\n"
        self.mf.write_bytes(original)
        const = self.tmp / "huge.md"
        const.write_text("fact line\n" * 800)
        out = memory.sync_constitution(str(const))
        self.assertIn("FAIL", out)
        self.assertEqual(self.mf.read_bytes(), original)

    def _run_sync(self, cfg, repo=None):
        ctx = Ctx(Flags())
        ctx._cfg = cfg
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = settings_cli.sync(ctx, mock.Mock(constitution=repo))
        return rc, buf.getvalue()

    def test_sync_import_dir_unset_copies_nothing(self):
        installed = self.tmp / "installed"
        installed.mkdir()
        with mock.patch.object(skills, "SKILLS_DIR", installed):
            rc, text = self._run_sync({"memory": {}, "skills": {}})
        self.assertEqual(rc, 0)
        self.assertIn("not configured", text)
        self.assertEqual(list(installed.iterdir()), [])
        self.assertFalse(self.mf.exists())

    def test_sync_import_dir_imports_one_skill_tree(self):
        src = self.tmp / "skill-src"
        (src / "demo").mkdir(parents=True)
        (src / "demo" / "SKILL.md").write_text("# demo\n")
        installed = self.tmp / "installed"
        installed.mkdir()
        with mock.patch.object(skills, "SKILLS_DIR", installed):
            rc, text = self._run_sync(
                {"memory": {}, "skills": {"import_dir": str(src)}})
        self.assertEqual(rc, 0)
        self.assertIn("imported", text)
        self.assertTrue((installed / "demo" / "SKILL.md").is_file())

    def test_positional_overrides_constitution_not_skill_dir(self):
        configured = self.tmp / "configured.md"
        configured.write_text("from config\n")
        override = self.tmp / "override.md"
        override.write_text("from positional\n")
        skill_root = self.tmp / "positional-skills"
        (skill_root / "demo").mkdir(parents=True)
        (skill_root / "demo" / "SKILL.md").write_text("# demo\n")
        installed = self.tmp / "installed"
        installed.mkdir()
        with mock.patch.object(skills, "SKILLS_DIR", installed):
            rc, text = self._run_sync(
                {"memory": {"constitution": str(configured)},
                 "skills": {}},
                repo=str(override))
        self.assertEqual(rc, 0)
        body = self.mf.read_text()
        self.assertIn("- from positional", body)
        self.assertNotIn("from config", body)
        self.assertIn("not configured", text)
        self.assertFalse((installed / "demo").exists())
        with mock.patch.object(skills, "SKILLS_DIR", installed):
            rc, text = self._run_sync(
                {"memory": {"constitution": str(configured)},
                 "skills": {}},
                repo=str(skill_root))
        self.assertEqual(rc, 0)
        self.assertIn("FAIL", text)
        self.assertIn(str(skill_root), text)
        self.assertIn("not configured", text)
        self.assertFalse((installed / "demo").exists())
        stayed = self.mf.read_text()
        self.assertIn("- from positional", stayed)
        self.assertNotIn("from config", stayed)

    def test_sync_help_golden_names_no_private_checkout(self):
        golden = (pathlib.Path(__file__).resolve().parents[1]
                  / "tests" / "golden" / "cli_help" / "sync.txt")
        text = golden.read_text()
        self.assertNotIn("luke-agents", text)
        self.assertNotIn("standard location", text)
        self.assertNotIn("Documents/github", text)

    def test_daemon_start_passes_configured_constitution(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "wispd").read_text()
        start = src.index("def run_daemon")
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        self.assertNotIn("luke-agents", body)
        self.assertNotIn("Documents/github/personal", body)
        self.assertIsNone(re.search(r"sync_constitution\(\s*\)", body))
        self.assertIn("constitution", body)
        self.assertRegex(body, r"""cfg\.get\(\s*["']memory["']\s*\)""")


if __name__ == "__main__":
    unittest.main()
