"""Learning and telemetry: train, review, learn, skills, recipes, trace,
eval."""
import datetime
import io

from .. import config
from .registry import CliError, GROUPS, command

GROUPS["train"] = "Training arena stats, history and the skill bank"
GROUPS["review"] = "Staged reviewer proposals"
GROUPS["learn"] = "Weekly corrections and failure log"
GROUPS["skills"] = "Installed skills"
GROUPS["recipes"] = "Recipes drafted from past runs"
GROUPS["trace"] = "Turn trace and daily digest"
GROUPS["eval"] = "Replay logged decisions through candidate routers"

_TEXT = {"text": "str"}


def _text(ctx, s):
    return ctx.emit({"text": s}, s)


@command("train stats", "Arena run counts and pass rates",
         ["wispd train stats"], _TEXT)
def train_stats(ctx, a):
    from .. import train
    return _text(ctx, train.stats_text())


@command("train history", "Recent arena runs",
         ["wispd train history"], _TEXT)
def train_history(ctx, a):
    from .. import train
    return _text(ctx, train.history_text())


@command("train bank", "Patterns in the skill bank",
         ["wispd train bank"], _TEXT)
def train_bank(ctx, a):
    from .. import train
    return _text(ctx, train.bank_text())


@command("train rebuild", "Rebuild the skill bank from every logged run",
         ["wispd train rebuild"], _TEXT)
def train_rebuild(ctx, a):
    from .. import train
    return _text(ctx, f"rebuilt skill bank — {len(train.replay_all())}"
                      " patterns")


@command("review list", "List staged reviewer proposals",
         ["wispd review list"], _TEXT)
def review_list(ctx, a):
    from .. import review
    return _text(ctx, review.list_text())


def _run_args(p):
    p.add_argument("n", nargs="?", type=int, default=10,
                   help="runs to review (default 10)")


@command("review run", "Run the reviewer over the latest runs",
         ["wispd review run 20"], _TEXT, args=_run_args)
def review_run(ctx, a):
    from .. import review
    r = review.run(ctx.cfg, limit=a.n)
    lines = [f"reviewed {r['reviewed']} → {r['proposed']} proposals"
             + (f", {r['skipped']} skipped" if r["skipped"] else "")]
    lines += [f"  - {n}" for n in r["notes"][:5]]
    return _text(ctx, "\n".join(lines))


def _idx_args(p):
    p.add_argument("n", nargs="?", type=int, default=0,
                   help="proposal number from `review list`")


@command("review approve", "Approve a proposal into the skill bank",
         ["wispd review approve 3"], _TEXT, args=_idx_args)
def review_approve(ctx, a):
    from .. import review
    return _text(ctx, review.approve(a.n))


@command("review reject", "Reject a staged proposal",
         ["wispd review reject 3"], _TEXT, args=_idx_args)
def review_reject(ctx, a):
    from .. import review
    return _text(ctx, review.reject(a.n))


@command("learn weekly", "Draft a proposal from this week's corrections",
         ["wispd learn weekly"], _TEXT)
def learn_weekly(ctx, a):
    from .. import learn
    out = learn.weekly()
    return _text(ctx, out if out
                 else "no corrections this week — nothing to propose")


@command("learn fails", "Show logged failures",
         ["wispd learn fails"], _TEXT)
def learn_fails(ctx, a):
    from .. import learn
    return _text(ctx, learn.fails())


@command("skills list", "List installed skills",
         ["wispd skills list"], {"skills": "list"})
def skills_list(ctx, a):
    from .. import skills
    idx = skills.index()
    return ctx.emit(
        {"skills": [{"name": s["name"], "description": s["description"]}
                    for s in idx]},
        "\n".join(f"{s['name']}: {s['description']}" for s in idx) or None)


def _import_args(p):
    p.add_argument("dir", help="directory of skills to import")
    p.add_argument("--list", action="store_true",
                   help="preview only; install nothing")


@command("skills import", "Import skills from a directory",
         ["wispd skills import --list ~/skills", "wispd skills import "
          "~/skills"], _TEXT, args=_import_args)
def skills_import(ctx, a):
    from .. import skills
    return _text(ctx, skills.import_dir(a.dir, preview=a.list))


@command("recipes draft", "Draft recipes from past runs",
         ["wispd recipes draft"], {"drafted": "list"})
def recipes_draft(ctx, a):
    from .. import trajectories
    out = [str(p) for p in trajectories.propose_recipes()]
    return ctx.emit({"drafted": out},
                    "\n".join(f"drafted {p}" for p in out) or None)


def _approve_args(p):
    p.add_argument("name", help="recipe-... name from `recipes draft`")


@command("recipes approve", "Install a drafted recipe as a skill",
         ["wispd recipes approve recipe-open-notes"], {"installed": "str"},
         args=_approve_args)
def recipes_approve(ctx, a):
    from .. import skills as sk
    src = config.DATA_DIR / "proposals" / f"{a.name}.md"
    if not a.name.startswith("recipe-") or not src.exists():
        raise CliError("E_USAGE", "That is not a drafted recipe.",
                       "wispd recipes draft")
    dest = sk.SKILLS_DIR / a.name
    dest.mkdir(parents=True, exist_ok=True)
    body = src.read_text()
    body += ("\n<!-- approved by wispd recipes approve "
             f"{datetime.datetime.now(datetime.timezone.utc).isoformat()}"
             " — human-gated install -->\n")
    (dest / "SKILL.md").write_text(body)
    sk.write_index_json()
    return ctx.emit({"installed": a.name}, f"installed {a.name}")


def _show_args(p):
    p.add_argument("--tail", type=int, default=50, metavar="N",
                   help="events to show (default 50)")
    p.add_argument("--turn", default="", metavar="ID",
                   help="only this turn")
    p.add_argument("--kind", default="", metavar="KIND",
                   help="only this event kind")
    p.add_argument("--latency", action="store_true",
                   help="p50/p90 per budget path instead of events")
    p.add_argument("--since", default="24h", metavar="AGE",
                   help="window for --latency (24h, 90m, 2d)")


@command("trace show", "Print the turn trace, or a latency summary",
         ["wispd trace show --tail 20", "wispd trace show --latency "
          "--since 6h"], _TEXT, args=_show_args)
def trace_show(ctx, a):
    from .. import trace
    argv = ["--tail", str(a.tail)]
    if a.turn:
        argv += ["--turn", a.turn]
    if a.kind:
        argv += ["--kind", a.kind]
    if a.latency:
        argv += ["--latency", "--since", a.since]
    return _capture(ctx, lambda: trace.main(argv))


def _hours_args(p):
    p.add_argument("hours", nargs="?", type=int, default=24,
                   help="window in hours (default 24)")


@command("trace digest", "Local digest over decisions and trace",
         ["wispd trace digest 48"], _TEXT, args=_hours_args)
def trace_digest(ctx, a):
    from .. import telemetry
    return _text(ctx, telemetry.text(a.hours))


def _route_args(p):
    p.add_argument("limit", nargs="?", type=int, default=0,
                   help="decisions to replay (default all)")


@command("eval route", "Replay logged decisions through candidate routers",
         ["wispd eval route 100"], _TEXT, args=_route_args)
def eval_route(ctx, a):
    from .. import evalroute
    return _text(ctx, evalroute.run(ctx.cfg, limit=a.limit))


def _capture(ctx, fn):
    """Run a function that prints; wrap its output under --json."""
    if ctx.json or ctx.flags.quiet:
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn()
        if rc:
            return rc
        return ctx.emit({"text": buf.getvalue().rstrip("\n")})
    return fn()
