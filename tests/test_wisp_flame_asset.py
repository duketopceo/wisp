"""The Wisp flame brand asset (assets/brand/wisp-flame): valid exports within budget.

The glTF is checked by parsing its binary header and JSON chunk directly, so
no 3D library is needed; loops and stills are read with Pillow.
"""
import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSET = ROOT / "assets" / "brand" / "wisp-flame"
EXPORT = ASSET / "export"
STATES = ("idle", "listening", "thinking", "speaking")
KB = 1024

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is a test dependency
    Image = None


def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack("<4sII", data[:12])
    chunk_len, chunk_type = struct.unpack("<I4s", data[12:20])
    return magic, version, length, len(data), chunk_type, json.loads(data[20:20 + chunk_len])


class GltfTest(unittest.TestCase):
    def setUp(self):
        self.magic, self.version, self.length, self.size, self.ctype, self.gltf = read_glb(
            EXPORT / "wisp-flame.glb")

    def test_is_binary_gltf_2(self):
        self.assertEqual(self.magic, b"glTF")
        self.assertEqual(self.version, 2)
        self.assertEqual(self.length, self.size)
        self.assertEqual(self.ctype, b"JSON")

    def test_has_exactly_the_four_state_animations(self):
        names = sorted(a["name"] for a in self.gltf["animations"])
        self.assertEqual(names, sorted(STATES))

    def test_states_were_not_merged_into_one_object(self):
        for anim in self.gltf["animations"]:
            nodes = {c["target"]["node"] for c in anim["channels"]}
            self.assertGreater(len(nodes), 1, anim["name"])

    def test_shell_carries_the_bend_morph_target(self):
        targets = [len(p.get("targets", [])) for m in self.gltf["meshes"] for p in m["primitives"]]
        self.assertGreaterEqual(max(targets), 1)
        paths = {c["target"]["path"] for a in self.gltf["animations"] for c in a["channels"]}
        self.assertIn("weights", paths)

    def test_heart_glows_and_is_opaque_under_a_blended_shell(self):
        mats = {m["name"]: m for m in self.gltf["materials"]}
        self.assertEqual(mats["shell"].get("alphaMode"), "BLEND")
        self.assertEqual(mats["heart"].get("alphaMode", "OPAQUE"), "OPAQUE")
        self.assertTrue(any(mats["heart"].get("emissiveFactor") or [0]))


@unittest.skipIf(Image is None, "Pillow not installed")
class LoopsAndStillsTest(unittest.TestCase):
    def test_every_state_has_animated_alpha_loops_at_both_sizes(self):
        for state in STATES:
            for size in (64, 256):
                path = EXPORT / "loops" / f"{state}-{size}.webp"
                with Image.open(path) as im:
                    self.assertEqual(im.size, (size, size), path.name)
                    self.assertTrue(getattr(im, "is_animated", False), path.name)
                    self.assertEqual(im.n_frames, 48, path.name)
                    self.assertEqual(im.convert("RGBA").getextrema()[3][0], 0, f"{path.name} has no transparency")

    def test_stills_exist_at_the_small_and_hero_sizes_with_alpha(self):
        for size in (20, 32, 130, 512):
            path = EXPORT / "stills" / f"wisp-flame-{size}.png"
            with Image.open(path) as im:
                self.assertEqual(im.size, (size, size))
                self.assertEqual(im.mode, "RGBA")


def load_assembler():
    path = ROOT / "scripts" / "brand" / "assemble_wisp_flame.py"
    spec = importlib.util.spec_from_file_location("assemble_wisp_flame", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(Image is None, "Pillow not installed")
class AssembleTest(unittest.TestCase):
    """Runs the assembler on a tiny synthetic render (no Blender needed)."""

    def setUp(self):
        self.asm = load_assembler()
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.render = self.tmp / "render"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def frame(self, size, offset=0):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        c = size // 2 + offset
        im.paste((230, 245, 255, 255), (c - size // 16, c - size // 16, c + size // 16, c + size // 16))
        return im

    def fake_render(self, states=STATES):
        for state in states:
            d = self.render / "frames" / state
            d.mkdir(parents=True)
            for i in range(3):
                self.frame(256, i).save(d / f"{i:04d}.png")
        self.frame(512).save(self.render / "still-512.png")

    def test_writes_loops_and_stills_at_every_size(self):
        self.fake_render()
        out = self.tmp / "export"
        self.asm.main(self.render, out)
        for state in STATES:
            for size in (64, 256):
                with Image.open(out / "loops" / f"{state}-{size}.webp") as im:
                    self.assertEqual(im.size, (size, size))
                    self.assertEqual(im.n_frames, 3)
                    self.assertEqual(im.convert("RGBA").getpixel((0, 0))[3], 0, "corner must stay transparent")
        for size in (20, 32, 130, 512):
            with Image.open(out / "stills" / f"wisp-flame-{size}.png") as im:
                self.assertEqual(im.size, (size, size))

    def test_bloom_glows_around_the_bright_heart_and_keeps_the_heart(self):
        src = self.frame(256)
        out = self.asm.bloom(src)
        near = (256 // 2 + 256 // 16 + 6, 256 // 2)  # just outside the bright square
        self.assertEqual(src.getpixel(near)[3], 0)
        r, g, b, a = out.getpixel(near)
        self.assertGreater(a, 0, "bloom adds alpha around the heart")
        self.assertGreater(b, r, "the glow is tinted cyan")
        self.assertEqual(out.getpixel((128, 128))[3], 255)
        self.assertEqual(out.getpixel((0, 0))[3], 0)

    def test_missing_state_frames_exit(self):
        self.fake_render(states=STATES[:-1])
        with self.assertRaises(SystemExit):
            self.asm.main(self.render, self.tmp / "export")


class BudgetTest(unittest.TestCase):
    def assert_under(self, path, kb):
        self.assertLessEqual(path.stat().st_size, kb * KB, f"{path.relative_to(ROOT)} over {kb} KB")

    def test_each_file_is_within_its_budget(self):
        self.assert_under(EXPORT / "wisp-flame.glb", 1536)
        self.assert_under(ASSET / "source" / "wisp-flame.blend", 5 * 1024)
        for state in STATES:
            self.assert_under(EXPORT / "loops" / f"{state}-256.webp", 400)
            self.assert_under(EXPORT / "loops" / f"{state}-64.webp", 120)

    def test_the_whole_asset_folder_is_at_most_10_mb(self):
        total = sum(p.stat().st_size for p in ASSET.rglob("*") if p.is_file())
        self.assertLessEqual(total, 10 * 1024 * KB)


class ReadmeTest(unittest.TestCase):
    def test_readme_names_the_build_command_source_of_truth_and_provenance(self):
        text = (ASSET / "README.md").read_text()
        self.assertIn("scripts/brand/render_wisp_flame.sh", text)
        self.assertIn("build_flame.py", text)
        self.assertIn("source of truth", text)
        self.assertIn("preview/vendor/PROVENANCE.md", text)


if __name__ == "__main__":
    unittest.main()
