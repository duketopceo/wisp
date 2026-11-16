"""Test helper: put the hypr module's bind registry back to empty."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import hypr  # noqa: E402


def reset_binds() -> None:
    hypr._binds.clear()
    hypr._submaps.clear()
    hypr._entered.clear()
    hypr._exit_hooked = False
