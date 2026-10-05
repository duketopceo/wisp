#!/usr/bin/env python3
"""CubeVM training worker — create a MicroVM sandbox, provision
chromium + the clicklab pages inside it, and hand back a CDP endpoint
that run.py --cdp can drive. Brain/model calls stay on the host; only
the browser runs in the sandbox.

  up [--count N]     create + provision N sandboxes, print CDP host:port
                     per worker (one per line, "i ip:port")
  run [run.py args]  up worker 0, then exec run.py --cdp <ip:port> with
                     the args
  down [--all]       kill every tracked sandbox
  status             show tracked sandboxes

State: ~/.local/share/wisp/cube-worker.json  {"workers":[{...}]}
Key:   $CUBE_API_KEY or omaseal cubesandbox/api-key
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.local/share/wisp/cube-worker.json")
API = os.environ.get("CUBE_API_URL", "http://127.0.0.1:3000")
TEMPLATE = os.environ.get("CUBE_TEMPLATE_ID",
                         "tpl-eb5676093459433d97e030bd")  # code-interpreter arm64
LAB_FILES = ["index.html", "apps.html", "arena.html"]
ENVD = 49983
CDP_PORT = 9222


def api_key() -> str:
    k = os.environ.get("CUBE_API_KEY")
    if k:
        return k
    r = subprocess.run(["omaseal", "get", "cubesandbox", "api-key"],
                       capture_output=True, text=True)
    k = r.stdout.strip()
    if not k:
        raise SystemExit("cube.py: no CUBE_API_KEY and omaseal "
                         "cubesandbox/api-key is empty")
    return k


def _req(method: str, path: str, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"X-API-Key": api_key(),
                 "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(d: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(d, f, indent=1)


def _workers() -> list:
    """Tracked workers; migrates the legacy {sandbox_id,ip} shape."""
    st = _state()
    if isinstance(st.get("workers"), list):
        return st["workers"]
    if st.get("sandbox_id") and st.get("ip"):
        return [st]
    return []


def _save_workers(ws: list):
    _save_state({"workers": ws})


def sandbox_ip(sandbox_id: str) -> str:
    out = subprocess.run(
        ["cubemastercli", "--address", "127.0.0.1", "info",
         "-s", sandbox_id],
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.strip().startswith("SANDBOX_IP"):
            return line.split()[-1]
    # fallback: redis hash
    r = subprocess.run(
        ["redis-cli", "-h", "127.0.0.1", "-a", "ceuhvu123",
         "HGET", f"cube:v1:shared:sandbox:proxy:{sandbox_id}",
         "SandboxIP"],
        capture_output=True, text=True)
    ip = r.stdout.strip()
    if ip:
        return ip
    raise RuntimeError(f"no SandboxIP for {sandbox_id}:\n{out}")


def exec_guest(ip: str, cmd: str, timeout: int = 300) -> str:
    """Run cmd via envd Connect RPC; returns stdout, raises on nonzero."""
    import struct
    def frame(d, f=0):
        return bytes([f]) + struct.pack(">I", len(d)) + d
    body = frame(json.dumps(
        {"process": {"cmd": "/bin/sh", "args": ["-c", cmd]},
         "tag": "wisp-lab"}).encode())
    req = urllib.request.Request(
        f"http://{ip}:{ENVD}/process.Process/Start", data=body,
        headers={"Content-Type": "application/connect+json",
                 "Connect-Protocol-Version": "1"}, method="POST")
    buf = urllib.request.urlopen(req, timeout=timeout).read()
    i, out, err, status = 0, [], [], ""
    while i < len(buf):
        f, ln = buf[i], struct.unpack(">I", buf[i + 1:i + 5])[0]
        d = buf[i + 5:i + 5 + ln]
        i += 5 + ln
        if f & 2:
            continue
        try:
            ev = json.loads(d).get("event", {})
        except Exception:
            continue
        if "data" in ev:
            s, e = (ev["data"].get(k) for k in ("stdout", "stderr"))
            if s:
                out.append(base64.b64decode(s).decode("utf-8", "replace"))
            if e:
                err.append(base64.b64decode(e).decode("utf-8", "replace"))
        if "end" in ev:
            status = ev["end"].get("status") or ""
    text = "".join(out)
    import re as _re
    m = _re.search(r"(\d+)\s*$", status)
    rc = int(m.group(1)) if m else (0 if not status else 1)
    if rc != 0:
        raise RuntimeError(f"guest cmd failed ({status}): {cmd}\n"
                           f"{''.join(err)[-800:]}")
    return text


def _wait_envd(ip: str, tries: int = 60) -> bool:
    for _ in range(tries):
        try:
            exec_guest(ip, "echo ok", timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


def _alive(w: dict) -> bool:
    try:
        exec_guest(w["ip"], "true", timeout=4)
        return True
    except Exception:
        return False


def _create() -> dict:
    resp = _req("POST", "/sandboxes",
                {"templateID": TEMPLATE, "timeout": 3600})
    sid = resp.get("sandboxID") or resp.get("sandboxId")
    print(f"[cube] created {sid}", file=sys.stderr)
    ip = None
    for _ in range(30):
        try:
            ip = sandbox_ip(sid)
            break
        except Exception:
            time.sleep(2)
    if not ip:
        raise SystemExit(f"[cube] no IP for {sid}")
    w = {"sandbox_id": sid, "ip": ip, "created": time.time()}
    if not _wait_envd(ip):
        raise SystemExit(f"[cube] envd never came up on {ip}")
    w["cdp_port"] = provision(ip)
    return w


def up(count: int = 1) -> list:
    """Ensure `count` live, provisioned workers; returns the list."""
    ws = _workers()
    live = []
    for w in ws:
        if _alive(w):
            print(f"[cube] reusing {w['sandbox_id']} @ {w['ip']}",
                  file=sys.stderr)
            w["cdp_port"] = provision(w["ip"])   # idempotent
            live.append(w)
        else:
            print(f"[cube] stale sandbox {w.get('sandbox_id')}, "
                  "recreating", file=sys.stderr)
    # save as we go: a _create() that raises must not strand the
    # sandboxes it already made — they would be running but untracked
    while len(live) < count:
        live.append(_create())
        _save_workers(live)
    # keep every live worker tracked — shrinking count must not leak
    # a running sandbox just because it isn't handed out this call
    _save_workers(live)
    return live[:count]


def provision(ip: str):
    guest = exec_guest(ip, "command -v chromium || command -v "
                           "chromium-browser || true").strip()
    if not guest:
        print("[cube] installing chromium (first run, ~1-2min)",
              file=sys.stderr)
        exec_guest(ip, "apt-get update -qq && DEBIAN_FRONTEND="
                       "noninteractive apt-get install -y -qq chromium",
                   timeout=600)
        exec_guest(ip, "apt-get clean")   # reclaim .deb cache — ~200MB
        guest = exec_guest(ip, "command -v chromium || command -v "
                               "chromium-browser").strip()
    print(f"[cube] chromium: {guest}", file=sys.stderr)
    exec_guest(ip, "mkdir -p /opt/lab")
    for name in LAB_FILES:
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            continue
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        exec_guest(ip, f"echo {b64} | base64 -d > /opt/lab/{name}")
    # [r] avoids pkill matching its own sh -c cmdline
    exec_guest(ip, "pkill -f '[r]emote-debugging' 2>/dev/null; "
                   "pkill -f 'cdp-[r]elay' 2>/dev/null; sleep 0.5; true")
    exec_guest(ip, f"nohup {guest} --headless=new --no-sandbox "
                   "--disable-gpu --disable-dev-shm-usage "
                   f"--remote-debugging-port={CDP_PORT} "
                   "about:blank >/tmp/chrome.log 2>&1 & sleep 3; "
                   f"curl -s http://127.0.0.1:{CDP_PORT}/json/version "
                   "| head -c 60")
    # chromium only binds CDP to loopback — forward 0.0.0.0:9223 → :9222
    relay = ("import socket,threading\n"
             "def p(a,b):\n"
             "  try:\n"
             "    while 1:\n"
             "      d=a.recv(65536)\n"
             "      if not d:break\n"
             "      b.sendall(d)\n"
             "  except Exception:pass\n"
             "  try:a.close();b.close()\n"
             "  except Exception:pass\n"
             f"s=socket.socket();s.setsockopt(socket.SOL_SOCKET,"
             "socket.SO_REUSEADDR,1)\n"
             f"s.bind(('0.0.0.0',{CDP_PORT+1}));s.listen(16)\n"
             "while 1:\n"
             "  c,_=s.accept()\n"
             f"  u=socket.create_connection(('127.0.0.1',{CDP_PORT}))\n"
             "  threading.Thread(target=p,args=(c,u),daemon=True).start()\n"
             "  threading.Thread(target=p,args=(u,c),daemon=True).start()\n")
    b64 = base64.b64encode(relay.encode()).decode()
    exec_guest(ip, f"echo {b64} | base64 -d > /tmp/cdp-relay.py && "
                   "nohup python3 /tmp/cdp-relay.py >/tmp/relay.log 2>&1 "
                   "& sleep 1; echo relay-started")
    # host-side reachability through the tap net
    relay_port = CDP_PORT + 1
    for _ in range(15):
        try:
            urllib.request.urlopen(
                f"http://{ip}:{relay_port}/json/version", timeout=2)
            print(f"[cube] CDP up at {ip}:{relay_port}",
                  file=sys.stderr)
            return relay_port
        except Exception:
            time.sleep(1)
    raise SystemExit(f"[cube] chromium CDP never reachable on {ip}")


def down():
    ws = _workers()
    if not ws:
        print("[cube] no tracked sandbox")
        return
    for w in ws:
        sid = w.get("sandbox_id")
        if not sid:
            continue
        last = None
        for method, path in (("DELETE", f"/sandboxes/{sid}"),
                             ("POST", f"/sandboxes/{sid}/kill")):
            try:
                _req(method, path, {})
                print(f"[cube] killed {sid}")
                last = None
                break
            except Exception as e:
                last = e
        if last is not None:
            print(f"[cube] kill {sid} failed: {last}")
    _save_state({})


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        return True
    return default


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "up"
    if cmd == "up":
        ws = up(int(_flag("--count", "1") or 1))
        for i, w in enumerate(ws):
            print(f"{i} {w['ip']}:{w.get('cdp_port', CDP_PORT + 1)}")
    elif cmd == "down":
        down()
    elif cmd == "status":
        print(json.dumps(_state(), indent=1))
    elif cmd == "run":
        ws = up(1)
        w = ws[0]
        args = [a for a in sys.argv[2:] if a != "--"]
        run = os.path.join(HERE, "run.py")
        rc = subprocess.call(
            [sys.executable, run, "--cdp",
             f"{w['ip']}:{w.get('cdp_port', CDP_PORT + 1)}",
             "--worker", "0", "--sandbox-id", w["sandbox_id"]]
            + args)
        sys.exit(rc)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
