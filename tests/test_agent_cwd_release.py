"""Workspace inference never accepts a truncated title path."""
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import agents


class WorkspaceTitleBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / "Code").mkdir()
        self.project = self.root / "Code Projects" / "wisp"
        self.project.mkdir(parents=True)

    def infer(self, title, app="Cursor", cfg=None):
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": app, "title": title}):
            return agents._infer_cwd(cfg)

    def test_complete_space_containing_project_wins_over_existing_prefix(self):
        self.assertEqual(self.infer(str(self.project)), str(self.project))

    def test_missing_full_path_cannot_be_replaced_by_existing_prefix(self):
        self.assertIsNone(self.infer(str(self.root / "Code Missing" / "absent")))

    def test_known_editor_caption_keeps_full_project(self):
        self.assertEqual(self.infer(f"{self.project} — Cursor"), str(self.project))

    def test_quoted_file_uses_its_actual_parent(self):
        target = self.project / "important notes.txt"
        target.write_text("fixture")
        self.assertEqual(self.infer(f'"{target}" — Cursor'), str(self.project))

    def test_browser_title_is_not_workspace_authority(self):
        self.assertIsNone(self.infer(str(self.project), app="Firefox"))

    def test_explicit_configuration_still_wins(self):
        self.assertEqual(
            self.infer("unrelated", app="Firefox",
                       cfg={"agents": {"cwd": str(self.project)}}),
            str(self.project))
