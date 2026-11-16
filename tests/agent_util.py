"""Test helper for the task reaper: one pass, as the daemon's tick runs it."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import agents, config  # noqa: E402


def reap_tick(cfg: dict, tasks_file=config.TASKS_FILE,
              log_dir=config.TASK_LOGS,
              kill_grace_s: float = agents.KILL_GRACE_S,
              routines_store=None) -> list:
    """One reaper pass. Returns the tasks that went running -> not
    running during it (`finished()` shape)."""
    return agents._tick_events(cfg, tasks_file, log_dir, kill_grace_s,
                               routines_store=routines_store)[1]
