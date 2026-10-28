"""B18: the outreach drafts are sourced, only name shipped features, and
nothing in the repo can send them."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "outreach" / "omarchy.md"

# Features that are NOT on master. A draft naming one fails this test; remove
# the phrase from this list in the PR that ships the feature.
NOT_ON_MASTER = [
    "wake word", "hands-free", "hosted trial", "free trial",
    "landing page", "multilingual", "bugreport", "what's new card",
    "context chips", "dictation safety net", "agent-installable",
]
BANNED = [r"\bbest\b", r"\bfastest\b", r"\b(the|a) first\b|\bfirst[- ](ever|to|class)", r"\bthe only\b",
          r"\b#1\b", r"\brevolutionary\b", r"\bseamless", r"\bunmatched\b",
          r"\bblazing"]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def text():
    return DOC.read_text("utf-8")


def facts():
    out = {}
    for ln in text().splitlines():
        m = re.match(r"\|\s*(F\d+)\s*\|(.+)\|(.+)\|\s*$", ln)
        if m:
            out[m.group(1)] = (m.group(2).strip(), m.group(3).strip())
    return out


def drafts():
    """Everything after the Facts table (the drafts themselves)."""
    return text().split("## 1. Marketplace submission issue", 1)[1]


class Outreach(unittest.TestCase):
    def test_every_fact_has_a_proof_that_resolves(self):
        f = facts()
        self.assertGreaterEqual(len(f), 15)
        for tag, (_claim, proof) in f.items():
            links = LINK.findall(proof)
            self.assertTrue(links, f"{tag} has no link")
            for target in links:
                if target.startswith("http"):
                    continue
                path = (DOC.parent / target.split("#")[0]).resolve()
                self.assertTrue(path.exists(), f"{tag}: {target}")

    def test_external_facts_are_dated(self):
        for tag, (_c, proof) in facts().items():
            if "http" in proof:
                self.assertRegex(proof, r"read 2026-\d\d-\d\d", tag)

    def test_every_tag_used_is_defined_and_every_draft_has_tags(self):
        defined = set(facts())
        used = set(re.findall(r"\[(F\d+)\]", drafts()))
        self.assertEqual(used - defined, set())
        d = drafts()
        for heading in ("## 2.", "## 3.", "## 4.", "## 5."):
            block = d.split(heading, 1)[1].split("\n## ", 1)[0]
            self.assertRegex(block, r"\[F\d+\]", heading)

    def test_no_feature_that_is_not_on_master(self):
        low = text().lower()
        for phrase in NOT_ON_MASTER:
            self.assertNotIn(phrase, low, phrase)

    def test_the_named_features_exist_in_the_repo(self):
        for rel in ("wisp/scribble.py", "wisp/omarchy_tutor.py",
                    "wisp/points.py", "wisp/ledger.py", "wisp/confirm.py",
                    "scripts/plugin_mirror.py"):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_no_superlatives_without_a_source(self):
        # The word is only allowed inside the facts table (quoting a source)
        # and in this file's own rule paragraph.
        body = drafts()
        body = re.sub(r"```.*?```", "", body, flags=re.S)
        for pat in BANNED:
            self.assertIsNone(re.search(pat, body, re.I), pat)

    def test_the_submission_body_keeps_the_marketplace_format(self):
        body = text().split("```markdown", 1)[1].split("```", 1)[0]
        heads = re.findall(r"^### (.+)$", body, re.M)
        self.assertEqual(heads, [
            "Repository URL", "Category", "Tags", "Suggest a missing tag",
            "Maintainer notes", "Submission checklist"])
        self.assertIn("https://github.com/duketopceo/wisp-plugin", body)
        self.assertIn("\nProductivity\n", body)
        tags = re.search(r"### Tags\n\n(.+)\n", body).group(1).split(", ")
        self.assertTrue(1 <= len(tags) <= 3)
        self.assertLessEqual(set(tags), {"ai", "hyprland", "education"})
        self.assertEqual(body.count("- [x]"), 5)


class NothingCanSend(unittest.TestCase):
    SKIP = {".git", "__pycache__", "venv", "node_modules", "target"}

    def files(self, base):
        for p in base.rglob("*"):
            if p.is_file() and not (set(p.parts) & self.SKIP):
                yield p

    def test_the_outreach_folder_is_one_markdown_file(self):
        self.assertEqual([p.name for p in DOC.parent.iterdir()],
                         ["omarchy.md"])

    def test_no_webhook_token_or_send_code_for_these_channels(self):
        pats = [r"hooks\.slack\.com", r"discord(app)?\.com/api/webhooks",
                r"rangers@omarchy\.org.*(smtp|sendmail|mailx)",
                r"gh issue create.*omarchy-plugin-marketplace.*--body-file "
                r"[^/\s]*\.md.*&&",
                r"omacom/omarchy-plugin-marketplace/issues"]
        # the single allowed mention of the issue command is the doc itself
        for p in list(self.files(ROOT / "scripts")) + list(
                self.files(ROOT / "wisp")) + [ROOT / "wispd"]:
            if p.suffix not in (".py", ".sh", ".yml", "") or p.is_dir():
                continue
            src = p.read_text("utf-8", errors="ignore")
            for pat in pats:
                self.assertIsNone(re.search(pat, src, re.I | re.S),
                                  f"{p}: {pat}")

    def test_workflows_do_not_post_issues_to_other_repos(self):
        for p in (ROOT / ".github").rglob("*.yml"):
            src = p.read_text("utf-8")
            self.assertNotIn("omarchy-plugin-marketplace", src, p.name)
            self.assertNotIn("gh issue create", src, p.name)


if __name__ == "__main__":
    unittest.main()
