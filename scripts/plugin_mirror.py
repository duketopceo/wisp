#!/usr/bin/env python3
"""Build the Omarchy marketplace mirror: the shell plugin alone (B15).

`omarchy plugin add <git url>` clones a repo whose root is the plugin
(manifest.json, its QML, a README and a license). This repo is the source of
truth and keeps the plugin under shell-plugin/, so a release builds a
plugin-only tree here and publishes it to a mirror repo.

    python3 scripts/plugin_mirror.py --out build/mirror --version v0.5.0
    python3 scripts/plugin_mirror.py --out build/mirror --version v0.5.0 --lint

The tree holds the plugin files, LICENSE, a README with the install and
removal commands, and preview.png (a README render). The manifest version
becomes the release tag. The same checks `omarchy plugin validate` makes are
run here (so CI works without the omarchy CLI); with the CLI present it is
run too, and with `--lint` so is qmllint. Nothing is published, pushed or
sent: this only writes a folder.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
PLUGIN_ID = "io.github.duketopceo.wisp"
REPO_URL = "https://github.com/duketopceo/wisp"
MIRROR_URL = "https://github.com/duketopceo/wisp-plugin"
PREVIEW = ROOT / "assets" / "readme" / "companion.png"
MAX_PREVIEW_KB = 600
SKIP = {"__pycache__", ".git", ".DS_Store"}
# kind -> the entry point it promises (Omarchy's table)
KIND_ENTRY = {"bar": "bar", "bar-widget": "barWidget", "menu": "menu",
              "overlay": "overlay", "panel": "panel", "service": "service"}

README = """\
# Wisp

Wisp is a voice teacher and doer for Omarchy: hold the key, ask, and it
answers out loud and points at your screen. This repository is the Omarchy
plugin only (the bar mark, the live pill and the overlay), built from
[{repo}]({repo}), where the code, tests and issues live.

![Wisp](preview.png)

## Install

```sh
omarchy plugin add {mirror}.git --enable
```

The plugin shows the daemon's state. The daemon itself (`wispd`) comes from
the release page; nothing is installed or edited until you say yes:

```sh
tar xzf wisp-linux-x86_64.tar.gz && cd wisp-linux-x86_64
python3 wispd install --from-plugin --dry-run   # every file, and the bind line
python3 wispd install --from-plugin             # prints the same, then asks
```

`--from-plugin` leaves this plugin folder to `omarchy plugin update`, and it
adds the push-to-talk bind to `~/.config/hypr/bindings.lua` only after your
yes.

## Remove

```sh
omarchy plugin remove {plugin_id}
systemctl --user disable --now wispd.service
rm -rf ~/.local/opt/wisp ~/.local/bin/wispd ~/.local/bin/wisp-trigger \\
       ~/.local/share/applications/wisp.desktop
```

Your settings and memory stay in `~/.config/wisp` and
`~/.local/share/wisp`; delete those for a full wipe. Remove the
`-- Wisp push-to-talk` lines from `~/.config/hypr/bindings.lua`.

## License

AGPL-3.0-only, see LICENSE (releases up to v0.9.0 were MIT). Bundled
third-party notices are in THIRD_PARTY_NOTICES.md. Version {version}.
"""


def _ignore(_dir, names):
    return [n for n in names if n in SKIP or n.endswith(".pyc")]


def load_manifest(folder: pathlib.Path):
    return json.loads((pathlib.Path(folder) / "manifest.json").read_text())


def validate(folder) -> list:
    """Problems with a plugin folder (empty when valid): the checks of
    `omarchy plugin validate`, in Python."""
    folder = pathlib.Path(folder)
    bad = []
    mf = folder / "manifest.json"
    if not mf.is_file():
        return [f"missing manifest.json in {folder}"]
    try:
        m = json.loads(mf.read_text())
    except ValueError:
        return ["manifest.json is not valid JSON"]
    if not isinstance(m, dict):
        return ["manifest.json is not an object"]
    if m.get("schemaVersion") != 1 or isinstance(m.get("schemaVersion"), bool):
        bad.append("schemaVersion must be the number 1")
    for f in ("id", "name", "version", "kinds", "entryPoints"):
        if f not in m:
            bad.append(f"manifest missing required field '{f}'")
    pid = str(m.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", pid) or ".." in pid:
        bad.append(f"invalid plugin id '{pid}'")
    if pid.startswith("omarchy."):
        bad.append(f"plugin id '{pid}' uses the reserved omarchy.* namespace")
    kinds = m.get("kinds")
    if not isinstance(kinds, list) or not kinds:
        bad.append("'kinds' must be a non-empty array")
        kinds = []
    eps = m.get("entryPoints")
    if not isinstance(eps, dict):
        bad.append("'entryPoints' must be an object")
        eps = {}
    section = (m.get("barWidget") or {}).get("defaultSection") \
        if isinstance(m.get("barWidget"), dict) else None
    if section is not None and section not in ("left", "center", "right"):
        bad.append("'barWidget.defaultSection' must be left, center, or "
                   "right")
    for name, ep in eps.items():
        if not isinstance(ep, str) or not ep:
            bad.append(f"entry point '{name}' is empty")
        elif ep.startswith("/") or ".." in ep or "\n" in ep:
            bad.append(f"entry point '{name}' is not a safe relative path: "
                       f"{ep!r}")
        elif not (folder / ep).is_file():
            bad.append(f"entry point file not found: '{ep}'")
    for kind in kinds:
        key = KIND_ENTRY.get(kind)
        if key and key not in eps:
            bad.append(f"kind '{kind}' requires an 'entryPoints.{key}'")
    for p in folder.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_symlink():
            bad.append(f"symlinks are not allowed: {p.relative_to(folder)}")
    return bad


def build(out, version: str, root: pathlib.Path = ROOT) -> dict:
    """Write the mirror tree into `out` (replaced when it exists)."""
    out = pathlib.Path(out)
    plugin = root / "shell-plugin"
    ver = version.lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", ver):
        raise ValueError(f"not a release version: {version!r}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(plugin, out, ignore=_ignore, symlinks=False)
    m = json.loads((out / "manifest.json").read_text())
    m["version"] = ver
    (out / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    shutil.copy2(root / "LICENSE", out / "LICENSE")
    (out / "README.md").write_text(README.format(
        repo=REPO_URL, mirror=MIRROR_URL, plugin_id=m["id"], version=ver))
    prev = root / "assets" / "readme" / "companion.png"
    if prev.is_file() and prev.stat().st_size <= MAX_PREVIEW_KB * 1024:
        shutil.copy2(prev, out / "preview.png")
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*")
                   if p.is_file())
    return {"id": m["id"], "version": ver, "files": files,
            "bytes": sum((out / f).stat().st_size for f in files)}


def omarchy_validate(folder):
    """(ran, ok, text): `omarchy plugin validate` when the CLI exists."""
    exe = shutil.which("omarchy")
    if not exe:
        return False, True, "omarchy CLI not found; skipped"
    r = subprocess.run([exe, "plugin", "validate", str(folder)],
                       capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    # Without the Qt QML modules installed (CI) qmllint cannot resolve
    # imports and warns about every file; only real errors (syntax) fail.
    errors = [ln for ln in out.splitlines() if ln.startswith("Error:")]
    return True, not errors, "\n".join(errors) if errors else out


def lint(folder):
    """(ran, ok, text): qmllint over the plugin's QML when it is installed.
    Warnings are advisory; only errors fail."""
    exe = shutil.which("qmllint") or shutil.which("pyside6-qmllint") \
        or shutil.which("qmllint6")
    if not exe:
        return False, True, "qmllint not found; skipped"
    files = sorted(str(p) for p in pathlib.Path(folder).rglob("*.qml"))
    r = subprocess.run([exe, *files], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    # Without the Qt QML modules installed (CI) qmllint cannot resolve
    # imports and warns about every file; only real errors (syntax) fail.
    errors = [ln for ln in out.splitlines() if ln.startswith("Error:")]
    return True, not errors, "\n".join(errors) if errors else out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="folder to write")
    ap.add_argument("--version", required=True, help="release tag, v1.2.3")
    ap.add_argument("--lint", action="store_true", help="also run qmllint")
    a = ap.parse_args(argv)
    try:
        res = build(a.out, a.version)
    except (ValueError, OSError) as e:
        print(f"plugin_mirror: {e}", file=sys.stderr)
        return 2
    problems = validate(a.out)
    for p in problems:
        print(f"invalid: {p}", file=sys.stderr)
    ok = not problems
    ran, good, text = omarchy_validate(a.out)
    print(f"omarchy plugin validate: {'ok' if ran and good else text}")
    ok = ok and good
    if a.lint:
        ran, good, text = lint(a.out)
        print(f"qmllint: {'ok' if ran and good else text}")
        ok = ok and good
    print(f"{res['id']} {res['version']}: {len(res['files'])} files, "
          f"{res['bytes'] // 1024} KB in {a.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
