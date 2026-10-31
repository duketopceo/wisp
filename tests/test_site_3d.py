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
        for filename in ("style.css", "app.mjs", "scene.mjs", "model.mjs",
                         "vendor/three.module.js", "vendor/THREE-LICENSE.txt",
                         "assets/companion.png"):
            self.assertTrue((SITE / filename).is_file(), filename)

    def test_fallback_and_accessible_controls_exist(self):
        html = (SITE / "index.html").read_text()
        self.assertIn("<noscript>", html)
        self.assertIn('id="scene-fallback"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('id="cancel-demo"', html)
        self.assertIn('id="approve-demo"', html)
        self.assertIn('id="reset-demo"', html)
        self.assertIn('id="sensitive-rules"', html)
        css = (SITE / "style.css").read_text()
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":focus-visible", css)


class GuidingLightPreview(unittest.TestCase):
    LIGHT = SITE / "light"

    def test_preview_is_csp_clean_and_self_hosted(self):
        html = (self.LIGHT / "index.html").read_text()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")  # script-src 'self': no inline script
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://[^"\']+\.(?:js|css|woff2?)')
        self.assertNotIn("fonts.googleapis", html + (self.LIGHT / "light.css").read_text())
        self.assertNotIn("importmap", html)
        self.assertIn("prefers-reduced-motion", html + (self.LIGHT / "light.css").read_text()
                      + (self.LIGHT / "light.mjs").read_text())

    def test_threeui_mit_credit_ships_with_the_preview(self):
        self.assertIn("Copyright (c) 2026 Meng To", (SITE / "vendor/THREEUI-LICENSE.txt").read_text())
        self.assertIn("Copyright (c) 2026 Meng To", (ROOT / "THIRD_PARTY_NOTICES.md").read_text())
        self.assertIn("ThreeUI Community", (self.LIGHT / "index.html").read_text())
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        self.assertIn("shader rewritten", notices)
        self.assertIn("shader rewritten", (SITE / "vendor/PROVENANCE.md").read_text())
        self.assertNotIn("adapts the `energy-orb`", notices)

    def test_stop_five_states_the_hybrid_model_story(self):
        html = (self.LIGHT / "index.html").read_text()
        stop = html[html.index("05 · Models"):html.index('class="stop finale"')]
        self.assertIn("OpenRouter", stop)
        self.assertIn("default", stop)
        self.assertIn("local models", stop)
        self.assertNotIn("stay on your machine", html)
        self.assertNotRegex(stop, r"\b\d+\s*ms\b")

    def test_preview_claims_stay_inside_the_readme(self):
        html = (self.LIGHT / "index.html").read_text()
        self.assertIn("docs/INSTALL.md", html)
        self.assertIn("experimental", html.lower())
        self.assertNotRegex(html, r"\b\d+\s*ms\b")
        self.assertNotIn("wisp.casa", html)


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


@unittest.skipUnless(shutil.which("node"), "Node is needed for the wisp motion sim")
class WispSim(unittest.TestCase):
    def evaluate(self, code):
        module = (SITE / "wisp/sim.mjs").as_uri()
        script = f"import {{createSim}} from {json.dumps(module)};\n{code}"
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_converges_without_overshoot_and_velocity_decays(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(600, 0);
            let maxX = 0, peak = 0, peakAt = 0, speeds = [];
            for (let i = 0; i < 600; i++) {
              const st = s.step(1/60);
              maxX = Math.max(maxX, st.x); speeds.push(st.speed);
              if (st.speed > peak) { peak = st.speed; peakAt = i; }
            }
            let mono = true;
            for (let i = peakAt + 1; i < speeds.length; i++) if (speeds[i] > speeds[i-1] + 1e-9) mono = false;
            console.log(JSON.stringify({over: maxX - 600, mono, end: s.state.x}));
        """)
        self.assertLessEqual(r["over"], 0.5)
        self.assertTrue(r["mono"])
        self.assertAlmostEqual(r["end"], 600, delta=0.5)

    def test_frame_time_does_not_change_the_resting_point(self):
        r = self.evaluate("""
            const out = [];
            for (const dt of [0.008, 0.016, 0.05, 0.5]) {
              const s = createSim({x: 10, y: 20});
              s.setTarget(400, 300);
              for (let i = 0; i < 4000; i++) s.step(dt);
              out.push([s.state.x, s.state.y]);
            }
            console.log(JSON.stringify(out));
        """)
        for x, y in r:
            self.assertAlmostEqual(x, 400, delta=0.01)
            self.assertAlmostEqual(y, 300, delta=0.01)

    def test_settles_stays_settled_and_tail_collapses(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(500, 200);
            let first = -1, flip = false;
            for (let i = 0; i < 1200; i++) {
              const st = s.step(1/60);
              if (st.settled && first < 0) first = i;
              if (first >= 0 && !st.settled) flip = true;
            }
            const tail = Math.max(...s.trail.map(Math.abs));
            console.log(JSON.stringify({first, flip, tail, len: s.state.tailLen, settled: s.settled}));
        """)
        self.assertGreater(r["first"], 10)
        self.assertFalse(r["flip"])
        self.assertTrue(r["settled"])
        self.assertLess(r["tail"], 1e-3)
        self.assertLess(r["len"], 1e-3)

    def test_target_change_after_settle_wakes_the_sim(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(100, 0);
            for (let i = 0; i < 1200; i++) s.step(1/60);
            const was = s.settled;
            s.setTarget(100, 0);
            const same = s.settled;
            s.setTarget(100, 300);
            const next = s.step(1/60);
            console.log(JSON.stringify([was, same, next.settled, s.settled]));
        """)
        self.assertEqual([True, True, False, False], r)

    def test_retarget_toward_new_target_does_not_overshoot(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(800, 0);
            for (let i = 0; i < 20; i++) s.step(1/60);
            s.setTarget(s.state.x + 40, 0);
            const t = s.target.x;
            let max = 0;
            for (let i = 0; i < 600; i++) max = Math.max(max, s.step(1/60).x - t);
            console.log(JSON.stringify(max));
        """)
        self.assertLessEqual(r, 0.5)

    def test_retarget_keeps_position_and_velocity_continuous(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(800, 0);
            for (let i = 0; i < 20; i++) s.step(1/60);
            const before = {...s.state};
            s.setTarget(800, 200);
            const after = {...s.state};
            console.log(JSON.stringify([after.x - before.x, after.y - before.y, after.vx - before.vx, after.vy - before.vy]));
        """)
        for d in r:
            self.assertEqual(0, d)

    def test_tail_is_bounded_ordered_and_constant_length(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0, tailN: 16, maxRadius: 0.4});
            s.setTarget(5000, 5000);
            let maxMag = 0, lens = new Set(), ordered = true;
            for (let i = 0; i < 240; i++) {
              s.step(1/60);
              lens.add(s.trail.length);
              for (let k = 0; k < 16; k++)
                maxMag = Math.max(maxMag, Math.hypot(s.trail[2*k], s.trail[2*k+1]));
              for (let k = 1; k < 16; k++) if (s.trailAge[k] < s.trailAge[k-1]) ordered = false;
            }
            console.log(JSON.stringify({maxMag, lens: [...lens], ordered}));
        """)
        self.assertLessEqual(r["maxMag"], 0.4 + 1e-6)
        self.assertEqual([32], r["lens"])
        self.assertTrue(r["ordered"])

    def test_values_stay_finite_for_hostile_frame_times(self):
        r = self.evaluate("""
            const s = createSim({x: 0, y: 0});
            s.setTarget(300, 300);
            let ok = true;
            for (const dt of [0, -1, NaN, 1e9, 0.0001]) {
              const st = s.step(dt);
              for (const v of [st.x, st.y, st.vx, st.vy, st.speed, st.tailLen]) if (!Number.isFinite(v)) ok = false;
            }
            console.log(JSON.stringify(ok));
        """)
        self.assertTrue(r)

    def test_module_has_no_dom_or_gl_references(self):
        src = (SITE / "wisp/sim.mjs").read_text()
        for word in ("document", "window", "gl.", "navigator", "requestAnimationFrame"):
            self.assertNotIn(word, src)
