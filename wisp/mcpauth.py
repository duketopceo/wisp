"""wispd connect — OAuth onboarding for the Strata connector suite.

BrowserOS runs a Klavis Strata gateway locally (connector_mcp_servers
exposes ~45 OAuth services: Gmail, GitHub, Slack, Notion, Linear,
Jira, Calendar, Drive, Salesforce, Figma…). `connect` asks the gateway
for a service's status; when it returns an authUrl we open the browser
and poll until the user finishes the sign-in, then register the
service in ~/.config/wisp/mcp.json so inventory + mcp_call see it.

Calls route back through the gateway: mcp_call 'gmail send {...}' →
browseros execute_action {server_name, action_name, params}.
"""
import json
import time

from . import config

WISP_MCP = config.HOME / ".config/wisp/mcp.json"
POLL_S, WAIT_S = 5, 240

# Browsers that may carry the OAuth flow, preference order. Launching the
# binary while the browser runs opens a tab in the existing profile — the
# user's logged-in session. xdg-open/open are deliberately absent: the
# system default can be a chooser (Junction) or the BrowserOS agent
# browser, and an OAuth flow there authenticates the wrong profile.
_PERSONAL_BROWSERS = (
    "chromium", "firefox", "google-chrome-stable", "brave",
    "zen-browser", "vivaldi-stable", "microsoft-edge-stable",
)
# hyprctl client `class` -> binaries that class can map to.
_CLASS_TO_BINS = {
    "chromium": ("chromium",),
    "chromium-browser": ("chromium",),
    "firefox": ("firefox",),
    "google-chrome": ("google-chrome-stable", "google-chrome"),
    "google-chrome-stable": ("google-chrome-stable", "google-chrome"),
    "chrome": ("google-chrome-stable", "google-chrome"),
    "brave": ("brave", "brave-browser"),
    "brave-browser": ("brave", "brave-browser"),
    "zen": ("zen-browser", "zen"),
    "zen-browser": ("zen-browser", "zen"),
    "vivaldi": ("vivaldi", "vivaldi-stable"),
    "vivaldi-stable": ("vivaldi", "vivaldi-stable"),
    "microsoft-edge": ("microsoft-edge-stable", "microsoft-edge"),
}

# user-facing alias -> (connector enum name, strata action name)
_ALIASES = {}


def _build_aliases() -> None:
    names = ["Gmail", "Google Calendar", "Google Docs", "Google Drive",
             "Google Sheets", "Slack", "LinkedIn", "Notion", "Airtable",
             "Confluence", "GitHub", "GitLab", "Linear", "Jira", "Figma",
             "Salesforce", "ClickUp", "Asana", "Monday",
             "Microsoft Teams", "Outlook Mail", "Outlook Calendar",
             "Supabase", "Vercel", "Postman", "Stripe", "Cloudflare",
             "Brave Search", "Mem0", "Dropbox", "OneDrive", "WordPress",
             "YouTube", "Box", "HubSpot", "PostHog", "Mixpanel",
             "Discord", "WhatsApp", "Shopify", "Cal.com", "Resend",
             "Google Forms", "Zendesk", "Intercom"]
    for n in names:
        key = n.lower()
        _ALIASES[key] = (n, key)
        _ALIASES[key.replace(" ", "")] = (n, key)
    _ALIASES.update({"google": ("Google Drive", "google drive"),
                     "cal": ("Google Calendar", "google calendar"),
                     "calendar": ("Google Calendar", "google calendar"),
                     "teams": ("Microsoft Teams", "microsoft teams"),
                     "outlook": ("Outlook Mail", "outlook mail"),
                     "onenote": ("OneDrive", "onedrive"),
                     "search": ("Brave Search", "brave search")})


def _browseros_url() -> str | None:
    from . import inventory
    spec = (inventory.load().get("mcp") or {}).get("browseros") or {}
    return spec.get("url")


def _canonical(name: str) -> tuple | None:
    if not _ALIASES:
        _build_aliases()
    return _ALIASES.get(name.strip().lower())


def list_connectors(cfg: dict) -> str:
    """connector_mcp_servers with no server_name → inventory/status."""
    url = _browseros_url()
    if not url:
        return "SKIP (browseros MCP not found — run wispd inventory)"
    from .tools import mcpclient
    return mcpclient._call_http(url, "connector_mcp_servers", {})


def list_connectors_json(cfg: dict) -> list:
    """Machine-readable catalog for the panel: every known service with
    a registered flag from ~/.config/wisp/mcp.json (cheap — the gateway
    status call is per-service and slow, so the UI merges these)."""
    if not _ALIASES:
        _build_aliases()
    try:
        data = json.loads(WISP_MCP.read_text())
        registered = {v.get("service", "")
                      for v in data.get("mcpServers", {}).values()}
    except (OSError, ValueError):
        registered = set()
    seen = {}
    for key, (label, strata) in _ALIASES.items():
        if label not in seen:
            seen[label] = {"name": label, "strata": strata,
                           "connected": strata in registered,
                           "alias": key}
    return sorted(seen.values(), key=lambda r: r["name"].lower())


def status(name: str, cfg: dict) -> dict:
    """{'connected': bool, 'auth_url': str|None, 'raw': str}"""
    canon = _canonical(name)
    if not canon:
        return {"connected": False, "auth_url": None,
                "raw": f"unknown service {name!r}"}
    url = _browseros_url()
    if not url:
        return {"connected": False, "auth_url": None,
                "raw": "browseros MCP not in inventory"}
    from .tools import mcpclient
    try:
        out = mcpclient._call_http(url, "connector_mcp_servers",
                                   {"server_name": canon[0]})
    except Exception as e:
        return {"connected": False, "auth_url": None,
                "raw": f"gateway unreachable: {type(e).__name__}: {e}"}
    # gateway replies with a JSON record: {"connected": bool,
    # "authUrl": "...", "proxy": {...}}
    try:
        rec = json.loads(out[out.index("{"):])
        if isinstance(rec, dict):
            return {"connected": bool(rec.get("connected")),
                    "auth_url": rec.get("authUrl"), "raw": out}
    except (ValueError, KeyError):
        pass
    import re as _re
    m = _re.search(r"https?://[^\s\"]+", out)
    return {"connected": "connected" in out.lower()
            and "not connected" not in out.lower() and not m,
            "auth_url": m.group(0) if m else None, "raw": out}


def register(name: str) -> None:
    """Persist 'name' as a wisp-owned MCP entry routing via strata."""
    key = name.strip().lower().replace(" ", "-")
    try:
        data = json.loads(WISP_MCP.read_text())
    except (OSError, ValueError):
        data = {}
    servers = data.setdefault("mcpServers", {})
    servers[key] = {"via": "strata",
                    "service": _canonical(name)[1] if _canonical(name)
                    else key}
    WISP_MCP.parent.mkdir(parents=True, exist_ok=True)
    WISP_MCP.write_text(json.dumps(data, indent=1) + "\n")


def _running_browser_bins() -> list:
    """Binaries of personal browsers with a live window, focused first.

    Reads hyprctl client classes; agent browsers (browseros*) and
    choosers (Junction) are not in the map, so they never win."""
    import shutil
    import subprocess
    if not shutil.which("hyprctl"):
        return []
    classes = []
    try:
        act = subprocess.run(["hyprctl", "activewindow", "-j"],
                             capture_output=True, text=True, timeout=3)
        cls = str(json.loads(act.stdout or "{}").get("class", "")).lower()
        if cls:
            classes.append(cls)
        out = subprocess.run(["hyprctl", "clients", "-j"],
                             capture_output=True, text=True, timeout=3)
        for c in json.loads(out.stdout or "[]"):
            cls = str(c.get("class", "")).lower() if isinstance(c, dict) else ""
            if cls and cls not in classes:
                classes.append(cls)
    except Exception:
        pass
    found = []
    for cls in classes:
        # chrome-<app>__-Default windows are Chrome PWAs — same profile
        key = "chrome" if cls.startswith("chrome-") else cls
        for b in _CLASS_TO_BINS.get(key, ()):
            if shutil.which(b) and b not in found:
                found.append(b)
    return found


def _open_auth_url(url: str) -> str:
    """Open the OAuth URL for the user. Returns 'browser' | 'clipboard'
    | 'failed'. Never xdg-open (see _PERSONAL_BROWSERS)."""
    import os
    import shutil
    import subprocess
    cand = []
    env = (os.environ.get("BROWSER") or "").split(":")[0].strip()
    if env and "xdg" not in env and "junction" not in env.lower() \
            and "browseros" not in env.lower():
        cand.append(env)
    cand.extend(_running_browser_bins())
    cand.extend(_PERSONAL_BROWSERS)
    for b in cand:
        if shutil.which(b):
            subprocess.Popen([b, url])
            return "browser"
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy"], input=url.encode(), timeout=3)
            if shutil.which("notify-send"):
                subprocess.Popen(
                    ["notify-send", "-a", "wisp", "wisp connect",
                     "Sign-in link copied — paste it in your browser"])
            return "clipboard"
        except Exception:
            pass
    return "failed"


def connect(name: str, cfg: dict,
            wait_s: int = WAIT_S) -> str:
    """Full connect flow. Returns a human-readable result string."""
    canon = _canonical(name)
    if not canon:
        known = ", ".join(sorted({v[0] for v in _ALIASES.values()}))
        return f"UNKNOWN service {name!r} — try: {known}"
    st = status(name, cfg)
    if st["connected"]:
        register(name)
        return f"CONNECTED {canon[0]} — registered in wisp mcp.json"
    if not st["auth_url"]:
        return (f"AUTH_NEEDED {canon[0]} — gateway returned no authUrl. "
                f"raw: {st['raw'][:200]}")
    url = st["auth_url"]
    where = _open_auth_url(url)
    if where == "failed":
        return f"OPEN_THIS {canon[0]}: {url}"
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(POLL_S)
        st = status(name, cfg)
        if st["connected"]:
            register(name)
            return (f"CONNECTED {canon[0]} — sign-in finished, "
                    "registered in wisp mcp.json")
    return (f"TIMEOUT waiting for {canon[0]} sign-in — retry "
            f"'wispd connect {name}' after finishing the browser flow")


def _unhook() -> None:  # test seam
    _ALIASES.clear()
