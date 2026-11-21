"""Content Planner: which clip is planned for which day.

The Clip Gallery is the library; the planner is the publishing calendar. This
module stores the calendar in the small state tree (``content_plan.json`` next
to settings and clip flags), so unplugging the media drive never takes the plan
with it. A day holds a list of clip references (``job_id`` + ``index``); the
clip metadata, poster and platform marks are read from the media tree when the
calendar is served, so the plan never goes stale after a re-render.

Stored shape::

    {"days": {"2026-11-21": [{"job_id": "...", "index": 0, "added_at": ...}]}}

The same clip may appear on more than one day (a repost or a cross-post), but
not twice on the same day. A reference whose clip is gone is skipped when the
calendar is read; :func:`prune` removes those refs for good when a caller has a
complete known set.
"""
import json
import os
import re
import threading
import time
from datetime import date

import storage
from jsonfile import write_json_atomic

PLAN_FILE = "content_plan.json"
MAX_PER_DAY = 60

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JOB_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

_lock = threading.RLock()


def plan_file():
    """Resolved at call time: tests move ``storage.STORAGE_DIR``."""
    return os.path.join(storage.STORAGE_DIR, PLAN_FILE)


def valid_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def valid_ref(job_id, index):
    try:
        index = int(index)
    except (TypeError, ValueError):
        return False
    return bool(_JOB_RE.match(str(job_id or ""))) and index >= 0


def _read():
    try:
        with open(plan_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(days):
    os.makedirs(storage.STORAGE_DIR, exist_ok=True)
    write_json_atomic(plan_file(), {"days": days})


def _clean(days):
    """Drop malformed days/refs, de-duplicate a day, and cap its length."""
    out = {}
    if not isinstance(days, dict):
        return out
    for day, refs in days.items():
        if not valid_date(day) or not isinstance(refs, list):
            continue
        seen = set()
        kept = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            job_id = str(ref.get("job_id") or "")
            try:
                index = int(ref.get("index"))
            except (TypeError, ValueError):
                continue
            if not valid_ref(job_id, index):
                continue
            key = f"{job_id}:{index}"
            if key in seen:
                continue
            seen.add(key)
            kept.append({
                "job_id": job_id,
                "index": index,
                "added_at": ref.get("added_at") or time.time(),
            })
        if kept:
            out[day] = kept[:MAX_PER_DAY]
    return out


def all_days():
    """Every planned day, cleaned and keyed by ``YYYY-MM-DD``."""
    with _lock:
        return _clean(_read().get("days"))


def days_between(start="", end=""):
    """The planned days inside an inclusive ``YYYY-MM-DD`` window."""
    days = all_days()
    if not start and not end:
        return days
    try:
        lo = date.fromisoformat(start) if start else date.min
        hi = date.fromisoformat(end) if end else date.max
    except ValueError:
        return {}
    return {day: refs for day, refs in days.items()
            if lo <= date.fromisoformat(day) <= hi}


def add(day, job_id, index):
    """Put a clip on a day. A duplicate on the same day is a no-op."""
    if not valid_date(day) or not valid_ref(job_id, index):
        raise ValueError("Invalid day or clip reference")
    index = int(index)
    with _lock:
        days = _clean(_read().get("days"))
        refs = days.get(day, [])
        if any(ref["job_id"] == job_id and ref["index"] == index for ref in refs):
            return {"added": False, "duplicate": True, "date": day}
        if len(refs) >= MAX_PER_DAY:
            raise ValueError(f"A day holds at most {MAX_PER_DAY} clips")
        refs = refs + [{"job_id": job_id, "index": index, "added_at": time.time()}]
        days[day] = refs
        _write(days)
        return {"added": True, "duplicate": False, "date": day}


def remove(day, job_id, index):
    """Take one clip off a day. Returns whether a ref was removed."""
    if not valid_date(day) or not valid_ref(job_id, index):
        raise ValueError("Invalid day or clip reference")
    index = int(index)
    with _lock:
        days = _clean(_read().get("days"))
        refs = days.get(day) or []
        kept = [ref for ref in refs
                if not (ref["job_id"] == job_id and ref["index"] == index)]
        if len(kept) == len(refs):
            return {"removed": False, "date": day}
        if kept:
            days[day] = kept
        else:
            days.pop(day, None)
        _write(days)
        return {"removed": True, "date": day}


def move(from_day, to_day, job_id, index):
    """Move a ref between days (drag/drop). Adding to the target is a no-op
    when it is already there; the source ref is removed either way."""
    if (not valid_date(from_day) or not valid_date(to_day)
            or not valid_ref(job_id, index)):
        raise ValueError("Invalid day or clip reference")
    index = int(index)
    with _lock:
        days = _clean(_read().get("days"))
        source = days.get(from_day) or []
        if not any(ref["job_id"] == job_id and ref["index"] == index
                   for ref in source):
            return {"moved": False, "from": from_day, "to": to_day}
        days[from_day] = [ref for ref in source
                          if not (ref["job_id"] == job_id and ref["index"] == index)]
        if not days[from_day]:
            days.pop(from_day, None)
        target = days.get(to_day) or []
        if not any(ref["job_id"] == job_id and ref["index"] == index
                   for ref in target):
            if len(target) >= MAX_PER_DAY:
                raise ValueError(f"A day holds at most {MAX_PER_DAY} clips")
            target = target + [{"job_id": job_id, "index": index,
                                "added_at": time.time()}]
            days[to_day] = target
        _write(days)
        return {"moved": True, "from": from_day, "to": to_day}


def prune(known_refs):
    """Drop planned refs whose clip no longer exists (only pass a full set)."""
    known = {f"{job_id}:{int(index)}" for job_id, index in known_refs}
    with _lock:
        days = _clean(_read().get("days"))
        changed = False
        for day, refs in list(days.items()):
            kept = [ref for ref in refs
                    if f"{ref['job_id']}:{ref['index']}" in known]
            if len(kept) != len(refs):
                changed = True
                if kept:
                    days[day] = kept
                else:
                    days.pop(day, None)
        if changed:
            _write(days)
    return sum(len(refs) for refs in days.values())
