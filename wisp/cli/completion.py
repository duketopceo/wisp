"""Shell completion scripts generated from the command registry."""
import argparse

from . import registry


def _tree():
    """{"top": [names], "verbs": {group: [verbs]}, "opts": {path: [flags]}}"""
    top = registry.build_parser()
    sub = next(a for a in top._actions
               if isinstance(a, argparse._SubParsersAction))
    names, verbs, opts = [], {}, {}

    def flags(p):
        out = []
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                continue
            out += [o for o in a.option_strings]
        return sorted(set(out))

    for name, p in sub.choices.items():
        names.append(name)
        opts[name] = flags(p)
        vsub = next((a for a in p._actions
                     if isinstance(a, argparse._SubParsersAction)), None)
        if vsub:
            verbs[name] = list(vsub.choices)
            for v, vp in vsub.choices.items():
                opts[f"{name} {v}"] = flags(vp)
    return names, verbs, opts


def _bash(names, verbs, opts):
    cases = []
    for g, vs in verbs.items():
        cases.append(f'    {g}) if [ "$COMP_CWORD" -eq 2 ]; then '
                     f'COMPREPLY=($(compgen -W "{" ".join(vs)}" -- "$cur"));'
                     f' else case "${{COMP_WORDS[2]}}" in\n'
                     + "".join(
                         f'      {v}) COMPREPLY=($(compgen -W "'
                         f'{" ".join(opts.get(g + " " + v, []))}" -- '
                         f'"$cur"));;\n' for v in vs)
                     + "      esac; fi;;")
    for n in names:
        if n not in verbs:
            cases.append(f'    {n}) COMPREPLY=($(compgen -W "'
                         f'{" ".join(opts.get(n, []))}" -- "$cur"));;')
    return f'''# bash completion for wispd (generated: wispd completion bash)
_wispd() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=($(compgen -W "{" ".join(names)} --json --quiet --no-color --help" -- "$cur"))
    return
  fi
  case "${{COMP_WORDS[1]}}" in
{chr(10).join(cases)}
  esac
}}
complete -F _wispd wispd
'''


def _zsh(names, verbs, opts):
    cmds = " ".join(names)
    groups = "\n".join(f"    {g}) _values verb {' '.join(vs)};;"
                       for g, vs in verbs.items())
    return f'''#compdef wispd
# zsh completion for wispd (generated: wispd completion zsh)
_wispd() {{
  local -a cmds
  cmds=({cmds})
  if (( CURRENT == 2 )); then
    _describe 'command' cmds
    compadd -- --json --quiet --no-color --help
    return
  fi
  case $words[2] in
{groups}
  esac
}}
compdef _wispd wispd
'''


def _fish(names, verbs, opts):
    lines = ["# fish completion for wispd (generated: wispd completion "
             "fish)", "complete -c wispd -f"]
    for n in names:
        lines.append(f"complete -c wispd -n '__fish_use_subcommand' "
                     f"-a {n}")
    for g, vs in verbs.items():
        for v in vs:
            lines.append(f"complete -c wispd -n '__fish_seen_subcommand_"
                         f"from {g}' -a {v}")
    for flag in ("json", "quiet", "no-color"):
        lines.append(f"complete -c wispd -l {flag}")
    return "\n".join(lines) + "\n"


def generate(shell: str) -> str:
    names, verbs, opts = _tree()
    fn = {"bash": _bash, "zsh": _zsh, "fish": _fish}.get(shell)
    if fn is None:
        raise registry.CliError("E_USAGE", f"Unknown shell {shell!r}.",
                                "wispd completion bash")
    return fn(names, verbs, opts)
