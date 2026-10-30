#!/usr/bin/env python3
"""W33: the docs only name commands, flags and config keys that exist.

Extracts `wispd ...` commands and `[section] key` / `section.key` names
from README.md, ROADMAP.md and docs/*.md (plans, brainstorms and design
research are history and are skipped) and checks them against the live
CLI registry (wisp/cli) and the config surface: DEFAULT_CONFIG, the
settings schema, and keys the code reads by name.

Add `<!-- doclint: skip -->` on the line before a fenced block to exempt
it (for example an example of an old name that must keep failing).
"""
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wisp import cli, config, settings_schema  # noqa: E402
from wisp.cli import registry  # noqa: E402

DOC_FILES = [ROOT / "README.md", ROOT / "ROADMAP.md"] + sorted(
    (ROOT / "docs").glob("*.md"))
# history, not reference
SKIP_DOCS = {"HANDOFF.md"}

GLOBAL_FLAGS = {"--json", "--quiet", "-q", "--no-color", "-h", "--help"}
# top-level words the script handles before the registry
SCRIPT_WORDS = {"wispd"}

FENCE = re.compile(r"^\s*```")
SPAN = re.compile(r"`([^`\n]+)`")


def doc_files():
    return [p for p in DOC_FILES if p.name not in SKIP_DOCS]


def code_chunks(path):
    """(lineno, text) for every inline code span and fenced-block line."""
    out, fenced, skip_next, skip_block = [], False, False, False
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            skip_block = fenced and skip_next
            skip_next = False
            continue
        if "doclint: skip" in line:
            skip_next = True
            continue
        skip_next = False
        if fenced:
            if not skip_block:
                out.append((i, line))
        else:
            out.extend((i, m.group(1)) for m in SPAN.finditer(line))
    return out


def wispd_invocations(path):  # noqa: C901
    """(lineno, [tokens after wispd]) for each command in the doc."""
    found = []
    for i, text in code_chunks(path):
        if "py_compile" in text:
            continue
        for m in re.finditer(r"(?:^|[\s$(`])wispd\s+(?=\S)", text):
            tail = text[m.end():]
            tail = re.split(r"\s(?:\||>|>>|&&|;|#|2>)|[;|]\s", tail)[0]
            toks = []
            for t in tail.split():
                t = t.strip(",.:)\"'")
                if not t:
                    continue
                toks.append(t)
            if toks:
                found.append((i, toks))
    return found


def _leaf_options():
    """command path -> set of option strings its parser accepts."""
    parser = registry.build_parser()
    out = {}

    def sub_actions(p):
        return [a for a in p._actions if a.choices and hasattr(a, "choices")
                and isinstance(a.choices, dict)]

    top = {}
    for act in sub_actions(parser):
        top.update(act.choices)
    for name, p in top.items():
        verbs = {}
        for act in sub_actions(p):
            verbs.update(act.choices)
        if verbs:
            for v, vp in verbs.items():
                out[f"{name} {v}"] = set(vp._option_string_actions)
        out.setdefault(name, set(p._option_string_actions))
        if verbs:
            out[name] = set(p._option_string_actions)
    return out


def resolve(tokens, cmds):
    """tokens -> (command path | None, problem string)."""
    return resolve_args(tokens, cmds)[:2]


def resolve_args(tokens, cmds):
    """tokens -> (command path | None, problem, argv after the command
    path with legacy aliases rewritten)."""
    rest, _flags = registry.extract_globals(list(tokens))
    if not rest:
        return "status", "", []
    first = rest[0]
    if first in SCRIPT_WORDS or first.startswith(("-", "<", "[", "(")):
        return None, "", []
    if first in cli.ALIASES:
        rest = cli.ALIASES[first](rest[1:])
    if not rest:
        return None, "", []
    if len(rest) > 1 and f"{rest[0]} {rest[1]}" in cmds:
        return f"{rest[0]} {rest[1]}", "", rest[2:]
    if rest[0] in cmds:
        return rest[0], "", rest[1:]
    groups = {p.split(" ")[0] for p in cmds}
    if rest[0] in groups:
        if len(rest) == 1 or rest[1].startswith(("-", "<", "[")):
            return rest[0], "", rest[1:]  # bare group in prose
        return None, f"unknown verb {rest[1]!r} for {rest[0]!r}", []
    return None, f"unknown command {first!r}", []


class CommandRefs(unittest.TestCase):
    def test_commands_and_flags_exist(self):
        cmds = registry.commands()
        opts = _leaf_options()
        bad, checked = [], 0
        for path in doc_files():
            for line, toks in wispd_invocations(path):
                cmd, problem, args = resolve_args(toks, cmds)
                where = f"{path.relative_to(ROOT)}:{line}: wispd {' '.join(toks)}"
                if problem:
                    bad.append(f"{where}  -> {problem}")
                    continue
                if cmd is None:
                    continue
                checked += 1
                known = opts.get(cmd, set()) | GLOBAL_FLAGS
                for t in args:
                    if t.startswith("-") and t not in ("-", "--"):
                        flag = t.split("=", 1)[0]
                        if flag not in known and not re.fullmatch(
                                r"-[A-Za-z]", flag):
                            bad.append(f"{where}  -> {cmd} has no {flag}")
        self.assertTrue(checked > 20, f"only {checked} commands checked")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_every_group_is_documented(self):
        """The README command section names every top-level command."""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        missing = sorted(
            g for g in {p.split(" ")[0] for p in registry.commands()}
            if not re.search(rf"\bwispd {g}\b", text))
        self.assertEqual(missing, [], f"README lacks: {missing}")


# -- config keys -------------------------------------------------------------

def known_keys():
    """{section: {key}} from DEFAULT_CONFIG (live and commented), the
    schema, and the default dict."""
    keys, section = {}, ""
    for line in config.DEFAULT_CONFIG.splitlines():
        s = line.strip().lstrip("#").strip()
        m = re.match(r"^\[([\w.]+)\]\s*(?:#.*)?$", s)
        if m and not line.lstrip().startswith("# ["):
            section = m.group(1)
            keys.setdefault(section, set())
            continue
        if line.lstrip().startswith("# ["):
            section = ""  # a commented example block: not this section's
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*=", s)
        if m and section:
            keys[section].add(m.group(1))
    for f in settings_schema.FIELDS:
        sec, _, key = f.key.partition(".")
        keys.setdefault(sec, set()).add(key)
    for sec, d in config._default_cfg_dict().items():
        keys.setdefault(sec, set()).update(d)
    return keys


def code_words():
    """Every quoted identifier the code reads (config keys read by name)."""
    words = set()
    srcs = list((ROOT / "wisp").rglob("*.py")) + [ROOT / "wispd"]
    for p in srcs:
        words.update(re.findall(r"""["']([A-Za-z_][\w-]*)["']""",
                                p.read_text(encoding="utf-8", errors="ignore")))
    return words


# `[sec] key` / `[sec] key = ...`  and  `sec.key` after config set
BRACKET = re.compile(r"\[([a-z][\w.]*)\]\s+([a-z_][\w]*)\b")
DOTTED = re.compile(r"wispd config set\s+([a-z_]+)\.([a-z_]+)\b")
HEAD = re.compile(r"^##+\s+\[([\w.<>]+)\]")
ROW = re.compile(r"^\|\s*`([a-z_][\w]*)`(?:\s*/\s*`([a-z_][\w]*)`)?\s*\|")
# sections whose keys are user-defined
OPEN_SECTIONS = {"apps", "health.units", "mcp", "env", "control"}


def config_refs(path):
    refs, section = [], None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        h = HEAD.match(line)
        if h:
            section = h.group(1)
            continue
        if line.startswith("#"):
            section = None
        if section and "<" not in section:
            m = ROW.match(line)
            if m:
                for k in filter(None, m.groups()):
                    refs.append((i, section, k))
        # Separate inline spans are not one config reference: joining
        # `[app_skill]` and `scripts/foo.py` invents a nonexistent key.
        for _, chunk in code_chunks_line(line):
            for m in BRACKET.finditer(chunk):
                refs.append((i, m.group(1), m.group(2)))
        for m in DOTTED.finditer(line):
            refs.append((i, m.group(1), m.group(2)))
    return refs


def code_chunks_line(line):
    return [(0, m.group(1)) for m in SPAN.finditer(line)]


class ConfigRefs(unittest.TestCase):
    def test_keys_exist(self):
        known, words = known_keys(), code_words()
        bad, checked = [], 0
        for path in doc_files():
            for line, sec, key in config_refs(path):
                if sec.split(".")[0] in OPEN_SECTIONS or sec in OPEN_SECTIONS:
                    continue
                if sec.startswith("brain.") and sec != "brain":
                    continue  # provider tables
                checked += 1
                if key in known.get(sec, set()):
                    continue
                if sec in known and key in words:
                    continue  # read by name in the code
                bad.append(f"{path.relative_to(ROOT)}:{line}: [{sec}] {key}")
        self.assertTrue(checked > 40, f"only {checked} keys checked")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))


class ConfigCoverage(unittest.TestCase):
    """The other direction: every shipped default is written up."""

    def test_defaults_are_documented(self):
        text = (ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
        heads = set(re.findall(r"^#+\s+\[([\w.<>]+)\]", text, re.M))
        mentioned = set(re.findall(r"\[([a-z][\w.]*)\]", text))
        missing = []
        for sec, ks in known_keys().items():
            if sec.startswith("brain.") or sec in OPEN_SECTIONS:
                continue
            if sec not in heads and sec not in mentioned:
                missing.append(f"[{sec}] has no section")
                continue
            missing += [f"[{sec}] {k}" for k in sorted(ks)
                        if not re.search(rf"\b{re.escape(k)}\b", text)]
        self.assertEqual(missing, [], "\nundocumented: " + ", ".join(missing))


class Extractor(unittest.TestCase):
    """The lint itself must be able to fail."""

    def test_config_refs_do_not_join_unrelated_inline_spans(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "example.md"
            path.write_text(
                "The `[app_skill]` prompt uses `scripts/skill_distill.py` "
                "and `context.snapshot()`; set `[agent] screenshots = false`.\n"
                "A bad setting remains visible: `[missing] bogus = true`.\n"
                "Use `wispd config set agent.screenshots false`.\n"
                "An explicit bad reference still counts: "
                "`[app_skill] scripts = true`.\n",
                encoding="utf-8")
            self.assertEqual(config_refs(path), [
                (1, "agent", "screenshots"),
                (2, "missing", "bogus"),
                (3, "agent", "screenshots"),
                (4, "app_skill", "scripts"),
            ])

    def test_separate_dev_commands_are_each_checked(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "example.md"
            path.write_text(
                "`wispd dev on`, `wispd dev off`, `wispd dev run`, "
                "`wispd dev runs`, `wispd dev review`.\n",
                encoding="utf-8")
            invocations = wispd_invocations(path)
            expected = ["dev on", "dev off", "dev run", "dev runs",
                        "dev review"]
            self.assertEqual([" ".join(t) for _, t in invocations], expected)
            for (_, tokens), command in zip(invocations, expected):
                self.assertEqual(resolve(tokens, registry.commands()),
                                 (command, ""))

    def test_resolver_flags_a_bad_command(self):
        cmds = registry.commands()
        self.assertEqual(resolve(["doctor"], cmds)[1], "")
        self.assertIn("unknown command", resolve(["nonesuch"], cmds)[1])
        self.assertIn("unknown verb", resolve(["cua", "frobnicate"], cmds)[1])
        self.assertEqual(resolve(["label", "correct"], cmds)[0], "label set")
        self.assertEqual(resolve(["install", "--units"], cmds)[0],
                         "daemon install")

    def test_flag_table_knows_real_flags(self):
        o = _leaf_options()
        self.assertIn("--units", o["daemon install"])
        self.assertIn("--status", o["onboard"])
        self.assertNotIn("--frobnicate", o["onboard"])

    def test_known_keys_cover_the_policy_keys(self):
        k = known_keys()
        self.assertIn("gate_primary", k["budget"])
        self.assertIn("kill_switch", k["cua"])
        self.assertIn("min_confidence", k["ground"])


class AgentRunbook(unittest.TestCase):
    """B20: the one-paste prompt and the runbook an agent follows."""
    INSTALL = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")

    def prompt(self):
        sec = self.INSTALL.split("## Let your coding agent do it", 1)[1]
        return re.search(r"```text\n(.*?)```", sec, re.S).group(1)

    def steps(self):
        sys.path.insert(0, str(HERE))
        import agent_fixture
        return agent_fixture.runbook()

    def test_the_prompt_has_no_key_outside_path_or_sudo(self):
        p = self.prompt()
        self.assertNotRegex(p, r"(?i)\bsudo\b|\bsu\b|\broot\b")
        self.assertNotRegex(p, r"sk-[A-Za-z0-9]|gh[pousr]_|Bearer |"
                            r"(?i:api[_-]?key|token)\s*=")
        text = re.sub(r"https?://\S+", "", p)      # URLs are not paths
        for path in re.findall(r"(?<![\w.])(~?/[\w.\-]+(?:/[\w.\-]+)*)",
                               text):
            self.assertTrue(path.startswith("~/"), f"outside $HOME: {path}")
        self.assertIn("Never read, print or copy any key", p)
        self.assertIn("https://github.com/duketopceo/wisp", p)

    def test_the_runbook_says_which_steps_need_the_user(self):
        user = " ".join(s["cmd"] for s in self.steps()
                        if s["who"] == "user").lower()
        for need in ("key", "microphone", "bind", "hold super+d"):
            self.assertIn(need, user)

    def test_the_agent_never_reads_keys_installs_or_uses_sudo(self):
        for s in self.steps():
            if s["who"] != "agent":
                continue
            c = s["cmd"]
            self.assertTrue(c.startswith("python3 wispd "), c)
            self.assertNotRegex(c, r"sudo|\.env|cat |omaseal|keyring|rm ")
            if " install" in c:
                self.assertIn("--dry-run", c)

    def test_every_wispd_verb_in_the_runbook_exists(self):
        cmds = registry.commands()
        for s in self.steps():
            if s["who"] != "agent":
                continue
            toks = s["cmd"].split()[2:]
            cmd, problem, args = resolve_args(toks, cmds)
            self.assertEqual(problem, "", s["cmd"])
            self.assertIsNotNone(cmd, s["cmd"])
            known = _leaf_options().get(cmd, set()) | GLOBAL_FLAGS
            for t in args:
                if t.startswith("-"):
                    self.assertIn(t, known, s["cmd"])

    def test_a_fixture_agent_runs_every_agent_step_on_a_clean_home(self):
        r = subprocess.run([sys.executable, str(HERE / "agent_fixture.py")],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("STOP"),
                         sum(s["who"] == "user" for s in self.steps()))
        self.assertGreaterEqual(r.stdout.count("ok "), 4)
        self.assertNotIn("FAIL", r.stdout)

    def test_the_fixture_agent_fails_on_an_unexpected_exit(self):
        sys.path.insert(0, str(HERE))
        import agent_fixture
        steps = agent_fixture.runbook(
            "```runbook\nagent  python3 wispd status  # exit 0\n```")
        self.assertEqual(steps[0]["ok"], [0])

    def test_agents_md_and_readme_point_at_the_runbook(self):
        self.assertIn("Let your coding agent do it",
                      (ROOT / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("docs/INSTALL.md#let-your-coding-agent-do-it",
                      (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
