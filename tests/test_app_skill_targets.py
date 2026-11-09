"""U9: the app-skill target list (docs/research/app-skill-targets.md) and
the skills that implement it: names, routing keys, uniqueness, frontmatter,
and one scorer-correct teach case per skill added from the list."""
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp import gauntlet, skills  # noqa: E402

SEED = ROOT / "wisp" / "skills_seed" / "apps"
DOC = ROOT / "docs" / "research" / "app-skill-targets.md"
TEACH = ROOT / "tests" / "fixtures" / "teach-skills"

# Batches of the targets doc whose skills are implemented so far.
IMPLEMENTED_BATCHES = (1, 2, 3, 4, 5, 6, 7)


def doc_text():
    return DOC.read_text()


def shipped_names():
    m = re.search(r"## Shipped \(\d+\)\n\n(.*?)\n\n##", doc_text(), re.S)
    return [n.strip() for n in m.group(1).replace("\n", " ").split(",")]


def batch_rows(n):
    """[(skill, matches-cell)] for batch n of the doc."""
    m = re.search(rf"## Batch {n}:[^\n]*\n(.*?)(?=\n## |\Z)", doc_text(),
                  re.S)
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] != "Skill" \
                and not set(cells[0]) <= {"-"}:
            rows.append((cells[0], cells[1]))
    return rows


def all_batch_numbers():
    return [int(n) for n in re.findall(r"## Batch (\d+):", doc_text())]


def implemented_rows():
    return [r for n in IMPLEMENTED_BATCHES for r in batch_rows(n)]


def load(name):
    text = (SEED / name / "SKILL.md").read_text()
    return text, skills._frontmatter(text)


def all_skill_names():
    return sorted(p.parent.name for p in SEED.glob("*/SKILL.md"))


class Doc(unittest.TestCase):
    def test_the_doc_states_a_total_of_89(self):
        self.assertIn("**89 skills**", doc_text())
        self.assertIn("that is **89**", doc_text())

    def test_doc_names_add_up_to_the_stated_total(self):
        total = len(shipped_names()) + sum(
            len(batch_rows(n)) for n in all_batch_numbers())
        self.assertEqual(total, 89)

    def test_every_shipped_name_exists_as_a_skill(self):
        missing = [n for n in shipped_names() if n not in all_skill_names()]
        self.assertEqual(missing, [])

    def test_every_implemented_batch_name_exists_as_a_skill(self):
        missing = [n for n, _ in implemented_rows()
                   if n not in all_skill_names()]
        self.assertEqual(missing, [])

    def test_skill_count_matches_shipped_plus_implemented_names(self):
        expected = len(shipped_names()) + len(implemented_rows())
        self.assertEqual(len(all_skill_names()), expected)


class Frontmatter(unittest.TestCase):
    def test_every_skill_is_on_the_whitelist_with_asks_and_provenance(self):
        for name in all_skill_names():
            text, meta = load(name)
            self.assertEqual(skills.frontmatter_problems(text), [], name)
            self.assertTrue(meta.get("asks"), f"{name}: asks")
            self.assertTrue(meta.get("provenance"), f"{name}: provenance")

    def test_new_skills_carry_the_seed_provenance_and_a_teaching_section(
            self):
        for name, _ in implemented_rows():
            text, meta = load(name)
            self.assertEqual(meta["name"], name)
            self.assertEqual(meta["provenance"],
                             "authored: wisp seed, 2026-11-08", name)
            self.assertEqual(meta.get("tier"), "safe", name)
            self.assertTrue(
                skills.teaching_section(skills._strip_frontmatter(text)),
                name)


class Routing(unittest.TestCase):
    def test_desktop_skills_have_classes_and_web_skills_hosts(self):
        for name, cell in implemented_rows():
            _, meta = load(name)
            classes = skills._list_field(meta.get("app_classes"))
            hosts = skills._list_field(meta.get("url_hosts"))
            head, _, tail = cell.partition("host `")
            tail = "`" + tail if tail else ""
            if "class" in head:
                self.assertEqual(set(classes),
                                 set(re.findall(r"`([^`]+)`", head)), name)
            else:
                self.assertEqual(classes, [], name)
            if tail:
                self.assertEqual(set(hosts),
                                 set(re.findall(r"`([^`]+)`", tail)), name)
            else:
                self.assertEqual(hosts, [], name)

    def test_no_two_skills_claim_the_same_class_or_host(self):
        owners = {}
        for name in all_skill_names():
            _, meta = load(name)
            for key in ("app_classes", "url_hosts"):
                for v in skills._list_field(meta.get(key)):
                    owners.setdefault((key, v.lower()), []).append(name)
        clashes = {k: v for k, v in owners.items() if len(v) > 1}
        self.assertEqual(clashes, {})


class Reachable(unittest.TestCase):
    """Every implemented skill is the one that wins for its own keys:
    desktop classes by window class alone, web hosts through a browser
    window (class chromium) plus the page host."""

    def _match(self, **kw):
        return skills.match_app_skill_info(skills_dir=SEED.parent, **kw)

    def test_each_skill_is_reachable_by_every_class_and_host_it_claims(self):
        for name, _ in implemented_rows():
            _, meta = load(name)
            for cls in skills._list_field(meta.get("app_classes")):
                got = self._match(window_class=cls)
                self.assertEqual(got and got["name"], name, f"{name}:{cls}")
            for host in skills._list_field(meta.get("url_hosts")):
                got = self._match(window_class="chromium", url_host=host)
                self.assertEqual(got and got["name"], name, f"{name}:{host}")
                self.assertEqual(got["matched_by"], "url_host", name)


class TeachCases(unittest.TestCase):
    def test_every_new_skill_has_a_correct_teach_case(self):
        for name, _ in implemented_rows():
            d = TEACH / f"skill-{name}"
            self.assertTrue((d / "case.json").exists(), name)
            case = gauntlet.load_teach_case(d)
            self.assertEqual(case.app, name)
            meta = json.loads((d / "case.json").read_text())
            self.assertEqual(meta["size"], [640, 400])
            self.assertTrue(meta["elements"], name)
            self.assertEqual(gauntlet.score_teach_case(case)["verdict"],
                             gauntlet.CORRECT, name)


if __name__ == "__main__":
    unittest.main()
