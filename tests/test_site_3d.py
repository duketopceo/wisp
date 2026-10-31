"""The optional visual landing must not weaken the default no-script site."""
import json
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site-3d"
INSTALL = 'f=$(mktemp) && curl -fsSL https://wisp.observer/install.py -o "$f" && python3 "$f" --version v1.0.0-rc.2'


class LandingContract(unittest.TestCase):
    def test_install_uses_pinned_authenticated_candidate(self):
        html = (SITE / "index.html").read_text()
        self.assertIn("--version v1.0.0-rc.2", html)
        self.assertIn("independently installed GitHub CLI", html)
        self.assertIn("not self-authenticating", html)
        self.assertIn("/blob/v1.0.0-rc.2/scripts/bootstrap/install.py", html)
        self.assertIn("~/.local/bin/wispd onboard", html)

    def test_install_and_demo_are_honest(self):
        html = (SITE / "index.html").read_text()
        self.assertIn(INSTALL.replace("&&", "&amp;&amp;"), html)
        self.assertIn("wisp.observer", html)
        self.assertIn("Illustrative demo", html)
        self.assertIn("not a live desktop session", html)
        self.assertNotIn("wisp.casa", html)
        self.assertNotIn("/install.sh", html)
        self.assertNotIn("real turn on the 3D", html)
        self.assertNotRegex(html, r"\b\d+\s*ms\b")
        self.assertIn("experimental", html.lower())

    def test_all_runtime_assets_are_self_hosted(self):
        html = (SITE / "index.html").read_text()
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://[^"\']+\.(?:js|css)')
        self.assertNotIn("importmap", html)
        self.assertNotIn("preconnect", html)
        for filename in ("style.css", "app.mjs", "scene.mjs", "model.mjs", "desktop.mjs",
                         "vendor/three.module.js", "vendor/THREE-LICENSE.txt",
                         "assets/companion.png"):
            self.assertTrue((SITE / filename).is_file(), filename)

    def test_fallback_and_accessible_controls_exist(self):
        html = (SITE / "index.html").read_text()
        self.assertIn("<noscript>", html)
        self.assertIn('id="scene-fallback"', html)
        self.assertIn('id="desktop"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('id="cancel-demo"', html)
        self.assertIn('id="approve-demo"', html)
        self.assertIn('id="reset-demo"', html)
        self.assertIn('id="sensitive-rules"', html)
        css = (SITE / "style.css").read_text()
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("desk-window", css)
        self.assertIn("draw-layer", css)


class EnhancedBuild(unittest.TestCase):
    def builder(self):
        spec = importlib.util.spec_from_file_location("build_3d", ROOT / "scripts/site/build_3d.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_build_is_deterministic_and_excludes_authoring_files(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            builder.build(a)
            builder.build(b)
            self.assertEqual((a / "inventory.json").read_bytes(), (b / "inventory.json").read_bytes())
            self.assertFalse((a / "DESIGN.md").exists())
            self.assertEqual([], builder.check(a))

    def test_missing_and_remote_runtime_assets_are_rejected(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            builder.build(out)
            (out / "app.mjs").write_text('import "https://example.com/tracker.js";')
            self.assertTrue(any("remote" in p for p in builder.check(out)))
            (out / "app.mjs").unlink()
            self.assertTrue(any("missing" in p for p in builder.check(out)))

    def test_output_cannot_replace_the_repository_or_source(self):
        builder = self.builder()
        for path in (ROOT, SITE, SITE / "build"):
            with self.assertRaises(builder.SiteError):
                builder.build(path)


@unittest.skipUnless(shutil.which("node"), "Node is needed for the optional web demo")
class DemoState(unittest.TestCase):
    def evaluate(self, code):
        module = (SITE / "model.mjs").as_uri()
        script = f"import {{initial, transition}} from {json.dumps(module)};\n{code}"
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_sensitive_action_waits_for_explicit_confirmation(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'sensitive'});
            s = transition(s, {type:'advance'});
            s = transition(s, {type:'advance'});
            const waiting = s.phase;
            s = transition(s, {type:'advance'});
            const automatic = s.phase;
            s = transition(s, {type:'approve'});
            console.log(JSON.stringify([waiting, automatic, s.phase]));
        """)
        self.assertEqual(["awaiting_choice", "awaiting_choice", "acting"], result)

    def test_cancelled_or_finished_turn_cannot_be_advanced(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'mail'});
            s = transition(s, {type:'cancel'});
            s = transition(s, {type:'advance'});
            s = transition(s, {type:'approve'});
            console.log(JSON.stringify(s.phase));
        """)
        self.assertEqual("cancelled", result)

    def test_new_turn_invalidates_stale_timer_events(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'mail'});
            const old = s.turn;
            s = transition(s, {type:'start', scenario:'sensitive'});
            s = transition(s, {type:'advance', turn:old});
            console.log(JSON.stringify([s.phase, s.scenario, s.turn > old]));
        """)
        self.assertEqual(["listening", "sensitive", True], result)

    def test_invalid_scenario_and_early_approval_do_nothing(self):
        result = self.evaluate("""
            let s = initial();
            s = transition(s, {type:'start', scenario:'unknown'});
            s = transition(s, {type:'approve'});
            console.log(JSON.stringify(s.phase));
        """)
        self.assertEqual("idle", result)

    def test_finished_turn_cannot_be_reapproved_or_advanced(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'work'});
            for (let i=0; i<3; i++) s=transition(s, {type:'advance'});
            s = transition(s, {type:'approve'});
            s = transition(s, {type:'advance'});
            console.log(JSON.stringify(s.phase));
        """)
        self.assertEqual("done", result)

    def test_reset_returns_idle_and_invalidates_the_previous_turn(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'sensitive'});
            const old=s.turn;
            s = transition(s, {type:'reset'});
            s = transition(s, {type:'advance', turn:old});
            console.log(JSON.stringify([s.phase,s.scenario,s.turn>old]));
        """)
        self.assertEqual(["idle", "mail", True], result)

    def test_media_example_is_available_without_sensitive_approval(self):
        result = self.evaluate("""
            let s = transition(initial(), {type:'start', scenario:'media'});
            for(let i=0;i<3;i++) s=transition(s,{type:'advance'});
            console.log(JSON.stringify([s.scenario,s.phase]));
        """)
        self.assertEqual(["media", "done"], result)

    def test_scripts_expose_control_changes_and_drawings(self):
        module = (SITE / "model.mjs").as_uri()
        script = f"""
            import {{initial, transition, scriptFor}} from {json.dumps(module)};
            let s = transition(initial(), {{type:'start', scenario:'mail'}});
            s = transition(s, {{type:'advance'}});
            s = transition(s, {{type:'advance'}});
            const acting = scriptFor(s);
            const hasHl = acting.drawings.some(d => d.type === 'hl');
            const hasArrow = acting.drawings.some(d => d.type === 'arrow');
            const hasNumber = acting.drawings.some(d => d.type === 'number');
            const active = acting.controls.some(c => c.active && c.value === 'opened');
            console.log(JSON.stringify([hasHl, hasArrow, hasNumber, active, acting.steps.length > 1]));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual([True, True, True, True, True], json.loads(result.stdout))

    def test_playback_toggle_changes_visible_control_value(self):
        module = (SITE / "model.mjs").as_uri()
        script = f"""
            import {{initial, transition, scriptFor}} from {json.dumps(module)};
            let s = transition(initial(), {{type:'start', scenario:'media'}});
            const before = scriptFor(s).controls.find(c => c.id === 'play').value;
            s = transition(s, {{type:'advance'}});
            s = transition(s, {{type:'advance'}});
            const after = scriptFor(s).controls.find(c => c.id === 'play').value;
            console.log(JSON.stringify([before, after]));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(["playing", "paused"], json.loads(result.stdout))
