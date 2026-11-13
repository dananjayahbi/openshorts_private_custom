"""Named caption/format/prompt combinations ("style profiles").

Different accounts need different looks: one channel wants the Hormozi captions
with a 9:16 crop, another wants the clean look on 1:1. A profile is the whole
bundle so the Clip Generator can apply it in one choice instead of re-picking
every control:

    {
      "id": "...", "name": "Gaming vertical",
      "caption": { CAPTION_STYLE_FIELDS ... },   # the pre-generation look
      "output":  { output_format, layouts, auto_hook, auto_hook_style,
                   target_clips, clip_min_seconds, clip_max_seconds },
      "prompts": { prompt_id: template }         # optional, overrides Settings
    }

Stored in ``Storage/style_profiles.json`` next to the media so a moved
``Storage/`` carries them, and so an MCP/agent job can name a profile by id.
"""
from __future__ import annotations

import threading
import time
import uuid

import caption_style
import storage
import prompt_store
from jsonfile import write_json_atomic
import os

_lock = threading.RLock()
_FILE = "style_profiles.json"

OUTPUT_FORMATS = ("vertical", "square", "horizontal", "auto")


class ProfileError(ValueError):
    pass


def _path() -> str:
    override = (os.environ.get("OPENSHORTS_PROFILES") or "").strip()
    if override:
        return override
    return os.path.join(storage.STORAGE_DIR, _FILE)


def _read() -> list:
    import json

    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(items: list) -> None:
    os.makedirs(storage.STORAGE_DIR, exist_ok=True)
    write_json_atomic(_path(), items, indent=2)


def _clean_output(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}

    fmt = raw.get("output_format")
    if fmt in OUTPUT_FORMATS:
        out["output_format"] = fmt

    layouts = raw.get("layouts")
    if isinstance(layouts, str):
        layouts = [p.strip() for p in layouts.split(",") if p.strip()]
    if isinstance(layouts, list):
        allowed = {"auto", "split", "screencast", "none"}
        out["layouts"] = [p for p in layouts if p in allowed][:3]

    if "auto_hook" in raw:
        out["auto_hook"] = bool(raw["auto_hook"])
    style = raw.get("auto_hook_style")
    if isinstance(style, str) and style:
        from hooks import HOOK_STYLES
        if style in HOOK_STYLES:
            out["auto_hook_style"] = style

    def _num(name, lo, hi, integer=False):
        value = raw.get(name)
        if value in (None, ""):
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if not (lo <= number <= hi):
            return
        out[name] = int(number) if integer else number

    _num("target_clips", 1, 15, integer=True)
    _num("clip_min_seconds", 5, 175)
    _num("clip_max_seconds", 10, 180)
    return out


def _clean_caption(raw: dict) -> dict:
    """Only the fields the burn understands; ranges are enforced server-side."""
    return caption_style.clean(raw) or {}


def _clean_prompts(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for prompt_id, template in raw.items():
        if not isinstance(template, str) or not template.strip():
            continue
        try:
            out[prompt_id] = prompt_store.validate(prompt_id, template)
        except prompt_store.PromptError as e:
            raise ProfileError(str(e)) from e
    return out


def _clean_name(name) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ProfileError("a profile needs a name")
    return text[:80]


def list_profiles() -> list:
    return sorted(_read(), key=lambda p: p.get("updated_at") or 0, reverse=True)


def get(profile_id: str) -> dict | None:
    for profile in _read():
        if profile.get("id") == profile_id:
            return profile
    return None


def create(data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    now = time.time()
    profile = {
        "id": uuid.uuid4().hex,
        "name": _clean_name(data.get("name")),
        "caption": _clean_caption(data.get("caption")),
        "output": _clean_output(data.get("output")),
        "prompts": _clean_prompts(data.get("prompts")),
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        items = _read()
        items.append(profile)
        _write(items)
    return profile


def update(profile_id: str, data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    with _lock:
        items = _read()
        for profile in items:
            if profile.get("id") != profile_id:
                continue
            if "name" in data:
                profile["name"] = _clean_name(data.get("name"))
            if "caption" in data:
                profile["caption"] = _clean_caption(data.get("caption"))
            if "output" in data:
                profile["output"] = _clean_output(data.get("output"))
            if "prompts" in data:
                profile["prompts"] = _clean_prompts(data.get("prompts"))
            profile["updated_at"] = time.time()
            _write(items)
            return profile
    raise ProfileError("profile not found")


def delete(profile_id: str) -> bool:
    with _lock:
        items = _read()
        kept = [p for p in items if p.get("id") != profile_id]
        if len(kept) == len(items):
            return False
        _write(kept)
    return True
