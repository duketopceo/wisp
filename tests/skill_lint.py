"""Lint for app-guide frontmatter, used by the guide gates in the tests."""
import re

from wisp import skills, tools

# The only frontmatter keys an app guide may carry (docs/research/
# app-skill-format.md). `tool:` and friends are absent on purpose: app
# skills are documentation and never register executable tools.
APP_FRONTMATTER_KEYS = frozenset({
    "name", "description", "url_hosts", "app_classes", "asks", "tier",
    "provenance", "draft", "pulls_tools",
})


def _unavailable_tools(text: str) -> list[str]:
    """`pulls_tools` tokens naming a tool this install does not have. A
    skill that says it needs `sandbox` on a build without one is refused
    here, by name, rather than at the first call that fails."""
    known = set(tools.REGISTRY)
    m = re.match(r"^---\n(.*?)\n---\n", text or "", re.S)
    if not m:
        return []
    raw = ""
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() == "pulls_tools":
            raw = v
    return [t for t in skills._list_field(raw) if t not in known]


def frontmatter_problems(text: str) -> list[str]:
    """Why an app guide's frontmatter is not acceptable, [] when it is:
    keys outside the whitelist, a missing name/description/provenance, or a
    `pulls_tools` token naming a tool that does not exist."""
    m = re.match(r"^---\n(.*?)\n---\n", text or "", re.S)
    if not m:
        return ["no frontmatter"]
    keys = [ln.partition(":")[0].strip() for ln in m.group(1).splitlines()
            if ln.strip() and not ln.startswith((" ", "\t", "#"))]
    out = [f"disallowed key: {k}" for k in keys
           if k not in APP_FRONTMATTER_KEYS]
    out += [f"missing key: {k}" for k in ("name", "description", "provenance")
            if k not in keys]
    for tok in _unavailable_tools(text):
        out.append(f"pulls_tools names no such tool: {tok}")
    return out
