"""A component that reads `root.tk` must declare it (OverlayLayer read an
undefined `root.tk` for its label ack colour; nothing failed loudly)."""
import pathlib
import re
import unittest

COMP = pathlib.Path(__file__).resolve().parent.parent / "shell-plugin" \
    / "components"


class RootTk(unittest.TestCase):
    def test_root_tk_is_declared_where_used(self):
        bad = []
        for f in sorted(COMP.glob("*.qml")):
            src = f.read_text()
            if re.search(r"\broot\.tk\b", src) and not re.search(
                    r"property\s+\w+\s+tk\b", src):
                bad.append(f.name)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
