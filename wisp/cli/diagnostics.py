"""Private, local-only diagnostic views that do not need a running daemon."""
from .. import config, growth
from .registry import CliError, command


def _recap_args(parser):
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--claim", action="store_true",
                        help="reserve this week's local card once (panel open)")
    action.add_argument("--off", action="store_true",
                        help="turn the local weekly recap off")


@command("recap", "Show last week's private local usage recap (opt-in)",
         ["wispd recap --json", "wispd recap --claim --json", "wispd recap --off"],
         {"enabled": "bool", "reason": "str", "card": "any", "logs": "dict"},
         args=_recap_args)
def recap(ctx, args):
    try:
        if args.off:
            config.set_config("growth", "weekly_recap", "false")
            result = {"enabled": False, "reason": "disabled", "card": None, "logs": {}}
        else:
            # Merely opening the panel must not create a config file or
            # bootstrap defaults, and must never resolve keys or call IPC.
            cfg = config.load_config() if config.CFG_FILE.exists() else {}
            result = growth.weekly_recap(cfg, claim=args.claim)
    except (OSError, ValueError):
        raise CliError("E_FAILED", "The local recap could not be read or saved.",
                       "wispd recap --off") from None
    card = result["card"]
    text = ((card["title"] + "\n" + card["summary"] + "\n" + card["spend_note"])
            if card else "weekly recap: " + result["reason"].replace("_", " "))
    return ctx.emit(result, text)
