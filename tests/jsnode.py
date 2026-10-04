"""Run the pure-JS shell-plugin libs (.pragma library) under node.

The QML libs have no Quickshell imports, so node can execute them for the
Python-side parity and reader tests. `call(lib, expr)` loads
shell-plugin/lib/<lib>.js (the `.pragma library` line is stripped) and
returns the JSON of `expr` evaluated in its scope. Tests skip when node
is not installed.
"""
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIB = ROOT / "shell-plugin" / "lib"
NODE = shutil.which("node")

_DRIVER = """
const fs = require('fs'), vm = require('vm');
const libs = JSON.parse(process.argv[1]);
const expr = process.argv[2];
const ctx = {};
vm.createContext(ctx);
const path = require('path');
// `.import "x.js" as Name` (QML library syntax): load x.js beside this
// file into its own scope and expose it as Name.
function load(file) {
  let src = fs.readFileSync(file, 'utf8').replace(/^\\.pragma library/m, '');
  const scope = {};
  vm.createContext(scope);
  src = src.replace(/^\\.import\\s+"([^"]+)"\\s+as\\s+(\\w+)\\s*$/gm, (_m, rel, name) => {
    scope[name] = load(path.join(path.dirname(file), rel));
    return '';
  });
  vm.runInContext(src, scope);
  return scope;
}
for (const [name, p] of Object.entries(libs)) ctx[name] = load(p);
process.stdout.write(JSON.stringify(vm.runInContext(expr, ctx)));
"""


def call(expr: str, **libs) -> object:
    """Evaluate `expr` with each lib exposed as a namespace, e.g.
    call("Copy.statusWord('idle')", Copy="copy")."""
    paths = {k: str(LIB / f"{v}.js") for k, v in libs.items()}
    p = subprocess.run([NODE, "-e", _DRIVER, json.dumps(paths), expr],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return json.loads(p.stdout)
