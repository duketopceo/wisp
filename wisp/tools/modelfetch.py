"""Bounded, allow-listed fetcher for 3D model cards (B13).

The same rules as `imagefetch`, for a `::model[url=...]` object: https
only, the host on `[models] allow` (default: GitHub's raw host, where the
Khronos sample models live), every redirect hop re-checked, no private
addresses, a body cap (`[models] max_kb`, default 4096) and a timeout.
Only the parts the card needs (`model3d.parse`) are stored, to
`<data dir>/models/<id>.json` (0600) with the source URL; the downloaded
file itself is dropped.
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

from .. import config, model3d
from . import imagefetch

DEFAULT_ALLOW = ("raw.githubusercontent.com",)
DEFAULT_MAX_KB = 4096
DEFAULT_TIMEOUT_S = 8


class ModelRefused(Exception):
    """The model may not be fetched. `str(e)` is a sentence to speak."""


class ModelFailed(Exception):
    """Allowed, but the fetch or the file failed. `str(e)` is speakable."""


def models_dir() -> pathlib.Path:
    return config.DATA_DIR / "models"


def _section(cfg) -> dict:
    return (cfg or {}).get("models") or {}


def allow_list(cfg=None) -> tuple:
    raw = str(_section(cfg).get("allow", "") or "")
    hosts = tuple(h.strip().lower().rstrip(".") for h in raw.split(",")
                  if h.strip())
    return hosts or DEFAULT_ALLOW


def _limit(cfg, key, default, cast=int):
    try:
        v = cast(_section(cfg).get(key, default))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def check_url(url: str, cfg=None) -> str:
    """The host of `url` when it may be fetched; raises ModelRefused with a
    spoken reason otherwise. Never touches the network."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
        host = (u.hostname or "").lower().rstrip(".")
    except ValueError:
        raise ModelRefused("I can't show that model: its address is not "
                           "valid.")
    if u.scheme != "https" or not host:
        raise ModelRefused("I can only show models from secure web "
                           "addresses.")
    if u.username or u.password:
        raise ModelRefused("I can't show a model from an address that "
                           "carries a login.")
    if not any(host == a or host.endswith("." + a)
               for a in allow_list(cfg)):
        raise ModelRefused(f"I can't show that model: {host} isn't on my "
                           "list of model sites.")
    return host


def _public(host: str) -> None:
    try:
        imagefetch._public(host)
    except imagefetch.ImageRefused:
        raise ModelRefused(f"I can't show that model: {host} points at a "
                           "private address.")
    except imagefetch.ImageFailed:
        raise ModelFailed(f"I couldn't reach {host}.")


def lookup(url: str):
    """The stored parts of `url` as {title, parts, source, host}, or None."""
    meta = models_dir() / f"{imagefetch.url_id(url)}.json"
    try:
        rec = json.loads(meta.read_text())
        if isinstance(rec.get("parts"), list) and rec["parts"]:
            return rec
    except (OSError, ValueError, AttributeError):
        pass
    return None


class _Hops(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def __init__(self, cfg, resolve):
        self.cfg, self.resolve = cfg, resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.resolve(check_url(newurl, self.cfg))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, cfg, opener, timeout):
    if opener is not None:
        return opener(url, timeout)
    op = urllib.request.build_opener(_Hops(cfg, _public))
    req = urllib.request.Request(
        url, headers={"User-Agent": "wisp-model-card",
                      "Accept": "model/gltf-binary,model/gltf+json,"
                                "application/json"})
    return op.open(req, timeout=timeout)


def fetch(url: str, cfg=None, *, opener=None, resolve=None) -> dict:
    """Fetch `url`, extract its parts and store them; the stored record.
    `opener(url, timeout)` and `resolve(host)` are test seams."""
    url = str(url or "").strip()
    host = check_url(url, cfg)
    have = lookup(url)
    if have:
        return have
    (resolve or _public)(host)
    max_bytes = _limit(cfg, "max_kb", DEFAULT_MAX_KB) * 1024
    timeout = _limit(cfg, "timeout_s", DEFAULT_TIMEOUT_S, float)
    try:
        chunks, n = [], 0
        with _open(url, cfg, opener, timeout) as r:
            while True:
                c = r.read(64 * 1024)
                if not c:
                    break
                n += len(c)
                if n > max_bytes:
                    raise ModelFailed("That 3D model is too large to show.")
                chunks.append(c)
    except (ModelRefused, ModelFailed):
        raise
    except (urllib.error.URLError, OSError, ValueError):
        raise ModelFailed(f"I couldn't load that model from {host}.")
    try:
        got = model3d.parse(b"".join(chunks))
    except model3d.ModelError as e:
        raise ModelFailed(str(e))
    rec = {"title": got["title"], "parts": got["parts"], "source": url,
           "host": host}
    d = models_dir()
    d.mkdir(parents=True, exist_ok=True)
    imagefetch._write(d / f"{imagefetch.url_id(url)}.json",
                      json.dumps(rec).encode())
    return rec
