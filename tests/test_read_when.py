"""The reference-on-demand table (§4e of the Clicky transfer): a
skill's frontmatter `read:` phrases name the situations that should
make the model reach for a reference file; the index shows the trigger,
`skill_view name:refs/x.md` reads the file, and the path stays inside
the skill dir."""

import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import skills


class ReadWhenTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()) / "skills"
        p = mock.patch.object(skills, "SKILLS_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)
        d = self.dir / "alpha"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: post to the tracker\n"
            "read: about to send, post or buy | a form with many fields\n---\nbody")
        (d / "refs").mkdir()
        (d / "refs" / "confirmations.md").write_text("# confirmations\nstop and check")

    def test_index_names_the_trigger(self):
        text = skills.index_text()
        self.assertIn("read it when: about to send, post or buy; "
                      "a form with many fields", text)

    def test_phrases_survive_commas_inside_one_item(self):
        meta = skills.index()[0]
        self.assertEqual(meta["read"],
                         ["about to send, post or buy", "a form with many fields"])

    def test_view_reads_a_reference_file(self):
        self.assertEqual(skills.view("alpha:refs/confirmations.md"),
                         "# confirmations\nstop and check")

    def test_view_refuses_traversal_and_absolute_paths(self):
        self.assertIn("FAIL", skills.view("alpha:../../etc/passwd"))
        self.assertIn("FAIL", skills.view("alpha:/etc/passwd"))

    def test_view_reports_a_missing_reference(self):
        self.assertIn("FAIL", skills.view("alpha:refs/nope.md"))

    def test_plain_view_still_works(self):
        self.assertIn("body", skills.view("alpha"))

    def test_pulls_tools_still_splits_on_commas(self):
        d = self.dir / "beta"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: beta\ndescription: e\npulls_tools: gh, git\n---\nb")
        beta = next(s for s in skills.index() if s["name"] == "beta")
        self.assertEqual(beta["pulls_tools"], ["gh", "git"])


if __name__ == "__main__":
    unittest.main()
