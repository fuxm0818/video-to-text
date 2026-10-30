"""Colour, size and type tokens for the light and dark themes."""
from __future__ import annotations

LIGHT = {
    "bg.app": "#EDEDED",
    "bg.sidebar": "#F2F1F0",
    "bg.content": "#FFFFFF",
    "bg.control": "#FFFFFF",
    "bg.hover": "#E8E7E6",
    "bg.selected": "#E3E2E1",
    "bg.selected_inactive": "#EAE9E8",
    "text.primary": "#1C1C1E",
    "text.secondary": "#6E6E73",
    "text.tertiary": "#9A9AA0",
    "line": "#D8D7D5",
    "line.hair": "#E5E4E3",
    "border": "#C8C7C5",
    "state.ok": "#1F7A38",
    "state.warn": "#9A5B00",
    "state.error": "#B02A1F",
    "track": "#D8D7D5",
}

DARK = {
    "bg.app": "#1C1C1E",
    "bg.sidebar": "#232325",
    "bg.content": "#2A2A2C",
    "bg.control": "#3A3A3C",
    "bg.hover": "#323233",
    "bg.selected": "#3A3A3C",
    "bg.selected_inactive": "#333335",
    "text.primary": "#F5F5F7",
    "text.secondary": "#A1A1A6",
    "text.tertiary": "#6E6E73",
    "line": "#3A3A3C",
    "line.hair": "#2F2F31",
    "border": "#4A4A4C",
    "state.ok": "#30D158",
    "state.warn": "#FF9F0A",
    "state.error": "#FF453A",
    "track": "#3A3A3C",
}

SIZES = {
    "toolbar": 38,
    "status": 26,
    "row": 44,
    "header": 28,
    "sidebar": 200,
    "radius": 6,
    "radius.window": 10,
    "progress.height": 4,
    "progress.width": 120,
}

_ACTIVE = LIGHT
_DARK = False


def palette(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def set_dark(dark: bool) -> None:
    global _ACTIVE, _DARK
    _DARK = bool(dark)
    _ACTIVE = palette(_DARK)


def is_dark() -> bool:
    return _DARK


def active() -> dict[str, str]:
    return _ACTIVE
