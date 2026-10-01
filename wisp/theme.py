"""Wisp theme tokens — DESIGN.md is the spec, theme.json the artifact.

Two authored palettes (no programmatic inversion — light is designed,
not negated). `emit()` writes DATA_DIR/theme.json; QML surfaces watch
it like state.json, so `wispd theme light` live-swaps without a shell
restart.
"""
import json

from . import config

FILE = config.DATA_DIR / "theme.json"

DARK = {
    "canvas": "#1a1b26", "surface": "#283457", "hairline": "#3b4261",
    "ink": "#c0caf5", "muted": "#9aa5ce", "faint": "#565f89",
    "accent": "#7aa2f7", "accentAlt": "#bb9af7", "guide": "#7dcfff",
    "ok": "#9ece6a", "warn": "#e0af68", "err": "#e05555",
}

LIGHT = {
    "canvas": "#f5f6fa", "surface": "#e2e6f2", "hairline": "#c3c9dd",
    "ink": "#1f2335", "muted": "#4c5578", "faint": "#8a91ad",
    "accent": "#2e7de9", "accentAlt": "#9854f1", "guide": "#007197",
    "ok": "#33701f", "warn": "#8f5e15", "err": "#c43a3a",
}

THEMES = {"dark": DARK, "light": LIGHT}


def current(cfg: dict) -> str:
    name = (cfg or {}).get("ui", {}).get("theme", "dark")
    return name if name in THEMES else "dark"


def tokens(cfg: dict) -> dict:
    return dict(THEMES[current(cfg)])


def emit(cfg: dict) -> str:
    """Write theme.json atomically. Returns the resolved theme name."""
    name = current(cfg)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"name": name, "tokens": tokens(cfg)}))
    tmp.replace(FILE)
    return name
