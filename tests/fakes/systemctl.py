"""Fake ``systemctl --user`` for health/models start.

``wisp.health.start_command`` builds ``systemctl --user start <units>``;
wispd runs it. The fake keeps unit states in a locked JSON file:
start/restart -> active (or failed when ``start_ok`` is false), stop ->
inactive, is-active -> state with exit 3 when not active, unknown unit
-> "not found" exit 5. System scope (no ``--user``) is REFUSED and
recorded as a violation.

script: {"units": {"llama-local.service": "inactive",
                   "x.service": {"state": "inactive", "start_ok": false}}}
"""


class FakeSystemctl:
    NAME = "systemctl"

    def __init__(self, bins, script: dict | None = None):
        self.bins = bins
        bins.install(self.NAME, dict(script or {}))

    def _calls(self) -> list:
        return self.bins.calls(self.NAME)

    def commands(self) -> list:
        """Recorded ``--user`` calls as 'verb unit ...' strings."""
        return [" ".join([c["verb"], *c["units"]]).strip()
                for c in self._calls() if "verb" in c]

    def violations(self) -> list:
        return [c["argv"] for c in self._calls() if "violation" in c]

    def state(self, unit: str) -> str:
        import json
        unit = unit if "." in unit else unit + ".service"
        try:
            st = json.loads(self.bins.state_file(self.NAME).read_text())
        except (OSError, ValueError):
            st = None
        if st is None:
            conf = self.bins.config(self.NAME).get("units", {})
            ent = conf.get(unit, "inactive")
        else:
            ent = st.get(unit, "inactive")
        return ent.get("state", "inactive") if isinstance(ent, dict) \
            else ent
