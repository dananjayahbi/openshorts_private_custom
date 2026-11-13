"""LLM routing: up to five providers tried in order.

The moment picker speaks two protocols:

* ``gemini`` — Google's SDK with a response schema (the historical path), and
* ``openai`` — any server that implements ``POST {base_url}/chat/completions``
  (OpenAI, OpenRouter, Groq, DeepSeek, Ollama, LM Studio, vLLM, llama.cpp,
  LocalAI).

Settings stores a five-slot chain. A call tries slot 1, and if it fails for any
reason — connection refused, quota, a 5xx, a model that returned malformed
JSON — it moves to slot 2, then 3, and so on. It is not necessary to fill all
five: one working level is a complete configuration.

The chain lives in ``Storage/settings.json`` so an MCP/agent job and the batch
queue use the same providers as a dashboard submission. When the file has no
levels, the old environment configuration is still honoured (``LLM_BASE_URL`` /
``GEMINI_API_KEY``) and behaves as a one-level chain.

What stays on Gemini, because it needs a model that can look at frames or a
video file: the layout picker (``layout_picker.py``), the on-screen content
detector (``screencast_layout.py``), burned-in subtitle detection
(``burned_subtitles.py``), hook grounding (``hook_grounding.py``) and the
silent-video path (``main.get_visual_clips``). ``gemini_key()`` / ``gemini_model()``
let those use a Gemini level from the chain instead of only the environment.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Optional, Tuple, Type

import httpx
from pydantic import BaseModel

import settings_store

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_TIMEOUT = 600.0  # local models on CPU are slow; a scoring batch can take minutes
MAX_LEVELS = 5

_PROVIDERS = ("gemini", "openai")
_OPENAI_ALIASES = ("openai", "ollama", "local", "openai-compatible")


# --- legacy environment surface (kept: /api/config, env-only installs) ------

def provider() -> str:
    """``"openai"`` when a compatible endpoint is configured, else ``"gemini"``."""
    explicit = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if explicit in _OPENAI_ALIASES:
        return "openai"
    if explicit == "gemini":
        return "gemini"
    return "openai" if base_url() else "gemini"


def base_url() -> str:
    return (os.environ.get("LLM_BASE_URL") or "").strip().rstrip("/")


def model_name() -> str:
    return (os.environ.get("LLM_MODEL") or "").strip() or DEFAULT_MODEL


def _env_timeout() -> float:
    try:
        return float(os.environ.get("LLM_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


# --- levels -----------------------------------------------------------------

def _norm_level(raw: dict, index: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    provider_name = str(raw.get("provider") or "").strip().lower()
    if provider_name not in _PROVIDERS:
        provider_name = "openai"
    try:
        timeout = float(raw.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = min(max(timeout, 5.0), 3600.0)
    return {
        "level": index + 1,
        "enabled": bool(raw.get("enabled", False)),
        "provider": provider_name,
        "model": str(raw.get("model") or "").strip(),
        "base_url": str(raw.get("base_url") or raw.get("baseUrl") or "").strip().rstrip("/"),
        "api_key": str(raw.get("api_key") or raw.get("apiKey") or "").strip(),
        "timeout": timeout,
    }


def _stored_raw() -> Optional[list]:
    section = settings_store.section("llm") or {}
    levels = section.get("levels") if isinstance(section, dict) else None
    return levels if isinstance(levels, list) else None


def _env_levels() -> list:
    if provider() == "openai" and base_url():
        return [{
            "level": 1, "enabled": True, "provider": "openai",
            "model": model_name(), "base_url": base_url(),
            "api_key": (os.environ.get("LLM_API_KEY") or "").strip(),
            "timeout": _env_timeout(),
        }]
    return [{
        "level": 1, "enabled": True, "provider": "gemini",
        "model": (os.environ.get("GEMINI_MODEL") or "").strip(),
        "base_url": "", "api_key": "", "timeout": _env_timeout(),
    }]


def _enabled_levels() -> list:
    raw = _stored_raw()
    all_levels = ([_norm_level(item, i) for i, item in enumerate(raw[:MAX_LEVELS])]
                  if raw is not None else _env_levels())
    return [lv for lv in all_levels if lv["enabled"]]


def levels() -> list:
    """The configured chain, in fallback order (enabled levels only)."""
    return _enabled_levels()


def _level_model(level: dict) -> str:
    if level["model"]:
        return level["model"]
    if level["provider"] == "gemini":
        return (os.environ.get("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL
    return model_name()


def _level_key(level: dict) -> str:
    if level["provider"] == "gemini":
        return level["api_key"] or (os.environ.get("GEMINI_API_KEY") or "").strip()
    return level["api_key"] or (os.environ.get("LLM_API_KEY") or "").strip()


def usable(level: dict) -> bool:
    if level["provider"] == "openai":
        return bool(level["base_url"])
    return bool(_level_key(level))


def configured() -> bool:
    """True when at least one level can actually answer a call."""
    return any(usable(lv) for lv in levels())


def active() -> bool:
    """True when the chain has an OpenAI-compatible level (batch sizing)."""
    return any(lv["provider"] == "openai" and usable(lv) for lv in levels())


def gemini_key() -> str:
    """A key for the frame/vision stages: the first Gemini level, else the env."""
    for level in levels():
        if level["provider"] == "gemini" and _level_key(level):
            return _level_key(level)
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def gemini_model() -> str:
    for level in levels():
        if level["provider"] == "gemini":
            return _level_model(level)
    return (os.environ.get("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL


def primary() -> Optional[dict]:
    for level in levels():
        if usable(level):
            return level
    return None


def primary_model_name() -> str:
    level = primary()
    return _level_model(level) if level else ""


def describe() -> Optional[dict]:
    """What ``/api/config`` tells the dashboard; keys are never included."""
    working = [lv for lv in levels() if usable(lv)]
    if not working:
        return None
    first = working[0]
    return {
        "provider": first["provider"],
        "model": _level_model(first),
        "baseUrl": first["base_url"],
        "configured": True,
        "levels": [_public_level(lv) for lv in levels()],
    }


def _public_level(level: dict) -> dict:
    return {
        "level": level["level"],
        "provider": level["provider"],
        "model": _level_model(level),
        "baseUrl": level["base_url"],
        "configured": usable(level),
        "apiKeySet": bool(_level_key(level)),
        "apiKeyFromEnv": bool(
            not level["api_key"] and level["provider"] == "gemini"
            and os.environ.get("GEMINI_API_KEY")),
    }


def levels_for_ui() -> list:
    """Exactly five slots for Settings; a blank OpenAI-compatible slot on first run."""
    raw = _stored_raw()
    if raw is None:
        blanks = [
            {"level": i + 1, "enabled": False, "provider": "openai", "model": "",
             "base_url": "", "api_key": "", "timeout": DEFAULT_TIMEOUT}
            for i in range(MAX_LEVELS)
        ]
        # No provider is privileged: slot 1 starts as a blank OpenAI-compatible
        # level. A legacy LLM_BASE_URL in the environment is prefilled because
        # it is what the pipeline already uses; GEMINI_API_KEY is NOT turned
        # into a Gemini slot (a text-only install usually does not have one).
        first = dict(blanks[0])
        first["enabled"] = True
        if base_url():
            first.update({
                "provider": "openai",
                "model": model_name(),
                "base_url": base_url(),
                "api_key": (os.environ.get("LLM_API_KEY") or "").strip(),
            })
        blanks[0] = first
        return [_ui_level(lv) for lv in blanks]
    levels_out = [_norm_level(item, i) for i, item in enumerate((raw or [])[:MAX_LEVELS])]
    while len(levels_out) < MAX_LEVELS:
        levels_out.append({
            "level": len(levels_out) + 1, "enabled": False, "provider": "openai",
            "model": "", "base_url": "", "api_key": "", "timeout": DEFAULT_TIMEOUT,
        })
    return [_ui_level(lv) for lv in levels_out]


def _ui_level(level: dict) -> dict:
    out = dict(level)
    # Keep the stored value (empty means "provider default") and expose what
    # the runtime would use, so the field is not silently filled with a model
    # the user never chose.
    out["resolvedModel"] = _level_model(level)
    out["configured"] = usable(level)
    out["apiKeyFromEnv"] = bool(
        not level["api_key"] and level["provider"] == "gemini"
        and os.environ.get("GEMINI_API_KEY"))
    return out


def save_levels(raw_levels: list) -> list:
    """Validate and persist the chain. Raises ``ValueError`` with a clear reason."""
    if not isinstance(raw_levels, list):
        raise ValueError("levels must be a list")
    if len(raw_levels) > MAX_LEVELS:
        raise ValueError(f"at most {MAX_LEVELS} levels")
    out = []
    for index, item in enumerate(raw_levels):
        level = _norm_level(item, index)
        if level["provider"] not in _PROVIDERS:
            raise ValueError(f"level {index + 1}: unknown provider")
        if level["enabled"] and level["provider"] == "openai" and not level["base_url"]:
            raise ValueError(f"level {index + 1}: an OpenAI-compatible level needs a base URL")
        if not (5.0 <= level["timeout"] <= 3600.0):
            raise ValueError(f"level {index + 1}: timeout must be 5-3600 seconds")
        out.append(level)
    settings_store.set_section("llm", {"levels": out})
    return levels_for_ui()


# --- calls ------------------------------------------------------------------

def _headers(level: dict) -> dict:
    # Ollama ignores the key but the OpenAI client convention (and vLLM with
    # --api-key) wants the header present; "ollama" is the documented placeholder.
    key = _level_key(level) or "ollama"
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _client(**kwargs) -> httpx.Client:
    """Factory so tests can swap in ``httpx.MockTransport``."""
    return httpx.Client(**kwargs)


def _response_formats(schema: Type[BaseModel]):
    name = getattr(schema, "__name__", "response").lower()
    yield {"type": "json_schema",
           "json_schema": {"name": name, "schema": schema.model_json_schema()}}
    yield {"type": "json_object"}
    yield None


def _is_format_rejection(resp: httpx.Response) -> bool:
    if resp.status_code not in (400, 422):
        return False
    body = resp.text.lower()
    return "response_format" in body or "json_schema" in body or "json_object" in body \
        or "format" in body


def _generate_openai(level: dict, prompt: str, schema: Type[BaseModel],
                     model: Optional[str] = None,
                     images: Optional[list] = None) -> Tuple[dict, Optional[dict]]:
    import gemini_worker  # local import: keeps this module free of the google SDK

    url = f"{level['base_url']}/chat/completions"
    model = model or _level_model(level)
    if images:
        content = [{"type": "text", "text": prompt}]
        for image in images:
            encoded = base64.b64encode(image).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            })
        messages = [{"role": "user", "content": content}]
    else:
        messages = [
            {"role": "system", "content": "You answer with a single JSON object and nothing else."},
            {"role": "user", "content": prompt},
        ]
    last_rejection: Optional[str] = None
    with _client(timeout=level["timeout"]) as client:
        for fmt in _response_formats(schema):
            body = {"model": model, "messages": messages, "temperature": 0.2, "stream": False}
            if fmt is not None:
                body["response_format"] = fmt
            resp = client.post(url, json=body, headers=_headers(level))
            if fmt is not None and _is_format_rejection(resp):
                # The server does not know this response_format flavour; the
                # next loop iteration asks for a looser one.
                last_rejection = resp.text[:200]
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"LLM server {resp.status_code} from {url}: {resp.text[:300]}")
            data = resp.json()
            break
        else:
            raise RuntimeError(
                f"LLM server rejected every response_format variant: {last_rejection}")

    choices = data.get("choices") or []
    text = ""
    if choices:
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
        if isinstance(text, list):  # some servers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    parsed = gemini_worker._parse_json_response_text(text)
    # Validate against the same schema Gemini enforces server-side, so a
    # local model that drops a field fails here with a readable error
    # (retried by the caller) instead of deep inside the clip pipeline.
    validated = schema.model_validate(parsed).model_dump()

    usage = data.get("usage") or {}
    cost = {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "thinking_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0,
        "model": model,
        "price_estimated": False,
        "local": True,
    }
    return validated, cost


def _generate_gemini(level: dict, prompt: str, schema: Type[BaseModel],
                     model: Optional[str] = None,
                     images: Optional[list] = None) -> Tuple[dict, Optional[dict]]:
    from google import genai
    from google.genai import types as genai_types

    import gemini_worker

    key = _level_key(level)
    if not key:
        raise RuntimeError(
            "Gemini level has no API key (set one here or GEMINI_API_KEY)")
    model = model or _level_model(level)
    client = genai.Client(api_key=key)
    contents = prompt
    if images:
        parts = [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg")
                 for b in images]
        contents = parts + [prompt]
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    gemini_worker.raise_if_blocked(response)
    parsed_obj = getattr(response, "parsed", None)
    if parsed_obj is not None:
        payload = parsed_obj.model_dump() if hasattr(parsed_obj, "model_dump") else parsed_obj
    else:
        payload = gemini_worker._parse_json_response_text(
            gemini_worker._get_response_text(response))
    validated = schema.model_validate(payload).model_dump()
    return validated, gemini_worker._calculate_cost_analysis(response, model)


def _call_level(level: dict, prompt: str, schema: Type[BaseModel],
                model: Optional[str] = None,
                images: Optional[list] = None) -> Tuple[dict, Optional[dict]]:
    if level["provider"] == "gemini":
        return _generate_gemini(level, prompt, schema, model, images)
    return _generate_openai(level, prompt, schema, model, images)


def generate_json(prompt: str, schema: Type[BaseModel], model: Optional[str] = None,
                  ) -> Tuple[dict, Optional[dict]]:
    """One schema-enforced call, falling through the chain until one answers.

    Returns ``(parsed_dict, cost_analysis)`` in the same shape for every
    provider. Raises the last provider's error when every level failed; the
    retry policy (3 attempts with backoff) lives in ``main._run_gemini_stage``.
    """
    levels_to_try = [lv for lv in levels() if usable(lv)]
    if not levels_to_try:
        raise RuntimeError(
            "No AI provider is configured. Add a level in Settings "
            "(or set GEMINI_API_KEY or LLM_BASE_URL).")
    last: Optional[BaseException] = None
    for index, level in enumerate(levels_to_try, 1):
        try:
            return _call_level(level, prompt, schema, model)
        except BaseException as e:  # noqa: BLE001 - any provider failure falls through
            last = e
            if index < len(levels_to_try):
                print(f"[llm] level {index} ({level['provider']} · "
                      f"{_level_model(level)}) failed: {type(e).__name__}: "
                      f"{str(e)[:180]} — falling back to level {index + 1}")
    assert last is not None
    raise last


def vision_available() -> bool:
    """True when at least one configured level can accept images.

    Both supported protocols carry stills (Gemini parts, OpenAI ``image_url``
    data URLs), so this is the same predicate as ``configured()``. The
    frame-based stages call it instead of checking for a Gemini key.
    """
    return any(usable(lv) for lv in levels())


def generate_vision_json(prompt: str, schema: Type[BaseModel],
                         images: list, model: Optional[str] = None) -> dict:
    """Ask each level in order to answer from JPEG stills; returns the payload.

    Used by the layout picker, the on-screen content detector, burned-in
    subtitle detection and hook grounding. A provider that cannot see images
    fails that call and the next level gets a turn — no stage is tied to one
    vendor.
    """
    images = [b for b in (images or []) if b]
    if not images:
        raise RuntimeError("No frames to analyze.")
    levels_to_try = [lv for lv in levels() if usable(lv)]
    if not levels_to_try:
        raise RuntimeError(
            "No AI provider is configured. Add a level in Settings "
            "(or set GEMINI_API_KEY or LLM_BASE_URL).")
    last: Optional[BaseException] = None
    for index, level in enumerate(levels_to_try, 1):
        try:
            parsed, _ = _call_level(level, prompt, schema, model, images)
            return parsed
        except BaseException as e:  # noqa: BLE001
            last = e
            if index < len(levels_to_try):
                print(f"[llm] vision level {index} ({level['provider']} · "
                      f"{_level_model(level)}) failed: {type(e).__name__}: "
                      f"{str(e)[:180]} — falling back to level {index + 1}")
    assert last is not None
    raise last


def test_level(raw_level: dict) -> dict:
    """A tiny round-trip used by the Settings page's Test button."""
    level = _norm_level(raw_level, 0)
    level["enabled"] = True
    started = time.monotonic()

    class Reachability(BaseModel):
        ok: bool

    try:
        _call_level(
            level,
            'Reply with exactly this JSON: {"ok": true}',
            Reachability,
        )
        return {
            "ok": True,
            "provider": level["provider"],
            "model": _level_model(level),
            "latencyMs": int((time.monotonic() - started) * 1000),
        }
    except BaseException as e:  # noqa: BLE001 - the error is the result
        return {
            "ok": False,
            "provider": level["provider"],
            "model": _level_model(level),
            "error": f"{type(e).__name__}: {str(e)[:400]}",
            "latencyMs": int((time.monotonic() - started) * 1000),
        }
