#!/usr/bin/env python3
"""Nothing unused ships (one-surface U5, R6).

An icon source, copy key or shell-plugin/lib function must be used somewhere
other than its own definition: by production code, or by a test that drives
it. Keys built at run time from a prefix ("ui.tab." + key) are allowed only
through PREFIXES, and every prefix there must itself still be built by
production code, so the allow-list cannot outlive its use.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import copy as wcopy  # noqa: E402

ICON_SRC = ROOT / "assets" / "icons" / "src"
LIB = ROOT / "shell-plugin" / "lib"
CODE = (".py", ".qml", ".js", ".mjs")
PROD_DIRS = ("shell-plugin", "shells", "wisp", "wispd", "scripts")
# Generated tables and the copy source: a key or icon named there is its
# definition, not a use.
DEFINITIONS = {ROOT / "wisp" / "copy.py", LIB / "copy.js", LIB / "icons.js"}

# Copy-key families built from a prefix at run time. Each entry names the
# prefix; test_every_prefix_family_is_still_built ties it to the code that
# builds it.
PREFIXES = (
    "ui.agent.",          # AgentRow, RunCard: + task state / outcome
    "ui.manage.audit.",   # AuditView, tui: + audit decision
    "ui.empty.",          # EmptyState: + tab (and + ".hint")
    "ui.page.",           # ManagePage: + frame (and + ".hint")
    "ui.onboard.step.",   # FirstRunCard: + step id
    "ui.onboard.state.",  # FirstRunCard: + step state
    "ui.cua.",            # HealthSection, tui: + cua state
    "ui.home.",           # HomeView: + daemon status
    "ui.tab.",            # PanelBody: + tab key
    "ui.settings.",       # QuickTab: + schema group
    "ui.rate.",           # rate.js: + label status
    "set.cat.",           # SettingsHost, SettingsPage, ManagePage: + page
    "set.group.",         # SettingsHost: + sidebar group
)


def _files(dirs, suffixes=CODE):
    out = []
    for d in dirs:
        out += [p for p in (ROOT / d).rglob("*") if p.suffix in suffixes
                and p.is_file() and "node_modules" not in p.parts]
    return out


def _read(paths):
    return {p: p.read_text(errors="ignore") for p in paths
            if p not in DEFINITIONS}


PROD = _read(_files(PROD_DIRS))
# Icons are drawn only by the shell surfaces.
SURFACES = {p: t for p, t in PROD.items()
            if p.is_relative_to(ROOT / "shell-plugin") or p.is_relative_to(ROOT / "shells")}
# Tests and their QML harness (scenes.json names fixtures and tabs); the
# pixel goldens are not code.
TESTS = _read([p for p in _files(["tests"], CODE + (".json",))
               if "snapshots" not in p.parts and "golden" not in p.parts])


def _quoted(name, texts):
    q = (f'"{name}"', f"'{name}'")
    return any(any(x in t for x in q) for t in texts.values())


class TestUnused(unittest.TestCase):
    def test_every_icon_source_is_referenced_by_name(self):
        # Icons are a production asset: a name only a test lists, or a
        # Python string that happens to match, is not a use.
        unused = [p.stem for p in sorted(ICON_SRC.glob("*.svg"))
                  if not _quoted(p.stem, SURFACES)]
        self.assertEqual(unused, [], "icon sources nothing draws; remove "
                         "them and rerun scripts/assets/build_icons.py")

    def test_every_copy_key_is_used(self):
        unused = [k for k in wcopy.STRINGS
                  if not k.startswith(PREFIXES)
                  and not _quoted(k, PROD) and not _quoted(k, TESTS)]
        self.assertEqual(unused, [], "copy keys nothing reads; remove them "
                         "from wisp/copy.py and rerun scripts/assets/gen_copy.py")

    def test_every_prefix_family_is_still_built(self):
        for prefix in PREFIXES:
            built = re.compile(r"""["']""" + re.escape(prefix) + r"""["']\s*\+""")
            self.assertTrue(any(built.search(t) for t in PROD.values()),
                            f"nothing builds {prefix}* keys; drop it from PREFIXES")
            self.assertTrue(any(k.startswith(prefix) for k in wcopy.STRINGS), prefix)

    def test_every_lib_function_is_used(self):
        others = {**PROD, **TESTS}
        unused = []
        for lib in sorted(LIB.glob("*.js")):
            src = lib.read_text()
            # comments do not count as a use
            code = re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", src)
            for name in re.findall(r"(?m)^function\s+(\w+)\s*\(", src):
                own = len(re.findall(r"(?<![\w$.])" + name + r"\b", code)) - 1
                # other files reach a lib function through its import alias
                # (Ink.textOn) or, in node-driven tests, by name
                qualified = re.compile(r"\." + name + r"\b|[\"']" + name + r"[\"']")
                if own == 0 and not any(qualified.search(t) for p, t in others.items()
                                        if p != lib):
                    unused.append(f"{lib.name}:{name}")
        self.assertEqual(unused, [], "lib functions nothing calls")


if __name__ == "__main__":
    unittest.main()
