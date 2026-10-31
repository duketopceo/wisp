"""spike/lfm-local: app-skill distiller mechanics (no network)."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import skill_distill  # noqa: E402
from wisp import brain  # noqa: E402
from wisp import skills  # noqa: E402


FIXTURE_SKILLS = ROOT / "tests" / "fixtures" / "skills"
SEED_GITHUB = ROOT / "wisp" / "skills_seed" / "apps" / "github"


class ExemplarTest(unittest.TestCase):
    """U3: exemplar skills load through skills.py and route on url_hosts."""

    def _index_dir(self, src):
        td = pathlib.Path(tempfile.mkdtemp())
        for d in src.iterdir():
            if d.is_dir():
                target = td / d.name
                target.mkdir()
                (target / "SKILL.md").write_text(
                    (d / "SKILL.md").read_text())
        return td

    def test_gmail_fixture_loads_and_routes(self):
        td = self._index_dir(FIXTURE_SKILLS)
        with mock.patch.object(skills, "SKILLS_DIR", td):
            idx = skills.index()
            names = [s["name"] for s in idx]
            self.assertIn("gmail-app", names)
            meta = skills._frontmatter(
                (td / "gmail-app" / "SKILL.md").read_text())
            self.assertIn("mail.google.com",
                          str(meta.get("url_hosts", "")))

    def test_github_seed_loads_and_routes(self):
        td = self._index_dir(SEED_GITHUB.parent)
        with mock.patch.object(skills, "SKILLS_DIR", td):
            meta = skills._frontmatter(
                (td / "github" / "SKILL.md").read_text())
            self.assertIn("github.com", str(meta.get("url_hosts", "")))
            self.assertNotIn("tool", meta)

    def test_exemplars_carry_required_sections(self):
        for f in [FIXTURE_SKILLS / "gmail-app" / "SKILL.md",
                  SEED_GITHUB / "SKILL.md"]:
            body = f.read_text()
            for sec in ("## Workflows", "## Verify before done",
                        "## Gotchas"):
                self.assertIn(sec, body, f"{f.name} missing {sec}")


class CapturesTest(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        (self.td / "a.png").write_bytes(b"\x89PNG")
        (self.td / "a.txt").write_text("the settings page")
        (self.td / "b.png").write_bytes(b"\x89PNG")

    def test_crawl_dir_pairs_notes(self):
        caps = skill_distill.captures_from(self.td, None)
        self.assertEqual(len(caps), 2)
        self.assertEqual(caps[0]["note"], "the settings page")
        self.assertEqual(caps[1]["note"], "")

    def test_spec_manifest(self):
        spec = self.td / "m.jsonl"
        spec.write_text(
            json.dumps({"image": "b.png", "page": "inbox"}) + "\n")
        caps = skill_distill.captures_from(self.td, spec)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["page"], "inbox")


class DistillTest(unittest.TestCase):
    def test_describe_and_merge_call_brain(self):
        td = pathlib.Path(tempfile.mkdtemp())
        (td / "a.png").write_bytes(b"\x89PNG")
        with mock.patch.object(brain, "chat",
                               return_value={"content": "- search box"}) as mc:
            d = skill_distill.describe(
                {"image": td / "a.png", "page": "home", "note": ""},
                "lfm:x", 5)
            self.assertIn("search box", d)
            self.assertEqual(mc.call_count, 1)
            body = skill_distill.merge(
                "TestApp", ["### home\n- search box"], "lfm:x", 5)
            self.assertTrue(body)

    def test_frontmatter_has_name_and_description(self):
        fm = skill_distill.frontmatter("perplexity-app", "Perplexity")
        self.assertIn("name: perplexity-app", fm)
        self.assertIn("description:", fm)

    def test_frontmatter_routing_and_provenance(self):
        fm = skill_distill.frontmatter(
            "gmail-app", "Gmail",
            hosts=["mail.google.com"], asks=["compose a reply"])
        self.assertIn("url_hosts: mail.google.com", fm)
        self.assertIn("asks: compose a reply", fm)
        self.assertIn("tier: safe", fm)
        self.assertIn("provenance:", fm)
        self.assertIn("draft: first-run", fm)

    def test_frontmatter_verified_drops_draft(self):
        fm = skill_distill.frontmatter("gmail-app", "Gmail", draft=False)
        self.assertNotIn("draft:", fm)

    def test_merge_passes_tools_note(self):
        with mock.patch.object(brain, "chat",
                               return_value={"content": "ok"}) as mc:
            skill_distill.merge("App", ["### a\n- x"], "lfm:x", 5,
                                tools_note="gh cli covers repos")
        prompt = mc.call_args[0][0][0]["content"]
        self.assertIn("gh cli covers repos", prompt)
        self.assertIn("## Tools", prompt)
        self.assertIn("## Verify before done", prompt)

    def test_merge_prompt_demands_populated_sections(self):
        with mock.patch.object(brain, "chat",
                               return_value={"content": "ok"}) as mc:
            skill_distill.merge("App", ["### a\n- x"], "lfm:x", 5)
        prompt = mc.call_args[0][0][0]["content"]
        self.assertIn("unverified", prompt)  # anti-hallucination rule
        self.assertNotIn("{tools_note}", prompt)

    def test_merge_template_echo_falls_back(self):
        echoed = ("## Overview        — what the app is\n"
                  "## Screens         — one line\n### home\n- search box")
        with mock.patch.object(brain, "chat",
                               return_value={"content": echoed}):
            body = skill_distill.merge(
                "App", ["### home\n- search box"], "lfm:x", 5,
                tools_note="gh cli")
        self.assertIn("## Workflows\nunverified", body)
        self.assertIn("gh cli", body)
        self.assertNotIn("— what the app is", body)

    def test_merge_good_body_passes_through(self):
        good = "## Overview\nreal merge\n\n## Workflows\n1. do thing"
        with mock.patch.object(brain, "chat",
                               return_value={"content": good}):
            body = skill_distill.merge("App", ["### a\n- x"], "lfm:x", 5)
        self.assertEqual(body, good)

    def test_sanitize_strips_executable_and_foreign_keys(self):
        text = ("---\nname: x\ntool: run.sh\ntier: safe\n"
                "version: 9\nauthor: Bob\nmetadata: {a: b}\n"
                "url_hosts: foo.com\n---\n\nbody")
        out = skill_distill.sanitize_frontmatter(text)
        self.assertNotIn("tool:", out.split("body")[0])
        self.assertNotIn("author:", out)
        self.assertNotIn("metadata:", out)
        self.assertIn("url_hosts: foo.com", out)
        self.assertIn("tier: safe", out)
        self.assertTrue(out.endswith("body"))


if __name__ == "__main__":
    unittest.main()


class MigrateRoutinesTest(unittest.TestCase):
    def test_migrates_json_routines_to_skills(self):
        import tempfile
        rj = pathlib.Path(tempfile.mkdtemp()) / "routines.json"
        rj.write_text(json.dumps({"routines": {
            "morning-mail": {"name": "morning mail", "task":
                             "check inbox and summarize", "schedule": "daily"},
            "empty": {"name": "empty", "task": ""}}}))
        sd = pathlib.Path(tempfile.mkdtemp())
        n = skills.migrate_routines(rj, sd)
        self.assertEqual(n, 1)
        f = sd / "routine-morning-mail" / "SKILL.md"
        self.assertTrue(f.exists())
        meta = skills._frontmatter(f.read_text())
        self.assertEqual(meta.get("provenance"), "migrated-from-routines")
        self.assertNotIn("tool", meta)
        # idempotent + JSON untouched
        self.assertEqual(skills.migrate_routines(rj, sd), 0)
        self.assertIn("morning-mail", json.loads(rj.read_text())["routines"])

    def test_missing_or_bad_json_returns_zero(self):
        import tempfile
        sd = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(skills.migrate_routines(
            pathlib.Path(tempfile.mkdtemp()) / "nope.json", sd), 0)


class BackfillTest(unittest.TestCase):
    def test_backfills_only_app_skills_without_routing(self):
        import tempfile
        sd = pathlib.Path(tempfile.mkdtemp())
        (sd / "perplexity-app").mkdir()
        (sd / "perplexity-app" / "SKILL.md").write_text(
            "---\nname: perplexity-app\ndescription: x\n---\nbody")
        (sd / "gmail-app").mkdir()
        (sd / "gmail-app" / "SKILL.md").write_text(
            "---\nname: gmail-app\nurl_hosts: mail.google.com\n---\nbody")
        (sd / "randomthing-app").mkdir()
        (sd / "randomthing-app" / "SKILL.md").write_text(
            "---\nname: randomthing-app\ndescription: x\n---\nbody")
        (sd / "not-an-app").mkdir()
        (sd / "not-an-app" / "SKILL.md").write_text(
            "---\nname: not-an-app\ndescription: x\n---\nbody")
        # dry run
        self.assertEqual(skills.backfill_routing(sd, dry_run=True),
                         ["perplexity-app"])
        # apply
        skills.backfill_routing(sd, dry_run=False)
        meta = skills._frontmatter(
            (sd / "perplexity-app" / "SKILL.md").read_text())
        self.assertEqual(meta.get("url_hosts"), "perplexity.ai")
        # already-routed + unknown + non-app untouched
        for name in ("gmail-app", "randomthing-app", "not-an-app"):
            meta = skills._frontmatter(
                (sd / name / "SKILL.md").read_text())
            self.assertNotIn("url_hosts", meta) if name != "gmail-app" \
                else self.assertEqual(meta["url_hosts"], "mail.google.com")
