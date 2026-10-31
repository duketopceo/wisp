#!/usr/bin/env python3
"""CI must not go green by skipping. Many suites skip when a tool is not
installed (qmltestrunner, qmllint, qsb, node), which is right on a
developer box and wrong on CI. A CI job names the tools it must have in
WISP_CI_REQUIRE_TOOLS (a comma list, or 1 for all of them), and a missing
one fails here instead of silently skipping."""
import os
import shutil
import unittest

REQUIRED = ("node", "qmltestrunner", "qmllint", "qsb")
QT_BIN = "/usr/lib/qt6/bin"


def found(tool: str) -> bool:
    return bool(shutil.which(tool)) or os.path.exists(os.path.join(QT_BIN, tool))


def required(env: str) -> tuple:
    env = (env or "").strip()
    if env == "1":
        return REQUIRED
    return tuple(t.strip() for t in env.split(",") if t.strip())


@unittest.skipUnless(os.environ.get("WISP_CI_REQUIRE_TOOLS"),
                     "only enforced on CI")
class RequiredTools(unittest.TestCase):
    def test_every_tool_the_skipping_suites_need_is_installed(self):
        need = required(os.environ["WISP_CI_REQUIRE_TOOLS"])
        self.assertTrue(need)
        missing = [t for t in need if not found(t)]
        self.assertEqual(missing, [], "these suites would skip: install "
                         + ", ".join(missing))


class Found(unittest.TestCase):
    def test_qt_bin_fallback(self):
        self.assertFalse(found("wisp-no-such-tool"))

    def test_required_reads_a_list_or_all(self):
        self.assertEqual(required("1"), REQUIRED)
        self.assertEqual(required("node, qsb"), ("node", "qsb"))
        self.assertEqual(required(""), ())


if __name__ == "__main__":
    unittest.main()
