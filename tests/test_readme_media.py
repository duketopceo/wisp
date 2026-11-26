#!/usr/bin/env python3
"""W33: README images exist, are real files, and stay inside a size budget."""
import pathlib
import re
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MEDIA = ROOT / "assets" / "readme"
BUDGET = 250 * 1024
IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
LINK = re.compile(r"\]\((assets/readme/[^)\s]+\.mp4)\)")
VIDEO_BUDGET = 5 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def linked():
    return [m.group(1) for m in IMG.finditer(README.read_text("utf-8"))]


def videos():
    return LINK.findall(README.read_text("utf-8"))


class ReadmeMedia(unittest.TestCase):
    def test_images_are_linked(self):
        self.assertGreaterEqual(len(linked()), 3)

    def test_every_linked_image_exists_in_budget(self):
        for rel in linked():
            self.assertFalse(rel.startswith(("http:", "https:")),
                             f"{rel}: README images must be local files")
            p = ROOT / rel
            self.assertTrue(p.is_file(), f"missing {rel}")
            self.assertLessEqual(p.stat().st_size, BUDGET,
                                 f"{rel} is over {BUDGET} bytes")

    def test_pngs_are_valid_and_not_tiny(self):
        for rel in linked():
            head = (ROOT / rel).read_bytes()[:24]
            self.assertEqual(head[:8], PNG_MAGIC, f"{rel} is not a PNG")
            w, h = struct.unpack(">II", head[16:24])
            self.assertGreaterEqual(w, 300, rel)
            self.assertGreaterEqual(h, 200, rel)

    def test_hero_video_is_local_and_in_budget(self):
        for rel in videos():
            p = ROOT / rel
            self.assertTrue(p.is_file(), f"missing {rel}")
            self.assertLessEqual(p.stat().st_size, VIDEO_BUDGET, rel)
            self.assertIn(rel.replace(".mp4", ".poster.png"), linked(),
                          "a hero video needs its poster image")

    def test_sheets_come_from_current_snapshot_scenes(self):
        # Each README sheet is composed from goldens that snap.py still
        # renders, and the committed PNG has the layout those goldens give.
        sys.path.insert(0, str(ROOT / "scripts" / "ui"))
        import readme_media
        for name, (_title, rows) in readme_media.SHEETS.items():
            for row in rows:
                for scale, gid, _cap in row:
                    self.assertTrue((readme_media.GOLDEN / scale / f"{gid}.png").is_file(),
                                    f"{name}: no golden {scale}/{gid}")
            rel = f"assets/readme/{name}.png"
            self.assertIn(rel, linked(), f"{rel} is not shown in the README")
            try:
                sheet = readme_media.compose(name)
            except ImportError:
                self.skipTest("Pillow is not installed")
            w, h = struct.unpack(">II", (ROOT / rel).read_bytes()[16:24])
            self.assertEqual((w, h), sheet.size,
                             f"{rel} is stale; run scripts/ui/readme_media.py")

    def test_no_orphans(self):
        names = {pathlib.Path(r).name for r in linked() + videos()}
        found = {p.name for p in MEDIA.glob("*") if p.is_file()}
        self.assertEqual(found - names, set(),
                         "files in assets/readme not linked from README")


if __name__ == "__main__":
    unittest.main()
