"""Bounded, allow-listed image fetcher for paper image cards (B5).

An answer's `::image[url=...]` object names a picture. This is the only
place that fetches it, and it fetches nothing it should not:

- the host must be on the allow-list (`[images] allow`, a comma list; each
  entry matches itself and its subdomains; the default is Wikimedia's image
  host) and the scheme must be https; a host that is not listed is refused
  before any connection, with a reason that can be spoken;
- every redirect hop is checked against the same list, and a host that
  resolves to a private, loopback or link-local address is refused;
- the body is capped (`[images] max_kb`, default 4096) and has a timeout
  (`[images] timeout_s`, default 8); it must decode as PNG, JPEG, GIF or
  WebP and stay under a pixel cap;
- the local copy goes to `<data dir>/images/<id>.<ext>` (0600) with a
  `<id>.json` sidecar recording the source URL, so a card can always show
  where a picture came from, and a repeat of the same URL costs nothing.
"""
import hashlib
import io
import ipaddress
import json
import os
import pathlib
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config

DEFAULT_ALLOW = ("upload.wikimedia.org",)
DEFAULT_MAX_KB = 4096
DEFAULT_TIMEOUT_S = 8
MAX_PIXELS = 40_000_000
FORMATS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}


class ImageRefused(Exception):
    """The picture may not be fetched. `str(e)` is a sentence to speak."""


class ImageFailed(Exception):
    """Allowed, but the fetch or the file failed. `str(e)` is speakable."""


def images_dir() -> pathlib.Path:
    return config.DATA_DIR / "images"


def _section(cfg) -> dict:
    return (cfg or {}).get("images") or {}


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


def host_allowed(host: str, cfg=None) -> bool:
    h = (host or "").lower().rstrip(".")
    return bool(h) and any(h == a or h.endswith("." + a)
                           for a in allow_list(cfg))


def check_url(url: str, cfg=None) -> str:
    """The host of `url` when it may be fetched; raises ImageRefused with a
    spoken reason otherwise. Never touches the network."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
        host = (u.hostname or "").lower()
    except ValueError:
        raise ImageRefused("I can't show that picture: its address is not "
                           "valid.")
    if u.scheme != "https" or not host:
        raise ImageRefused("I can only show pictures from secure web "
                           "addresses.")
    if u.username or u.password:
        raise ImageRefused("I can't show a picture from an address that "
                           "carries a login.")
    if not host_allowed(host, cfg):
        raise ImageRefused(f"I can't show that picture: {host} isn't on my "
                           "list of image sites.")
    return host


def _public(host: str) -> None:
    """Refuse a host that resolves to anything but a public address."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ImageFailed(f"I couldn't reach {host}.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ImageRefused(f"I can't show that picture: {host} points "
                               "at a private address.")


def url_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:20]


def lookup(url: str):
    """The stored copy of `url` as {path, source, host, w, h}, or None."""
    meta = images_dir() / f"{url_id(url)}.json"
    try:
        rec = json.loads(meta.read_text())
        if pathlib.Path(rec["path"]).is_file():
            return rec
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class _Hops(urllib.request.HTTPRedirectHandler):
    """Every redirect target meets the same rules as the first URL."""
    max_redirections = 3

    def __init__(self, cfg, resolve):
        self.cfg, self.resolve = cfg, resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = check_url(newurl, self.cfg)
        self.resolve(host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, cfg, host, opener, timeout):
    if opener is not None:
        return opener(url, timeout)
    handler = _Hops(cfg, _public)
    op = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        url, headers={"User-Agent": "wisp-image-card",
                      "Accept": "image/png,image/jpeg,image/gif,image/webp"})
    return op.open(req, timeout=timeout)


def fetch(url: str, cfg=None, *, opener=None, resolve=None) -> dict:
    """Fetch `url` into the images dir; {path, source, host, w, h}.
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
        r = _open(url, cfg, host, opener, timeout)
        chunks, n = [], 0
        with r:
            while True:
                c = r.read(64 * 1024)
                if not c:
                    break
                n += len(c)
                if n > max_bytes:
                    raise ImageFailed("That picture is too large to show.")
                chunks.append(c)
    except (ImageRefused, ImageFailed):
        raise
    except (urllib.error.URLError, OSError, ValueError):
        raise ImageFailed(f"I couldn't load that picture from {host}.")
    data = b"".join(chunks)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        fmt = FORMATS.get(img.format or "")
        w, h = img.size
        if not fmt:
            raise ImageFailed("That file isn't a picture I can show.")
        if w * h > MAX_PIXELS:
            raise ImageFailed("That picture is too large to show.")
        img.verify()
    except ImageFailed:
        raise
    except Exception:
        raise ImageFailed("That file isn't a picture I can show.")
    d = images_dir()
    d.mkdir(parents=True, exist_ok=True)
    uid = url_id(url)
    path = d / f"{uid}.{fmt}"
    _write(path, data)
    rec = {"path": str(path), "source": url, "host": host, "w": w, "h": h,
           "bytes": len(data), "fetched_at": time.strftime(
               "%Y-%m-%dT%H:%M:%S%z")}
    _write(d / f"{uid}.json", json.dumps(rec).encode())
    return rec


def _write(path: pathlib.Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
