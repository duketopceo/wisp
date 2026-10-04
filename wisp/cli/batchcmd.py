"""Batch lane: offline OpenRouter Batch jobs (W15). Never the live path."""
from .registry import CliError, GROUPS, command

GROUPS["batch"] = "Offline OpenRouter batch jobs (cheap models, capped)"

_JOB = {"job_id": "str", "kind": "str", "model": "str", "status": "str",
        "settled": "bool", "est_usd": "float", "failed": "dict"}

_CODES = {"model_not_allowed": "E_USAGE", "bad_job_id": "E_USAGE",
          "unknown_job": "E_USAGE"}


def _lane(ctx):
    from .. import batch
    cfg = ctx.cfg
    return batch, batch.Lane(cfg, batch.Client(
        cfg.get("batch", {}).get("base_url") or batch.BASE_URL))


def _guard(fn):
    def run(ctx, a):
        from .. import batch
        try:
            return fn(ctx, a)
        except batch.BatchRefused as e:
            raise CliError(_CODES.get(e.code, "E_FAILED"), f"Batch {e}.")
        except batch.ApiError as e:
            raise CliError("E_FAILED", f"{e}.")
    run.__name__ = fn.__name__
    return run


def _row(j):
    n = len(j.get("failed") or {})
    return [j["job_id"], j["kind"], j["status"],
            f"${j.get('est_usd', 0):.4f}", str(n) if n else "-"]


def _job_text(ctx, j):
    return ctx.table(["job", "kind", "status", "est", "failed"], [_row(j)])


@command("batch status", "List batch jobs from local state (no network)",
         ["wispd batch status", "wispd batch status learn-2026-W40"],
         {"jobs": "list"},
         args=lambda p: p.add_argument("job", nargs="?", help="job id"))
@_guard
def batch_status(ctx, a):
    from .. import batch
    lane = batch.Lane(ctx.cfg)
    jobs = [lane.status(a.job)] if a.job else lane.status()
    if a.job and jobs[0] is None:
        raise CliError("E_USAGE", f"No batch job '{a.job}'.",
                       "wispd batch status")
    text = (ctx.table(["job", "kind", "status", "est", "failed"],
                      [_row(j) for j in jobs])
            if jobs else "no batch jobs")
    return ctx.emit({"jobs": jobs, "reserved_usd": lane.reserved()}, text)


@command("batch submit-learn", "Submit this week's learn pass as a batch",
         ["wispd batch submit-learn"], _JOB,
         args=lambda p: p.add_argument(
             "--model", help="allowlisted model slug"))
@_guard
def batch_submit_learn(ctx, a):
    batch, lane = _lane(ctx)
    job = batch.submit_learn(lane, a.model)
    if job is None:
        return ctx.emit({"job_id": None},
                        "no corrections this week, nothing to submit")
    return ctx.emit(job, _job_text(ctx, job))


@command("batch poll", "Check jobs, record spend, stage finished results",
         ["wispd batch poll", "wispd batch poll learn-2026-W40"],
         {"jobs": "list"},
         args=lambda p: p.add_argument("job", nargs="?", help="job id"))
@_guard
def batch_poll(ctx, a):
    batch, lane = _lane(ctx)
    ap = batch.applier()
    if a.job:
        jobs = [lane.poll(a.job, ap if a.job.startswith("learn-")
                          else None)]
    else:
        jobs = lane.poll_all(
            lambda j: ap if j["kind"] == "learn" else None)
    text = (ctx.table(["job", "kind", "status", "est", "failed"],
                      [_row(j) for j in jobs]) if jobs
            else "no jobs in flight")
    return ctx.emit({"jobs": jobs}, text)


@command("batch cancel", "Cancel a batch job (finished items stay billed)",
         ["wispd batch cancel learn-2026-W40"], _JOB,
         args=lambda p: p.add_argument("job", help="job id"))
@_guard
def batch_cancel(ctx, a):
    batch, lane = _lane(ctx)
    job = lane.cancel(a.job)
    return ctx.emit(job, _job_text(ctx, job))
