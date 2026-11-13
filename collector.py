"""Collector: a local shelf of videos to clip later.

The point is to separate *finding* videos from *processing* them:

* a YouTube link only fetches metadata and its thumbnail (tens of KB, no
  video), so a research session costs almost no bandwidth;
* "Download" fetches the file into ``Storage/collector/files`` once, when the
  user is ready;
* a local upload is stored right away;
* anything can be put in the queue, and the Clip Generator processes the queue
  one video at a time.

Everything lives under ``Storage/collector`` (see storage.py) and is served at
``/collector/...``. The index is rewritten atomically; only media extensions
pass the mount's allowlist, so ``items.json`` is not public.
"""
import json
import os
import re
import threading
import time
import uuid

import storage
from jsonfile import write_json_atomic

COLLECTOR_DIR = os.path.join(storage.STORAGE_DIR, "collector")
FILES_DIR = os.path.join(COLLECTOR_DIR, "files")
THUMBS_DIR = os.path.join(COLLECTOR_DIR, "thumbs")
INDEX_FILE = os.path.join(COLLECTOR_DIR, "items.json")

MAX_THUMB_BYTES = 5 * 1024 * 1024
_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

_lock = threading.RLock()
_downloading = set()


def ensure():
    for path in (COLLECTOR_DIR, FILES_DIR, THUMBS_DIR):
        os.makedirs(path, exist_ok=True)
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


def _slug(text, limit=70):
    """A filesystem-safe stem from a title (ASCII, no spaces)."""
    text = (text or "").strip()
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip("-._")
    return (stem[:limit] or "video")


def _relative(path):
    """``files/x.mp4`` style path, or None when outside the tree."""
    try:
        rel = os.path.relpath(path, COLLECTOR_DIR)
    except ValueError:
        return None
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    return rel.replace("\\", "/")


def _media_path(rel):
    """Absolute path for an index entry, or None if it escapes the tree.

    ``file`` entries are stored relative (``files/x.mp4``); thumbnails are
    public URLs (``/collector/thumbs/x.jpg``). Both are accepted.
    """
    if not rel or not isinstance(rel, str):
        return None
    if rel.startswith("/collector/"):
        rel = rel[len("/collector/"):]
    elif rel.startswith("/") or ".." in rel.split("/"):
        return None
    path = os.path.join(COLLECTOR_DIR, *rel.split("/"))
    root = os.path.abspath(COLLECTOR_DIR)
    if os.path.commonpath([os.path.abspath(path), root]) != root:
        return None
    return path


def _file_path(item):
    rel = item.get("file")
    path = _media_path(rel) if rel else None
    return path if path and os.path.isfile(path) else None


def file_path(item):
    """Absolute path of a downloaded/uploaded file, or None."""
    return _file_path(item or {})


def public(item):
    """The API shape: URLs instead of host paths."""
    path = _file_path(item)
    size = os.path.getsize(path) if path else item.get("size_bytes")
    return {
        "id": item.get("id"),
        "source": item.get("source"),
        "title": item.get("title") or "Untitled",
        "channel": item.get("channel"),
        "url": item.get("url"),
        "duration": item.get("duration"),
        "thumbnail": item.get("thumbnail"),
        "state": item.get("state") or ("ready" if path else "remote"),
        "error": item.get("error"),
        "ready": bool(path),
        "queued": bool(item.get("queued")),
        "size_bytes": size,
        "added_at": item.get("added_at"),
        "downloaded_at": item.get("downloaded_at"),
        "job_id": item.get("job_id"),
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
                return public(item)
    return None


# --------------------------------------------------------------------------- #
# Adding sources
# --------------------------------------------------------------------------- #
def _probe_url(url):
    """Metadata only: no video bytes are fetched here."""
    from security_utils import assert_public_url
    assert_public_url(url)
    from yt_clients import youtube_non_video_reason
    reason = youtube_non_video_reason(url)
    if reason:
        raise ValueError(f"This link is {reason}.")

    import yt_dlp
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 2,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("Could not read this link.")
    if info.get("_type") == "playlist":
        raise ValueError("That is a playlist; paste one video's link.")
    return info


def _fetch_thumbnail(item_id, url):
    """Save the remote thumbnail locally; return the public path or None."""
    if not url:
        return None
    try:
        import httpx
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            with client.stream("GET", url, headers={"Accept": "image/*"}) as res:
                res.raise_for_status()
                content_type = (res.headers.get("content-type") or "").split(";")[0]
                ext = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
                name = f"{item_id}{ext}"
                dest = os.path.join(THUMBS_DIR, name)
                size = 0
                with open(dest, "wb") as out:
                    for chunk in res.iter_bytes():
                        size += len(chunk)
                        if size > MAX_THUMB_BYTES:
                            raise ValueError("thumbnail too large")
                        out.write(chunk)
        if size == 0:
            os.remove(dest)
            return None
        return f"/collector/thumbs/{name}"
    except Exception:
        return None


def add_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("Paste a video link.")
    info = _probe_url(url)
    item_id = str(uuid.uuid4())
    thumb = _fetch_thumbnail(item_id, info.get("thumbnail"))
    if not thumb:
        thumbs = [t.get("url") for t in (info.get("thumbnails") or []) if t.get("url")]
        if thumbs:
            thumb = _fetch_thumbnail(item_id, thumbs[-1])
    item = {
        "id": item_id,
        "source": "url",
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "Untitled",
        "channel": info.get("channel") or info.get("uploader"),
        "duration": float(info["duration"]) if info.get("duration") else None,
        "thumbnail": thumb,
        "state": "remote",
        "queued": False,
        "added_at": time.time(),
    }
    with _lock:
        items = _read()
        items.append(item)
        _write(items)
    return public(item)


def add_upload(filename, upload_file, max_bytes, duration_probe, thumb_probe):
    """Store a local file straight into the collector.

    ``upload_file`` is FastAPI's ``UploadFile`` (read in chunks, never loaded
    whole); ``duration_probe(path)`` and ``thumb_probe(path, thumb_path)`` are
    the ffprobe/ffmpeg helpers owned by app.py, so this module stays free of
    process spawning.
    """
    item_id = str(uuid.uuid4())
    base = os.path.basename(filename or "video.mp4")
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in _VIDEO_EXT:
        ext = ".mp4"
    name = f"{item_id}_{_slug(stem)}{ext}"
    dest = os.path.join(FILES_DIR, name)
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"File too large. Max size {max_bytes // (1024 * 1024)}MB")
                out.write(chunk)
        if size == 0:
            raise ValueError("Empty file")
    except Exception:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise

    duration = duration_probe(dest)
    thumb_name = f"{item_id}.jpg"
    thumb_probe(dest, os.path.join(THUMBS_DIR, thumb_name))
    item = {
        "id": item_id,
        "source": "upload",
        "url": None,
        "title": stem or "Untitled",
        "channel": None,
        "duration": duration,
        "thumbnail": f"/collector/thumbs/{thumb_name}" if os.path.exists(
            os.path.join(THUMBS_DIR, thumb_name)) else None,
        "file": f"files/{name}",
        "size_bytes": size,
        "state": "ready",
        "queued": False,
        "added_at": time.time(),
        "downloaded_at": time.time(),
    }
    with _lock:
        items = _read()
        items.append(item)
        _write(items)
    return public(item)


# --------------------------------------------------------------------------- #
# Downloading a URL item, in the background
# --------------------------------------------------------------------------- #
def start_download(item_id):
    """Fetch the video; returns the public item (state 'downloading')."""
    item = get(item_id)
    if item is None:
        raise KeyError("not found")
    if _file_path(item):
        return public(item)
    with _lock:
        if item_id in _downloading:
            return public(item)
        _downloading.add(item_id)
    public_item = _update(item_id, state="downloading", error=None)
    threading.Thread(target=_download_worker, args=(item_id,), daemon=True,
                     name=f"collector-{item_id[:8]}").start()
    return public_item


def _download_worker(item_id):
    try:
        item = get(item_id)
        if not item or not item.get("url"):
            return
        from main import download_youtube_video
        path, title = download_youtube_video(item["url"], FILES_DIR, allow_paid=False)
        if not get(item_id):
            # Deleted while downloading: do not leave the file behind.
            try:
                os.remove(path)
            except OSError:
                pass
            return
        stem, ext = os.path.splitext(os.path.basename(path))
        ext = ext.lower() if ext.lower() in _VIDEO_EXT else ".mp4"
        name = f"{item_id}_{_slug(item.get('title') or title or stem)}{ext}"
        dest = os.path.join(FILES_DIR, name)
        os.replace(path, dest)
        _update(item_id, file=f"files/{name}", state="ready", error=None,
                size_bytes=os.path.getsize(dest), downloaded_at=time.time(),
                title=item.get("title") or title)
    except Exception as e:
        _update(item_id, state="error", error=str(e)[:400])
    finally:
        with _lock:
            _downloading.discard(item_id)


def delete(item_id):
    with _lock:
        items = _read()
        keep = [i for i in items if i.get("id") != item_id]
        if len(keep) == len(items):
            return False
        gone = [i for i in items if i.get("id") == item_id][0]
        _write(keep)
    for rel in (gone.get("file"), gone.get("thumbnail")):
        path = _media_path(rel) if rel else None
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    return True


def set_queued(item_id, queued):
    return _update(item_id, queued=bool(queued))


def mark_job(item_id, job_id):
    return _update(item_id, job_id=job_id, queued=False, last_job_at=time.time())


def forget_job(job_id):
    """Clear a cancelled job's id from the item that started it, so the shelf
    does not link to a job whose files were removed."""
    changed = 0
    for item in list_items():
        if item.get("job_id") == job_id:
            _update(item["id"], job_id=None)
            changed += 1
    return changed


def queued_items():
    return [i for i in list_items() if i["queued"]]
