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
# U9 app-skill cases live apart from the baseline battery above: their
# replies are written to be correct, so mixing them in would inflate the
# measured teach baseline (docs/ACCURACY.md).
SKILL_OUT = OUT.parent / "teach-skills"
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


# U9: one synthetic case per skill added from docs/research/app-skill-targets.md.
# Each draws a generic mock window (a menu row, a tool column, a work area)
# and asks for one labelled control; every reply is correct.
# (skill, window title, goal, [menu labels], target label, say, why)
_APP_CASES = [
    ("alacritty", "Terminal", "open a second Alacritty window", ["New window"],
     "New window", "Click New window at the top.", "Alacritty has no tabs, so a second window is the way."),
    ("ghostty", "Terminal", "split this Ghostty window to the right", ["Split right", "New tab"],
     "Split right", "Click Split right.", "A split puts two shells side by side."),
    ("gnome-terminal", "Terminal", "open a new tab in GNOME Terminal", ["New tab", "Menu"],
     "New tab", "Click the plus in the tab bar.", "Tabs keep several shells open."),
    ("konsole", "Terminal", "split the Konsole view in two", ["View", "Settings"],
     "View", "Open the View menu and choose Split View.", "Split View shows two shells together."),
    ("dolphin", "Files", "split Dolphin into two panes", ["Split", "Places"],
     "Split", "Click Split in the toolbar.", "Two panes make copying between folders easy."),
    ("thunar", "Files", "open a terminal in this Thunar folder", ["File", "Edit", "View"],
     "File", "Open the File menu and pick Open Terminal Here.", "The terminal starts in this folder."),
    ("vlc", "Media Player", "add a subtitle file in VLC", ["Media", "Subtitle", "Tools"],
     "Subtitle", "Open the Subtitle menu and pick Add Subtitle File.", "That loads the file for this video."),
    ("mpv", "Video", "show the on-screen controls in mpv", ["Seek bar", "Volume"],
     "Seek bar", "Move the pointer near the bottom to reveal the seek bar.", "The controller appears on pointer movement."),
    ("evince", "Document Viewer", "show the page thumbnails", ["Sidebar", "Find", "Menu"],
     "Sidebar", "Click the sidebar toggle at the top left.", "The sidebar lists page thumbnails."),
    ("gnome-text-editor", "Text Editor", "open the preferences", ["Open", "Menu"],
     "Menu", "Click the menu button at the top right.", "Preferences is listed in that menu."),
    ("inkscape", "Vector Editor", "draw a rectangle in Inkscape", ["Select", "Rectangle", "Ellipse", "Text"],
     "Rectangle", "Click the rectangle tool in the toolbox.", "Then drag on the canvas to draw it."),
    ("krita", "Painting", "pick the eraser in Krita", ["Brush", "Eraser", "Fill"],
     "Eraser", "Click the eraser in the toolbox.", "The eraser removes paint from the layer."),
    ("kdenlive", "Video Editor", "open the render dialog", ["Project", "Render"],
     "Render", "Click Render in the toolbar.", "Render writes the finished video file."),
    ("obs-studio", "Recorder", "start a recording in OBS", ["Start Streaming", "Start Recording", "Settings"],
     "Start Recording", "Click Start Recording in the Controls dock.", "Recording saves a file locally."),
    ("audacity", "Audio Editor", "start recording audio", ["Play", "Record", "Stop"],
     "Record", "Click the red record button.", "Recording begins on a new track."),
    ("darktable", "Photos", "switch to the darkroom to edit a photo", ["Lighttable", "Darkroom"],
     "Darkroom", "Click Darkroom at the top right.", "Editing happens in the darkroom view."),
    ("shotcut", "Video Editor", "export the video from Shotcut", ["Open File", "Export"],
     "Export", "Click Export in the toolbar.", "Export renders the finished video."),
    ("okular", "Document Viewer", "start annotating a PDF in Okular", ["File", "Tools", "Settings"],
     "Tools", "Open the Tools menu and choose Review.", "Review shows the annotation tools."),
    ("calibre", "Library", "add a book to calibre", ["Add books", "Convert books", "View"],
     "Add books", "Click Add books in the toolbar.", "That copies the book into the library."),
    ("flameshot", "Capture", "save the Flameshot capture to a file", ["Copy", "Save", "Cancel"],
     "Save", "Click the save button in the tool bar.", "That writes the capture to a file."),
    ("zed", "Editor", "open the command palette in Zed", ['Project', 'Search', 'Terminal', 'Palette'], "Palette", "Press Control Shift P, or open the command palette from the menu.", "The palette runs any command by name."),
    ("sublime-text", "Editor", "open the sidebar in Sublime Text", ['File', 'Edit', 'View', 'Goto'], "View", "Open the View menu and pick Side Bar.", "That shows the project folders."),
    ("intellij-idea", "IDE", "run the project in IntelliJ IDEA", ['Project', 'Run', 'Debug', 'Git'], "Run", "Click the Run button in the toolbar.", "Run starts the selected configuration."),
    ("emacs", "Editor", "switch buffers in Emacs", ['File', 'Edit', 'Options', 'Buffers'], "Buffers", "Open the Buffers menu to switch buffers.", "Split commands also live in the File menu."),
    ("kate", "Editor", "open the terminal in Kate", ['Documents', 'Projects', 'Terminal'], "Terminal", "Click Terminal at the bottom.", "That opens the embedded terminal panel."),
    ("postman", "API Client", "send a request in Postman", ['Params', 'Headers', 'Body', 'Send'], "Send", "Click Send beside the URL bar.", "The response appears below the request."),
    ("dbeaver", "Database", "open a SQL editor in DBeaver", ['Navigator', 'SQL Editor', 'Run'], "SQL Editor", "Click SQL Editor in the toolbar.", "That opens a script for the selected connection."),
    ("virt-manager", "Virtual Machines", "create a new virtual machine", ['New', 'Open', 'Run', 'Shut Down'], "New", "Click the New button at the top left.", "The wizard walks through the setup."),
    ("gitlab", "Merge Request", "open the changes of a merge request", ['Overview', 'Commits', 'Pipelines', 'Changes'], "Changes", "Click the Changes tab.", "It shows the diff to review."),
    ("stack-overflow", "Questions", "ask a new question", ['Home', 'Questions', 'Tags', 'Ask Question'], "Ask Question", "Click the Ask Question button.", "It opens the form for a title and details."),
    ("slack", "Workspace", "search messages in Slack", ['Home', 'DMs', 'Search', 'Threads'], "Search", "Click the search bar at the top.", "Search covers messages and files."),
    ("discord", "Server", "open user settings in Discord", ['Servers', 'Channels', 'Voice', 'Settings'], "Settings", "Click the gear next to your name.", "User Settings opens from there."),
    ("signal", "Chats", "attach a file in Signal", ['Chats', 'Search', 'Attach', 'Send'], "Attach", "Click the plus beside the message box.", "It lets you pick a file to attach."),
    ("telegram", "Chats", "open Saved Messages in Telegram", ['Menu', 'Search', 'Folders'], "Menu", "Click the menu button at the top left.", "Saved Messages is listed in that menu."),
    ("element", "Rooms", "start a new chat in Element", ['Home', 'Explore', 'Start chat', 'Settings'], "Start chat", "Click the plus above the room list.", "It offers a new chat or room."),
    ("zoom", "Home", "join a meeting in Zoom", ['New meeting', 'Join', 'Schedule', 'Share screen'], "Join", "Click Join on the home screen.", "Enter the meeting ID or link there."),
    ("google-meet", "Meeting", "turn on captions in Meet", ['Mic', 'Camera', 'Captions', 'Present'], "Captions", "Click the captions button in the bottom bar.", "Captions show what people say."),
    ("microsoft-teams", "Teams", "start a chat in Teams", ['Activity', 'Chat', 'Teams', 'Calendar'], "Chat", "Click Chat in the left rail.", "The new chat button is above the list."),
    ("whatsapp-web", "Chats", "attach a file in WhatsApp Web", ['Chats', 'Status', 'Attach', 'Send'], "Attach", "Click the attach button beside the message box.", "It lets you pick a file."),
    ("gmail", "Inbox", "compose a new email in Gmail", ['Compose', 'Inbox', 'Sent', 'Labels'], "Compose", "Click Compose at the top left.", "A new message window opens."),
    ("google-docs-editors", "Document", "share this document", ['File', 'Edit', 'View', 'Share'], "Share", "Click the Share button at the top right.", "It sets who can view or edit."),
    ("google-drive", "My Drive", "upload a file to Drive", ['New', 'My Drive', 'Shared', 'Trash'], "New", "Click New at the top left, then File upload.", "The file goes into the open folder."),
    ("google-calendar", "Calendar", "create a new event", ['Create', 'Today', 'Week', 'Settings'], "Create", "Click the Create button at the top left.", "It opens a new event."),
    ("outlook-web", "Mail", "write a new message in Outlook", ['New mail', 'Reply', 'Delete', 'Archive'], "New mail", "Click New mail above the message list.", "A compose pane opens."),
    ("office-web", "OneDrive", "upload a file to OneDrive", ['New', 'Upload', 'Share', 'Sort'], "Upload", "Click Upload in the command bar.", "Choose Files or Folder."),
    ("dropbox", "Files", "upload a file to Dropbox", ['Upload', 'Create', 'Share', 'Search'], "Upload", "Click Upload at the top right.", "Pick Files or Folder."),
    ("notion", "Page", "share a Notion page", ['Share', 'Comments', 'Updates', 'More'], "Share", "Click Share at the top right.", "It sets who can view or edit."),
    ("overleaf", "Project", "compile the Overleaf project", ['Menu', 'Share', 'History', 'Recompile'], "Recompile", "Click Recompile above the preview.", "The PDF refreshes after the compile."),
    ("zotero", "Library", "add a new item in Zotero", ['New Item', 'New Note', 'Attach', 'Search'], "New Item", "Click New Item in the toolbar.", "It adds an item to the library."),
    ("joplin", "Notes", "create a new notebook in Joplin", ['New note', 'New to-do', 'New notebook', 'Sync'], "New notebook", "Click New notebook in the toolbar.", "Give it a name to create it."),
    ("linear", "Issues", "create a new issue in Linear", ['New issue', 'Inbox', 'My issues', 'Filter'], "New issue", "Click New issue at the top of the sidebar.", "It opens the issue form."),
    ("jira", "Board", "create an issue in Jira", ['Create', 'Board', 'Backlog', 'Filters'], "Create", "Click Create in the top bar.", "Pick the project and issue type."),
    ("trello", "Board", "add a card to the first list", ['Add a card', 'Filter', 'Share', 'Menu'], "Add a card", "Click Add a card at the bottom of the list.", "Type the card title and press Enter."),
    ("asana", "Project", "add a task in Asana", ['Add task', 'List', 'Board', 'Timeline'], "Add task", "Click Add task at the top of the project.", "Type a name and press Enter."),
    ("airtable", "Base", "add a new field in Airtable", ['Grid view', 'Filter', 'Sort', 'Add field'], "Add field", "Click the plus at the end of the column headers.", "Choose the field type next."),
    ("figma", "Design", "draw a rectangle in Figma", ['Move', 'Frame', 'Rectangle', 'Text'], "Rectangle", "Click the rectangle tool in the toolbar.", "Then drag on the canvas."),
    ("canva", "Editor", "download the design from Canva", ['Elements', 'Text', 'Share', 'Download'], "Share", "Click Share at the top right.", "Download is in the menu that opens."),
    ("miro", "Board", "add a sticky note in Miro", ['Select', 'Sticky note', 'Shapes', 'Share'], "Sticky note", "Click the sticky note icon in the left toolbar.", "Then click the board to place it."),
    ("excalidraw", "Canvas", "draw an arrow in Excalidraw", ['Selection', 'Rectangle', 'Arrow', 'Text'], "Arrow", "Click the arrow tool in the top toolbar.", "Then drag on the canvas."),
    ("clickup", "List", "add a task in ClickUp", ['Add Task', 'List', 'Board', 'Calendar'], "Add Task", "Click Add Task at the top right of the list.", "Type a name and press Enter."),
    ("youtube", "Video", "turn on captions in YouTube", ['Play', 'Captions', 'Settings', 'Fullscreen'], "Captions", "Click the CC button in the player.", "Captions appear over the video."),
    ("google-search", "Search", "search for images", ['All', 'Images', 'News', 'Tools'], "Images", "Click Images under the search box.", "Picture results replace the web results."),
    ("google-maps", "Map", "get directions in Google Maps", ['Search', 'Directions', 'Saved', 'Layers'], "Directions", "Click Directions beside the search box.", "Then enter a start and a destination."),
    ("wikipedia", "Article", "see the history of an article", ['Read', 'Edit', 'View history', 'Tools'], "View history", "Click View history at the top of the article.", "It lists past edits."),
    ("reddit", "Subreddit", "create a post on Reddit", ['Home', 'Popular', 'Create', 'Search'], "Create", "Click Create in the top bar.", "Pick a community first."),
    ("x", "Home", "write a post on X", ['Home', 'Explore', 'Bookmarks', 'Post'], "Post", "Click Post in the left list.", "It opens the composer."),
    ("linkedin", "Feed", "search for jobs on LinkedIn", ['Home', 'My Network', 'Jobs', 'Messaging'], "Jobs", "Click Jobs in the top bar.", "Job search and filters open there."),
    ("amazon", "Product", "add this item to the cart", ['Add to Cart', 'Buy Now', 'Orders', 'Cart'], "Add to Cart", "Click Add to Cart on the right.", "It only adds the item; nothing is bought."),
    ("chatgpt", "Chat", "start a new chat in ChatGPT", ['New chat', 'Search chats', 'Library', 'Settings'], "New chat", "Click New chat at the top of the sidebar.", "It opens an empty conversation."),
    ("claude", "Chat", "start a new chat in Claude", ['New chat', 'Chats', 'Projects', 'Settings'], "New chat", "Click New chat at the top of the sidebar.", "It opens an empty conversation."),
    ("bitwarden", "Vault", "add a new login in Bitwarden", ['Vaults', 'Send', 'Tools', 'New'], "New", "Click New at the top right.", "Choose Item, then Login."),
    ("keepassxc", "Database", "add a new entry in KeePassXC", ['Database', 'Entries', 'Groups', 'Tools'], "Entries", "Open the Entries menu and choose New Entry.", "It opens the entry form."),
]


def app_scene(title, labels):
    s = Scene(title)
    for i, n in enumerate(labels):
        s.control(n, [8 + i * 118, 28, 112, 24])
    s.plain([8, 64, W - 16, H - 76], (40, 43, 50), "")
    return s


for _id, _title, _goal, _labels, _target, _say, _why in _APP_CASES:
    case(f"skill-{_id}", _id, _goal, (lambda t=_title, l=_labels: app_scene(t, l)),
         "click", _target, reply(step(_say, _target, _why, kind="click")))


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
        d = (SKILL_OUT if c["id"].startswith("skill-") else OUT) / c["id"]
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
    print(f"wrote {len(CASES)} cases to {OUT} and {SKILL_OUT}")


if __name__ == "__main__":
    sys.exit(main())
