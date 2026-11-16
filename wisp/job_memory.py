"""Per-job memory: what one piece of work must not forget (§2 of the
Clicky transfer).

The gap the transfer doc names: MEMORY.md is global (who the user is),
two concurrent jobs cannot both own it, and a long run's corrections
live only in the transcript. This module gives each run a small file —
`<log_dir>/<task>/out/../memory.md`, beside the job's own out dir —
that the model itself writes and that is shown back at the start of
every model call in the run. The transfer doc's rule is copied exactly
because the pointing behaviour is what makes it survive: *short, and
it points at detail rather than holding it.*

Read by `act.run_act_loop` before each model call (a disk read, never
inside the message history, so nothing can summarise it away); written
by the model through `memory_save` with the full file — no appends, no
deletes — so the file is always exactly what the model believes and a
hallucinated merge cannot leave a stale rule standing.
"""

from __future__ import annotations

from pathlib import Path

MEMORY_NAME = "memory.md"
MEMORY_MAX_CHARS = 2_000
MEMORY_TRIGGER = (
    "When this work spans many steps or has rules you must keep, save a "
    "memory file with memory_save: the goal in a line, every rule or "
    "correction the user gave in their words, what counts as done, and "
    "where progress lives. Keep it short — it points at detail rather "
    "than holding it. It is shown back to you before every step, so "
    "write it before the bulk of the work and update it when a rule or "
    "the plan changes. Save the whole file each time: it replaces what "
    "you had."
)


def job_dir(out_dir: str | Path) -> Path:
    """The job folder that owns this run's out dir: out_dir's parent
    (the task dir under log_dir), or out_dir itself when it has no
    parent task dir. Never DATA_DIR — a job's memory is not global."""
    p = Path(out_dir)
    return p.parent if p.name in ("out", "output") else p


def memory_path(out_dir: str | Path) -> Path:
    return job_dir(out_dir) / MEMORY_NAME


def read(out_dir: str | Path) -> str | None:
    """The job's memory file as the model last wrote it, or None when
    there is none — None must not splice an empty reminder in."""
    try:
        text = memory_path(out_dir).read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    return text[:MEMORY_MAX_CHARS] if text else None


def write(out_dir: str | Path, text: str) -> bool:
    """Replace the memory file whole. Empty text is refused: a model
    that wants the memory gone must say why in the file, not delete it
    silently."""
    if not text or not text.strip():
        return False
    p = memory_path(out_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text.strip()[:MEMORY_MAX_CHARS], encoding="utf-8")
    except OSError:
        return False
    return True


def reminder(out_dir: str | Path) -> str | None:
    """The per-step message: the file's text for the model to see
    before it acts, or None when the model has not written one yet (the
    SYSTEM trigger handles the first write)."""
    body = read(out_dir)
    if body is None:
        return None
    return (f"[job memory — as you last wrote it; update with "
            f"memory_save when a rule changes]\n{body}")
