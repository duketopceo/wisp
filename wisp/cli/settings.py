"""Settings and onboarding data: config, theme, connect, sync, inventory."""
import json

from .. import config, settings_schema
from .registry import CliError, GROUPS, command

GROUPS["config"] = "Show or change config.toml (live, no restart)"
GROUPS["theme"] = "Pick the theme or audit its contrast"
GROUPS["connect"] = "Connect outside services (OAuth via the gateway)"

_TEXT = {"text": "str"}


@command("config show", "Print the live config as JSON",
         ["wispd config show", "wispd config show --json"],
         {"config": "dict"})
def config_show(ctx, a):
    try:
        cfg = ctx.send({"cmd": "config"})["config"]
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        cfg = config.load_config()
    return ctx.emit({"config": cfg}, json.dumps(cfg, indent=2))


def set_key(ctx, key: str, value: str):
    """Set one config key through the daemon (live reload), or straight
    in config.toml when no daemon is running. Raises CliError."""
    section, _, name = key.rpartition(".")
    if not section or not name:
        raise CliError("E_USAGE", "Config keys must look like "
                       "section.key.", "wispd config set audio.seconds 30")
    bad = settings_schema.message(key, value)
    if bad:
        raise CliError("E_BAD_CONFIG", bad, "wispd config keys")
    try:
        resp = ctx.send({"cmd": "config", "set": {key: value}})
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        try:
            config.set_config(section, name, value)
        except ValueError as ve:
            raise CliError("E_BAD_CONFIG", f"{str(ve).rstrip('.')}.")
    else:
        if not resp.get("ok"):
            raise CliError("E_BAD_CONFIG",
                           f"The daemon rejected it: {resp.get('error')}.")
    ctx.reload_cfg()


def _set_args(p):
    p.add_argument("key", help="section.key, for example audio.seconds")
    p.add_argument("value")
    # the key table comes from the settings schema, never hand written
    p.epilog = settings_schema.help_table() + "\n\n" + p.epilog


@command("config set", "Set one config key (live when the daemon runs)",
         ["wispd config set audio.seconds 30",
          "wispd config set pointer.mode drive"],
         {"key": "str", "value": "str"}, args=_set_args)
def config_set(ctx, a):
    set_key(ctx, a.key, a.value)
    return ctx.emit({"key": a.key, "value": a.value},
                    f"{a.key} = {a.value}")


@command("config keys", "List the settings wispd checks, with ranges",
         ["wispd config keys", "wispd config keys --json"],
         {"keys": "list"})
def config_keys(ctx, a):
    return ctx.emit({"keys": [f.as_dict() for f in settings_schema.FIELDS]},
                    settings_schema.help_table())


@command("theme show", "Print the active theme and refresh theme.json",
         ["wispd theme show"], {"theme": "str"})
def theme_show(ctx, a):
    from .. import theme
    theme.emit(ctx.cfg)
    name = theme.current(ctx.cfg)
    return ctx.emit({"theme": name}, name)


def _theme_set_args(p):
    p.add_argument("name", help="dark or light")


@command("theme set", "Switch the fallback theme",
         ["wispd theme set light"], {"theme": "str"}, args=_theme_set_args)
def theme_set(ctx, a):
    from .. import theme
    if a.name not in theme.THEMES:
        raise CliError("E_USAGE", f"Unknown theme {a.name!r}. Choose "
                       f"{' or '.join(sorted(theme.THEMES))}.",
                       "wispd theme set dark")
    config.set_config("ui", "theme", a.name)
    ctx.reload_cfg()
    return ctx.emit({"theme": a.name}, f"theme = {theme.emit(ctx.cfg)}")


def _dir_arg(p):
    p.add_argument("dir", nargs="?", help="theme directory (default: the "
                   "active Omarchy theme)")


@command("theme check", "Audit the theme's contrast pairs (exit 1 on fail)",
         ["wispd theme check", "wispd theme check ~/.config/omarchy/"
          "themes/tokyo-night"],
         {"source": "str", "mode": "str", "rows": "list"}, args=_dir_arg)
def theme_check(ctx, a):
    from .. import theme
    res = theme.load(a.dir, ctx.cfg)
    rows = theme.check(res)
    lines = [f"source {res['source']}, mode {res['mode']}"]
    for r in rows:
        mark = "ok  " if r["ok"] else "FAIL"
        lines.append(f"{mark} {r['pair']:<18} {r['fg']} on {r['bg']}  "
                     f"{r['ratio']:>5.2f} (min {r['min']})")
    data = {"source": res["source"], "mode": res["mode"], "rows": rows}
    if all(r["ok"] for r in rows):
        return ctx.emit(data, "\n".join(lines))
    if not ctx.json:
        print("\n".join(lines))
    raise CliError("E_FAILED", "A theme pair is below its contrast floor.",
                   "wispd theme check --help", data=data)


def _css_args(p):
    p.add_argument("dir", nargs="?", help="theme directory")
    p.add_argument("out", nargs="?", help="output file, or - for stdout")


@command("theme css", "Write theme.css from the theme tokens",
         ["wispd theme css", "wispd theme css ~/themes/x -"],
         {"path": "str|null", "css": "str|null"}, args=_css_args)
def theme_css(ctx, a):
    from .. import theme
    res = theme.load(a.dir, ctx.cfg)
    if a.out == "-":
        css = theme.css(res)
        return ctx.emit({"path": None, "css": css}, css.rstrip("\n"))
    path = theme.write_css(res, a.out)
    return ctx.emit({"path": str(path), "css": None}, str(path))


@command("connect list", "List connectable services and their status",
         ["wispd connect list"], {"connectors": "list"})
def connect_list(ctx, a):
    from .. import mcpauth
    if ctx.legacy and ctx.json:
        # old `wispd connect --list --json`: the bare catalog the panel reads
        print(json.dumps(mcpauth.list_connectors_json(ctx.cfg)))
        return 0
    return ctx.emit({"connectors": mcpauth.list_connectors_json(ctx.cfg)},
                    mcpauth.list_connectors(ctx.cfg))


def _svc_args(p):
    p.add_argument("service", help="service name from `connect list`")


@command("connect add", "Connect a service (opens the OAuth flow)",
         ["wispd connect add github"], _TEXT, args=_svc_args)
def connect_add(ctx, a):
    from .. import mcpauth
    out = mcpauth.connect(a.service, ctx.cfg)
    return ctx.emit({"text": out}, out)


def _sync_args(p):
    p.add_argument("repo", nargs="?", help="luke-agents checkout (default "
                   "the standard location)")


@command("sync", "Refresh the MEMORY constitution block and import skills",
         ["wispd sync"], _TEXT, args=_sync_args)
def sync(ctx, a):
    from .. import memory as _m, skills as _sk
    lines = [_m.sync_constitution(a.repo),
             _sk.import_dir("~/Documents/github/personal/luke-agents/_LUKE")]
    _sk.write_index_json()
    text = "\n".join(str(x) for x in lines)
    return ctx.emit({"text": text}, text)


@command("inventory", "Scan installed apps, CLI tools and MCP servers",
         ["wispd inventory"], _TEXT)
def inventory(ctx, a):
    from .. import inventory as _inv
    inv = _inv.scan(ctx.cfg)
    o = inv.get("omarchy", {})
    df = inv.get("dayflow", {})
    lines = [
        f"inventory.json — {inv.get('generated', '?')}",
        f"  apps:        {len(inv.get('apps', []))}",
        f"  cli_tools:   {len(inv.get('cli_tools', {}))}",
        f"  mcp servers: {len(inv.get('mcp', {}))} "
        f"({', '.join(list(inv.get('mcp', {}))[:8])}…)",
        f"  omarchy:     {len(o.get('plugins', []))} plugins, "
        f"{len(o.get('bindings', []))} bindings",
        f"  dayflow:     {len(df.get('top_apps', []))} top apps, "
        f"{len(df.get('project_terms', []))} project terms",
        f"  skills:      {len(inv.get('skills', []))}",
        f"  file: {_inv.FILE}"]
    text = "\n".join(lines)
    return ctx.emit({"text": text}, text)
