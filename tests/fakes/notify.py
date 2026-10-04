"""Fake notification server (quickshell-shaped), as two commands.

``gdbus`` (W18): ``gdbus call --session --dest org.freedesktop.
Notifications --method ...Notify|CloseNotification|GetCapabilities|
GetServerInformation`` and ``gdbus monitor`` streaming
``ActionInvoked`` / ``NotificationClosed``. Capabilities mirror
quickshell: persistence, body, body-markup, body-hyperlinks, actions,
icon-static (no sound). ``--system`` is refused. Notify args are parsed
from GVariant text (actions = flat [name, label, ...] list); replace-id
reuses the id; the reply is ``(uint32 N,)``.

``notify-send`` (libnotify, legacy ``platform.notify_cmd``; options: -a -u -t -i -c -h -r/--replace-id -p/--print-id
-A/--action -w/--wait -e) backed by a small id table that behaves like a
server: ids count from 1, ``-r N`` reuses id N, ``-p`` prints the id,
``-w`` with ``-A`` prints the action named by ``script(invoke=...)``.

Each record: id, replaces (0 = new), title, body, app, urgency, timeout,
icon, category, actions [{name,label}], hints, wait, print_id, argv.
"""


class FakeNotify:
    NAME = "notify-send"

    def __init__(self, bins, script: dict | None = None):
        self.bins = bins
        bins.install(self.NAME, {})
        bins.install("gdbus", {})
        bins.configure(self.CFG, dict(script or {}))

    CFG = "notify"   # shared script/state name for both commands

    def script(self, **kw) -> None:
        """Change behaviour mid-run: invoke=<action> (notify-send -w),
        auto_invoke={"action","delay_ms"} (gdbus: emit ActionInvoked for
        the next Notify that has actions), capabilities=[...],
        server_down=True, exit=<code>, latency_ms=<n>."""
        self.bins.update(self.CFG, **kw)

    @property
    def notifications(self) -> list:
        return [c["notification"] for c in self.bins.calls()
                if c["bin"] in ("notify-send", "gdbus")
                and "notification" in c]

    def _state(self) -> dict:
        import json
        try:
            return json.loads(self.bins.state_file(self.CFG).read_text())
        except (OSError, ValueError):
            return {}

    def closed(self) -> list:
        """[(id, reason)] of NotificationClosed signals emitted."""
        return [tuple(s["args"]) for s in self._state().get("signals", [])
                if s["kind"] == "NotificationClosed"]

    def _push(self, kind: str, args: list) -> None:
        import fcntl
        import json
        p = self.bins.state_file(self.CFG)
        with open(str(p) + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            st = self._state() or {"next": 1, "live": {}, "signals": []}
            st["signals"].append({"kind": kind, "args": args, "at": 0})
            p.write_text(json.dumps(st))

    def invoke(self, nid: int, action: str) -> None:
        """Driver: the user clicked `action` on notification `nid`."""
        self._push("ActionInvoked", [nid, action])

    def close(self, nid: int, reason: int = 3) -> None:
        """Driver: notification closed (1 expired, 2 dismissed, 3 by call,
        4 undefined)."""
        self._push("NotificationClosed", [nid, reason])

    @property
    def last(self) -> dict | None:
        n = self.notifications
        return n[-1] if n else None

    def bodies(self) -> list:
        return [n["body"] for n in self.notifications]

    def live_bodies(self) -> list:
        """Bodies currently shown (a replace overwrites in place)."""
        st = self._state()
        return [v["body"] for _, v in sorted(
            st.get("live", {}).items(), key=lambda kv: int(kv[0]))]
