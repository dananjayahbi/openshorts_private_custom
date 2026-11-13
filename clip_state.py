"""Per-clip review state for the Clip Gallery: used / archived.

The gallery is derived from the job directories on disk, so a clip has no row
of its own to write to. This keeps a small JSON sidecar in ``Storage`` keyed by
``<job_id>:<index>``: it survives a re-render of the same clip (which only
changes the filename), costs one file read per gallery page, and never touches
the media. Deleting a job leaves a stale key behind, which is harmless and is
pruned by :func:`prune` when the gallery scans.
"""
import json
import os
import threading
import time

import storage
from jsonfile import write_json_atomic

_INDEX_FILE = "clip_state.json"

_lock = threading.RLock()


def state_file():
    """Resolved at call time: tests move ``storage.STORAGE_DIR``."""
    return os.path.join(storage.STORAGE_DIR, _INDEX_FILE)


def _key(job_id, index):
    return f"{job_id}:{int(index)}"


def _read():
    path = state_file()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    os.makedirs(storage.STORAGE_DIR, exist_ok=True)
    write_json_atomic(state_file(), data)


def flags(job_id, index):
    """``{"used": bool, "archived": bool}`` (plus timestamps when set)."""
    entry = _read().get(_key(job_id, index)) or {}
    return {
        "used": bool(entry.get("used")),
        "archived": bool(entry.get("archived")),
        "used_at": entry.get("used_at"),
        "archived_at": entry.get("archived_at"),
    }


def snapshot():
    """Every stored entry, keyed by ``<job_id>:<index>`` (one file read)."""
    with _lock:
        data = _read()
    return {
        key: {
            "used": bool(entry.get("used")),
            "archived": bool(entry.get("archived")),
            "used_at": entry.get("used_at"),
            "archived_at": entry.get("archived_at"),
        }
        for key, entry in data.items()
    }


def set_flags(job_id, index, used=None, archived=None):
    """Set only the flags passed; returns the stored entry."""
    with _lock:
        data = _read()
        key = _key(job_id, index)
        entry = dict(data.get(key) or {})
        now = time.time()
        if used is not None:
            if bool(used):
                entry["used"] = True
                entry.setdefault("used_at", now)
            else:
                entry.pop("used", None)
                entry.pop("used_at", None)
        if archived is not None:
            if bool(archived):
                entry["archived"] = True
                entry.setdefault("archived_at", now)
            else:
                entry.pop("archived", None)
                entry.pop("archived_at", None)
        if entry:
            data[key] = entry
        else:
            data.pop(key, None)
        _write(data)
        return {
            "used": bool(entry.get("used")),
            "archived": bool(entry.get("archived")),
            "used_at": entry.get("used_at"),
            "archived_at": entry.get("archived_at"),
        }


def archive_used(keys=None):
    """Archive every clip marked used (or only ``keys`` when given).

    ``keys`` is a list of ``(job_id, index)`` pairs; the gallery passes the
    full set it just scanned so a stray key from a deleted job is ignored.
    """
    now = time.time()
    archived = 0
    with _lock:
        data = _read()
        wanted = {_key(j, i) for j, i in keys} if keys is not None else None
        for key, entry in data.items():
            if not entry.get("used") or entry.get("archived"):
                continue
            if wanted is not None and key not in wanted:
                continue
            entry["archived"] = True
            entry["archived_at"] = now
            archived += 1
        if archived:
            _write(data)
    return archived


def prune(known_keys):
    """Drop entries whose job/clip no longer exists (called on gallery scans)."""
    known = {_key(j, i) for j, i in known_keys}
    with _lock:
        data = _read()
        kept = {k: v for k, v in data.items() if k in known}
        if len(kept) != len(data):
            _write(kept)
    return len(data) - len(kept)
