"""AS2 profile-store ownership regressions; fake procfs/CDP only."""
import pathlib
import shlex
import tempfile
import unittest
from unittest import mock

from wisp.tools import desktop


class BrowserProfileStoreReleaseTest(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.proc = root / "proc"
        (self.proc / "net").mkdir(parents=True)
        (self.proc / "net" / "tcp").write_text(
            "header\n"
            "0: 0100007F:2407 00000000:0000 0A "
            "00000000:00000000 00:00000000 00000000 1000 0 12345\n")
        self.owner = self.proc / "123"
        (self.owner / "fd").mkdir(parents=True)
        (self.owner / "fd" / "7").symlink_to("socket:[12345]")
        self.binary = root / "chromium"
        self.binary.touch()
        (self.owner / "exe").symlink_to(self.binary)
        self.enterContext(mock.patch.object(desktop, "_PROC_ROOT", self.proc))
        self.enterContext(mock.patch.object(
            desktop.shutil, "which", return_value=str(self.binary)))

    def _set_owner_args(self, *args):
        (self.owner / "cmdline").write_bytes(
            ("\0".join([str(self.binary), *args]) + "\0").encode())

    def _selected(self, *args):
        return " ".join(shlex.quote(arg) for arg in (str(self.binary), *args))

    def test_same_profile_label_in_unconfigured_store_cannot_activate_tab(self):
        self._set_owner_args(
            "--profile-directory=Work",
            "--user-data-dir=/profiles/personal",
            "--remote-debugging-port=9223")
        selected = self._selected("--profile-directory=Work")
        page = {"id": "different-store", "type": "page",
                "title": "Inbox — Work", "url": "https://mail.google.com",
                "_cdp_port": 9223}
        with mock.patch.object(desktop, "_cdp_pages",
                               return_value=(9223, [page])), \
             mock.patch.object(desktop, "_cdp_get",
                               return_value=b"activated") as activate, \
             mock.patch.object(desktop, "_focus_browser") as focus:
            result = desktop._try_switch_open_tab(
                "mail work", url="https://mail.google.com", browser=selected)
        self.assertIsNone(result)
        activate.assert_not_called()
        focus.assert_not_called()

    def test_matching_default_or_explicit_identity_preserves_tab_reuse(self):
        cases = [
            ((), ()),
            (("--profile-directory=Work",),
             ("--profile-directory", "Work")),
            (("--profile-directory=Work", "--user-data-dir=/profiles/work"),
             ("--user-data-dir", "/profiles/work",
              "--profile-directory", "Work")),
            (("--user-data-dir=/profiles/work",),
             ("--user-data-dir=/profiles/work",)),
        ]
        page = {"id": "matching-store", "type": "page",
                "title": "Inbox", "url": "https://mail.google.com",
                "_cdp_port": 9223}
        for selected_args, actual_args in cases:
            with self.subTest(selected=selected_args, actual=actual_args):
                self._set_owner_args(*actual_args,
                                     "--remote-debugging-port=9223")
                selected = self._selected(*selected_args)
                with mock.patch("wisp.platform.active_window",
                                return_value={}), \
                     mock.patch.object(desktop, "_cdp_pages",
                                       return_value=(9223, [page])), \
                     mock.patch.object(desktop, "_cdp_get",
                                       return_value=b"activated") as activate, \
                     mock.patch.object(desktop, "_focus_browser") as focus:
                    result = desktop._try_switch_open_tab(
                        "mail", url="https://mail.google.com", browser=selected)
                self.assertEqual(
                    result, "SWITCHED tab 'Inbox' -> mail.google.com")
                activate.assert_called_once_with(
                    9223, "/json/activate/matching-store")
                focus.assert_called_once_with(
                    "Inbox", profile="", browser=selected)

    def test_extra_or_missing_profile_store_selectors_fail_closed(self):
        cases = [
            ((), ("--user-data-dir=/profiles/personal",)),
            ((), ("--profile-directory=Work",)),
            (("--user-data-dir=/profiles/work",), ()),
            (("--profile-directory=Work", "--user-data-dir=/profiles/work"),
             ("--profile-directory=Work", "--user-data-dir=/profiles/personal")),
            (("--user-data-dir=/profiles/work",),
             ("--user-data-dir=/profiles/work", "--profile-directory=Personal")),
            ((), ("--profile=/profiles/personal",)),
            ((), ("-P", "Personal")),
        ]
        for selected_args, actual_args in cases:
            with self.subTest(selected=selected_args, actual=actual_args):
                self._set_owner_args(*actual_args)
                self.assertFalse(desktop._cdp_owner_matches(
                    9223, self._selected(*selected_args)))

    def test_guest_and_private_context_protections_remain(self):
        for mode in ("--guest", "--incognito", "--private-window"):
            with self.subTest(mode=mode):
                self._set_owner_args(mode)
                self.assertFalse(desktop._cdp_owner_matches(
                    9223, self._selected()))
                self.assertTrue(desktop._cdp_owner_matches(
                    9223, self._selected(mode)))
                self._set_owner_args()
                self.assertFalse(desktop._cdp_owner_matches(
                    9223, self._selected(mode)))


if __name__ == "__main__":
    unittest.main()
