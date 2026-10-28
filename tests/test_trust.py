"""B25: docs/TRUST.md is generated from the code and cannot go stale."""
import pathlib
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gen_trust as gt  # noqa: E402
from wisp import config  # noqa: E402


class Page(unittest.TestCase):
    def test_the_page_is_what_the_generator_writes(self):
        found = gt.scan()
        self.assertEqual(
            (ROOT / "docs" / "TRUST.md").read_text(), gt.render(found),
            "docs/TRUST.md is stale: python3 scripts/gen_trust.py")

    def test_check_flag_agrees(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gen_trust.py"),
             "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_host_in_the_code_is_explained(self):
        self.assertEqual(gt.problems(), [])

    def test_the_page_names_every_host_it_found(self):
        text = (ROOT / "docs" / "TRUST.md").read_text()
        for host in gt.scan():
            self.assertIn(f"`{host}`", text, host)

    def test_entries_are_complete(self):
        classes = {gt.AUDIO, gt.SHOT, gt.TEXT, gt.NONE}
        for host, e in gt.HOSTS.items():
            for f in ("what", "sends", "detail", "default", "key",
                      "control"):
                self.assertTrue(e.get(f), f"{host}.{f}")
            self.assertTrue(set(e["sends"]) <= classes, host)
        for host, why in gt.MENTIONS.items():
            self.assertTrue(why, host)
        self.assertFalse(set(gt.HOSTS) & set(gt.MENTIONS))

    def test_loopback_is_not_a_host(self):
        for h in gt.scan():
            self.assertNotIn(h, ("localhost",))
            self.assertFalse(re.fullmatch(r"[\d.]+", h), h)


class NewHost(unittest.TestCase):
    def tree(self, name, body):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        f = root / name
        f.parent.mkdir(parents=True)
        f.write_text(body)
        return root

    def test_a_new_python_url_fails_with_the_host_name(self):
        root = self.tree("wisp/new.py",
                         'URL = "https://collect.newvendor.io/v1/e"\n')
        probs = gt.problems(root)
        self.assertTrue(any("collect.newvendor.io" in p and
                            "no entry" in p for p in probs), probs)

    def test_a_bare_host_string_is_caught(self):
        root = self.tree("wisp/new.py", 'H = "api.sneaky.ai"\n')
        self.assertTrue(any("api.sneaky.ai" in p
                            for p in gt.problems(root)))

    def test_a_host_in_an_f_string_url_is_caught(self):
        root = self.tree(
            "wisp/new.py", 'def u(x):\n    return f"https://f.hook.dev/{x}"\n')
        self.assertTrue(any("f.hook.dev" in p for p in gt.problems(root)))

    def test_rust_and_qml_urls_are_caught(self):
        for name, body, host in (
                ("rs/wispd/src/x.rs",
                 'const U: &str = "https://rs.vendor.com/a";\n',
                 "rs.vendor.com"),
                ("shell-plugin/X.qml",
                 'Item { property string u: "https://q.vendor.org/a" }\n',
                 "q.vendor.org")):
            root = self.tree(name, body)
            self.assertTrue(any(host in p for p in gt.problems(root)),
                            name)

    def test_loopback_and_property_access_are_not_hosts(self):
        root = self.tree(
            "shell-plugin/X.qml",
            'Item { x: model.data.app; u: "http://127.0.0.1:8081/x";'
            ' v: "http://localhost:11434" }\n')
        found = gt.scan(root)
        self.assertEqual(found, {})

    def test_a_removed_host_makes_its_entry_stale(self):
        root = self.tree("wisp/empty.py", "X = 1\n")
        probs = gt.problems(root)
        self.assertTrue(any("openrouter.ai" in p and "no code" in p
                            for p in probs))


class Claims(unittest.TestCase):
    """What the page says about settings is true of the defaults."""

    def test_every_named_setting_exists(self):
        cfg = tomllib.loads(config.DEFAULT_CONFIG)
        text = (ROOT / "docs" / "TRUST.md").read_text()
        seen = 0
        for sect, key in re.findall(r"`\[([a-z.]+)\] ([a-z_]+)", text):
            seen += 1
            node = cfg
            for part in sect.split("."):
                node = node.get(part, {})
            commented = re.search(
                rf"^#\s*{re.escape(key)}\s*=", config.DEFAULT_CONFIG,
                re.M)
            self.assertTrue(key in node or commented,
                            f"[{sect}] {key} is not a setting")
        self.assertGreater(seen, 8)

    def test_defaults_match_what_the_page_says(self):
        cfg = tomllib.loads(config.DEFAULT_CONFIG)
        self.assertEqual(cfg["stt"]["provider"], "openai")
        self.assertIn("api.groq.com", cfg["stt"]["base_url"])
        self.assertIn("openrouter.ai", cfg["brain"]["openrouter"]["base_url"])
        self.assertEqual(cfg["agent"]["screenshots"], True)
        self.assertEqual(cfg["recall"]["provider"], "none")
        self.assertEqual(cfg["report"]["dsn"], "")
        self.assertIs(cfg["sense"]["enabled"], False)


class Links(unittest.TestCase):
    def test_the_readme_links_the_page(self):
        self.assertIn("docs/TRUST.md",
                      (ROOT / "README.md").read_text())

    def test_the_landing_page_links_the_page(self):
        src = (ROOT / "site" / "index.html").read_text()
        self.assertIn("docs/TRUST.md", src)


if __name__ == "__main__":
    unittest.main()
