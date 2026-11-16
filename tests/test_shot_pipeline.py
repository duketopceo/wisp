#!/usr/bin/env python3
"""The screenshot pipeline encodes once: the normalize pass writes the
model's JPEG beside the PNG, and model_image uses that JPEG instead of
decoding the PNG a second time. A JPEG older than its PNG (the PNG was
changed after normalize) is never used."""
import base64
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import points  # noqa: E402
from wisp.tools import system  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class Sidecar(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.png = self.d / "shot-1.png"
        import struct
        self.png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                             + struct.pack(">II", 3456, 2234))
        self.jpg = pathlib.Path(system._model_jpeg(self.png))

    def tearDown(self):
        for p in self.d.iterdir():
            p.unlink()
        self.d.rmdir()

    def test_a_fresh_sidecar_is_used_without_a_second_encode(self):
        self.jpg.write_bytes(JPEG)
        with mock.patch.object(system.shutil, "which",
                               return_value="/usr/bin/magick"), \
                mock.patch.object(system._cancel, "run") as run:
            url = system.model_image(self.png)
        run.assert_not_called()
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), JPEG)
        self.assertFalse(self.jpg.exists())     # consumed once

    def test_a_sidecar_older_than_its_png_is_ignored(self):
        self.jpg.write_bytes(JPEG)
        old = time.time() - 60
        os.utime(self.jpg, (old, old))

        def run(argv, **kw):
            pathlib.Path(argv[-1]).write_bytes(b"\xff\xd8re-encoded")
            return mock.Mock(returncode=0)
        with mock.patch.object(system.shutil, "which",
                               return_value="/usr/bin/magick"), \
                mock.patch.object(system._cancel, "run",
                                  side_effect=run) as r:
            url = system.model_image(self.png)
        r.assert_called_once()
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]),
                         b"\xff\xd8re-encoded")

    def test_a_truncated_png_header_does_not_crash_normalize(self):
        self.png.write_bytes(b"\x89PNG\r\n\x1a\nshort")
        with mock.patch.object(system.shutil, "which",
                               return_value="/usr/bin/magick"), \
                mock.patch.object(points, "monitors", return_value=[]), \
                mock.patch.object(points, "logical_bbox",
                                  return_value=(0, 0, 1728, 1117)), \
                mock.patch.object(system._cancel, "run",
                                  return_value=mock.Mock(returncode=0)):
            self.assertEqual(system._normalize_shot(self.png), (0, 0))

    def test_normalize_writes_png_and_model_jpeg_in_one_pass(self):
        argv = []

        def run(a, **kw):
            argv.append(a)
            return mock.Mock(returncode=0)
        with mock.patch.object(system.shutil, "which",
                               return_value="/usr/bin/magick"), \
                mock.patch.object(points, "monitors", return_value=[]), \
                mock.patch.object(points, "logical_bbox",
                                  return_value=(0, 0, 1728, 1117)), \
                mock.patch.object(system._cancel, "run", side_effect=run):
            self.assertEqual(system._normalize_shot(self.png), (0, 0))
        self.assertEqual(len(argv), 1)          # one magick process
        a = argv[0]
        self.assertIn("-write", a)
        self.assertEqual(a[a.index("-write") + 1], str(self.png))
        self.assertEqual(a[-1], str(self.jpg))
        self.assertIn("png:compression-level=1", a)
        self.assertIn("1728x1117!", a)


if __name__ == "__main__":
    unittest.main()
