#!/usr/bin/env python3
"""Adapter catalog tests."""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp.tools import adapters  # noqa: E402


class CatalogTest(unittest.TestCase):
    def test_linux_path_untouched(self):
        with mock.patch.object(adapters, "_linux_catalog",
                               return_value={"code": {"launch": "code"}}):
            self.assertEqual(adapters.generic_catalog(),
                             {"code": {"launch": "code"}})


if __name__ == "__main__":
    unittest.main()
