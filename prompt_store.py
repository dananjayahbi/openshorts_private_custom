"""Editable copies of the AI instruction blocks ("system prompts").

Every model call used to format a module constant. This registry keeps those
constants as the defaults and lets the Settings page store an edited copy in
``Storage/settings.json`` without touching Python::

    prompt_store.render("score", video_duration=..., language=..., windows_json=...)

Three layers, highest wins:

1. ``PROMPT_OVERRIDES_JSON`` in the job environment (a Style Profile's own
   prompts, handed to the pipeline subprocess by ``/api/process``).
2. ``Storage/settings.json`` → ``prompts`` (the Settings page).
3. The module constant (what shipped).

Only prompts that take named placeholders are formatted; the frame-based ones
(layout, on-screen content, burned-in subtitles) are used verbatim.
"""
from __future__ import annotations

import json
import os
from string import Formatter
from typing import Dict, List, Optional

import settings_store


class PromptError(ValueError):
    """An edited prompt would break a call site (missing/unknown placeholder)."""


# One entry per editable constant. ``module``/``attr`` are imported lazily so
# this module never drags the heavy pipeline into the API process.
SPECS: List[dict] = [
    {
        "id": "score",
        "label": "Moment picker · scoring pass",
        "group": "Clip selection",
        "module": "gemini_worker",
        "attr": "SCORE_PROMPT_TEMPLATE",
        "where": "main.get_viral_clips (pass 1)",
        "placeholders": ["video_duration", "language", "windows_json"],
        "description": (
            "Scores every candidate transcript window 0-100. This is the prompt "
            "that decides which moments are shortlisted before the expensive "
            "detail pass."
        ),
    },
    {
        "id": "detail",
        "label": "Moment picker · detail pass",
        "group": "Clip selection",
        "module": "gemini_worker",
        "attr": "DETAIL_PROMPT_TEMPLATE",
        "where": "main.get_viral_clips (pass 2)",
        "placeholders": ["video_duration", "language", "min_clips", "max_clips",
                         "min_secs", "max_secs", "windows_json"],
        "description": (
            "Turns the shortlist into final clips and writes the hook, YouTube "
            "title and TikTok/Instagram captions."
        ),
    },
    {
        "id": "visual",
        "label": "Silent video · vision picker",
        "group": "Clip selection",
        "module": "gemini_worker",
        "attr": "VISUAL_PROMPT_TEMPLATE",
        "where": "main.get_visual_clips",
        "placeholders": ["video_duration", "language", "min_clips", "max_clips",
                         "min_secs", "max_secs"],
        "description": (
            "Used instead of the transcript picker when a video has no usable "
            "speech: Gemini watches the footage and picks visual moments."
        ),
    },
    {
        "id": "layout",
        "label": "Layout picker",
        "group": "Framing",
        "module": "gemini_worker",
        "attr": "LAYOUT_CHOICE_PROMPT",
        "where": "layout_picker.pick",
        "placeholders": [],
        "description": (
            "Chooses none / screencast / split per video from sampled frames. "
            "The comment above the default reports its measured accuracy; "
            "reword it only if you are willing to re-measure."
        ),
    },
    {
        "id": "screen_content",
        "label": "On-screen content detector",
        "group": "Framing",
        "module": "gemini_worker",
        "attr": "SHOT_CONTENT_PROMPT",
        "where": "screencast_layout.detect_content_ranges",
        "placeholders": [],
        "description": (
            "Classifies each shot as screen / beside / camera and finds the "
            "readable focus box for the re-frame."
        ),
    },
    {
        "id": "hook_grounding",
        "label": "Hook grounding",
        "group": "Copywriting",
        "module": "gemini_worker",
        "attr": "GROUNDED_HOOK_PROMPT",
        "where": "hook_grounding.reground",
        "placeholders": ["language", "current_hook", "current_title", "transcript"],
        "description": (
            "Rewrites the hook and title from the clip's frames when the meaning "
            "is on screen (screencasts, slides, demos)."
        ),
    },
    {
        "id": "burned_subtitles",
        "label": "Burned-in subtitle detector",
        "group": "Captions",
        "module": "burned_subtitles",
        "attr": "PROMPT",
        "where": "burned_subtitles.detect",
        "placeholders": [],
        "description": (
            "Finds subtitles already burned into the source so the clip is "
            "cropped above them instead of covering them."
        ),
    },
]

_SPEC_BY_ID: Dict[str, dict] = {s["id"]: s for s in SPECS}


def _default(spec: dict) -> str:
    import importlib

    module = importlib.import_module(spec["module"])
    return str(getattr(module, spec["attr"]))


def _fields(template: str) -> List[str]:
    try:
        return [name for _, name, _, _ in Formatter().parse(template) if name]
    except ValueError as e:
        raise PromptError(f"malformed braces: {e}") from e


def validate(prompt_id: str, template: str) -> str:
    """Raise :class:`PromptError` unless the edit keeps the call contract."""
    spec = _SPEC_BY_ID.get(prompt_id)
    if spec is None:
        raise PromptError(f"unknown prompt: {prompt_id}")
    text = str(template or "")
    if not text.strip():
        raise PromptError("the prompt cannot be empty (reset it instead)")
    fields = _fields(text)
    missing = [p for p in spec["placeholders"] if p not in fields]
    if missing:
        raise PromptError(
            "missing placeholder(s): " + ", ".join("{" + m + "}" for m in missing))
    unknown = [f for f in fields if f not in spec["placeholders"]]
    if unknown:
        raise PromptError(
            "unknown placeholder(s): " + ", ".join("{" + u + "}" for u in unknown)
            + ("" if spec["placeholders"] else " (this prompt takes no variables)"))
    return text


def _stored() -> Dict[str, str]:
    data = settings_store.section("prompts", {}) or {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in _SPEC_BY_ID and v}


def _job_overrides() -> Dict[str, str]:
    raw = os.environ.get("PROMPT_OVERRIDES_JSON") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in _SPEC_BY_ID and v}


def effective(prompt_id: str) -> str:
    if prompt_id not in _SPEC_BY_ID:
        raise PromptError(f"unknown prompt: {prompt_id}")
    job = _job_overrides().get(prompt_id)
    if job:
        return job
    stored = _stored().get(prompt_id)
    if stored:
        return stored
    return _default(_SPEC_BY_ID[prompt_id])


def text(prompt_id: str) -> str:
    """The instruction block, no formatting (frame-based prompts)."""
    return effective(prompt_id)


def render(prompt_id: str, **values) -> str:
    """Format with the call site's values; the same string the model receives."""
    spec = _SPEC_BY_ID.get(prompt_id)
    if spec is None:
        raise PromptError(f"unknown prompt: {prompt_id}")
    template = effective(prompt_id)
    if not spec["placeholders"]:
        return template
    try:
        return template.format(**values)
    except KeyError as e:
        raise PromptError(f"{prompt_id} needs a value for {e}") from e


def set_overrides(mapping: Dict[str, str]) -> List[str]:
    """Save edited prompts. An empty value removes the override (back to default)."""
    current = dict(_stored())
    for prompt_id, template in (mapping or {}).items():
        if prompt_id not in _SPEC_BY_ID:
            raise PromptError(f"unknown prompt: {prompt_id}")
        if template is None or not str(template).strip():
            current.pop(prompt_id, None)
            continue
        current[prompt_id] = validate(prompt_id, template)
    settings_store.set_section("prompts", current)
    return sorted(current)


def reset(prompt_ids: Optional[List[str]] = None) -> List[str]:
    """Drop overrides for every prompt, or only the ids given."""
    current = dict(_stored())
    if prompt_ids is None:
        current = {}
    else:
        for prompt_id in prompt_ids:
            current.pop(prompt_id, None)
    settings_store.set_section("prompts", current)
    return sorted(current)


def all_prompts() -> List[dict]:
    """Everything Settings needs: effective text, the default, and metadata."""
    stored = _stored()
    out = []
    for spec in SPECS:
        default = _default(spec)
        out.append({
            "id": spec["id"],
            "label": spec["label"],
            "group": spec["group"],
            "where": spec["where"],
            "description": spec["description"],
            "placeholders": spec["placeholders"],
            "template": stored.get(spec["id"]) or default,
            "default": default,
            "overridden": spec["id"] in stored,
        })
    return out
