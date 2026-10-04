"""Copy lint: the no-emoji, no-dash, no-banned-word rules (WISP-PLAN
section 0, DESIGN-v2 5.9) applied to user-facing strings.

Only string literals are checked; comments and docstrings are exempt.
Rules, per string:
  - no emoji or Unicode symbol stand-ins (arrows, dingbats, misc symbols,
    pictographs, variation selectors)
  - no em dash or en dash
  - no banned word (marketing filler and apology words)
"""
import ast
import re

EMOJI = re.compile(
    "[\u2190-\u21ff\u2300-\u23ff\u25a0-\u27bf\u2900-\u297f\u2b00-\u2bff"
    "\u200d\ufe0e\ufe0f\U0001F000-\U0001FFFF]")
DASH = re.compile("[\u2014\u2013]")
BANNED = ("utilize", "leverage", "seamless", "seamlessly", "simply",
          "oops", "whoops", "sorry", "unfortunately", "awesome", "magic",
          "magical", "supercharge", "unleash", "delve", "kindly",
          "ai-powered")
_BANNED = re.compile(r"\b(" + "|".join(map(re.escape, BANNED)) + r")\b",
                     re.I)


def check_string(s: str) -> list:
    """Rule names `s` breaks (empty when clean)."""
    out = []
    if EMOJI.search(s):
        out.append("emoji")
    if DASH.search(s):
        out.append("dash")
    if _BANNED.search(s):
        out.append("banned-word")
    return out


def python_strings(source: str) -> list:
    """String constants of a Python module, docstrings excluded."""
    tree = ast.parse(source)
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef,
                          ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(
                    getattr(first, "value", None), ast.Constant):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"(?m)(^|[^:\"'\\])//.*$")
_STR = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")


def qml_strings(source: str) -> list:
    """String literals of QML/JS source with comments removed. A `//` that
    follows a quote or colon (URLs) is not treated as a comment."""
    src = _BLOCK.sub("", source)
    src = _LINE.sub(lambda m: m.group(1), src)
    return [m.group()[1:-1] for m in _STR.finditer(src)]


def violations(strings) -> list:
    """[(string, [rules])] for every string that breaks a rule."""
    bad = []
    for s in strings:
        rules = check_string(s)
        if rules:
            bad.append((s, rules))
    return bad
