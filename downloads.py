"""Download Manager: full sources into temp storage, then split into the Collector.

The task behind this page: fetch an hours-long YouTube video once, cut it into
editable chunks (for example 20-minute parts), and put those parts on the
Collector shelf. A queue of links downloads one at a time into
``Storage/downloads/<id>/``; each item keeps its own chunk length, so a 1.5 h
video can be cut into 20-minute parts while the next one uses 1-hour parts.

Nothing here is served over HTTP: these are working files, not media. Splitting
uses ffmpeg's segment muxer with stream copy (fast, keyframe-aligned) and then
hands every part to :func:`collector.add_file`, which is what puts it in the
Collector library with a poster frame and duration. Deleting an item removes the
temp source, never the Collector parts.
"""
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

import storage
from jsonfile import write_json_atomic

DOWNLOADS_DIR = storage.DOWNLOADS_DIR
INDEX_FILE = os.path.join(DOWNLOADS_DIR, "items.json")
CHUNKS_SUBDIR = "chunks"

MIN_CHUNK_SECONDS = 60
MAX_CHUNK_SECONDS = 24 * 60 * 60
DEFAULT_CHUNK_SECONDS = 20 * 60

_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

_lock = threading.RLock()
_download_running = False
_split_running = False
_split_queue = []


def ensure():
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    if not os.path.exists(INDEX_FILE):
        write_json_atomic(INDEX_FILE, [])


def valid_id(item_id) -> bool:
    return isinstance(item_id, str) and bool(_ID_RE.match(item_id))


def _read():
    ensure()
    try:
        with open(INDEX_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(items):
    write_json_atomic(INDEX_FILE, list(items))


def _dir(item_id):
    return os.path.join(DOWNLOADS_DIR, item_id)


def _file_path(item):
    rel = item.get("file")
    if not rel or not isinstance(rel, str) or ".." in rel.split("/"):
        return None
    path = os.path.join(_dir(item["id"]), *rel.split("/"))
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(_dir(item["id"]))]) \
            != os.path.abspath(_dir(item["id"])):
        return None
    return path if os.path.isfile(path) else None


def _dir_bytes(item_id):
    total = 0
    for root, _dirs, files in os.walk(_dir(item_id)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _chunk_count(duration, chunk_seconds):
    try:
        duration = float(duration or 0)
        chunk = int(chunk_seconds or 0)
    except (TypeError, ValueError):
        return None
    if duration <= 0 or chunk <= 0:
        return None
    return max(1, math.ceil(duration / chunk))


def public(item):
    """The API shape: no host paths, plus live progress while downloading."""
    path = _file_path(item)
    expected = item.get("expected_bytes") or None
    downloaded = _dir_bytes(item["id"]) if item.get("state") == "downloading" else (
        item.get("size_bytes") or (os.path.getsize(path) if path else 0))
    progress = None
    if item.get("state") == "downloading" and expected:
        progress = min(99, int(downloaded * 100 / expected))
    elif item.get("state") in ("ready", "done", "splitting"):
        progress = 100
    return {
        "id": item.get("id"),
        "url": item.get("url"),
        "title": item.get("title") or item.get("url") or "Untitled",
        "channel": item.get("channel"),
        "duration": item.get("duration"),
        "state": item.get("state") or "queued",
        "error": item.get("error"),
        "split_error": item.get("split_error"),
        "expected_bytes": expected,
        "downloaded_bytes": downloaded,
        "progress": progress,
        "size_bytes": item.get("size_bytes"),
        "chunk_seconds": item.get("chunk_seconds") or DEFAULT_CHUNK_SECONDS,
        "parts_expected": _chunk_count(item.get("duration"), item.get("chunk_seconds")),
        "parts_done": item.get("parts_done") or 0,
        "collector_ids": item.get("collector_ids") or [],
        "added_at": item.get("added_at"),
        "downloaded_at": item.get("downloaded_at"),
        "split_at": item.get("split_at"),
    }


def list_items():
    with _lock:
        return [public(item) for item in _read()]


def get(item_id):
    if not valid_id(item_id):
        return None
    with _lock:
        for item in _read():
            if item.get("id") == item_id:
                return item
    return None


def get_public(item_id):
    item = get(item_id)
    return public(item) if item else None


def _update(item_id, **fields):
    with _lock:
        items = _read()
        for item in items:
            if item.get("id") == item_id:
                item.update(fields)
                _write(items)
                return item
    return None


# --------------------------------------------------------------------------- #
# Adding links
# --------------------------------------------------------------------------- #
def add_urls(urls):
    """Create one item per link and start the download queue.

    The probe (title/duration/size) runs inside the download worker so a batch
    of links returns immediately; invalid or blocked links end as an error item
    instead of failing the whole batch.
    """
    from security_utils import assert_public_url

    clean = []
    seen = set()
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url or url in seen:
            continue
        assert_public_url(url)  # schemes/loopback/dot-local hosts
        seen.add(url)
        clean.append(url)
    if not clean:
        raise ValueError("Paste at least one video link.")

    created = []
    now = time.time()
    with _lock:
        items = _read()
        for url in clean:
            item = {
                "id": str(uuid.uuid4()),
                "url": url,
                "title": None,
                "channel": None,
                "duration": None,
                "state": "queued",
                "error": None,
                "chunk_seconds": DEFAULT_CHUNK_SECONDS,
                "added_at": now,
            }
            items.append(item)
            created.append(item)
        _write(items)
    _start_downloads()
    return [public(item) for item in created]


def configure(item_id, chunk_seconds):
    item = get(item_id)
    if item is None:
        raise KeyError("not found")
    try:
        seconds = int(float(chunk_seconds))
    except (TypeError, ValueError):
        raise ValueError("Chunk length must be a number of seconds.")
    if not (MIN_CHUNK_SECONDS <= seconds <= MAX_CHUNK_SECONDS):
        raise ValueError(
            f"Chunk length must be between {MIN_CHUNK_SECONDS // 60} and "
            f"{MAX_CHUNK_SECONDS // 60} minutes.")
    if item.get("state") in ("splitting", "split_queued"):
        raise ValueError("This item is already being split.")
    return public(_update(item_id, chunk_seconds=seconds, split_error=None))


def delete(item_id):
    item = get(item_id)
    if item is None:
        return False
    if item.get("state") in ("queued", "downloading", "splitting", "split_queued"):
        raise ValueError("Wait for this item to finish, then delete it.")
    with _lock:
        items = _read()
        keep = [i for i in items if i.get("id") != item_id]
        if len(keep) == len(items):
            return False
        _write(keep)
    shutil.rmtree(_dir(item_id), ignore_errors=True)
    return True


# --------------------------------------------------------------------------- #
# Download queue
# --------------------------------------------------------------------------- #
def _start_downloads():
    global _download_running
    with _lock:
        if _download_running:
            return
        _download_running = True
    threading.Thread(target=_download_loop, daemon=True,
                     name="download-manager").start()


def _download_loop():
    global _download_running
    try:
        while True:
            with _lock:
                pending = next((i for i in _read() if i.get("state") == "queued"), None)
            if pending is None:
                return
            _download_one(pending["id"])
    finally:
        with _lock:
            _download_running = False
            # One more if an item was added as this thread was finishing.
            again = any(i.get("state") == "queued" for i in _read())
        if again:
            _start_downloads()


def _probe_info(url):
    import collector
    return collector._probe_url(url)


def _expected_bytes(info):
    size = info.get("filesize_approx") or info.get("filesize")
    if not size:
        sizes = [f.get("filesize") or 0 for f in (info.get("formats") or [])]
        size = max(sizes) if sizes else 0
    try:
        return int(size) if size else None
    except (TypeError, ValueError):
        return None


def _download_one(item_id):
    item = get(item_id)
    if item is None or not item.get("url"):
        return
    os.makedirs(_dir(item_id), exist_ok=True)
    _update(item_id, state="downloading", error=None)
    try:
        info = _probe_info(item["url"])
        _update(item_id,
                title=info.get("title") or item["url"],
                channel=info.get("channel") or info.get("uploader"),
                duration=float(info["duration"]) if info.get("duration") else None,
                expected_bytes=_expected_bytes(info))
        from main import download_youtube_video
        path, title = download_youtube_video(
            item["url"], _dir(item_id), allow_paid=False)
        if get(item_id) is None:
            # Deleted while downloading: do not leave the file behind.
            shutil.rmtree(_dir(item_id), ignore_errors=True)
            return
        rel = os.path.relpath(path, _dir(item_id)).replace("\\", "/")
        _update(item_id,
                file=rel,
                state="ready",
                error=None,
                title=item.get("title") or title or item["url"],
                size_bytes=os.path.getsize(path) if os.path.exists(path) else None,
                downloaded_at=time.time())
    except Exception as e:
        _update(item_id, state="error", error=(str(e).strip() or "Download failed")[:400])


# --------------------------------------------------------------------------- #
# Splitting into the Collector
# --------------------------------------------------------------------------- #
def _probe_duration(path):
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float((res.stdout or "").strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _thumb(path, dest):
    """Same frame choice as the Collector's own thumbs (30 s in, else middle)."""
    duration = _probe_duration(path) or 0
    at = 30.0 if duration > 30 else max(0.1, duration / 2) if duration else 0.5
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", path,
             "-frames:v", "1", "-vf", "scale=640:-2", "-y", dest],
            check=True, capture_output=True, timeout=60)
    except Exception:
        pass


def start_split(item_ids, chunk_seconds=None):
    """Queue items for splitting; the worker processes them one at a time."""
    if not item_ids:
        return list_items()
    seconds_override = None
    if chunk_seconds is not None:
        try:
            seconds_override = int(float(chunk_seconds))
        except (TypeError, ValueError):
            raise ValueError("Chunk length must be a number of seconds.")
        if not (MIN_CHUNK_SECONDS <= seconds_override <= MAX_CHUNK_SECONDS):
            raise ValueError(
                f"Chunk length must be between {MIN_CHUNK_SECONDS // 60} and "
                f"{MAX_CHUNK_SECONDS // 60} minutes.")
    marked = []
    now = time.time()
    with _lock:
        items = _read()
        wanted = {i for i in item_ids if valid_id(i)}
        for item in items:
            if item.get("id") not in wanted:
                continue
            if item.get("state") != "ready":
                continue
            fields = {"state": "split_queued", "split_error": None, "split_at": now}
            if seconds_override is not None:
                fields["chunk_seconds"] = seconds_override
            item.update(fields)
            marked.append(item["id"])
            if item["id"] not in _split_queue:
                _split_queue.append(item["id"])
        if marked:
            _write(items)
    if marked:
        _start_splits()
    return list_items()


def start_split_all(chunk_overrides=None):
    overrides = {
        str(i.get("id")): i.get("chunk_seconds")
        for i in (chunk_overrides or []) if isinstance(i, dict)
    }
    with _lock:
        ready = [i["id"] for i in _read() if i.get("state") == "ready"]
    if overrides:
        with _lock:
            items = _read()
            for item in items:
                if item.get("id") in overrides and overrides[item["id"]] is not None:
                    try:
                        seconds = int(float(overrides[item["id"]]))
                    except (TypeError, ValueError):
                        continue
                    if MIN_CHUNK_SECONDS <= seconds <= MAX_CHUNK_SECONDS:
                        item["chunk_seconds"] = seconds
            _write(items)
    # Per-item overrides need to land before start_split marks them.
    start_split(ready)
    return list_items()


def _start_splits():
    global _split_running
    with _lock:
        if _split_running:
            return
        _split_running = True
    threading.Thread(target=_split_loop, daemon=True,
                     name="download-manager-split").start()


def _split_loop():
    global _split_running
    try:
        while True:
            with _lock:
                item_id = _split_queue.pop(0) if _split_queue else None
            if item_id is None:
                return
            item = get(item_id)
            if item is None:
                continue
            _update(item_id, state="splitting", split_error=None, parts_done=0,
                    collector_ids=[])
            try:
                _split_one(item_id)
            except Exception as e:
                _update(item_id, state="ready",
                        split_error=(str(e).strip() or "Split failed")[:400])
    finally:
        with _lock:
            _split_running = False
            again = bool(_split_queue)
        if again:
            _start_splits()


def _split_one(item_id):
    import collector

    item = get(item_id)
    if item is None:
        return
    # A retry after a failed split must not duplicate the parts already added.
    for old_id in item.get("collector_ids") or []:
        try:
            collector.delete(old_id)
        except Exception:
            pass
    _update(item_id, collector_ids=[], parts_done=0)
    src = _file_path(item)
    if not src:
        raise RuntimeError("The downloaded video is no longer on disk.")
    chunk = int(item.get("chunk_seconds") or DEFAULT_CHUNK_SECONDS)
    duration = _probe_duration(src) or item.get("duration") or 0
    item_dir = _dir(item_id)
    chunks_dir = os.path.join(item_dir, CHUNKS_SUBDIR)
    shutil.rmtree(chunks_dir, ignore_errors=True)
    os.makedirs(chunks_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(item.get("title") or "video"))[0]

    segments = []
    if duration and duration <= chunk + 2:
        one = os.path.join(chunks_dir, "part_000.mp4")
        shutil.copy2(src, one)
        segments = [one]
    else:
        out_pattern = os.path.join(chunks_dir, "part_%03d.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c", "copy", "-f", "segment",
            "-segment_time", str(chunk), "-reset_timestamps", "1",
            "-avoid_negative_ts", "make_zero", out_pattern,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             errors="replace", timeout=6 * 3600)
        if res.returncode != 0:
            stderr = (res.stderr or "").strip()[-500:]
            raise RuntimeError(f"ffmpeg could not split the video: {stderr or 'unknown error'}")
        segments = sorted(
            os.path.join(chunks_dir, name) for name in os.listdir(chunks_dir)
            if name.endswith(".mp4"))
        if not segments:
            raise RuntimeError("ffmpeg produced no chunks.")

    ids = []
    for index, path in enumerate(segments, start=1):
        if get(item_id) is None:
            return
        title = base if len(segments) == 1 else f"{base} - part {index:02d}"
        part = collector.add_file(
            path, title, source_url=item.get("url"), channel=item.get("channel"),
            duration_probe=_probe_duration, thumb_probe=_thumb, move=True)
        ids.append(part["id"])
        _update(item_id, parts_done=index, collector_ids=list(ids))
    shutil.rmtree(chunks_dir, ignore_errors=True)
    _update(item_id, state="done", split_error=None, split_at=time.time(),
            parts_done=len(ids), collector_ids=ids)
