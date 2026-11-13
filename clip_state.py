"""Per-clip review state for the Clip Gallery: posted-on platforms / archived.

The gallery is derived from the job directories on disk, so a clip has no row
of its own to write to. This keeps a small JSON sidecar in ``Storage`` keyed by
``<job_id>:<index>``: it survives a re-render of the same clip (which only
changes the filename), costs one file read per gallery page, and never touches
the media. Deleting a job leaves a stale key behind, which is harmless and is
pruned by :func:`prune` when the gallery scans.

A clip is posted per platform (this build uses Facebook and YouTube), not as a
single switch: the same clip can be out on one and not the other. ``used`` is
kept as the derived "on at least one platform" flag, so older state and the
Used tab keep working.
"""
import json
import os
import threading
import time

import storage
from jsonfile import write_json_atomic

_INDEX_FILE = "clip_state.json"

# The platforms this build posts to, in display order.
PLATFORMS = ("facebook", "youtube")

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


def _platform_flags(entry):
    """The two platform booleans stored on an entry (missing = not posted)."""
    raw = entry.get("platforms")
    if not isinstance(raw, dict):
        raw = {}
    return {name: bool(raw.get(name)) for name in PLATFORMS}


def _public(entry):
    entry = entry or {}
    platforms = _platform_flags(entry)
    times = entry.get("platform_times")
    times = times if isinstance(times, dict) else {}
    return {
        # Derived, so a platform mark or an older plain "used" both read used.
        "used": bool(entry.get("used")) or any(platforms.values()),
        "archived": bool(entry.get("archived")),
        "used_at": entry.get("used_at"),
        "archived_at": entry.get("archived_at"),
        "platforms": platforms,
        "platform_times": {k: times.get(k) for k in PLATFORMS if times.get(k)},
    }


def flags(job_id, index):
    """A clip's review state, with per-platform posted marks."""
    return _public(_read().get(_key(job_id, index)))


def snapshot():
    """Every stored entry, keyed by ``<job_id>:<index>`` (one file read)."""
    with _lock:
        data = _read()
    return {key: _public(entry) for key, entry in data.items()}


def set_flags(job_id, index, used=None, archived=None, platforms=None):
    """Set only the flags passed; returns the stored entry.

    ``platforms`` is a partial ``{"facebook": bool, "youtube": bool}`` patch.
    Posting to any platform makes the clip "used"; clearing the last one makes
    it unused again (a legacy plain ``used`` is converted on the first toggle).
    """
    with _lock:
        data = _read()
        key = _key(job_id, index)
        entry = dict(data.get(key) or {})
        now = time.time()

        if platforms is not None:
            current = _platform_flags(entry)
            times = dict(entry.get("platform_times") or {})
            changed = False
            for name in PLATFORMS:
                if name not in platforms:
                    continue
                on = bool(platforms[name])
                current[name] = on
                if on:
                    times.setdefault(name, now)
                else:
                    times.pop(name, None)
                changed = True
            if changed:
                fired = any(current.values())
                if fired:
                    entry["platforms"] = current
                    entry["platform_times"] = times
                    entry["used"] = True
                    entry.setdefault("used_at", now)
                else:
                    entry.pop("platforms", None)
                    entry.pop("platform_times", None)
                    entry.pop("used", None)
                    entry.pop("used_at", None)

        if used is not None:
            if bool(used):
                entry["used"] = True
                entry.setdefault("used_at", now)
            else:
                entry.pop("used", None)
                entry.pop("used_at", None)
                # A plain "unused" is an explicit "not posted anywhere".
                entry.pop("platforms", None)
                entry.pop("platform_times", None)

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
        return _public(entry)


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
            if not _public(entry)["used"] or entry.get("archived"):
                continue
            if wanted is not None and key not in wanted:
                continue
            entry["archived"] = True
            entry["archived_at"] = now
            archived += 1
        if archived:
            _write(data)
    return archived


def forget_job(job_id):
    """Drop every entry of a job whose directory was deleted (cancel)."""
    prefix = f"{job_id}:"
    with _lock:
        data = _read()
        kept = {k: v for k, v in data.items() if not k.startswith(prefix)}
        if len(kept) != len(data):
            _write(kept)
        return len(data) - len(kept)


def forget(job_id, index):
    """Drop one clip's entry (the clip file was deleted from the gallery)."""
    with _lock:
        data = _read()
        if data.pop(_key(job_id, index), None) is None:
            return False
        _write(data)
        return True


def prune(known_keys):
    """Drop entries whose job/clip no longer exists (called on gallery scans)."""
    known = {_key(j, i) for j, i in known_keys}
    with _lock:
        data = _read()
        kept = {k: v for k, v in data.items() if k in known}
        if len(kept) != len(data):
            _write(kept)
    return len(data) - len(kept)
