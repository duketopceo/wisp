#!/usr/bin/env python3
"""U3/U4: file-manager keyboard routes and the invented-path guard,
driven through run_act_loop with recorded planner replies."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import act, act_guards, skills, tools  # noqa: E402

SEED = pathlib.Path(__file__).resolve().parent.parent / "wisp" / \
    "skills_seed" / "apps"
ROUTES = {
    "open_path": {"key": "ctrl+l", "text": "open path: `ctrl+l`, type."},
    "go_up": {"key": "alt+up", "text": "go up: `alt+Up`."},
    "new_folder": {"key": "ctrl+shift+n", "text": "new folder: `ctrl+shift+n`."},
    "rename": {"key": "f2", "text": "rename: `F2`."},
}


def _msg(content=None, calls=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = calls
    return m


def _call(name, arg=""):
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps({"arg": arg})}}


class Win:
    """A fake focused window whose title and text the test moves."""
    def __init__(self, title="Home", text="", cls="org.gnome.Nautilus"):
        self.title, self.text, self.cls = title, text, cls

    def window(self):
        return {"class": self.cls, "title": self.title}

    def read(self):
        return self.text


def run_loop(task, replies, win, tool_run=None):
    """One act run with recorded replies; returns (result, tool calls,
    the planner messages it was shown)."""
    seen, calls = [], []

    def post(messages, cfg):
        seen.append(json.loads(json.dumps(messages, default=str)))
        return replies.pop(0)

    def run(name, arg, cfg, harness=None):
        calls.append((name, arg))
        return tool_run(name, arg) if tool_run else "ok"

    real = act_guards.RunGuards

    def make(t, ur="", cfg=None, **kw):
        return real(t, ur, cfg, window=win.window, text=win.read,
                    routes=ROUTES)
    with mock.patch.object(act, "_write_pack"), \
         mock.patch.object(act, "_post", side_effect=post), \
         mock.patch.object(tools, "run", side_effect=run), \
         mock.patch.object(act_guards, "RunGuards", side_effect=make), \
         mock.patch.object(act, "_aim",
                           side_effect=lambda n, a, c, g, st: (a, None, None)), \
         mock.patch.object(act, "_gate", return_value=None):
        out = act.run_act_loop(task, {"agent": {}}, initial_image="aGk=",
                               user_request=task)
    return out, calls, seen


class Routes(unittest.TestCase):
    def test_seeded_file_managers_carry_routes(self):
        for app in ("nautilus", "thunar", "dolphin"):
            r = act_guards.parse_routes((SEED / app / "SKILL.md").read_text())
            self.assertEqual(
                {k: v["key"] for k, v in r.items()},
                {"open_path": "ctrl+l", "go_up": "alt+up",
                 "new_folder": "ctrl+shift+n", "rename": "f2"}, app)

    def test_routes_resolve_by_window_class_and_stay_in_prompt_budget(self):
        r = act_guards.routes_for_window("org.gnome.nautilus")
        self.assertIn("new_folder", r)
        info = skills.match_app_skill_info("org.gnome.nautilus")
        self.assertIn("Keyboard routes", info["body"])
        self.assertEqual(act_guards.routes_for_window("firefox"), {})

    def test_intents(self):
        i = act_guards.intent_of
        self.assertEqual(i("create a new folder called archive"), "new_folder")
        self.assertEqual(i("go up one level"), "go_up")
        self.assertEqual(i("rename draft.txt to final.txt"), "rename")
        self.assertEqual(i("open /srv/data/photos"), "open_path")
        self.assertEqual(i("open the Videos folder"), "")


class KeyboardRoutes(unittest.TestCase):
    def test_click_is_turned_back_once_then_the_key_route_runs(self):
        win = Win(title="Home")
        replies = [_msg(calls=[_call("click", "back arrow")]),
                   _msg(calls=[_call("key", "alt+Up")]),
                   _msg(content="Went up.")]

        def tool_run(name, arg):
            if name == "key":
                win.title = "Documents"
            return "KEY"
        out, calls, seen = run_loop("go up one level", replies, win, tool_run)
        self.assertEqual(calls, [("key", "alt+Up")])
        self.assertIn("keyboard route covers this", json.dumps(seen[1]))
        self.assertTrue(out.startswith("ACTED"), out)

    def test_second_click_is_not_blocked_again(self):
        win = Win()
        replies = [_msg(calls=[_call("click", "a")]),
                   _msg(calls=[_call("click", "b")]),
                   _msg(content="clicked")]
        _, calls, _ = run_loop("go up one level", replies, win)
        self.assertEqual(calls, [("click", "b")])

    def test_rename_click_to_select_is_allowed(self):
        win = Win()
        replies = [_msg(calls=[_call("click", "draft.txt")]),
                   _msg(content="selected")]
        _, calls, _ = run_loop("rename draft.txt to final.txt", replies, win)
        self.assertEqual(calls, [("click", "draft.txt")])

    def test_non_file_manager_window_is_untouched(self):
        win = Win(cls="firefox")
        with mock.patch.object(act_guards, "routes_for_window",
                               return_value={}):
            g = act_guards.RunGuards("go up one level", window=win.window,
                                     text=win.read)
            self.assertIsNone(g.pre_dispatch("click", "x"))

    def test_new_folder_waits_for_the_name_field(self):
        win = Win(title="Home", text="Files Home")
        replies = [_msg(calls=[_call("key", "ctrl+shift+n")]),
                   _msg(calls=[_call("type_text", "archive")]),
                   _msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("type_text", "archive")]),
                   _msg(content="done"), _msg(content="done")]
        out, calls, seen = run_loop(
            "create a new folder called archive", replies, win)
        # the first type_text never reached the app: no dialog yet
        self.assertEqual([c for c in calls if c[0] == "type_text"],
                         [("type_text", "archive")])
        self.assertIn("name field is not on screen", json.dumps(seen[2]))

    def test_new_folder_types_once_the_dialog_is_up(self):
        win = Win(title="Home", text="")
        replies = [_msg(calls=[_call("key", "ctrl+shift+n")]),
                   _msg(calls=[_call("type_text", "archive")]),
                   _msg(calls=[_call("key", "enter")]),
                   _msg(content="done")]

        def tool_run(name, arg):
            if name == "key" and arg == "ctrl+shift+n":
                win.title = "New Folder"
                win.text = "Folder name"
            if name == "key" and arg == "enter":
                win.title, win.text = "Home", "archive"
            return "ok"
        out, calls, _ = run_loop("create a new folder called archive",
                                 replies, win, tool_run)
        self.assertEqual([c[0] for c in calls],
                         ["key", "type_text", "key"])
        self.assertTrue(out.startswith("ACTED"), out)

    def test_done_without_the_new_folder_visible_is_nudged_back(self):
        win = Win(title="Home", text="Files: notes")
        replies = [_msg(calls=[_call("key", "ctrl+shift+n")]),
                   _msg(content="Created it."),
                   _msg(content="Created it.")]

        def tool_run(name, arg):
            win.title, win.text = "New Folder", "Folder name"
            return "ok"
        out, _, seen = run_loop("create a new folder called archive",
                                replies, win, tool_run)
        self.assertIn("'archive' is not in the window", json.dumps(seen[-1]))

    def test_open_path_route_verifies_by_title(self):
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "photos"
            target.mkdir()
            win = Win(title="Home")
            replies = [_msg(calls=[_call("key", "ctrl+l")]),
                       _msg(calls=[_call("type_text", str(target))]),
                       _msg(calls=[_call("key", "enter")]),
                       _msg(content="Opened photos.")]

            def tool_run(name, arg):
                if (name, arg) == ("key", "enter"):
                    win.title = "photos"
                return "ok"
            out, calls, _ = run_loop(f"open {target}", replies, win, tool_run)
            self.assertEqual(len(calls), 3)
            self.assertTrue(out.startswith("ACTED"), out)

    def test_open_path_done_with_the_wrong_title_is_not_confirmed(self):
        g = act_guards.RunGuards("open /srv/data/photos", window=lambda: {
            "class": "x", "title": "Home"}, text=lambda: "", routes=ROUTES)
        g.pre_dispatch("key", "ctrl+l")
        self.assertIn("'photos'", g.unverified_done())

    def test_go_up_unchanged_title_is_unverified(self):
        g = act_guards.RunGuards("go up one level", window=lambda: {
            "class": "x", "title": "Home"}, text=lambda: "", routes=ROUTES)
        g.pre_dispatch("key", "Alt+Up")
        self.assertIn("did not change", g.unverified_done())


class PathGuard(unittest.TestCase):
    def guard(self, task="open my projects", text="", **kw):
        return act_guards.RunGuards(task, window=lambda: {}, text=lambda: text,
                                    routes={}, **kw)

    def test_guessed_home_path_is_rejected_and_replanned(self):
        guessed = "/home/nobody-here/Projects"
        win = Win(cls="x")
        replies = [_msg(calls=[_call("type_text", guessed)]),
                   _msg(calls=[_call("ask_user", "Which folder?")]),
                   _msg(content="asked")]
        out, calls, seen = run_loop("open my projects folder", replies, win)
        self.assertEqual([c for c in calls if c[0] == "type_text"], [])
        self.assertIn("path guard", json.dumps(seen[1]))
        self.assertNotIn("TYPED", out)

    def test_rejection_reads_as_guessed_input_in_the_category_report(self):
        from wisp import learn
        steps = [{"tool": "type_text", "arg": "/home/zz/Projects",
                  "result": self.guard().invented_path("/home/zz/Projects")}]
        self.assertEqual(learn.categorize("ACTED (1 steps): x", steps=steps),
                         "guessed input")

    def test_existing_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self.guard().invented_path(td))
        self.assertIsNone(self.guard().invented_path("~"))

    def test_path_in_the_task_is_allowed(self):
        g = self.guard(task="open /srv/not-yet/photos please")
        self.assertIsNone(g.invented_path("/srv/not-yet/photos"))

    def test_path_in_window_text_is_allowed(self):
        g = self.guard(text="cwd: /srv/shown/on/screen\n$")
        self.assertIsNone(g.invented_path("/srv/shown/on/screen"))
        self.assertIsNotNone(g.invented_path("/srv/other/place"))

    def test_path_from_an_earlier_tool_result_is_allowed(self):
        steps = [{"tool": "shell", "arg": "pwd",
                  "result": "OUT /srv/from/pwd"}]
        self.assertIsNone(self.guard().invented_path("/srv/from/pwd", steps))

    def test_commands_and_relative_names_are_not_path_checked(self):
        g = self.guard()
        self.assertIsNone(g.invented_path("mkdir -p /srv/new/dir"))
        self.assertIsNone(g.invented_path("Videos"))
        self.assertIsNone(g.invented_path("hello world"))


if __name__ == "__main__":
    unittest.main()
