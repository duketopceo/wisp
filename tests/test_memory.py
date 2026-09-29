"""U5b: curated memory — add/replace/remove round-trips, bound
enforcement, frozen-snapshot injection."""
import tempfile
import unittest
import pathlib
from unittest import mock

from dim import memory


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


if __name__ == "__main__":
    unittest.main()
