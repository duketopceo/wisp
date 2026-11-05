#!/usr/bin/env python3
"""Draw the synthetic multi-step teach fixtures under tests/fixtures/teach/.

Each case is a recapture sequence: the screen the user sees before each
planner turn, drawn here with PIL (640x400 mock windows, never a real
screenshot), and the planner reply recorded for that screen.

THE REPLIES ARE HAND-AUTHORED. They are not real model output. They imitate
what the planner could plausibly return, and a few are deliberately flawed
(a step for a control that is not on the screen any more, an opener planned
a second time) so the loop has something to correct.

A case directory is also a valid U1 case: `case.json` keeps the first
screen's capture, reply, expected step and `elements` at the top level, so
the first-step scorer (`wisp.gauntlet.score_teach_cases`) reads it as-is.
The extra keys are `after` (which screen follows when the user presses a
labelled control), `then` (screens 1..n, each with capture, reply, elements
and `after`), `expected_delivery` (the labels Wisp should point at, in
order) and `expected_plans` (planner calls the loop should make).

Run: python scripts/gen_replan_fixtures.py   (rewrites the fixtures in place)
"""
import json
import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "tests" / "fixtures" / "teach")
W, H = 640, 400
BG, BAR, FG = (30, 32, 38), (52, 56, 66), (225, 228, 235)
CTRL, EDGE = (74, 80, 94), (110, 118, 136)
_FONT = ImageFont.load_default()


def _text(d, xy, s):
    d.text(xy, s, fill=FG, font=_FONT)


class Scene:
    def __init__(self, title):
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.els = []
        self.d.rectangle([0, 0, W, 22], fill=BAR)
        _text(self.d, (8, 6), title)

    def control(self, label, rect):
        x, y, w, h = rect
        self.d.rectangle([x, y, x + w, y + h], fill=CTRL, outline=EDGE)
        _text(self.d, (x + 4, y + max(2, h // 2 - 5)), label[: max(1, w // 6)])
        self.els.append({"label": label, "rect": list(rect)})

    def plain(self, rect, text=""):
        x, y, w, h = rect
        self.d.rectangle([x, y, x + w, y + h], fill=(40, 43, 50), outline=EDGE)
        for i, line in enumerate(text.split("\n") if text else []):
            _text(self.d, (x + 6, y + 6 + 12 * i), line)


def reply(*steps):
    return {"raw": json.dumps({"steps": list(steps)})}


def step(say, label, why, kind="click"):
    return {"say": say, "label": label, "why": why, "kind": kind}


EMPTY = reply()


# -- writer-export-pdf: every planned step is still on screen after the
# previous one, so the loop plans twice (the plan, then a closing check) --
def writer_export():
    s0 = Scene("Writer")
    s0.control("File", [8, 26, 40, 20])
    s0.control("Edit", [52, 26, 40, 20])
    s0.plain([8, 60, 624, 330], "Quarterly notes\n\nBody text.")
    s1 = Scene("Writer")
    s1.control("File", [8, 26, 40, 20])
    s1.control("Export as PDF", [8, 48, 140, 20])
    s1.control("Print", [8, 70, 140, 20])
    s1.plain([8, 100, 624, 290], "Quarterly notes")
    s2 = Scene("Export as PDF")
    s2.control("Save", [440, 340, 80, 24])
    s2.control("Cancel", [530, 340, 80, 24])
    s3 = Scene("Writer")
    s3.control("File", [8, 26, 40, 20])
    s3.plain([8, 60, 624, 330], "Quarterly notes\n\nSaved: notes.pdf")
    first = reply(
        step("Open the File menu.", "File",
             "Export lives in the File menu."),
        step("Choose Export as PDF.", "Export as PDF",
             "This turns the document into a PDF file."),
        step("Press Save.", "Save", "Saving writes the file to disk."))
    return {
        "id": "writer-export-pdf", "app": "writer",
        "goal": "export this document as a PDF",
        "expected_kind": "click",
        "expected_target": {"label": "File", "rect": [8, 26, 40, 20]},
        "screens": [(s0, first, {"File": 1}),
                    (s1, EMPTY, {"Export as PDF": 2}),
                    (s2, EMPTY, {"Save": 3}),
                    (s3, EMPTY, {})],
        "expected_delivery": ["File", "Export as PDF", "Save"],
        "expected_plans": 2,
    }


# -- browser-tab-group: the menu that opens is not the one the plan named,
# so the loop re-plans from the new screen; the second reply plans the
# opener again and must not be pointed at twice --
def browser_group():
    s0 = Scene("Web Browser")
    s0.control("Tab menu", [596, 28, 32, 24])
    s0.plain([8, 60, 624, 330], "Start page")
    s1 = Scene("Web Browser")
    s1.control("Tab menu", [596, 28, 32, 24])
    s1.control("Add tab to new group", [440, 56, 188, 22])
    s1.control("Close other tabs", [440, 80, 188, 22])
    s1.plain([8, 90, 420, 300], "Start page")
    s2 = Scene("Web Browser")
    s2.control("Tab menu", [596, 28, 32, 24])
    s2.control("Group name", [200, 160, 240, 24])
    s2.control("Done", [450, 160, 60, 24])
    s3 = Scene("Web Browser")
    s3.control("Tab menu", [596, 28, 32, 24])
    s3.plain([8, 60, 624, 330], "Start page\n\n[Group 1] is on the tab strip")
    first = reply(
        step("Open the tab menu.", "Tab menu",
             "Tab groups are managed from the tab menu."),
        step("Choose New group.", "New group",
             "A group keeps related tabs together."))
    second = reply(
        step("Open the tab menu.", "Tab menu", "It is already open."),
        step("Choose Add tab to new group.", "Add tab to new group",
             "This starts a group with the current tab in it."),
        step("Press Done.", "Done", "Done keeps the group name."))
    return {
        "id": "browser-tab-group", "app": "browser",
        "goal": "put this tab in a new tab group",
        "expected_kind": "click",
        "expected_target": {"label": "Tab menu", "rect": [596, 28, 32, 24]},
        "screens": [(s0, first, {"Tab menu": 1}),
                    (s1, second, {"Add tab to new group": 2}),
                    (s2, EMPTY, {"Done": 3}),
                    (s3, EMPTY, {})],
        "expected_delivery": ["Tab menu", "Add tab to new group", "Done"],
        "expected_plans": 3,
    }


# -- settings-night-light: the user switched the toggle on their own after
# the first step; the next plan skips it --
def settings_night_light():
    s0 = Scene("Settings")
    s0.control("Display", [8, 30, 120, 24])
    s0.control("Sound", [8, 58, 120, 24])
    s0.plain([140, 30, 490, 360], "Pick a section")
    s1 = Scene("Display")
    s1.control("Display", [8, 30, 120, 24])
    s1.control("Schedule", [160, 100, 120, 24])
    s1.plain([140, 60, 490, 30], "Night light: on")
    s2 = Scene("Display")
    s2.control("Display", [8, 30, 120, 24])
    s2.control("Sunset to sunrise", [160, 130, 160, 24])
    s3 = Scene("Display")
    s3.control("Display", [8, 30, 120, 24])
    s3.plain([140, 60, 490, 60], "Night light: on\nSchedule: sunset to sunrise")
    first = reply(
        step("Open Display settings.", "Display",
             "Night light is a display setting."),
        step("Turn on Night light.", "Night light toggle",
             "It warms the screen colours at night."))
    second = reply(
        step("Open Display settings.", "Display", "Already open."),
        step("Open the Schedule options.", "Schedule",
             "The schedule decides when the warmer colours start."))
    third = reply(
        step("Choose Sunset to sunrise.", "Sunset to sunrise",
             "This follows the daylight where you are."))
    return {
        "id": "settings-night-light", "app": "settings",
        "goal": "turn on night light on a schedule",
        "expected_kind": "click",
        "expected_target": {"label": "Display", "rect": [8, 30, 120, 24]},
        "screens": [(s0, first, {"Display": 1}),
                    (s1, second, {"Schedule": 2}),
                    (s2, third, {"Sunset to sunrise": 3}),
                    (s3, EMPTY, {})],
        "expected_delivery": ["Display", "Schedule", "Sunset to sunrise"],
        "expected_plans": 4,
    }


def write(case):
    d = OUT / case["id"]
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for i, (scene, rep, after) in enumerate(case["screens"]):
        cap = "capture.png" if i == 0 else f"capture-{i}.png"
        rp = "reply.json" if i == 0 else f"reply-{i}.json"
        scene.img.save(d / cap, optimize=True)
        (d / rp).write_text(json.dumps(rep, indent=1) + "\n")
        files.append({"capture": cap, "reply": rp, "elements": scene.els,
                      "after": after})
    data = {k: case[k] for k in ("id", "app", "goal")}
    data.update({"capture": "capture.png", "reply": "reply.json",
                 "size": [W, H], "expected_kind": case["expected_kind"],
                 "expected_target": case["expected_target"],
                 "elements": files[0]["elements"], "after": files[0]["after"],
                 "then": files[1:],
                 "expected_delivery": case["expected_delivery"],
                 "expected_plans": case["expected_plans"]})
    (d / "case.json").write_text(json.dumps(data, indent=1) + "\n")


if __name__ == "__main__":
    for make in (writer_export, browser_group, settings_night_light):
        write(make())
    print("wrote", OUT)
