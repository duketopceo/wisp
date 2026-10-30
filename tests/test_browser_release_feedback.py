"""PR #259 browser/focus feedback regressions using fake OS/CDP seams only."""
import json
import pathlib
import shlex
import tempfile
import unittest
from unittest import mock

from wisp import act
from wisp.tools import desktop


class BrowserReleaseFeedbackTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch("wisp.tools.adapters.generic_catalog", return_value={}),
            mock.patch("wisp.inventory.defaults", return_value={}),
            mock.patch.object(desktop, "_wm_down", return_value=None),
            mock.patch.object(desktop, "_browseros_live", return_value=False),
            mock.patch.object(desktop, "_find_window", return_value=None),
            mock.patch.object(desktop, "_on_path", return_value=True),
            mock.patch.object(desktop.shutil, "which", return_value=None),
            mock.patch("wisp.platform.active_window", return_value={}),
            mock.patch.object(desktop, "_cdp_get",
                              side_effect=OSError("no CDP endpoint")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.launcher = self.enterContext(mock.patch.object(
            desktop, "_exec_detached", return_value=True))

    def test_catalog_names_keep_their_leading_article(self):
        for name in ("The Game", "open The Game"):
            with self.subTest(name=name):
                result = desktop.launch(
                    name, {"apps": {"thegame": "the-game"}})
                self.assertTrue(result.startswith("LAUNCHED"), result)
                self.launcher.assert_called_with("the-game")

    def test_exact_catalog_names_precede_spoken_verb_interpretation(self):
        result = desktop.launch(
            "Open Board", {"apps": {"openboard": "open-board"}})
        self.assertTrue(result.startswith("LAUNCHED"), result)
        self.launcher.assert_called_once_with("open-board")

    def test_failed_default_browser_launch_is_not_reported_opened(self):
        self.launcher.return_value = False
        with mock.patch.object(desktop, "_web_browser", return_value=None), \
             mock.patch.object(desktop.shutil, "which",
                               side_effect=lambda binary:
                               "/fake/xdg-open" if binary == "xdg-open"
                               else None):
            for name in ("stripe", "https://example.test"):
                with self.subTest(name=name):
                    result = desktop.launch(name, {})
                    self.assertTrue(result.startswith("SKIP"), result)
                    self.assertIn("could not open", result)

    def test_focusing_browser_does_not_prove_service_destination_opened(self):
        for task, arg, cls, start in (
                ("open my email", "mail", "browseros", "browseros"),
                ("open my email", "mail", "chromium", "foot"),
                ("go to Stripe", "browser", "firefox", "firefox"),
                ("open Linear", "chromium", "chromium", ""),
                ("open Notion", "chromium", "chromium", "chromium")):
            with self.subTest(task=task, start=start):
                steps = [{"tool": "focus", "arg": arg,
                          "result": f"FOCUSED {arg} -> {cls} (already running)"}]
                why = act._unsupported_done(task, steps, start_focus=start)
                self.assertIsNotNone(why)
                self.assertIn("destination", why)

    def test_mail_reuse_requires_configured_destination_host(self):
        cfg = {"apps": {"chromium": "chromium"},
               "web": {"mail": "https://outlook.office.com/mail"}}
        wrong_tab = {"id": "gmail", "type": "page", "title": "Mail",
                     "url": "https://mail.google.com/mail/u/0"}
        with mock.patch("wisp.inventory.defaults", return_value={
                "browser": "chromium", "mail": "chromium"}), \
             mock.patch.object(desktop, "_cdp_pages",
                               return_value=(9100, [wrong_tab])), \
             mock.patch.object(desktop, "_cdp_owner_matches",
                               return_value=True), \
             mock.patch.object(desktop, "_cdp_get",
                               return_value=b"Target activated") as cdp, \
             mock.patch.object(desktop, "_focus_browser"):
            result = desktop.launch("email", cfg)
        self.assertEqual(
            result, "OPENED https://outlook.office.com/mail -> chromium")
        self.launcher.assert_called_once_with(
            "chromium https://outlook.office.com/mail")
        cdp.assert_not_called()

    def test_service_launch_does_not_reuse_another_browser_endpoint(self):
        selected = "firefox --profile /profiles/work"
        tab = {"id": "stripe", "type": "page", "title": "Stripe",
               "url": "https://dashboard.stripe.com", "_cdp_port": 9108}
        with mock.patch.object(desktop, "_web_browser",
                               return_value=selected), \
             mock.patch.object(desktop, "_cdp_pages",
                               return_value=(9108, [tab])), \
             mock.patch.object(desktop, "_cdp_get",
                               return_value=b"Target activated") as cdp, \
             mock.patch.object(desktop, "_focus_browser"), \
             mock.patch.object(desktop, "_cdp_owner_matches",
                               return_value=False) as owner:
            result = desktop.launch("stripe", {})
        self.assertEqual(
            result, f"OPENED https://dashboard.stripe.com -> {selected}")
        self.launcher.assert_called_once_with(
            selected + " https://dashboard.stripe.com")
        owner.assert_called_once_with(9108, selected)
        cdp.assert_not_called()

    def _fake_proc_owner(self, args):
        root = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        proc = root / "proc"
        (proc / "net").mkdir(parents=True)
        (proc / "net" / "tcp").write_text(
            "header\n"
            "0: 0100007F:2407 00000000:0000 0A "
            "00000000:00000000 00:00000000 00000000 1000 0 12345\n")
        process = proc / "123"
        (process / "fd").mkdir(parents=True)
        (process / "fd" / "7").symlink_to("socket:[12345]")
        binary = root / "chromium"
        binary.touch()
        (process / "exe").symlink_to(binary)
        (process / "cmdline").write_bytes(
            ("\0".join([str(binary), *args]) + "\0").encode())
        self.enterContext(mock.patch.object(
            desktop, "_PROC_ROOT", proc))
        return binary, process

    def test_cdp_ownership_is_proven_by_socket_and_executable(self):
        binary, _ = self._fake_proc_owner([
            "--profile-directory=Work", "--remote-debugging-port=9223"])
        with mock.patch.object(desktop.shutil, "which",
                               return_value=str(binary)):
            self.assertTrue(desktop._cdp_owner_matches(
                9223, shlex.quote(str(binary)) + " --profile-directory=Work"))

    def test_cdp_owner_must_match_configured_profile_arguments(self):
        binary, _ = self._fake_proc_owner([
            "--profile-directory", "Personal",
            "--user-data-dir=/profiles/personal"])
        with mock.patch.object(desktop.shutil, "which",
                               return_value=str(binary)):
            for selected_args in ("--profile-directory=Work",
                                  "--user-data-dir /profiles/work",
                                  "--guest"):
                with self.subTest(selected_args=selected_args):
                    self.assertFalse(desktop._cdp_owner_matches(
                        9223, shlex.quote(str(binary)) + " " + selected_args))

    def test_service_reuse_never_falls_back_to_wrong_or_unknown_profile(self):
        selected = "chromium --profile-directory=Work"
        for title in ("Stripe — Personal", "Stripe"):
            with self.subTest(title=title), \
                 mock.patch.object(desktop, "_web_browser",
                                   return_value=selected), \
                 mock.patch.object(desktop, "_cdp_pages", return_value=(
                     9223, [{"id": "stripe", "type": "page", "title": title,
                             "url": "https://dashboard.stripe.com"}])), \
                 mock.patch.object(desktop, "_cdp_owner_matches",
                                   return_value=True), \
                 mock.patch.object(desktop, "_cdp_get",
                                   return_value=b"Target activated") as cdp, \
                 mock.patch.object(desktop, "_focus_browser"):
                result = desktop.launch("Stripe for work", {})
                self.assertEqual(
                    result, f"OPENED https://dashboard.stripe.com -> {selected}")
                self.launcher.assert_called_with(
                    selected + " https://dashboard.stripe.com")
                cdp.assert_not_called()

    def test_reused_tab_raises_only_the_selected_browser_window(self):
        tab = {"id": "stripe", "type": "page", "title": "Stripe — Work",
               "url": "https://dashboard.stripe.com"}
        windows = [
            {"class": "firefox", "title": "Stripe — Work", "address": "other"},
            {"class": "chromium", "title": "Stripe — Work", "address": "chosen"},
        ]
        with mock.patch.object(desktop, "_cdp_pages",
                               return_value=(9223, [tab])), \
             mock.patch.object(desktop, "_cdp_owner_matches",
                               return_value=True), \
             mock.patch.object(desktop, "_cdp_get",
                               return_value=b"Target activated"), \
             mock.patch("wisp.platform.uses_hypr", return_value=True), \
             mock.patch.object(desktop.hypr, "available", return_value=True), \
             mock.patch.object(desktop.hypr, "query", return_value=windows), \
             mock.patch("wisp.platform._try", return_value=True) as focus:
            result = desktop._try_switch_open_tab(
                "stripe work", url="https://dashboard.stripe.com",
                browser="chromium --profile-directory=Work")
        self.assertTrue(result.startswith("SWITCHED"), result)
        focus.assert_called_once_with([
            desktop.hypr.LuaCmd(desktop.hypr.focus_window("address:chosen"))])

    def test_discovery_uses_actual_endpoint_not_page_supplied_port(self):
        payload = [{"id": "stripe", "type": "page", "title": "Stripe",
                    "url": "https://dashboard.stripe.com", "_cdp_port": 9223}]
        with mock.patch.object(desktop, "CDP_PORTS", (9108,)), \
             mock.patch.object(desktop, "_cdp_get",
                               return_value=json.dumps(payload).encode()):
            port, pages = desktop._cdp_pages()
        self.assertEqual(port, 9108)
        self.assertEqual(pages[0]["_cdp_port"], 9108)

    def test_normal_browser_selection_does_not_reuse_guest_context(self):
        binary, _ = self._fake_proc_owner(["--guest"])
        with mock.patch.object(desktop.shutil, "which",
                               return_value=str(binary)):
            self.assertFalse(desktop._cdp_owner_matches(
                9223, shlex.quote(str(binary))))

    def test_owned_matching_service_tabs_reuse_selected_profile(self):
        binary, _ = self._fake_proc_owner(["--profile-directory=Work"])
        selected = shlex.quote(str(binary)) + " --profile-directory=Work"
        pages = [
            {"id": "stripe", "type": "page", "title": "Stripe — Work",
             "url": "https://dashboard.stripe.com"},
            {"id": "mail", "type": "page", "title": "Inbox — Work",
             "url": "https://mail.google.com"},
        ]

        def cdp_get(port, path):
            if path == "/json/list":
                return json.dumps(pages if port == 9223 else []).encode()
            return b"Target activated"

        with mock.patch.object(desktop.shutil, "which",
                               side_effect=lambda name:
                               str(binary) if name == str(binary) else None), \
             mock.patch("wisp.inventory.defaults", return_value={
                 "browser": "chromium", "mail": "chromium"}), \
             mock.patch.object(desktop, "_cdp_get",
                               side_effect=cdp_get) as cdp, \
             mock.patch.object(desktop, "_focus_browser") as focus:
            cfg = {"apps": {"chromium": selected}}
            stripe = desktop.launch("Stripe for work", cfg)
            mail = desktop.launch("email for work", cfg)
        self.assertIn("SWITCHED tab 'Stripe — Work'", stripe)
        self.assertIn("SWITCHED tab 'Inbox — Work'", mail)
        self.assertIn(mock.call(9223, "/json/activate/stripe"),
                      cdp.call_args_list)
        self.assertIn(mock.call(9223, "/json/activate/mail"),
                      cdp.call_args_list)
        focus.assert_called_with("Inbox — Work", profile="work",
                                 browser=selected)
        self.launcher.assert_not_called()

    def test_unknown_or_mismatched_endpoint_owner_is_not_trusted(self):
        binary, process = self._fake_proc_owner([])
        other = binary.with_name("firefox")
        other.touch()
        with mock.patch.object(desktop.shutil, "which",
                               return_value=str(other)):
            self.assertFalse(desktop._cdp_owner_matches(9223, str(other)))
        (process / "fd" / "7").unlink()
        with mock.patch.object(desktop.shutil, "which",
                               return_value=str(binary)):
            self.assertFalse(desktop._cdp_owner_matches(9223, str(binary)))
        with mock.patch.object(desktop, "_PROC_ROOT",
                               binary.parent / "missing-proc"), \
             mock.patch.object(desktop.shutil, "which",
                               return_value=str(binary)):
            self.assertFalse(desktop._cdp_owner_matches(9223, str(binary)))

    def test_focus_guard_keeps_native_handlers_and_confirmed_navigation(self):
        for result, tool, arg in (
                ("FOCUSED thunderbird -> thunderbird (already running)",
                 "launch", "thunderbird"),
                ("SWITCHED tab 'Inbox' -> mail.google.com", "tab", "mail"),
                ("OPENED https://mail.google.com -> browseros",
                 "launch", "mail")):
            with self.subTest(result=result):
                self.assertIsNone(act._unsupported_done(
                    "open my email",
                    [{"tool": tool, "arg": arg, "result": result}],
                    start_focus="foot"))
        self.assertIsNotNone(act._unsupported_done(
            "open my email",
            [{"tool": "focus", "arg": "chromium", "result": "FOCUSED chromium"}],
            start_focus="chromium"))


if __name__ == "__main__":
    unittest.main()
