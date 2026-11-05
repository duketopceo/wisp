#!/usr/bin/env python3
"""Draw the synthetic U1 teach fixtures under tests/fixtures/teach/.

Each case is one directory: capture.png (a 640x400 mock UI drawn here with
PIL, never a real screenshot), case.json (goal, expected kind, expected
target region, and the labelled controls the capture contains: the recorded
stand-in for label grounding) and reply.json (a recorded planner reply).

THE REPLIES ARE HAND-AUTHORED. They are not real model output. They imitate
what the current planner (one JSON object of say/label/why steps, kind
optional) could plausibly return, and a few are deliberately wrong so the
baseline is below 100% and later units have something to move.

Run: python scripts/gen_teach_fixtures.py   (rewrites the fixtures in place)
"""
import json
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "teach"
W, H = 640, 400
BG, BAR, FG = (30, 32, 38), (52, 56, 66), (225, 228, 235)
CTRL, EDGE, ACC = (74, 80, 94), (110, 118, 136), (90, 150, 230)

_FONT = ImageFont.load_default()


def _text(d, xy, s, fill=FG):
    d.text(xy, s, fill=fill, font=_FONT)


class Scene:
    """A mock window plus the labelled controls drawn into it."""

    def __init__(self, title):
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.els = []
        self.d.rectangle([0, 0, W, 22], fill=BAR)
        _text(self.d, (8, 6), title)

    def control(self, label, rect, text=None, fill=CTRL, record=True):
        x, y, w, h = rect
        self.d.rectangle([x, y, x + w, y + h], fill=fill, outline=EDGE)
        t = label if text is None else text
        if t:
            _text(self.d, (x + 4, y + max(2, h // 2 - 5)), t[: max(1, w // 6)])
        if record and label:
            self.els.append({"label": label, "rect": list(rect)})

    def plain(self, rect, fill=(40, 43, 50), text=""):
        x, y, w, h = rect
        self.d.rectangle([x, y, x + w, y + h], fill=fill, outline=EDGE)
        for i, line in enumerate(text.split("\n") if text else []):
            _text(self.d, (x + 6, y + 6 + 12 * i), line)


def terminal():
    s = Scene("Terminal")
    s.plain([0, 24, W, H - 24], (14, 15, 18),
            "demo@box:~/projects$ pwd\n/home/demo/projects\ndemo@box:~/projects$ _")
    s.control("New tab", [600, 2, 32, 18], "+")
    return s


def browser():
    s = Scene("Web Browser")
    s.control("Back", [8, 28, 28, 24], "<")
    s.control("Address bar", [48, 28, 440, 24], "https://example.org")
    s.control("Bookmark this page", [496, 28, 28, 24], "*")
    s.control("Menu", [600, 28, 32, 24], "...")
    s.control("New tab", [560, 2, 32, 18], "+")
    s.plain([0, 60, W, H - 60], (240, 240, 244), "")
    return s


def writer():
    s = Scene("Document - Writer")
    for i, n in enumerate(["File", "Edit", "View", "Insert", "Format"]):
        s.control(n, [8 + i * 52, 26, 48, 20])
    s.control("Bold", [8, 52, 32, 26], "B")
    s.control("Italic", [44, 52, 32, 26], "I")
    s.control("Underline", [80, 52, 32, 26], "U")
    s.plain([80, 90, 480, 290], (250, 250, 250), "")
    return s


def calc():
    s = Scene("Spreadsheet - Calc")
    s.control("File", [8, 26, 48, 20])
    for r in range(6):
        for c in range(6):
            x, y = 40 + c * 90, 70 + r * 28
            s.plain([x, y, 90, 28], (250, 250, 250))
            _text(s.d, (x + 4, y + 8), "ABCDEF"[c] + str(r + 1), (120, 120, 130))
    return s


def gimp():
    s = Scene("Image Editor")
    for i, n in enumerate(["Move", "Crop", "Paintbrush", "Eraser", "Text"]):
        s.control(n, [6, 30 + i * 36, 90, 30])
    s.plain([110, 40, 400, 300], (120, 120, 130), "")
    s.control("Top-left crop handle", [110, 40, 12, 12], "", ACC)
    s.control("Bottom-right crop handle", [498, 328, 12, 12], "", ACC)
    s.control("Layer visibility eye", [528, 52, 24, 24], "eye")
    s.control("Layers panel", [520, 84, 112, 200], "Layers", record=False)
    return s


def files():
    s = Scene("Files")
    for i, n in enumerate(["Home", "Documents", "Pictures", "Downloads"]):
        s.control(n, [6, 30 + i * 30, 110, 26])
    s.control("New Folder", [540, 28, 92, 24])
    for i, n in enumerate(["report.txt", "notes.md", "photo.png"]):
        s.control(n, [140 + i * 110, 90, 100, 60], "", record=(n == "report.txt"))
        _text(s.d, (144 + i * 110, 160), n)
    return s


def omarchy_desktop():
    s = Scene("Workspace 1")
    s.plain([0, 24, W, H - 24], (22, 24, 30), "")
    s.control("Workspace indicator", [4, 2, 90, 18], "1 2 3", BAR)
    return s


def omarchy_settings():
    s = Scene("Omarchy Settings")
    for i, n in enumerate(["Appearance", "Display", "Keyboard", "Network", "Power"]):
        s.control(n, [10, 34 + i * 40, 220, 34])
    s.plain([250, 34, 380, 340], (40, 43, 50), "Pick a section on the left.")
    return s


# (id, app, goal, scene, expected kind, target (label or None), radius, reply)
CASES = []


def case(cid, app, goal, scene, kind, target, reply, radius=None):
    CASES.append(dict(id=cid, app=app, goal=goal, scene=scene, kind=kind,
                      target=target, reply=reply, radius=radius))


def step(say, label="", why="", kind=None, x=None, y=None):
    d = {"say": say, "label": label, "why": why}
    if kind:
        d["kind"] = kind
    if x is not None:
        d["x"], d["y"] = x, y
    return d


def reply(*steps, fence=False, pre=""):
    body = json.dumps({"steps": list(steps)})
    return pre + ("```json\n" + body + "\n```" if fence else body)


case("terminal-list-files", "terminal", "show me how to list the files in this folder",
     terminal, "voice-confirm", None,
     reply(step("Type ls and press Enter.", "",
                "ls prints the names of everything in the current folder.")))
case("terminal-new-tab", "terminal", "open a second terminal tab",
     terminal, "click", "New tab",
     reply(step("Click the plus button at the top right.", "New tab",
                "Tabs let you keep several shells open side by side."), fence=True))
case("browser-new-tab", "browser", "open a new tab in the browser",
     browser, "click", "New tab",
     # DELIBERATE wrong-target: points at the bookmark star
     reply(step("Click the plus next to your tabs.", "Bookmark this page",
                "A new tab keeps this page open.")))
case("browser-address-bar", "browser", "how do I type a web address",
     browser, "click", "Address bar",
     reply(step("Click the address bar at the top.", "Address bar",
                "That is where a site address goes.")))
case("browser-open-settings", "browser", "open the browser settings",
     browser, "click", "Menu",
     # DELIBERATE no-element: label is not on screen and no coordinates
     reply(step("Open the Settings page.", "Settings",
                "Settings holds privacy and startup options.")))
case("writer-bold", "libreoffice", "make the selected text bold in Writer",
     writer, "click", "Bold",
     reply(step("Click the bold button.", "Bold",
                "Bold makes the selection heavier so it stands out.")))
case("calc-select-range", "libreoffice", "select cells A1 to C3 in Calc",
     calc, "area", "A1:C3",
     reply(step("Drag from cell A1 down to cell C3.", "",
                "Selecting a block lets you format or sum it at once.",
                x=130, y=98)), radius=0)
case("writer-file-menu", "libreoffice", "where do I save this document",
     writer, "click", "File",
     reply(step("Open the File menu.", "File", "Save and Save As live there.")))
case("gimp-paintbrush", "gimp", "pick the paintbrush tool",
     gimp, "click", "Paintbrush",
     reply(step("Click the paintbrush in the toolbox.", "Paintbrush",
                "The brush paints soft strokes in your foreground colour.")))
case("gimp-crop-handle", "gimp", "resize the crop box from the bottom-right corner",
     gimp, "handle", "Bottom-right crop handle",
     # DELIBERATE wrong-target: the top-left handle
     reply(step("Drag the corner handle to resize the crop.",
                "Top-left crop handle", "Dragging a corner resizes the box.")))
case("gimp-layer-eye", "gimp", "show me what the eye icon in Layers does",
     gimp, "hover", "Layer visibility eye",
     # DELIBERATE wrong-kind: right control, explicit click instead of hover
     reply(step("Click the eye icon in the layers panel.",
                "Layer visibility eye", "It hides or shows the layer.",
                kind="click")))
case("files-new-folder", "files", "make a new folder here",
     files, "click", "New Folder",
     reply(step("Click New Folder at the top right.", "New Folder",
                "Folders keep related files together.")))
case("files-drag-to-folder", "files", "move report.txt into Documents",
     files, "motion", "Documents",
     reply(step("Drag report.txt onto the Documents folder in the sidebar.",
                "Documents", "Dropping a file on a folder moves it there.")))
case("omarchy-no-activities", "omarchy", "open the Activities overview to find an app",
     omarchy_desktop, "voice-confirm", None,
     reply(step("There is no Activities view here. Press Super and Space to "
                "open the launcher.", "",
                "Apps start from the launcher, not an overview.")))
case("omarchy-display-settings", "omarchy", "change the display scaling in settings",
     omarchy_settings, "click", "Display",
     # DELIBERATE no-element: prose, no JSON object at all
     "Sure. Open the settings app, find the display section, and look for the "
     "scaling option there.")


def rect_of(scene, label):
    if label == "A1:C3":
        return [40, 70, 270, 84]
    for e in scene.els:
        if e["label"] == label:
            return e["rect"]
    raise SystemExit(f"label {label!r} not drawn")


def main():
    for c in CASES:
        sc = c["scene"]()
        d = OUT / c["id"]
        d.mkdir(parents=True, exist_ok=True)
        sc.img.convert("P", palette=Image.ADAPTIVE, colors=32).save(
            d / "capture.png", optimize=True)
        target = None
        if c["target"]:
            target = {"label": c["target"], "rect": rect_of(sc, c["target"]),
                      "radius": c["radius"]}
            if target["radius"] is None:
                del target["radius"]
        case_json = {"id": c["id"], "app": c["app"], "goal": c["goal"],
                     "capture": "capture.png", "reply": "reply.json",
                     "size": [W, H], "expected_kind": c["kind"],
                     "expected_target": target, "elements": sc.els}
        (d / "case.json").write_text(json.dumps(case_json, indent=1) + "\n")
        (d / "reply.json").write_text(json.dumps({"raw": c["reply"]}, indent=1) + "\n")
    print(f"wrote {len(CASES)} cases to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
