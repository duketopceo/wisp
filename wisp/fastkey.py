#!/usr/bin/env python3
"""Key-bind client: send one IPC command to wispd with no heavy imports.

The Hyprland submap binds (wisp/keys.py) run this instead of `wispd`
because Esc must stop a turn inside the 150 ms stop budget and a cold
`wispd` import costs about 120 ms by itself. Standard library only; it
speaks the same unix-socket JSON the daemon's `interrupt` and `choice`
commands do.

    fastkey.py --sock PATH interrupt
    fastkey.py --sock PATH choice N        (1-based option index)
"""
import json
import socket
import sys


def build(args: list):
    """-> command dict, or None for anything unexpected."""
    if args == ["interrupt"]:
        return {"cmd": "interrupt"}
    if len(args) == 2 and args[0] == "choice" and args[1].isdigit() \
            and int(args[1]) >= 1:
        return {"cmd": "choice", "pick": "", "index": int(args[1])}
    return None


def main(argv: list) -> int:
    if len(argv) < 3 or argv[0] != "--sock":
        return 2
    cmd = build(argv[2:])
    if cmd is None:
        return 2
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(argv[1])
        s.sendall(json.dumps(cmd).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    except OSError:
        return 1
    finally:
        s.close()
    try:
        return 0 if json.loads(data.decode()).get("ok") else 1
    except ValueError:
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
