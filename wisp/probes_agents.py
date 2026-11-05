"""Agent runtime probe (U2): is the pinned ori + OpenCode usable?

`AgentsProbe.check()` classifies the install into one state, first match
wins:

  absent          ori or opencode missing from the runtime root
  opencode_v1     opencode reports 1.x (Wisp refuses to drive it)
  wrong_version   ori or opencode differs from the pin
  installed       both match; sign-in not checked (`auth=False`)
  not_signed_in   `ori auth --json` fails or does not report authenticated
  ready           everything fine

Only the pinned `current` binaries are consulted, never PATH, and the
auth output is reduced to `data.authenticated` (its `source` label can name
an env var even when the credential is stored); secrets are never read.
"""
import json
import subprocess

from . import agent_install, agent_pins

STATES = ("absent", "opencode_v1", "wrong_version", "installed",
          "not_signed_in", "ready")
_CODES = {"absent": "agents_absent", "opencode_v1": "agents_opencode_v1",
          "wrong_version": "agents_version",
          "not_signed_in": "agents_signin"}
_FIX = {
    "absent": "wispd install --agents (or the onboarding agents step)",
    "opencode_v1": "wispd install --agents (Wisp runs its own pinned "
                   "OpenCode 2.x and never uses OpenCode 1.x)",
    "wrong_version": "wispd install --agents (reinstall the pinned "
                     "versions)",
    "not_signed_in": "wispd onboard (agents step) to sign ori in to "
                     "OpenRouter",
}


def _auth(ori) -> tuple:
    """-> (returncode, parsed JSON or None) from `ori auth --json`."""
    env = agent_pins.ori_env()
    try:
        r = subprocess.run([str(ori), "auth", "--json"], capture_output=True,
                           text=True, timeout=5, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return 1, None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = None
    return r.returncode, data if isinstance(data, dict) else None


class AgentsProbe:
    def __init__(self, root=None, version_fn=agent_install.version_of,
                 auth_fn=_auth):
        self.paths = agent_pins.runtime_paths(root)
        self._version = version_fn
        self._auth = auth_fn

    def check(self, auth: bool = True) -> dict:
        """-> {state, ok, code, fix, ori, opencode}; versions are the
        reported ones. Never raises."""
        out = {"state": "absent", "ok": False, "code": None, "fix": None,
               "ori": None, "opencode": None}
        try:
            out["state"] = self._classify(out, auth)
        except Exception:
            out["state"] = "absent"
        out["ok"] = out["state"] in ("installed", "ready")
        out["code"] = _CODES.get(out["state"])
        out["fix"] = _FIX.get(out["state"])
        return out

    def _classify(self, out, auth) -> str:
        ori, oc = self.paths["ori"], self.paths["opencode"]
        if not (ori.is_file() and oc.is_file()):
            return "absent"
        out["ori"], out["opencode"] = self._version(ori), self._version(oc)
        if (out["opencode"] or "").startswith("1."):
            return "opencode_v1"
        if out["ori"] != agent_pins.ORI_VERSION \
                or out["opencode"] != agent_pins.OPENCODE_VERSION:
            return "wrong_version"
        if not auth:
            return "installed"
        rc, data = self._auth(ori)
        body = (data or {}).get("data")
        if rc != 0 or not isinstance(body, dict) or body.get("authenticated") is not True:
            return "not_signed_in"
        return "ready"
