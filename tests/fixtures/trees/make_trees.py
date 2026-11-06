"""Regenerates the synthetic recorded-tree fixtures next to this file.

Nothing here comes from a real session: app names, labels and geometry are
invented. Run `python tests/fixtures/trees/make_trees.py` after changing
the format in wisp/elementtree.py. Never paste a real tree in: window
titles and control labels are the user's content.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wisp import elementtree as et  # noqa: E402

HERE = pathlib.Path(__file__).parent


def el(label, role, x, y, w, h):
    return {"label": label, "role": role, "rect": [x, y, w, h]}


def build() -> dict:
    out = {}
    # a settings dialog: labelled buttons, a toolbar, one huge panel
    out["settings_dialog"] = et.tree_to_fixture(
        "fixture-settings", (100, 100, 800, 600), [
            el("Content", "panel", 100, 140, 800, 560),
            el("Save", "push button", 700, 640, 80, 32),
            el("Cancel", "push button", 790, 640, 80, 32),
            el("Search", "entry", 120, 110, 300, 28),
            el("Dark mode", "toggle button", 300, 300, 60, 28),
        ])
    # two windows of one app; "Apply" exists only in the unfocused one
    out["two_windows"] = et.tree_to_fixture("fixture-editor", None, [], windows=[
        {"title": "main", "frame": [0, 0, 900, 700], "focused": True,
         "elements": [el("Run", "push button", 20, 20, 60, 28),
                      el("Run", "push button", 600, 500, 60, 28)]},
        {"title": "prefs", "frame": [950, 0, 400, 300], "focused": False,
         "elements": [el("Apply", "push button", 1200, 250, 70, 28)]},
    ])
    # a floating palette covers the focused window's lower right
    out["occluded"] = et.tree_to_fixture("fixture-editor", None, [], windows=[
        {"title": "main", "frame": [0, 0, 900, 700], "focused": True,
         "elements": [el("Export", "push button", 800, 650, 80, 30),
                      el("Open", "push button", 20, 20, 60, 28)]},
        {"title": "palette", "frame": [700, 600, 200, 100],
         "focused": False, "above": True, "elements": []},
    ])
    # a patchy tree: only containers, as GPU-drawn apps publish
    out["patchy"] = et.tree_to_fixture(
        "fixture-canvas", (0, 0, 1000, 800), [
            el("Canvas", "canvas", 0, 0, 1000, 800),
            el("Document", "document frame", 0, 40, 1000, 760),
        ])
    out["unavailable"] = et.tree_to_fixture(
        "", (0, 0, 0, 0), [], state=et.UNAVAILABLE,
        reason="gi/Atspi bindings not installed")
    out["unbound"] = et.tree_to_fixture(
        "", (0, 0, 0, 0), [], state=et.UNBOUND,
        reason="no toplevel binds to the focused window")
    return out


if __name__ == "__main__":
    for name, data in build().items():
        (HERE / f"{name}.json").write_text(
            json.dumps(data, indent=1, sort_keys=True) + "\n")
