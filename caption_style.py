"""The caption look a job is rendered with, before any clip exists.

The same 17 fields ``/api/subtitle`` accepts, validated once so three callers
agree: the Clip Generator's pre-generation panel, the Playground/Profile store,
and ``/api/process`` which hands the look to the pipeline as
``AUTO_CAPTION_STYLE_JSON``. Bad values are dropped or clamped here rather than
reaching libass, which fails in less legible ways.
"""
from __future__ import annotations

import json
import re
from typing import Optional

FIELDS = (
    "style", "position", "font_size", "font_name", "font_color",
    "border_color", "border_width", "bg_color", "bg_opacity",
    "highlight_color", "effect", "base_opacity", "uppercase", "reveal",
    "shadow", "max_chars", "max_duration")

ENUMS = {
    "style": {"karaoke", "classic"},
    "position": {"top", "middle", "bottom"},
    "effect": {"none", "glow", "pop", "box", "highlight"},
}

COLOR_FIELDS = ("font_color", "border_color", "bg_color", "highlight_color")
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")

# name: (low, high, integer)
NUMBERS = {
    "font_size": (10, 120, True),
    "border_width": (0, 10, True),
    "bg_opacity": (0.0, 1.0, False),
    "base_opacity": (0.0, 1.0, False),
    "shadow": (0, 10, True),
    "max_chars": (1, 80, True),
    "max_duration": (0.2, 5.0, False),
}


def clean(raw) -> Optional[dict]:
    """A safe copy of ``raw`` (dict or JSON string), or None when empty."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for name, allowed in ENUMS.items():
        value = raw.get(name)
        if value in allowed:
            out[name] = value
    font = raw.get("font_name")
    if isinstance(font, str) and font.strip():
        out["font_name"] = font.strip()[:64]
    for name in COLOR_FIELDS:
        value = raw.get(name)
        if isinstance(value, str) and _HEX.match(value.strip()):
            text = value.strip()
            out[name] = text if text.startswith("#") else f"#{text}"
    for name, (low, high, integer) in NUMBERS.items():
        value = raw.get(name)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        number = min(max(number, low), high)
        out[name] = int(number) if integer else round(number, 2)
    for name in ("uppercase", "reveal"):
        if name in raw:
            out[name] = bool(raw[name])
    return out or None
