"""Model and daemon text is shown as plain text, never as markup.

QtQuick Text defaults to AutoText, which renders anything that looks like
HTML. An answer containing an <img> tag would then fetch an arbitrary host
the moment it is shown, leaking the client address and timing without a
click. Every Text in the shell plugin is pinned to Text.PlainText.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
TEXT = re.compile(r"\bText\s*\{")


class PlainText(unittest.TestCase):
    def test_every_text_item_is_plain(self):
        bad, seen = [], 0
        for p in sorted(PLUGIN.rglob("*.qml")):
            lines = p.read_text().splitlines()
            for i, line in enumerate(lines):
                if not TEXT.search(line) or "TextInput" in line:
                    continue
                seen += 1
                head = "\n".join(lines[i:i + 4])
                if "textFormat: Text.PlainText" not in head:
                    bad.append(f"{p.relative_to(ROOT)}:{i + 1}")
        self.assertGreater(seen, 50)
        self.assertEqual(bad, [], "Text without textFormat: Text.PlainText")

    def test_no_markup_formats_anywhere(self):
        for p in PLUGIN.rglob("*.qml"):
            src = p.read_text()
            for bad in ("Text.RichText", "Text.StyledText", "Text.AutoText",
                        "Text.MarkdownText"):
                self.assertNotIn(bad, src, p.name)

    def test_the_answer_body_is_plain(self):
        src = (PLUGIN / "components" / "Answer.qml").read_text()
        m = re.search(r"Text\s*\{[^}]*?text:\s*root\.body", src,
                      re.S)
        self.assertIsNotNone(m)
        self.assertIn("textFormat: Text.PlainText", m.group(0))


if __name__ == "__main__":
    unittest.main()
