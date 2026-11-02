"""First module `unittest discover` imports (sorted order): installs the
hermetic environment before any other test module imports `wisp`, and guards
that the suite can never again point at the real home or runtime dir."""
import os
import unittest
from pathlib import Path

import hermetic  # tests/hermetic.py (tests/ is on sys.path under discover)

hermetic.install()


def _inside(p, root) -> bool:
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


class HermeticEnvironment(unittest.TestCase):
    def test_env_points_at_the_temp_root(self):
        root = hermetic.root()
        self.assertTrue(root)
        for var in ("HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            self.assertTrue(_inside(os.environ[var], root),
                            f"{var} escapes the temp root")

    def test_not_the_real_home_or_runtime_dir(self):
        rh, rr = hermetic.real_home(), hermetic.real_runtime_dir()
        self.assertTrue(Path(os.environ["HOME"]) != Path(rh))
        for var in ("HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            for real in filter(None, (rh, rr)):
                self.assertFalse(_inside(os.environ[var], real),
                                 f"{var} is inside the real {real}")

    def test_wisp_paths_resolve_inside_the_temp_root(self):
        from wisp import config, errlog
        root = hermetic.root()
        for name in ("DATA_DIR", "RUN_DIR", "SOCK_FILE", "CFG_DIR"):
            self.assertTrue(_inside(getattr(config, name), root),
                            f"config.{name} = {getattr(config, name)}")
        self.assertTrue(_inside(errlog.FILE, root))

    def test_dbus_is_neutralised(self):
        addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        self.assertTrue(addr.startswith("unix:path="))
        self.assertFalse(os.path.exists(addr[len("unix:path="):]))

    def test_notify_send_is_the_stub(self):
        import shutil
        found = shutil.which("notify-send")
        self.assertTrue(found and _inside(found, hermetic.root()), found)


if __name__ == "__main__":
    unittest.main()
