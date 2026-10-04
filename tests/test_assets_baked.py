#!/usr/bin/env python3
"""Baked shaders (W21, Ember U7): the committed .qsb must match its .frag.

assets/shaders/<name>.frag is the source; scripts/assets/bake_shaders.sh
bakes it into shell-plugin/shaders/<name>.frag.qsb (the directory the
installer copies) and records the source hash in <name>.frag.sha256. The
hash test always runs; the compile test needs qsb and is skipped without.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "shaders"
OUT = ROOT / "shell-plugin" / "shaders"
QSB = shutil.which("qsb") or (
    "/usr/lib/qt6/bin/qsb" if os.path.exists("/usr/lib/qt6/bin/qsb") else None)


class TestBakedShaders(unittest.TestCase):
    def frags(self):
        got = sorted(SRC.glob("*.frag"))
        self.assertTrue(got, "no shader sources")
        return got

    def test_every_source_is_baked(self):
        for f in self.frags():
            self.assertTrue((OUT / (f.name + ".qsb")).is_file(),
                            f"{f.name}: run scripts/assets/bake_shaders.sh")

    def test_recorded_hash_matches_source(self):
        for f in self.frags():
            want = hashlib.sha256(f.read_bytes()).hexdigest()
            rec = (SRC / (f.name + ".sha256")).read_text().strip()
            self.assertEqual(rec, want,
                             f"{f.name} changed: rebake with "
                             "scripts/assets/bake_shaders.sh")

    def test_no_orphan_qsb(self):
        names = {f.name + ".qsb" for f in self.frags()}
        have = {p.name for p in OUT.glob("*.qsb")}
        self.assertEqual(have - names, set())

    def test_check_flag_agrees(self):
        p = subprocess.run([str(ROOT / "scripts/assets/bake_shaders.sh"),
                            "--check"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    @unittest.skipUnless(QSB, "qsb not installed")
    def test_source_compiles(self):
        for f in self.frags():
            with tempfile.TemporaryDirectory() as d:
                out = pathlib.Path(d) / "x.qsb"
                p = subprocess.run([QSB, "--qt6", "-o", str(out), str(f)],
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertGreater(out.stat().st_size, 100)

    def test_shader_stays_small(self):
        # one small shader (DESIGN-v2 7): keep the source lean
        for f in self.frags():
            body = [ln for ln in f.read_text().splitlines()
                    if ln.strip() and not ln.strip().startswith("//")]
            self.assertLess(len(body), 90, f.name)


if __name__ == "__main__":
    unittest.main()
