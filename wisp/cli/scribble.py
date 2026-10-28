"""Scribble to ask: `scribble set` / `scribble clear` (B7)."""
import json

from .registry import CliError, GROUPS, command

GROUPS["scribble"] = "Strokes drawn on the screen while asking (overlay)"


def _set_args(p):
    p.add_argument("data", help='JSON {"strokes": [[[x, y], ...]], '
                                '"w": screen width, "h": screen height}')


@command("scribble set",
         "Store the strokes the next turn draws into its screenshot",
         ['wispd scribble set \'{"strokes":[[[10,10],[80,40]]],'
          '"w":1920,"h":1080}\''],
         {"strokes": "int", "points": "int"}, args=_set_args)
def scribble_set(ctx, a):
    from .. import scribble
    try:
        doc = json.loads(a.data)
    except ValueError:
        raise CliError("E_USAGE", "The strokes are not valid JSON.",
                       "wispd scribble set --help")
    res = scribble.save(doc)
    return ctx.emit(res, f"{res['strokes']} stroke(s) stored")


@command("scribble clear", "Forget the stored strokes",
         ["wispd scribble clear"], {"cleared": "bool"})
def scribble_clear(ctx, a):
    from .. import scribble
    scribble.clear()
    return ctx.emit({"cleared": True}, "cleared")
