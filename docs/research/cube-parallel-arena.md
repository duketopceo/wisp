# R6 — CubeSandbox parallel clicklab arena: feasibility recipe

Verdict: **GO, with one required repair first** — the CubeProxy data plane
(`cube-sandbox-cube-proxy.service`) is crash-looping (restart #1569) because
`tailscaled` holds `100.74.41.80:443` via Tailscale Funnel
(`omarchy-max.tailaf1559.ts.net → 127.0.0.1:8787`). Everything else is in
place: control plane live and authenticated, READY template, `/dev/kvm`
present, `*.cube.app` wildcard DNS works, outbound egress is default-allow,
`SandboxIP` is directly routable from the host so the data plane can be
bypassed entirely if needed.

## Verified state (probed, read-only)

| Fact | Evidence |
|---|---|
| API live | `GET http://127.0.0.1:3000/health` → `{"status":"ok","sandboxes":0}` |
| Auth required | `GET /` → 401; `GET /templates` → 401 without key |
| Auth mode | Static key (`CUBE_API_KEY`, 52 chars) in `/usr/local/services/cubetoolbox/.one-click.env` (root-only). `CubeAPI/src/middleware/auth.rs:92-119`: callback URL unset → simple-key mode. Header `X-API-Key: <key>` or `Authorization: Bearer <key>` |
| Key works | `GET /templates` → 200 with `X-API-Key` (verified via sudo read of `.one-click.env`; **do not commit the value**) |
| READY template | `tpl-eb5676093459433d97e030bd` alias `code-interpreter`, image `cube-sandbox-cn.tencentcloudcr.com/cube-sandbox/sandbox-code:latest`, spec `cpu=2000m,mem=2000Mi`, arm64 (built on this node 2026-09-29) |
| KVM | `/dev/kvm` present, `crw-rw-rw-` |
| DNS | `*.cube.app` → `192.168.1.123` via `cube-dns0`/systemd-resolved (CoreDNS container) |
| Sandbox subnet | `10.100.0.0/18 dev cube-dev` route exists — VM tap IPs are **host-routable directly** |
| Data plane | **DOWN** — cube-proxy crash-loops on `:443` conflict; ports 80/9090/8082 unbound |
| Resources | 10 CPUs, 62G RAM (~33G free), `/data/cubelet` 100G loop, 98G free |
| SDK | `~/src/cubesandbox/sdk/python` (pure py, deps httpx+requests), NOT pip-installed; `cubemastercli` at `/usr/local/bin` works vs `--address 127.0.0.1 --port 8089` |

## Auth recipe

```bash
# SDK picks these up (Config in sdk/python/cubesandbox/_config.py):
export CUBE_API_URL="http://127.0.0.1:3000"     # E2B_API_URL also accepted by examples
export CUBE_API_KEY="$(sudo grep -oP '^CUBE_API_KEY=\K.*' \
    /usr/local/services/cubetoolbox/.one-click.env | tr -d '"\'')"
# SDK sends X-API-Key on both control plane and data plane.
```

## The blocker, in detail

`journalctl -u cube-sandbox-cube-proxy`: `port 443 is already in use; cube-proxy
uses host networking ... Set CUBE_PROXY_HTTPS_PORT to a free port`. The squatter
is tailscaled's Funnel listener (serve config: `https://omarchy-max... →
127.0.0.1:8787`; nothing is on :8787 now, so the funnel looks stale, but do not
touch it without asking).

**Fix (recommended, one line, needs root):** add
`CUBE_PROXY_HTTPS_PORT=11443` to `/usr/local/services/cubetoolbox/.one-click.env`
(supported by `scripts/one-click/up-cube-proxy.sh:69`), then
`systemctl reset-failed cube-sandbox-cube-proxy && systemctl start
cube-sandbox-cube-proxy`. Ports 80/9090/8082 are free and will bind. Funnel keeps
443. After that, all SDK paths (`commands.run`, `files.*`, `run_code`, CDP via
`https://<port>-<sid>.cube.app`) work as documented.

**Alternative (no repair needed): bypass the proxy.** CubeProxy itself resolves
a sandbox route to `SandboxIP` and dials it directly
(`CubeProxy/lua/sandbox_backend.lua:264`). The host already routes
`10.100.0.0/18` via `cube-dev`, so `http://<SandboxIP>:49983` reaches envd and
`http://<SandboxIP>:<any-port>` reaches in-VM services — no proxy involved.
Get `SandboxIP` per sandbox via `cubemastercli --address 127.0.0.1 info -s
<sandboxID>` (prints `SANDBOX_IP`) or
`HGETALL cube:v1:shared:sandbox:proxy:<id>` (redis `127.0.0.1:6379`, password
`ceuhvu123` per `CubeMaster/conf.yaml`). The `POST /sandboxes` create response
carries `envdAccessToken`; envd wants `X-Access-Token: <token>` +
`Authorization: Basic base64("root:")` — the SDK's `Commands`/`Filesystem`
already send these (`_commands.py:117-120`), so monkeypatching
`Sandbox.get_host` to return `f"{sandbox_ip}:{port}"` makes the *entire* SDK
work over direct IP. Unverified against a live VM — 5-min test once a sandbox
exists. **Create itself needs no proxy** (CubeAPI→CubeMaster→Cubelet path only).

## Code-injection path (three tiers, pick per need)

1. **`Sandbox.create` env_vars + `files.write`** — push `index.html`,
   `apps.html`, driver script (~40KB total) into `/workspace` via envd `/files`.
   Zero build step; needs envd reachable (proxy fix or direct-IP).
2. **`metadata={"host-mount": ...}`** — bind-mount host dirs into the VM.
   `hostPath` must live under `/data/shared/` (exists, root-owned, empty;
   configurable via `allowed_host_mount_prefixes` in CubeMaster conf).
   Recipe: `/data/shared/clicklab/` → `/opt/clicklab` (ro, the pages) and
   `/data/shared/clicklab-out/` → `/out` (rw, results — host `tail`s them or
   they land straight into a shared `clicklab.jsonl`).
3. **Bake into template** — `cubemastercli tpl create-from-image --image ...
   --cpu 2000 --memory 2048 --expose-port 49983 --probe 49983 --probe-path
   /health`; or mutate a running sandbox then `tpl commit` / `create_snapshot()`
   (snapshots are usable as `template=` IDs directly — `Sandbox.clone()` already
   implements snapshot→N-create fan-out with `concurrency=`).

## Chromium: the arch wrinkle

`sandbox-browser:latest` (the example's image) is **amd64-only** per
`docker manifest inspect` — will not boot on this aarch64 host. But
`ghcr.io/tencentcloud/cubesandbox-base:2026.16` is multiarch (amd64+arm64), and
`sandbox-code` already proved arm64 works here (READY template). Options:

- **Baked image** (best): `FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16`
  (Ubuntu 22.04; `envd` + `cube-entrypoint.sh` preinstalled at known paths),
  `apt install -y chromium` won't work on 22.04 (snap shim) — use a Debian base
  (`python:3.11-slim` has real `chromium` on arm64) with
  `COPY --from=ghcr.io/tencentcloud/cubesandbox-base:2026.16 /usr/bin/envd
  /usr/bin/envd` + entrypoint, or `pip install playwright && playwright install
  --with-deps chromium` (arm64 chromium CDN builds). Push via a local
  `registry:2` container and reference it as `http://127.0.0.1:5000/clicklab:x`
  (the `http://` prefix for insecure registries is documented in
  `docs/guide/tutorials/bring-your-own-image.md` §2.2; cubelet pulls on the host
  network so loopback works). Or `--enable-inject-envd` on `create-from-image`
  injects envd at build time (`CubeMaster/.../envd_inject.go`).
- **Runtime install** (no registry needed): create from `code-interpreter`,
  `commands.run("apt-get update && apt-get install -y chromium || pip install
  playwright && playwright install chromium")`, then `create_snapshot()` → use
  the snapshot ID as the template for all N workers. One install, N clones.
- Headless chromium DOM-mode needs no GPU/X: `chromium --headless=new
  --remote-debugging-port=9222 --no-sandbox --disable-gpu`.

## Egress (OpenRouter)

Default network config: `allowInternetAccess=true` + deny of RFC1918/CGNAT
(`10/8, 100.64/10, 172.16/12, 192.168/16` — see `CubeMaster/conf.yaml`
`cube_box_req_template` and `docs/guide/network-policy.md:64`). So plain
`https://openrouter.ai` egress works out of the box.

Two ways to get the key in:
- **env_vars** (simple): `Sandbox.create(env_vars={"OPENROUTER_API_KEY": ...})`.
  Key material lands in the VM — fine for eval key on a private host.
- **CubeEgress inject** (clean): `network={"rules": [Rule(name="or",
  match=Match(host="openrouter.ai"), action=Action(allow=True,
  inject=[Inject(header="Authorization", secret=KEY,
  format="Bearer ${SECRET}")]))]}` — VM holds only a placeholder; egress MITM
  adds the real header on :443. Requires the template built with
  `--with-cube-ca` (default true → `/etc/cube/ca/cube-root-ca.crt` baked) and
  the in-VM client pointed at it (`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`).
  Sandboxes cannot reach host services — private CIDRs are denied — so the
  orchestrator must collect results via envd reads or a host-mount, not by the
  VM POSTing back to 127.0.0.1.

## Concurrency estimate (64G host, 10 cores)

Per-VM accounting (`Cubelet/config/config.toml`): `mem_spec + 42Mi +
mem/64` guest overhead; ~0.3 CPU + 20Mi host overhead each.

| Template spec | RAM/sandbox | Sandboxes in ~30G headroom | CPU note |
|---|---|---|---|
| default 2000m/2000Mi | ~2.1 GiB | ~14 | 2.0 cores × 14 = 28 CPUs of quota on 10 cores — ~3× overcommit, OK for bursty DOM-eval |
| lean `--memory 1024 --cpu 1000` | ~1.1 GiB | ~27 | chromium headless peaks ~300-500Mi; 1Gi is tight but workable |
| `--memory 1536 --cpu 1000` | ~1.6 GiB | ~18 | recommended sweet spot |

Scheduler: `create_concurrent_limit=100`, `create_timeout_insec=600`,
`tap_init_num=500` — platform won't bottleneck N≤25. **Recommended N=8–12**
parallel at default spec; N=15–20 with a lean template. Other host load
(Ollama, docker, desktop) already eats ~29G — keep ~4G safety margin.

## Recommended runner design (DOM mode)

**Thin-VM (recommended): browser only in the sandbox.** Wisp's DOM mode reduces
to one primitive — `_dom_eval(cfg, code)` → evaluate JS in the page and return a
string (`wisp/tools/system.py:241-261`); clicks/keys/typing are all synthetic
`dispatchEvent` calls, shots are SVG rasterized by `magick` on the host. So:

- Per sandbox: chromium `--headless=new --remote-debugging-port=9222` +
  clicklab HTML pushed via `files.write` (or host-mount ro).
- Host worker thread per sandbox: `playwright.chromium.connect_over_cdp(
  f"http://{SandboxIP}:9222")` (playwright installed; direct-IP, no proxy/TLS
  needed) → `page.goto("file:///workspace/index.html?seed=N")`; replace
  `mcpclient.call('browseros-neo evaluate ...')` with `page.evaluate(code)` —
  ~15-line adapter. OpenRouter stays on host under the existing `orch`/
  `arena_policy` spend gate; results append to `~/.local/share/wisp/
  clicklab.jsonl` natively.
- `magick` stays on host (already required today).

**Thick-VM alternative** (better isolation, more setup): host-mount wisp ro into
`/opt/wisp`, run the whole act loop + driver in-VM, OpenRouter via egress-inject
or env_vars, results written to an rw host-mount → `clicklab.jsonl` directly.
Use this when moving to remote cube nodes where host↔VM RTT per eval matters.

Reusable assets: `examples/mini-rl-training/scripts/run-concurrent.py`
(ThreadPoolExecutor fan-out + shared `ApiClient` + per-task sandbox lifecycle),
`examples/cube-bench` (Go create/delete latency prober — run `-c 12 -n 60`
post-fix to validate concurrency claims), `Sandbox.clone(n, concurrency=)`
(snapshot→fan-out).

## Exact create recipe

```python
# pip install ~/src/cubesandbox/sdk/python  (or pip install cubesandbox)
import os, threading, json, pathlib
from cubesandbox import Sandbox, Config

cfg = Config(api_url="http://127.0.0.1:3000",
             api_key=os.environ["CUBE_API_KEY"])  # see Auth recipe

def make(i):
    return Sandbox.create(
        template="code-interpreter",          # or tpl-id; chromium baked via snapshot/custom image
        timeout=3600,                          # NEVER_TIMEOUT=-1 also valid
        env_vars={"CLICKLAB_SEED": str(i)},
        metadata={"host-mount": json.dumps([
            {"hostPath": "/data/shared/clicklab", "mountPath": "/opt/clicklab", "readOnly": True},
            {"hostPath": "/data/shared/clicklab-out", "mountPath": "/out", "readOnly": False}])},
        allow_internet_access=True,
        config=cfg)

sandboxes = [f.result() for f in
             [threading.ThreadPoolExecutor(12).submit(make, i) for i in range(12)]]
# per sandbox: sb.files.write("/workspace/driver.py", SRC); sb.commands.run(...)
# direct-IP variant: get SandboxIP via `cubemastercli info -s <id>`, then
#   sb.get_host = lambda port: f"{ip}:{port}"  → commands/files/run_code all work
```

## Precise blocker list (in order)

1. **cube-proxy down** — set `CUBE_PROXY_HTTPS_PORT=11443` in `.one-click.env`
   (root) + restart the unit, *or* use the direct-`SandboxIP` envd path
   (bypass, unverified but architecturally sound). Without one of these,
   `commands.run`/`files.write`/`run_code` all fail — create still works.
2. **No arm64 chromium image** — `sandbox-browser` is x86-only; bake a custom
   arm64 image (cubesandbox-base is multiarch) or runtime-install + snapshot.
3. **Unverified**: sandbox *create* on this host (control plane healthy, 0
   sandboxes, but the Sept-29 template builds showed transient
   `CreateSerialManager(Epoll: PermissionDenied)` failures — if that recurs on
   create it's a cube-shim perms issue to chase). First test should be a single
   `Sandbox.create(template="code-interpreter")` + `cubemastercli info` +
   direct-envd `GET http://<SandboxIP>:49983/health` (expect 204).
4. SDK not pip-installed: `pip install ~/src/cubesandbox/sdk/python` (pure py;
   python3.14 host). Env: `CUBE_API_URL`, `CUBE_API_KEY`, `CUBE_TEMPLATE_ID`,
   opt `CUBE_PROXY_NODE_IP` (skip — only useful when proxy is up).

**Bottom line:** GO after one root-level fix (remap cube-proxy HTTPS port off
443) — or even without it, via direct-VM-IP envd + playwright-over-CDP to
`SandboxIP:9222`. Concurrency 8–12 safely, ~15–20 with a lean template.
