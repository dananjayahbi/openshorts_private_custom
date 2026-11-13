"""Server-side settings that outlive a browser profile.

The app's keys used to live only in ``localStorage``, which meant a job started
by an agent (MCP) or by the batch queue could not use them. This is the one
small JSON file the server owns instead::

    Storage/settings.json
    {
      "llm":     {"levels": [ ... five provider slots ... ]},
      "prompts": {"score": "...", ...}         # only edited prompts are stored
    }

``OPENSHORTS_SETTINGS`` overrides the path (the test suite points it at a temp
file so a developer's real chain never changes a test result).

Writes are locked and atomic: the pipeline subprocess reads the same file while
the dashboard saves, and a half-written document would silently fall back to
defaults.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

import storage
from jsonfile import write_json_atomic

_lock = threading.RLock()
_FILE = "settings.json"


def path() -> str:
    """Resolved at call time: tests move it, and Storage can be relocated."""
    override = (os.environ.get("OPENSHORTS_SETTINGS") or "").strip()
    if override:
        return override
    return os.path.join(storage.STORAGE_DIR, _FILE)


def read() -> dict:
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write(data: dict) -> None:
    target = path()
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    with _lock:
        write_json_atomic(target, data)


def section(name: str, default: Any = None) -> Any:
    """One top-level section; ``default`` when it was never written."""
    value = read().get(name)
    return default if value is None else value


def set_section(name: str, value: Any) -> None:
    with _lock:
        data = read()
        data[name] = value
        write(data)
