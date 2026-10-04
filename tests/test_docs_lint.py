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
import sys
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
OPEN_SECTIONS = {"apps", "health.units", "mcp", "env"}


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
        for m in BRACKET.finditer(" ".join(t for _, t in code_chunks_line(line))):
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


if __name__ == "__main__":
    unittest.main()
