#!/usr/bin/env python3
"""CI must not go green by skipping. Many suites skip when a tool is not
installed (qmltestrunner, qmllint, qsb, node), which is right on a
developer box and wrong on CI: the unit job sets WISP_CI_REQUIRE_TOOLS=1,
and then a missing tool fails here instead of silently skipping."""
import os
import shutil
import unittest

REQUIRED = ("node", "qmltestrunner", "qmllint", "qsb")
QT_BIN = "/usr/lib/qt6/bin"


def found(tool: str) -> bool:
    return bool(shutil.which(tool)) or os.path.exists(os.path.join(QT_BIN, tool))


@unittest.skipUnless(os.environ.get("WISP_CI_REQUIRE_TOOLS") == "1",
                     "only enforced on CI")
class RequiredTools(unittest.TestCase):
    def test_every_tool_the_skipping_suites_need_is_installed(self):
        missing = [t for t in REQUIRED if not found(t)]
        self.assertEqual(missing, [], "these suites would skip: install "
                         + ", ".join(missing))


class Found(unittest.TestCase):
    def test_qt_bin_fallback(self):
        self.assertFalse(found("wisp-no-such-tool"))


if __name__ == "__main__":
    unittest.main()
