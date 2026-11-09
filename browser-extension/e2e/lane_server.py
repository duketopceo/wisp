"""wispd's side of the browser e2e: the real Lane and native socket, driven
by JSON lines on stdin so a test can play "the agent".

  {"id": 1, "tool": "<browser tool argument>"}   -> {"id": 1, "out": "..."}
  {"id": 2, "ctl": "paired"}                    -> {"id": 2, "value": true}
  {"id": 3, "ctl": "stop"}                      -> {"id": 3, "value": true}
  {"id": 4, "ctl": "turn", "turn": "t2"}        -> {"id": 4, "value": "t2"}
  {"id": 5, "raw": {"op": "batch", ...}}        -> {"id": 5, "value": {...}}

`raw` sends a command to the extension without wispd's own checks, to test
the extension's refusals on their own.

Tools run on their own thread, so a Stop can land while one waits. The
agent's turn is a fixed string and the audit log is off: nothing here
reads a clock or the network. XDG_RUNTIME_DIR decides where the socket is,
the same variable `wispd nmhost` reads.
"""
import json
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wisp import config, trace  # noqa: E402
from wisp.tools import browser, browser_nm  # noqa: E402

CFG = {"browser": {"lane": "extension"}, "cua": {"audit": "false"}}


def main() -> int:
    turn = {"id": "t1"}
    trace.current = lambda: turn["id"]
    out_dir = pathlib.Path(sys.argv[1])
    lane = browser.Lane(0)
    path = lane.start_native(config.RUN_DIR / browser_nm.SOCKET_NAME)
    wlock = threading.Lock()

    def say(obj: dict) -> None:
        with wlock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    say({"ready": True, "socket": str(path)})

    def tool(req: dict) -> None:
        text = browser.run(req["tool"], CFG, lane=lane, out_dir=out_dir)
        say({"id": req["id"], "out": text})

    def raw(req: dict) -> None:
        say({"id": req["id"], "value": lane.call(req["raw"])})

    for line in sys.stdin:
        req = json.loads(line)
        if "raw" in req:
            threading.Thread(target=raw, args=(req,), daemon=True).start()
        elif "tool" in req:
            threading.Thread(target=tool, args=(req,), daemon=True).start()
        elif req.get("ctl") == "paired":
            say({"id": req["id"], "value": lane.paired})
        elif req.get("ctl") == "stop":
            lane.stop()
            say({"id": req["id"], "value": True})
        elif req.get("ctl") == "turn":
            turn["id"] = req["turn"]
            say({"id": req["id"], "value": turn["id"]})
    lane.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
