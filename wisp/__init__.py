"""Wisp — resident voice assistant daemon for Omarchy/Hyprland."""
import os
import sys


def _isolate_test_desktop() -> None:
    """Under `python -m unittest` (any form: discover, one module, CI),
    cut the process off from the live desktop before any wisp module
    reads its environment. Every test imports `wisp`, so this one place
    runs first for all of them, and child processes inherit the result.
    Tests that want a fake compositor set their own env afterwards."""
    # unittest rewrites argv[0] to "python -m unittest"; a test file run
    # directly shows up as tests/test_*.py with unittest already loaded.
    a0 = sys.argv[0] if sys.argv else ""
    if not ("unittest" in a0 or (
            "unittest" in sys.modules
            and os.path.basename(a0).startswith("test_"))):
        return
    if os.environ.get("WISP_TEST_ALLOW_DESKTOP"):
        return
    import atexit
    import shutil
    import tempfile
    for k in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY"):
        os.environ.pop(k, None)
    rt = tempfile.mkdtemp(prefix="wisp-test-run-")  # 0700
    os.environ["XDG_RUNTIME_DIR"] = rt
    atexit.register(shutil.rmtree, rt, True)


_isolate_test_desktop()
