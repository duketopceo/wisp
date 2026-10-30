"""Pinned agent runtimes (KTD7): the exact `ori` and OpenCode builds Wisp
installs and drives. Ships in the release tarball with the rest of wisp/.

Each SHA-256 below was copied from its release's `SHA256SUMS` on
2026-10-28 and the arm64 assets were cross-checked against a local
download. To bump a pin, change the version/tag and all four hashes
together; `install()` refuses any pin that is not a 64-hex digest.
"""
import os
import pathlib
import platform
import re

from . import config

ORI_VERSION = "0.16.1"
ORI_TAG = "cli-0.16.1-91f9f29"
ORI_REPO = "OpenRouterLabs/ori-releases"
OPENCODE_VERSION = "2.2.0"
OPENCODE_TAG = "v2.2.0"
OPENCODE_REPO = "anomalyco/opencode"
OPENCODE_MAJOR = 2

SHA256 = {
    "ori-linux-arm64": "8f9870b7a53525a48469dd2daaf6934c8856a3814caad62df0d946228c11a9ba",
    "ori-linux-x64": "586b0976bec6246505e4d38f6219562368ae10788ec449e3f273f4e929bf122f",
    # the .tar.gz archive
    "opencode-linux-arm64": "1f1ce0fc07b9245a815ffa9d652dbb80e6b0f07e5bf74ea87d2b1c0339fbac52",
    "opencode-linux-x64": "6d597970a8cc448f1b9a9f645532584b339dd3ab9583bb5f063f13d83e54768f",
}

ARCHES = ("arm64", "x64")
_MACHINE = {"aarch64": "arm64", "arm64": "arm64",
            "x86_64": "x64", "amd64": "x64"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def machine_arch() -> str:
    m = platform.machine().lower()
    return _MACHINE.get(m, m)


def is_placeholder(sha) -> bool:
    return not _SHA.match(str(sha or "").lower())


def pin(tool: str, arch: str) -> dict | None:
    """-> {version, url, sha256, archive} or None for an unknown tool or
    arch. `archive` is True when the download is a .tar.gz holding the
    binary, False for a bare executable."""
    if arch not in ARCHES:
        return None
    key = f"{tool}-linux-{arch}"
    if tool == "ori":
        url = (f"https://github.com/{ORI_REPO}/releases/download/"
               f"{ORI_TAG}/ori-linux-{arch}")
        return {"version": ORI_VERSION, "url": url,
                "sha256": SHA256[key], "archive": False}
    if tool == "opencode":
        url = (f"https://github.com/{OPENCODE_REPO}/releases/download/"
               f"{OPENCODE_TAG}/opencode-linux-{arch}.tar.gz")
        return {"version": OPENCODE_VERSION, "url": url,
                "sha256": SHA256[key], "archive": True}
    return None


def ori_env(base=None) -> dict:
    """Env for a direct `ori` call: no self-update check (pins must not
    drift) and no update notice on stdout."""
    return dict(os.environ if base is None else base, ORI_NO_UPDATE_CHECK="1")


def runtime_root(root=None) -> pathlib.Path:
    return pathlib.Path(root) if root else config.DATA_DIR / "agent-runtime"


def runtime_paths(root=None) -> dict:
    """The pinned `current` binaries Wisp launches (never `which ori`).
    Presence of a path does not mean it is ready; see probes_agents."""
    r = runtime_root(root)
    return {"ori": r / "ori" / "current" / "ori",
            "opencode": r / "opencode" / "current" / "opencode"}
