"""Unit-file lint for the shipped scripts/units templates."""
import configparser

from wisp import svc


def lint_unit(text: str, name: str = "") -> list:
    """Problems with a unit file; [] when clean."""
    cp = configparser.ConfigParser(strict=True, interpolation=None,
                                   delimiters=("=",))
    cp.optionxform = str
    try:
        cp.read_string(text)
    except configparser.Error as e:
        return [f"parse error: {str(e).splitlines()[0]}"]
    p = []
    for sec in ("Unit", "Service", "Install"):
        if sec not in cp:
            p.append(f"missing [{sec}]")
    if p:
        return p
    u, s = cp["Unit"], cp["Service"]
    for sec, key in (("Unit", "Description"), ("Service", "ExecStart"),
                     ("Service", "Restart"), ("Service", "RestartSec"),
                     ("Install", "WantedBy")):
        if key not in cp[sec]:
            p.append(f"missing {key}")
    if "StartLimitIntervalSec" not in u or "StartLimitBurst" not in u:
        p.append("missing StartLimitIntervalSec/StartLimitBurst")
    if s.get("Slice") == "app.slice":
        p.append("Slice=app.slice is oomd-killable (use session.slice)")
    if "WatchdogSec" in s and s.get("Type") != "notify":
        p.append("WatchdogSec needs Type=notify")
    if name in svc.LLAMA and s.get("Slice") != "session.slice" \
            and s.get("ManagedOOMPreference") != "omit":
        p.append("Slice=session.slice or ManagedOOMPreference=omit "
                 "required")
    return p
