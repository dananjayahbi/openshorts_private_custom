"""The Archive: finished clips kept out of the working folders, on local disk.

A rendered clip normally lives in ``Storage/videos/<job_id>/`` and is swept
after ``JOB_RETENTION_SECONDS``. Archiving a clip moves its video and poster
into ``Storage/archive/files/<id>/`` first, so the sweep can never touch it,
and records it in ``Storage/archive/archive.db`` (SQLite, stdlib). That index is
what makes a library of thousands of clips cheap to filter, sort and page: the
Archive page never scans folders to render a page.

External storage vaults
-----------------------
An external device (USB stick, HDD, SSD) can hold one or more *vaults*. A vault
is a single preallocated ``<name>-<id>.osvault`` file: creating one writes it
out to the chosen size, so the space is really occupied and the rest of the
device stays usable. Inside the file:

    0 .. 1 MiB         header: magic, JSON manifest (id, name, key, capacity,
                       allocation pointer and free ranges)
    1 MiB .. capacity  entries: 4 KiB entry header + payload, block aligned

The manifest never holds video metadata that matters for the library: the
SQLite index does. The vault only needs enough to find an entry again after the
drive was unplugged (id, name, size, sha256, allocation), which also lets a
vault be adopted by a fresh install.

Transfer is a verified move: copy the bytes into the vault while hashing, write
the entry header, then delete the local copy. The original clip's hash is
computed when it is archived, so a mismatch aborts the push and the local file
stays. Everything runs in one background worker: the HTTP handlers only flip a
row's state, and the page polls.

Playback streams straight out of the container with HTTP Range support, so a
vaulted clip seeks like a normal file while its device is connected. When the
device is unplugged the card stays (poster, title, vault name) and the player
asks for that vault instead.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import struct
import string
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import clip_copy
import clip_state
import clip_tags
import storage
from jsonfile import write_json_atomic

# --------------------------------------------------------------------------- #
# Paths and constants
# --------------------------------------------------------------------------- #
ARCHIVE_DIR = os.path.join(storage.STORAGE_DIR, "archive")
FILES_DIR = os.path.join(ARCHIVE_DIR, "files")
DB_FILE = os.path.join(ARCHIVE_DIR, "archive.db")

VAULT_MAGIC = b"OSVAULT1\n"
ENTRY_MAGIC = b"OSVENT1\n"
HEADER_REGION = 1024 * 1024
DATA_START = 1024 * 1024
ENTRY_HEADER = 4096
BLOCK = 4096
COPY_CHUNK = 4 * 1024 * 1024

MIN_VAULT_BYTES = 64 * 1024 * 1024
MAX_VAULT_BYTES = 64 * 1024 ** 4          # 64 TB, a sanity bound
RESERVE_HEADROOM = 64 * 1024 * 1024       # never fill the device completely
MAX_FREE_RANGES = 4000

DEFAULT_AUTO_DAYS = 7
AUTO_ARCHIVE_INTERVAL = 30 * 60
SCAN_INTERVAL = 10

DATE_PRESETS = ("any", "today", "yesterday", "week", "month", "custom")
SORTS = ("newest", "oldest", "longest", "shortest", "score", "largest", "smallest")
PLATFORMS = ("any", "youtube", "facebook", "both", "none")
STATES = ("any", "local", "vaulted", "pending_delete", "missing", "pushing")

_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ITEM_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_lock = threading.RLock()
_scan_lock = threading.Lock()
_ensured: set = set()
_cancelled: set = set()
_cancelled_vaults: set = set()
_worker_running = False
_started = False
_last_scan = 0.0


class VaultFull(ValueError):
    """The vault has no free range large enough for the next entry."""


class VaultMissing(ValueError):
    """The device (or its container file) is not connected."""


class _Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _now():
    return time.time()


def _item_id():
    return uuid.uuid4().hex


def _vault_id():
    return str(uuid.uuid4())


def valid_item_id(item_id) -> bool:
    return isinstance(item_id, str) and bool(_ITEM_ID_RE.match(item_id))


def valid_vault_id(vault_id) -> bool:
    return isinstance(vault_id, str) and bool(_ID_RE.match(vault_id))


def _json_load(raw, default):
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _sha256_file(path, progress=None):
    digest = hashlib.sha256()
    size = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, size)
    return digest.hexdigest()


def _move(src, dst, tries=12, delay=0.25):
    """Move a file, retrying while Windows still has it open in a player."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    last = None
    for attempt in range(max(1, tries)):
        try:
            shutil.move(src, dst)
            return True
        except PermissionError as exc:
            last = exc
            if attempt == tries - 1:
                break
            time.sleep(delay)
    raise PermissionError(
        "The file is still open in another program (the clip player or a "
        "download manager). Close it and try again.") from last


def _remove(path, tries=12, delay=0.25):
    for attempt in range(max(1, tries)):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
            return True
        except PermissionError:
            if attempt == tries - 1:
                return False
            time.sleep(delay)
        except OSError:
            return False
    return False


def _fmt_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (slug or "vault")[:40]


def _image_size(path):
    """(width, height) for a JPEG/PNG poster, or (None, None)."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = struct.unpack(">II", head[16:24])
                return int(width), int(height)
            if head[:2] != b"\xff\xd8":
                return None, None
            f.seek(2)
            while True:
                byte = f.read(1)
                if not byte:
                    return None, None
                if byte != b"\xff":
                    continue
                marker = f.read(1)
                while marker == b"\xff":
                    marker = f.read(1)
                if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5",
                              b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb",
                              b"\xcd", b"\xce", b"\xcf"):
                    length = struct.unpack(">H", f.read(2))[0]
                    data = f.read(5)
                    height, width = struct.unpack(">HH", data[1:5])
                    return int(width), int(height)
                length = struct.unpack(">H", f.read(2))[0]
                f.seek(max(0, length - 2), 1)
    except (OSError, struct.error):
        return None, None


def _date_window(preset, date_from, date_to):
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if preset == "today":
        return midnight.timestamp(), None
    if preset == "yesterday":
        return (midnight - timedelta(days=1)).timestamp(), midnight.timestamp()
    if preset == "week":
        return (midnight - timedelta(days=now.weekday())).timestamp(), None
    if preset == "month":
        return midnight.replace(day=1).timestamp(), None
    if preset != "custom":
        return None, None
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").astimezone()
        end = datetime.strptime(date_to or date_from, "%Y-%m-%d").astimezone()
    except (TypeError, ValueError):
        raise ValueError("custom dates must be YYYY-MM-DD (date_from and date_to)")
    end += timedelta(days=1)
    if end <= start:
        raise ValueError("date_to must be on or after date_from")
    return start.timestamp(), end.timestamp()


# --------------------------------------------------------------------------- #
# SQLite index
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    clip_index INTEGER NOT NULL,
    title TEXT,
    hook TEXT,
    tags TEXT,
    facebook_title TEXT,
    youtube_title TEXT,
    youtube_description TEXT,
    platform_fb INTEGER NOT NULL DEFAULT 0,
    platform_yt INTEGER NOT NULL DEFAULT 0,
    posted_at REAL,
    duration REAL,
    score REAL,
    created_at TEXT,
    archived_at REAL NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    poster_width INTEGER,
    poster_height INTEGER,
    state TEXT NOT NULL,
    vault_id TEXT,
    vault_entry_off INTEGER,
    vault_entry_size INTEGER,
    sha256 TEXT,
    local_video TEXT,
    local_poster TEXT,
    error TEXT,
    progress_bytes INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    delete_after INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_clip ON items(job_id, clip_index);
CREATE INDEX IF NOT EXISTS idx_archive_state ON items(state);
CREATE INDEX IF NOT EXISTS idx_archive_vault ON items(vault_id);
CREATE INDEX IF NOT EXISTS idx_archive_time ON items(archived_at);

CREATE TABLE IF NOT EXISTS vaults (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    capacity_bytes INTEGER NOT NULL,
    folder TEXT,
    rel_folder TEXT,
    path TEXT,
    connected INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'ready',
    progress_bytes INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    used_bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_seen REAL
);

CREATE TABLE IF NOT EXISTS foreign_vaults (
    path TEXT PRIMARY KEY,
    id TEXT,
    name TEXT,
    capacity_bytes INTEGER,
    seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    "auto_archive_enabled": False,
    "auto_archive_days": DEFAULT_AUTO_DAYS,
}


def _db_file():
    return DB_FILE


def _files_dir():
    return FILES_DIR


def ensure():
    """Create the tree and the index once per database path."""
    os.makedirs(_files_dir(), exist_ok=True)
    db_path = _db_file()
    if db_path in _ensured:
        return
    with _lock:
        if db_path in _ensured:
            return
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _ensured.add(db_path)


def _db():
    ensure()
    conn = sqlite3.connect(_db_file(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def _conn():
    """A short-lived connection: always closed, so Windows can release the file."""
    conn = _db()
    try:
        yield conn
    finally:
        conn.close()


def _settings_from(conn):
    data = dict(DEFAULT_SETTINGS)
    try:
        for row in conn.execute("SELECT key, value FROM settings"):
            if row["key"] == "auto_archive_enabled":
                data["auto_archive_enabled"] = str(row["value"]).lower() in ("1", "true", "yes")
            elif row["key"] == "auto_archive_days":
                try:
                    data["auto_archive_days"] = max(0, min(365, int(row["value"])))
                except (TypeError, ValueError):
                    pass
    except sqlite3.Error:
        pass
    return data


def get_settings():
    ensure()
    with _conn() as conn:
        return _settings_from(conn)


def set_settings(enabled=None, days=None):
    ensure()
    with _lock, _conn() as conn:
        if enabled is not None:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('auto_archive_enabled', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if enabled else "0",))
        if days is not None:
            value = max(0, min(365, int(days)))
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('auto_archive_days', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(value),))
        conn.commit()
        return _settings_from(conn)


# --------------------------------------------------------------------------- #
# Vault container format
# --------------------------------------------------------------------------- #
def _read_header(path):
    with open(path, "rb") as f:
        prefix = f.read(len(VAULT_MAGIC) + 4)
        if not prefix.startswith(VAULT_MAGIC):
            raise ValueError("Not a Clip Studio vault (bad magic).")
        length = struct.unpack("<I", prefix[len(VAULT_MAGIC):])[0]
        if not 0 < length <= HEADER_REGION - len(VAULT_MAGIC) - 4:
            raise ValueError("Vault header is corrupt.")
        raw = f.read(length)
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Vault header is corrupt.")
    if not isinstance(header, dict) or header.get("format") != 1:
        raise ValueError("Unsupported vault format.")
    return header


def _write_header(f, header):
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    room = HEADER_REGION - len(VAULT_MAGIC) - 4
    if len(raw) > room:
        raise ValueError(
            "The vault manifest is full. Compact or expand the vault, or create a new one.")
    f.seek(0)
    f.write(VAULT_MAGIC)
    f.write(struct.pack("<I", len(raw)))
    f.write(raw)
    f.write(b" " * (room - len(raw)))


def _entry_bytes(record):
    raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
    room = ENTRY_HEADER - len(ENTRY_MAGIC) - 4
    if len(raw) > room:
        raise ValueError("Vault entry name is too long.")
    return (ENTRY_MAGIC + struct.pack("<I", len(raw)) + raw
            + b"\0" * (room - len(raw)))


def _read_entry(f, offset):
    f.seek(offset)
    prefix = f.read(len(ENTRY_MAGIC) + 4)
    if not prefix.startswith(ENTRY_MAGIC):
        return None
    length = struct.unpack("<I", prefix[len(ENTRY_MAGIC):])[0]
    if not 0 < length <= ENTRY_HEADER - len(ENTRY_MAGIC) - 4:
        return None
    raw = f.read(length)
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _padded_size(size):
    return ((ENTRY_HEADER + int(size) + BLOCK - 1) // BLOCK) * BLOCK


def _used_bytes(header):
    free = sum(int(length) for _off, length in (header.get("free") or []))
    return max(0, int(header.get("next", DATA_START)) - DATA_START - free)


def _allocate(header, need):
    free = header.setdefault("free", [])
    for index, (offset, length) in enumerate(free):
        if length >= need:
            if length == need:
                free.pop(index)
            else:
                free[index] = [offset + need, length - need]
            return int(offset)
    start = int(header.get("next", DATA_START))
    capacity = int(header["capacity"])
    if start + need > capacity:
        usable = capacity - DATA_START
        used = _used_bytes(header)
        raise VaultFull(
            f"The vault is full: {_gb(used)} of {_gb(usable)} used. Expand the "
            "vault or push to another one.")
    header["next"] = start + need
    return start


def _release(header, offset, length):
    free = list(header.get("free") or [])
    free.append([int(offset), int(length)])
    free.sort(key=lambda pair: pair[0])
    merged = []
    for start, span in free:
        if merged and start <= merged[-1][0] + merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], start + span - merged[-1][0])
        else:
            merged.append([start, span])
    if len(merged) > MAX_FREE_RANGES:
        raise VaultFull(
            "The vault is too fragmented to reuse safely. Compact it by "
            "restoring its videos and creating a fresh vault.")
    header["free"] = merged


def _copy_to_vault(handle, offset, source, on_progress, cancelled):
    digest = hashlib.sha256()
    size = os.path.getsize(source)
    done = 0
    handle.seek(offset + ENTRY_HEADER)
    with open(source, "rb") as src:
        while True:
            if cancelled and cancelled():
                raise _Cancelled()
            chunk = src.read(COPY_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, size)
    handle.flush()
    os.fsync(handle.fileno())
    return digest.hexdigest(), size


def _preallocate(path, capacity, on_progress=None, cancelled=None):
    """Write the whole container out so the space is really occupied."""
    with open(path, "wb") as f:
        zero = b"\0" * COPY_CHUNK
        done = 0
        while done < capacity:
            if cancelled and cancelled():
                raise _Cancelled()
            amount = min(len(zero), capacity - done)
            f.write(zero[:amount])
            done += amount
            if on_progress:
                on_progress(done, capacity)
        f.flush()
        os.fsync(f.fileno())


def _gb(value):
    number = float(value or 0) / (1024 ** 3)
    if number >= 100:
        return f"{number:.0f} GB"
    if number >= 10:
        return f"{number:.1f} GB"
    return f"{number:.2f} GB"


# --------------------------------------------------------------------------- #
# Vault registry
# --------------------------------------------------------------------------- #
def _vault_row(conn, vault_id):
    return conn.execute("SELECT * FROM vaults WHERE id=?", (vault_id,)).fetchone()


def _vault_public(conn, row):
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE vault_id=?", (row["id"],)).fetchone()["n"]
    capacity = int(row["capacity_bytes"] or 0)
    usable = max(0, capacity - DATA_START)
    used = int(row["used_bytes"] or 0)
    return {
        "id": row["id"],
        "name": row["name"],
        "state": row["state"],
        "connected": bool(row["connected"]) and row["state"] == "ready",
        "path": row["path"],
        "folder": row["folder"],
        "file_name": row["file_name"],
        "capacity_bytes": capacity,
        "usable_bytes": usable,
        "used_bytes": used,
        "free_bytes": max(0, usable - used),
        "items": count,
        "progress_bytes": row["progress_bytes"],
        "progress": (min(99, int(int(row["progress_bytes"] or 0) * 100 / capacity))
                     if row["state"] in ("creating", "expanding") and capacity else None),
        "error": row["error"],
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
    }


def list_vaults(with_foreign=True):
    ensure()
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vaults ORDER BY created_at ASC").fetchall()
        vaults = [_vault_public(conn, row) for row in rows]
        foreign = []
        if with_foreign:
            foreign = [dict(row) for row in conn.execute(
                "SELECT path, id, name, capacity_bytes FROM foreign_vaults "
                "ORDER BY seen_at DESC")]
        return {"vaults": vaults, "unrecognized": foreign}


def _check_name(conn, name, ignore_id=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the vault a name.")
    if len(name) > 60:
        raise ValueError("Vault names are at most 60 characters.")
    if any(ch in name for ch in '\\/:*?"<>|'):
        raise ValueError("Vault names cannot contain path characters.")
    row = conn.execute(
        "SELECT id FROM vaults WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if row and row["id"] != ignore_id:
        raise ValueError(f"A vault named “{name}” already exists.")
    return name


def _free_at(folder):
    try:
        usage = shutil.disk_usage(folder)
        return int(usage.free)
    except OSError:
        return None


def create_vault(folder, name, size_bytes):
    """Register a vault and let the worker preallocate its container file."""
    ensure()
    folder = os.path.abspath(os.path.expanduser(str(folder or "").strip()))
    if not folder or not os.path.isdir(folder):
        raise ValueError("Choose a folder on the storage device.")
    try:
        capacity = int(size_bytes)
    except (TypeError, ValueError):
        raise ValueError("Vault size must be a number of bytes.")
    if capacity < MIN_VAULT_BYTES or capacity <= DATA_START + BLOCK:
        raise ValueError(f"A vault has to be at least {_gb(max(MIN_VAULT_BYTES, DATA_START + BLOCK))}.")
    if capacity > MAX_VAULT_BYTES:
        raise ValueError("That vault size is too large.")
    free = _free_at(folder)
    if free is not None and capacity > free - RESERVE_HEADROOM:
        raise ValueError(
            f"Not enough free space: the device has {_gb(free)} free, and a "
            f"vault of {_gb(capacity)} plus headroom does not fit.")

    vault_id = _vault_id()
    key = secrets.token_hex(16)
    with _lock, _conn() as conn:
        clean = _check_name(conn, name)
        file_name = f"{_fmt_slug(clean)}-{vault_id[:8]}.osvault"
        conn.execute(
            "INSERT INTO vaults(id, name, key, file_name, capacity_bytes, folder, "
            "rel_folder, path, connected, state, used_bytes, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,0,'creating',0,?)",
            (vault_id, clean, key, file_name, capacity, folder,
             _rel_folder(folder), os.path.join(folder, file_name), _now()))
        conn.commit()
        row = _vault_row(conn, vault_id)
        result = _vault_public(conn, row)
    _kick()
    return result


def _rel_folder(folder):
    """How a folder sits under its mount root, so a new drive letter still finds it."""
    folder = os.path.abspath(folder)
    for root in mounted_roots():
        root = os.path.abspath(root)
        try:
            if os.path.commonpath([folder, root]) == root:
                rel = os.path.relpath(folder, root)
                return "" if rel == "." else rel
        except ValueError:
            continue
    return ""


def update_vault(vault_id, name=None, size_bytes=None):
    ensure()
    with _lock, _conn() as conn:
        row = _vault_row(conn, vault_id)
        if row is None:
            raise KeyError("not found")
        if row["state"] != "ready":
            raise ValueError("Wait for the vault to finish its current job.")
        if name is not None:
            clean = _check_name(conn, name, ignore_id=vault_id)
            conn.execute("UPDATE vaults SET name=? WHERE id=?", (clean, vault_id))
        if size_bytes is not None:
            try:
                capacity = int(size_bytes)
            except (TypeError, ValueError):
                raise ValueError("Vault size must be a number of bytes.")
            current = int(row["capacity_bytes"])
            if capacity <= current:
                raise ValueError("A vault can only grow; it cannot shrink.")
            if capacity < MIN_VAULT_BYTES:
                raise ValueError(f"A vault has to be at least {_gb(MIN_VAULT_BYTES)}.")
            free = _free_at(row["folder"])
            if free is not None and (capacity - current) > free - RESERVE_HEADROOM:
                raise ValueError(
                    f"Not enough free space to grow by {_gb(capacity - current)} "
                    f"(the device has {_gb(free)} free).")
            conn.execute(
                "UPDATE vaults SET state='expanding', progress_bytes=?, capacity_bytes=?, "
                "error=NULL WHERE id=?",
                (current, capacity, vault_id))
        conn.commit()
        result = _vault_public(conn, _vault_row(conn, vault_id))
    if size_bytes is not None:
        _kick()
    return result


def delete_vault(vault_id, confirm=False):
    """Delete a vault: its container file and every archived clip inside it."""
    if not confirm:
        raise ValueError("Deleting a vault wipes its contents; confirm it first.")
    ensure()
    with _lock, _conn() as conn:
        row = _vault_row(conn, vault_id)
        if row is None:
            raise KeyError("not found")
        state = row["state"]
        path = row["path"]
        items = conn.execute(
            "SELECT id FROM items WHERE vault_id=?", (vault_id,)).fetchall()
        if state == "creating":
            # Creation writes the container: let the worker stop and clean up.
            _cancelled_vaults.add(vault_id)
            conn.execute("UPDATE vaults SET state='deleting' WHERE id=?", (vault_id,))
            conn.commit()
            return {"deleting": len(items), "vault": _vault_public(conn, _vault_row(conn, vault_id))}
        if state in ("ready", "error") and state == "ready" and not row["connected"]:
            raise ValueError(
                "Connect the device that holds this vault before deleting it. "
                "Its videos would otherwise be lost without removing the file.")
        if state == "expanding":
            raise ValueError("Wait for the vault to finish expanding.")
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM items WHERE vault_id=?", (vault_id,))
        conn.execute("DELETE FROM vaults WHERE id=?", (vault_id,))
        conn.execute("DELETE FROM foreign_vaults WHERE path=?", (path,))
        conn.commit()
    for item in items:
        _remove(os.path.join(_files_dir(), item["id"]))
    if path:
        _remove(path)
    return {"deleted": len(items), "vault_id": vault_id}


def adopt_vault(path):
    """Register a vault file found on a device (created by this or another install)."""
    ensure()
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ValueError("That vault file is not there anymore.")
    header = _read_header(path)
    vault_id = str(header.get("id") or "")
    name = str(header.get("name") or "Vault")
    capacity = int(header.get("capacity") or os.path.getsize(path))
    key = str(header.get("key") or "")
    if not vault_id or not key:
        raise ValueError("That vault header is missing its identity.")

    with _lock, _conn() as conn:
        existing = conn.execute("SELECT * FROM vaults WHERE id=?", (vault_id,)).fetchone()
        if existing is None:
            unique = name
            suffix = 1
            while conn.execute("SELECT 1 FROM vaults WHERE name=? COLLATE NOCASE",
                               (unique,)).fetchone():
                suffix += 1
                unique = f"{name} ({suffix})"
            conn.execute(
                "INSERT INTO vaults(id, name, key, file_name, capacity_bytes, folder, "
                "rel_folder, path, connected, state, used_bytes, created_at, last_seen) "
                "VALUES(?,?,?,?,?,?,?,?,1,'ready',?,?,?)",
                (vault_id, unique, key, os.path.basename(path), capacity,
                 os.path.dirname(path), _rel_folder(os.path.dirname(path)), path,
                 _used_bytes(header), _now(), _now()))
        else:
            conn.execute(
                "UPDATE vaults SET path=?, folder=?, rel_folder=?, connected=1, "
                "state='ready', capacity_bytes=?, key=?, error=NULL, last_seen=? "
                "WHERE id=?",
                (path, os.path.dirname(path), _rel_folder(os.path.dirname(path)),
                 capacity, key, _now(), vault_id))
        conn.commit()
        imported = _import_entries(conn, vault_id, path, header)
        conn.execute("DELETE FROM foreign_vaults WHERE path=?", (path,))
        conn.commit()
        row = _vault_row(conn, vault_id)
        result = _vault_public(conn, row)
    _kick()
    return {"vault": result, "imported": imported}


def _import_entries(conn, vault_id, path, header):
    """Bring entry headers into the index when adopting/rewiring a vault."""
    imported = 0
    capacity = int(header.get("capacity") or 0)
    end = min(int(header.get("next", DATA_START)), capacity)
    with open(path, "rb") as f:
        offset = DATA_START
        while offset < end:
            record = _read_entry(f, offset)
            if not record:
                break
            alloc = int(record.get("alloc") or _padded_size(record.get("size") or 0))
            if alloc < ENTRY_HEADER:
                break
            if not record.get("deleted") and record.get("id"):
                item_id = str(record["id"])
                exists = conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO items(id, job_id, clip_index, title, tags, "
                        "created_at, archived_at, size_bytes, state, vault_id, "
                        "vault_entry_off, vault_entry_size, sha256, local_poster, updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?, 'vaulted', ?,?,?,?,?,?)",
                        (item_id, "", 0, str(record.get("name") or "Vaulted clip"),
                         "[]", None, _now(), int(record.get("size") or 0), vault_id,
                         offset, alloc, record.get("sha256"),
                         None, _now()))
                    imported += 1
            offset += alloc
    return imported


# --------------------------------------------------------------------------- #
# Device discovery and scanning
# --------------------------------------------------------------------------- #
def mounted_roots():
    """Directories that can hold a removable/fixed device, cheap to enumerate."""
    roots = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            try:
                if os.path.isdir(root):
                    roots.append(root)
            except OSError:
                continue
        return roots
    candidates = ["/media", "/mnt", "/Volumes", "/run/media"]
    for base in candidates:
        try:
            if not os.path.isdir(base):
                continue
            roots.append(base)
            for entry in os.scandir(base):
                if entry.is_dir(follow_symlinks=False):
                    roots.append(entry.path)
                    if base == "/run/media":
                        try:
                            for nested in os.scandir(entry.path):
                                if nested.is_dir(follow_symlinks=False):
                                    roots.append(nested.path)
                        except OSError:
                            pass
        except OSError:
            continue
    roots.append("/")
    return roots


def _root_for(path):
    path = os.path.abspath(path)
    best = None
    for root in mounted_roots():
        root = os.path.abspath(root)
        try:
            if os.path.commonpath([path, root]) == root:
                if best is None or len(root) > len(best):
                    best = root
        except ValueError:
            continue
    return best


def _device_label(root):
    if os.name != "nt":
        return os.path.basename(root.rstrip("/")) or root
    try:
        import ctypes
        volume = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint()
        maxlen = ctypes.c_uint()
        flags = ctypes.c_uint()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), volume, 261, ctypes.byref(serial),
            ctypes.byref(maxlen), ctypes.byref(flags), filesystem, 261)
        if ok and volume.value:
            return f"{volume.value} ({root.rstrip(chr(92))})"
    except Exception:
        pass
    return root


def devices():
    """Mount roots with their free space, for the vault folder picker."""
    result = []
    seen = set()
    for root in mounted_roots():
        path = os.path.abspath(root)
        if path in seen:
            continue
        seen.add(path)
        try:
            usage = shutil.disk_usage(path)
            total, free = int(usage.total), int(usage.free)
        except OSError:
            total = free = None
        result.append({
            "path": path,
            "label": _device_label(path),
            "free_bytes": free,
            "total_bytes": total,
        })
    result.sort(key=lambda item: (item["path"] != os.path.abspath(os.sep),
                                  ":" not in item["path"], item["path"].lower()))
    return {"devices": result, "home": os.path.expanduser("~")}


def browse(path):
    """Sub-folders of ``path`` (the vault modal's folder picker)."""
    raw = str(path or "").strip()
    if not raw:
        return {"path": "", "parent": None, "directories": []}
    target = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isdir(target):
        raise ValueError("That folder does not exist.")
    directories = []
    try:
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = entry.name
                if name.startswith(".") or name in ("$RECYCLE.BIN", "System Volume Information"):
                    continue
                directories.append({"name": name, "path": entry.path})
    except PermissionError:
        raise ValueError("Windows would not let the app read that folder.")
    directories.sort(key=lambda item: item["name"].lower())
    parent = os.path.dirname(target.rstrip("\\/"))
    if not parent or parent == target or os.path.normcase(parent) == os.path.normcase(target):
        parent = None
    if parent and os.name == "nt" and len(parent) == 2 and parent[1] == ":":
        parent = parent + "\\"
    try:
        usage = shutil.disk_usage(target)
        free, total = int(usage.free), int(usage.total)
    except OSError:
        free = total = None
    return {
        "path": target,
        "parent": parent,
        "directories": directories[:500],
        "free_bytes": free,
        "total_bytes": total,
    }


def _candidate_paths(roots):
    """Known vault files by their file name, under every mounted root."""
    ensure()
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT path, file_name, rel_folder FROM vaults WHERE state != 'deleting'"
        ).fetchall()
    paths = []
    seen = set()

    def add(candidate):
        if candidate and candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)

    for row in rows:
        if row["path"]:
            add(os.path.abspath(row["path"]))
        name = row["file_name"]
        rel = (row["rel_folder"] or "").strip("\\/")
        for root in roots:
            add(os.path.join(root, name))
            if rel and rel not in (".", ".."):
                add(os.path.join(root, rel, name))
    return paths


def scan(roots=None):
    """Reconnect known vaults and record unknown ones found on connected devices."""
    global _last_scan
    if not _scan_lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        ensure()
        roots = [os.path.abspath(root) for root in (roots or mounted_roots())]
        candidates = list(_candidate_paths(roots))
        # Files at a mount root that this install has never seen are how a
        # vault from another install (or a fresh DB) shows up for adoption.
        for root in roots:
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False) \
                                    and entry.name.lower().endswith(".osvault"):
                                candidates.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
        seen_ids = set()
        seen_paths = set()
        found = []
        for path in candidates:
            if path in seen_paths or not os.path.isfile(path):
                continue
            seen_paths.add(path)
            try:
                header = _read_header(path)
            except (OSError, ValueError):
                continue
            found.append((path, header))

        with _lock, _conn() as conn:
            rows = conn.execute("SELECT * FROM vaults").fetchall()
            by_id = {row["id"]: row for row in rows}
            for path, header in found:
                vault_id = str(header.get("id") or "")
                if not vault_id:
                    continue
                row = by_id.get(vault_id)
                if row is None:
                    conn.execute(
                        "INSERT OR REPLACE INTO foreign_vaults"
                        "(path, id, name, capacity_bytes, seen_at) VALUES(?,?,?,?,?)",
                        (path, vault_id, str(header.get("name") or "Vault"),
                         int(header.get("capacity") or 0), _now()))
                    continue
                if str(header.get("key") or "") != row["key"]:
                    continue
                seen_ids.add(vault_id)
                used = _used_bytes(header)
                conn.execute(
                    "UPDATE vaults SET path=?, folder=?, rel_folder=?, connected=1, "
                    "capacity_bytes=?, used_bytes=?, last_seen=?, "
                    "error = CASE WHEN state='ready' THEN NULL ELSE error END "
                    "WHERE id=?",
                    (path, os.path.dirname(path), _rel_folder(os.path.dirname(path)),
                     int(header.get("capacity") or row["capacity_bytes"]), used,
                     _now(), vault_id))
            for row in rows:
                if row["id"] not in seen_ids and row["state"] in ("ready", "error"):
                    conn.execute("UPDATE vaults SET connected=0 WHERE id=?", (row["id"],))
            # Unrecognized files that vanished should not linger in the picker.
            known_foreign = {path for path, _header in found}
            for row in conn.execute("SELECT path FROM foreign_vaults").fetchall():
                if row["path"] not in known_foreign:
                    conn.execute("DELETE FROM foreign_vaults WHERE path=?", (row["path"],))
            conn.commit()
        _last_scan = _now()
        if seen_ids:
            _kick()
        return {"connected": len(seen_ids), "found": len(found)}
    finally:
        _scan_lock.release()


def scan_if_stale(seconds=5):
    """The page's refresh cost: at most one device scan every few seconds."""
    if _now() - _last_scan < seconds:
        return {"skipped": True}
    return scan()


# --------------------------------------------------------------------------- #
# Item shape and queries
# --------------------------------------------------------------------------- #
def _row_public(row):
    tags = _json_load(row["tags"], [])
    platforms = {
        "facebook": bool(row["platform_fb"]),
        "youtube": bool(row["platform_yt"]),
    }
    state = row["state"]
    connected = bool(row["vault_connected"]) if "vault_connected" in row.keys() else False
    size = int(row["size_bytes"] or 0)
    progress = 0
    if state == "pushing" and size:
        progress = min(99, int(int(row["progress_bytes"] or 0) * 100 / size))
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "index": row["clip_index"],
        "title": row["title"] or "Untitled clip",
        "hook": row["hook"],
        "tags": tags,
        "facebook_title": row["facebook_title"],
        "youtube_title": row["youtube_title"] or row["title"],
        "youtube_description": row["youtube_description"],
        "platforms": platforms,
        "posted_at": row["posted_at"],
        "duration": row["duration"] or 0,
        "score": row["score"],
        "created_at": row["created_at"],
        "archived_at": row["archived_at"],
        "size_bytes": size,
        "poster_width": row["poster_width"],
        "poster_height": row["poster_height"],
        "state": state,
        "vault_id": row["vault_id"],
        "vault_name": row["vault_name"] if "vault_name" in row.keys() else None,
        "vault_connected": connected,
        "progress": progress,
        "error": row["error"],
        "sha256": row["sha256"],
        "poster": (f"/api/archive/items/{row['id']}/poster"
                   if row["local_poster"] else None),
        "video": f"/api/archive/items/{row['id']}/video",
        "playable": state == "local" or (state == "vaulted" and connected),
    }


_SELECT = (
    "SELECT i.*, v.name AS vault_name, v.connected AS vault_connected "
    "FROM items i LEFT JOIN vaults v ON v.id = i.vault_id "
)


def list_items(limit=48, page=1, q="", date="any", date_from="", date_to="",
               vault="any", state="any", platform="any", sort="newest"):
    ensure()
    limit = min(max(1, int(limit or 48)), 200)
    page = max(1, int(page or 1))
    date = date if date in DATE_PRESETS else "any"
    sort = sort if sort in SORTS else "newest"
    platform = platform if platform in PLATFORMS else "any"
    state = state if state in STATES else "any"
    start_epoch, end_epoch = _date_window(
        date, (date_from or "").strip(), (date_to or "").strip())

    where = []
    params = []
    if q and str(q).strip():
        needle = f"%{str(q).strip()[:100]}%"
        where.append("(i.title LIKE ? OR i.hook LIKE ? OR i.tags LIKE ? "
                     "OR i.facebook_title LIKE ? OR i.youtube_description LIKE ? "
                     "OR i.job_id LIKE ?)")
        params.extend([needle] * 6)
    if start_epoch is not None:
        where.append("i.archived_at >= ?")
        params.append(start_epoch)
    if end_epoch is not None:
        where.append("i.archived_at < ?")
        params.append(end_epoch)
    if vault == "local":
        where.append("i.vault_id IS NULL")
    elif vault == "missing":
        where.append("i.state = 'missing'")
    elif vault and vault != "any":
        where.append("i.vault_id = ?")
        params.append(vault)
    if state != "any":
        where.append("i.state = ?")
        params.append(state)
    if platform == "facebook":
        where.append("i.platform_fb = 1")
    elif platform == "youtube":
        where.append("i.platform_yt = 1")
    elif platform == "both":
        where.append("i.platform_fb = 1 AND i.platform_yt = 1")
    elif platform == "none":
        where.append("i.platform_fb = 0 AND i.platform_yt = 0")

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = {
        "newest": "i.archived_at DESC",
        "oldest": "i.archived_at ASC",
        "longest": "i.duration DESC",
        "shortest": "i.duration ASC",
        "score": "COALESCE(i.score, -1) DESC",
        "largest": "i.size_bytes DESC",
        "smallest": "i.size_bytes ASC",
    }[sort]

    with _lock, _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM items i" + clause, params).fetchone()["n"]
        pages = (total + limit - 1) // limit if total else 0
        if pages:
            page = min(page, pages)
        rows = conn.execute(
            _SELECT + clause + f" ORDER BY {order}, i.archived_at DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit]).fetchall()
        counts = {row["state"]: row["n"] for row in conn.execute(
            "SELECT state, COUNT(*) AS n FROM items GROUP BY state")}
        totals = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS bytes FROM items"
        ).fetchone()
        vault_totals = conn.execute(
            "SELECT COALESCE(SUM(size_bytes),0) AS bytes FROM items "
            "WHERE vault_id IS NOT NULL").fetchone()
    return {
        "items": [_row_public(row) for row in rows],
        "total": total,
        "page": page or 1,
        "pages": pages,
        "limit": limit,
        "counts": counts,
        "stats": {
            "items": totals["n"],
            "bytes": int(totals["bytes"] or 0),
            "bytes_vaulted": int(vault_totals["bytes"] or 0),
            "bytes_local": int(totals["bytes"] or 0) - int(vault_totals["bytes"] or 0),
        },
    }


def stats():
    ensure()
    with _lock, _conn() as conn:
        counts = {row["state"]: row["n"] for row in conn.execute(
            "SELECT state, COUNT(*) AS n FROM items GROUP BY state")}
        totals = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS bytes FROM items"
        ).fetchone()
    return {"counts": counts, "items": totals["n"], "bytes": int(totals["bytes"] or 0)}


def get_item(item_id):
    if not valid_item_id(item_id):
        return None
    ensure()
    with _lock, _conn() as conn:
        row = conn.execute(_SELECT + "WHERE i.id=?", (item_id,)).fetchone()
        return _row_public(row) if row else None


# --------------------------------------------------------------------------- #
# Moving clips into and out of the archive
# --------------------------------------------------------------------------- #
def _job_dir(job_id):
    return os.path.join(storage.VIDEOS_DIR, str(job_id))


def _metadata_path(job_dir):
    files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not files:
        return None
    try:
        return max(files, key=os.path.getmtime)
    except OSError:
        return files[0]


def _clip_file(job_dir, index):
    candidates = [
        path for path in glob.glob(os.path.join(job_dir, f"*clip_{int(index) + 1}.mp4"))
        if not os.path.basename(path).startswith("wm_")
    ]
    if not candidates:
        return None
    try:
        return max(candidates, key=os.path.getmtime)
    except OSError:
        return candidates[0]


def _poster_file(job_dir, index):
    path = os.path.join(job_dir, f"poster_clip_{int(index) + 1}.jpg")
    return path if os.path.isfile(path) else None


def _clip_metadata(job_dir, index):
    meta = _metadata_path(job_dir)
    if not meta:
        return None, None
    try:
        with open(meta, encoding="utf-8") as f:
            data = json.load(f)
        created = datetime.fromtimestamp(os.path.getmtime(meta), timezone.utc).isoformat()
    except (OSError, ValueError):
        return None, None
    clips = data.get("shorts") if isinstance(data, dict) else None
    if not isinstance(clips, list) or index >= len(clips):
        return None, None
    clip = clips[index] if isinstance(clips[index], dict) else {}
    return clip, created


def _existing_item(conn, job_id, index):
    return conn.execute(
        "SELECT * FROM items WHERE job_id=? AND clip_index=?",
        (job_id, int(index))).fetchone()


def archive_clip(job_id, index):
    """Move one rendered clip (video + poster) into the permanent archive."""
    ensure()
    job_id = str(job_id or "")
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise ValueError("Invalid clip index.")
    if index < 0 or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", job_id):
        raise ValueError("Invalid clip reference.")

    job_dir = _job_dir(job_id)
    with _lock, _conn() as conn:
        existing = _existing_item(conn, job_id, index)
        if existing:
            return _row_public(conn.execute(
                _SELECT + "WHERE i.id=?", (existing["id"],)).fetchone())
    clip, created = _clip_metadata(job_dir, index)
    if clip is None:
        raise ValueError("This clip has no metadata; it cannot be archived.")
    video = _clip_file(job_dir, index)
    if not video:
        raise ValueError("The clip file is already gone.")

    title = (clip_copy.youtube_title(clip) or clip.get("viral_hook_text")
             or f"Clip {index + 1}")
    tags = clip.get("tags") or clip_tags.five(
        None, title,
        (clip.get("youtube_description"),
         clip.get("video_description_for_instagram"),
         clip.get("video_description_for_tiktok")))
    flags = clip_state.flags(job_id, index)
    times = [value for value in (flags.get("platform_times") or {}).values() if value]
    platforms = flags.get("platforms") or {}
    posted_at = max(times) if times else flags.get("used_at")

    item_id = _item_id()
    dest = os.path.join(_files_dir(), item_id)
    os.makedirs(dest, exist_ok=True)
    video_name = "video" + (os.path.splitext(video)[1].lower() or ".mp4")
    try:
        sha = _sha256_file(video)
        _move(video, os.path.join(dest, video_name))
        poster_name = None
        poster = _poster_file(job_dir, index)
        if poster:
            poster_name = "poster" + (os.path.splitext(poster)[1].lower() or ".jpg")
            try:
                _move(poster, os.path.join(dest, poster_name))
            except PermissionError:
                # The tile is only a still; a locked poster must not undo the
                # archive (the gallery can remake it if the clip comes back).
                poster_name = None
    except Exception:
        _remove(dest)
        raise

    width = height = None
    if poster_name:
        width, height = _image_size(os.path.join(dest, poster_name))
    size = os.path.getsize(os.path.join(dest, video_name))
    try:
        duration = max(0.0, float(clip.get("end") or 0) - float(clip.get("start") or 0))
    except (TypeError, ValueError):
        duration = 0.0

    with _lock, _conn() as conn:
        existing = _existing_item(conn, job_id, index)
        if existing:
            _remove(dest)
            return _row_public(conn.execute(
                _SELECT + "WHERE i.id=?", (existing["id"],)).fetchone())
        try:
            conn.execute(
                "INSERT INTO items(id, job_id, clip_index, title, hook, tags, "
                "facebook_title, youtube_title, youtube_description, platform_fb, "
                "platform_yt, posted_at, duration, score, created_at, archived_at, "
                "size_bytes, poster_width, poster_height, state, sha256, "
                "local_video, local_poster, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'local',?,?,?,?)",
                (item_id, job_id, index, title, clip.get("viral_hook_text"),
                 json.dumps(tags), clip_copy.facebook_title(clip), title,
                 clip_copy.youtube_description(clip),
                 1 if platforms.get("facebook") else 0,
                 1 if platforms.get("youtube") else 0,
                 posted_at,
                 duration,
                 clip.get("predicted_score"), created, _now(), size,
                 width, height, sha, video_name, poster_name, _now()))
            conn.commit()
            row = conn.execute(_SELECT + "WHERE i.id=?", (item_id,)).fetchone()
            result = _row_public(row)
        except Exception:
            _remove(dest)
            raise
    clip_state.set_flags(job_id, index, archived=True)
    return result


def archive_clips(refs):
    archived, failed = [], []
    for ref in refs or []:
        try:
            job_id = (ref or {}).get("job_id")
            index = (ref or {}).get("index")
            archived.append(archive_clip(job_id, index))
        except Exception as exc:
            failed.append({
                "job_id": (ref or {}).get("job_id"),
                "index": (ref or {}).get("index"),
                "error": str(exc)[:300] or "Could not archive this clip.",
            })
    return {"archived": archived, "failed": failed}


def unarchive(item_id):
    """Move an archived clip back into its job folder (the Clip Gallery).

    A local archive is a rename; a vaulted clip is copied out with the same
    hash check as a push, the vault entry is freed, and only then does the
    index row and the local archive copy go. So one button returns a clip to
    main storage whether it sits on this PC or in a connected vault.
    """
    ensure()
    row = _raw_item(item_id)
    if row is None:
        raise KeyError("not found")
    state = row["state"]
    if state == "pushing":
        raise ValueError("Wait for the vault copy to finish before returning this clip.")
    if state == "pending_delete":
        raise ValueError("This clip is queued for deletion; it cannot return to the gallery.")
    if state not in ("local", "vaulted"):
        raise ValueError("This clip is not available right now.")
    job_dir = _job_dir(row["job_id"])
    if not os.path.isdir(job_dir) or not _metadata_path(job_dir):
        raise ValueError(
            "The original job folder is gone, so this clip cannot return to the "
            "gallery. Download it instead.")
    index = int(row["clip_index"])
    target_video = os.path.join(job_dir, f"clip_{index + 1}.mp4")
    _remove(target_video)

    if state == "local":
        source = os.path.join(_files_dir(), row["id"], row["local_video"] or "video.mp4")
        if not os.path.isfile(source):
            raise ValueError("The archived video file is missing.")
        _move(source, target_video)
    else:
        vault = _raw_vault(row["vault_id"])
        if vault is None or not vault["connected"] or not os.path.isfile(vault["path"] or ""):
            raise ValueError(
                "Connect the vault that holds this clip before returning it to the gallery.")
        try:
            _copy_vault_entry(vault, row, target_video)
            # The gallery copy is verified before the vault space is freed.
            _remove_vault_entry(vault, row)
        except Exception:
            _remove(target_video)
            raise

    poster = os.path.join(_files_dir(), row["id"], row["local_poster"] or "") if row["local_poster"] else ""
    if poster and os.path.isfile(poster):
        _remove(os.path.join(job_dir, f"poster_clip_{index + 1}.jpg"))
        _move(poster, os.path.join(job_dir, f"poster_clip_{index + 1}.jpg"))
    _remove(os.path.join(_files_dir(), row["id"]))
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
    # A gallery scan prunes state for clips with no file, which is exactly what
    # an archived clip is. Restore the posted marks from the archive row so the
    # clip does not come back as a fresh, unposted one.
    platforms = None
    if row["platform_fb"] or row["platform_yt"]:
        platforms = {"facebook": bool(row["platform_fb"]),
                     "youtube": bool(row["platform_yt"])}
    clip_state.set_flags(
        row["job_id"], index, archived=False, platforms=platforms,
        used=True if (row["posted_at"] and platforms is None) else None)
    return {"unarchived": item_id, "job_id": row["job_id"], "index": index}


def unarchive_ref(job_id, index):
    """The gallery's archive toggle: use the item when there is one."""
    ensure()
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT id FROM items WHERE job_id=? AND clip_index=?",
            (str(job_id), int(index))).fetchone()
    if row:
        return unarchive(row["id"])
    return clip_state.set_flags(job_id, index, archived=False)


def import_legacy_archived():
    """Adopt clips archived before this page existed (flag set, file on disk).

    The old archive only flipped a flag, so those files were still inside the
    job dirs and at the mercy of the retention sweep. This moves them once.
    Files that are already gone are simply skipped.
    """
    imported = 0
    for key, flags in clip_state.snapshot().items():
        if not flags.get("archived"):
            continue
        try:
            job_id, index = key.rsplit(":", 1)
            with _lock, _conn() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM items WHERE job_id=? AND clip_index=?",
                    (job_id, int(index))).fetchone()
            if exists:
                continue
            archive_clip(job_id, int(index))
            imported += 1
        except Exception:
            continue
    return imported


def _raw_item(item_id):
    if not valid_item_id(item_id):
        return None
    ensure()
    with _lock, _conn() as conn:
        return conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


def delete_items(item_ids):
    """Delete archived clips: locally now, in a vault when that device returns."""
    ensure()
    results = {"deleted": [], "queued": [], "failed": []}
    for item_id in item_ids or []:
        row = _raw_item(item_id)
        if row is None:
            results["failed"].append({"id": item_id, "error": "Not in the archive."})
            continue
        state = row["state"]
        if state == "pushing":
            with _lock, _conn() as conn:
                conn.execute(
                    "UPDATE items SET cancel_requested=1, delete_after=1 WHERE id=?",
                    (item_id,))
                conn.commit()
            results["queued"].append(item_id)
            continue
        if state == "pending_delete":
            results["queued"].append(item_id)
            continue
        if state == "vaulted":
            vault = _raw_vault(row["vault_id"])
            if vault is None or not vault["connected"]:
                with _lock, _conn() as conn:
                    conn.execute(
                        "UPDATE items SET state='pending_delete', error=NULL, updated_at=? "
                        "WHERE id=?", (_now(), item_id))
                    conn.commit()
                results["queued"].append(item_id)
                continue
            try:
                _remove_vault_entry(vault, row)
            except Exception as exc:
                results["failed"].append({"id": item_id, "error": str(exc)[:300]})
                continue
        _drop_item_files(item_id)
        with _lock, _conn() as conn:
            conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            conn.commit()
        results["deleted"].append(item_id)
    return results


def _raw_vault(vault_id):
    if not valid_vault_id(vault_id):
        return None
    ensure()
    with _lock, _conn() as conn:
        return conn.execute("SELECT * FROM vaults WHERE id=?", (vault_id,)).fetchone()


def _drop_item_files(item_id):
    _remove(os.path.join(_files_dir(), item_id))


def _remove_vault_entry(vault, row, header=None):
    path = vault["path"]
    if not path or not os.path.isfile(path):
        raise VaultMissing("That vault is not connected.")
    offset = row["vault_entry_off"]
    if offset is None:
        raise ValueError("The vault entry has no location recorded.")
    with _lock:
        with open(path, "r+b") as handle:
            header = header or _read_header(path)
            entry = _read_entry(handle, int(offset))
            alloc = int((entry or {}).get("alloc") or row["vault_entry_size"] or 0)
            if entry and not entry.get("deleted"):
                entry["deleted"] = True
                handle.seek(int(offset))
                handle.write(_entry_bytes(entry))
            if alloc:
                _release(header, int(offset), alloc)
            _write_header(handle, header)
            handle.flush()
            os.fsync(handle.fileno())
            used = _used_bytes(header)
        with _conn() as conn:
            conn.execute("UPDATE vaults SET used_bytes=? WHERE id=?",
                         (used, vault["id"]))
            conn.commit()


# --------------------------------------------------------------------------- #
# Push queue
# --------------------------------------------------------------------------- #
def push_items(item_ids, vault_id):
    """Queue archived clips for a verified move into a connected vault."""
    ensure()
    vault = _raw_vault(vault_id)
    if vault is None:
        raise KeyError("Vault not found")
    if vault["state"] == "creating":
        raise ValueError("That vault is still being prepared.")
    if vault["state"] == "expanding":
        raise ValueError("That vault is still expanding.")
    if not vault["connected"]:
        raise ValueError(f"Connect the device that holds “{vault['name']}” first.")
    queued = []
    with _lock, _conn() as conn:
        for item_id in item_ids or []:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                continue
            if row["state"] != "local":
                continue
            source = os.path.join(_files_dir(), row["id"], row["local_video"] or "")
            if not row["local_video"] or not os.path.isfile(source):
                continue
            conn.execute(
                "UPDATE items SET state='pushing', vault_id=?, progress_bytes=0, "
                "error=NULL, cancel_requested=0, delete_after=0, updated_at=? WHERE id=?",
                (vault_id, _now(), item_id))
            queued.append(item_id)
        conn.commit()
    if queued:
        _kick()
    return {"queued": queued}


def cancel_push(item_id):
    with _lock:
        _cancelled.add(item_id)
    ensure()
    with _conn() as conn:
        conn.execute("UPDATE items SET cancel_requested=1 WHERE id=?", (item_id,))
        conn.commit()
    return {"cancelled": item_id}


def _copy_vault_entry(vault, row, dest):
    """Copy one vault entry's payload to ``dest`` and verify its SHA-256."""
    offset = row["vault_entry_off"]
    if offset is None:
        raise ValueError("The vault entry has no location recorded.")
    with open(vault["path"], "rb") as handle, open(dest, "wb") as out:
        handle.seek(int(offset) + ENTRY_HEADER)
        remaining = int(row["size_bytes"] or 0)
        digest = hashlib.sha256()
        while remaining > 0:
            chunk = handle.read(min(COPY_CHUNK, remaining))
            if not chunk:
                raise ValueError("The vault entry is shorter than recorded.")
            out.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        out.flush()
        os.fsync(out.fileno())
    if row["sha256"] and digest.hexdigest() != row["sha256"]:
        _remove(dest)
        raise ValueError("The restored bytes do not match the original hash.")


def restore_items(item_ids):
    """Copy vaulted clips back to local archive storage (then optional unarchive)."""
    ensure()
    results = {"restored": [], "failed": []}
    for item_id in item_ids or []:
        row = _raw_item(item_id)
        if row is None:
            results["failed"].append({"id": item_id, "error": "Not in the archive."})
            continue
        if row["state"] == "local":
            results["restored"].append(item_id)
            continue
        if row["state"] != "vaulted":
            results["failed"].append({"id": item_id, "error": "This clip cannot be restored right now."})
            continue
        vault = _raw_vault(row["vault_id"])
        if vault is None or not vault["connected"] or not os.path.isfile(vault["path"] or ""):
            results["failed"].append({"id": item_id, "error": "Connect the vault that holds this clip."})
            continue
        try:
            dest_dir = os.path.join(_files_dir(), item_id)
            os.makedirs(dest_dir, exist_ok=True)
            name = "video" + (os.path.splitext(row["local_video"] or "video.mp4")[1] or ".mp4")
            dest = os.path.join(dest_dir, name)
            _copy_vault_entry(vault, row, dest)
            # The copy is safe on disk: free the space in the vault.
            _remove_vault_entry(vault, row)
            with _lock, _conn() as conn:
                conn.execute(
                    "UPDATE items SET state='local', vault_id=NULL, vault_entry_off=NULL, "
                    "vault_entry_size=NULL, local_video=?, error=NULL, updated_at=? "
                    "WHERE id=?",
                    (name, _now(), item_id))
                conn.commit()
            results["restored"].append(item_id)
        except Exception as exc:
            results["failed"].append({"id": item_id, "error": str(exc)[:300]})
    return results


def _set_item(item_id, **fields):
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key}=?" for key in fields)
    with _lock, _conn() as conn:
        conn.execute(f"UPDATE items SET {assignments} WHERE id=?",
                     list(fields.values()) + [item_id])
        conn.commit()


def _set_vault(vault_id, **fields):
    assignments = ", ".join(f"{key}=?" for key in fields)
    with _lock, _conn() as conn:
        conn.execute(f"UPDATE vaults SET {assignments} WHERE id=?",
                     list(fields.values()) + [vault_id])
        conn.commit()


def _kick():
    global _worker_running
    with _lock:
        if _worker_running:
            return
        _worker_running = True
    threading.Thread(target=_work_loop, daemon=True,
                     name="archive-worker").start()


def _next_work():
    with _lock, _conn() as conn:
        vault = conn.execute(
            "SELECT * FROM vaults WHERE state='creating' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if vault:
            return ("create", vault)
        vault = conn.execute(
            "SELECT * FROM vaults WHERE state='expanding' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if vault:
            return ("expand", vault)
        vault = conn.execute(
            "SELECT * FROM vaults WHERE state='deleting' LIMIT 1").fetchone()
        if vault:
            return ("delete", vault)
        item = conn.execute(
            "SELECT * FROM items WHERE state='pushing' ORDER BY updated_at ASC LIMIT 1"
        ).fetchone()
        if item:
            return ("push", item)
        item = conn.execute(
            "SELECT * FROM items WHERE state='pending_delete' ORDER BY updated_at ASC LIMIT 1"
        ).fetchone()
        if item:
            vault = _vault_row(conn, item["vault_id"])
            if vault and vault["connected"]:
                return ("delete_item", item)
        return None


def _work_loop():
    global _worker_running
    try:
        while True:
            work = _next_work()
            if work is None:
                return
            kind, row = work
            try:
                if kind == "create":
                    _create_one(row["id"])
                elif kind == "expand":
                    _expand_one(row["id"])
                elif kind == "delete":
                    _finish_vault_delete(row["id"])
                elif kind == "push":
                    _push_one(row["id"])
                elif kind == "delete_item":
                    _delete_pending(row["id"])
            except _Cancelled:
                pass
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the queue
                print(f"⚠️ archive worker: {exc}")
    finally:
        with _lock:
            _worker_running = False
        # A row added while this thread was finishing still needs a worker.
        if _has_work():
            _kick()


def _has_work():
    with _lock, _conn() as conn:
        if conn.execute("SELECT 1 FROM vaults WHERE state IN "
                        "('creating','expanding','deleting') LIMIT 1").fetchone():
            return True
        if conn.execute("SELECT 1 FROM items WHERE state='pushing' LIMIT 1").fetchone():
            return True
        row = conn.execute(
            "SELECT i.id FROM items i JOIN vaults v ON v.id=i.vault_id "
            "WHERE i.state='pending_delete' AND v.connected=1 LIMIT 1").fetchone()
        return row is not None


def _progress_callback(vault_id, capacity):
    last = [0.0]

    def report(done, _total=None):
        now = _now()
        if now - last[0] < 0.4 and done < capacity:
            return
        last[0] = now
        _set_vault(vault_id, progress_bytes=int(done))

    return report


def _create_one(vault_id):
    vault = _raw_vault(vault_id)
    if vault is None:
        return
    folder = vault["folder"]
    path = vault["path"] or os.path.join(folder, vault["file_name"])
    if not os.path.isdir(folder):
        _set_vault(vault_id, state="error", error="That folder is no longer available.")
        return
    try:
        _preallocate(
            path, int(vault["capacity_bytes"]),
            on_progress=_progress_callback(vault_id, int(vault["capacity_bytes"])),
            cancelled=lambda: vault_id in _cancelled_vaults)
        header = {
            "format": 1,
            "id": vault_id,
            "name": vault["name"],
            "key": vault["key"],
            "capacity": int(vault["capacity_bytes"]),
            "data_start": DATA_START,
            "next": DATA_START,
            "free": [],
            "created_at": vault["created_at"],
        }
        with open(path, "r+b") as handle:
            _write_header(handle, header)
            handle.flush()
            os.fsync(handle.fileno())
        _set_vault(vault_id, state="ready", connected=1, path=path,
                   rel_folder=_rel_folder(folder), progress_bytes=0, error=None,
                   last_seen=_now(), used_bytes=0)
    except _Cancelled:
        _remove(path)
        with _lock, _conn() as conn:
            conn.execute("DELETE FROM vaults WHERE id=?", (vault_id,))
            conn.commit()
        _cancelled_vaults.discard(vault_id)
    except Exception as exc:
        _remove(path)
        _set_vault(vault_id, state="error", connected=0, progress_bytes=0,
                   error=(str(exc).strip() or "Could not create the vault file.")[:400])


def _expand_one(vault_id):
    vault = _raw_vault(vault_id)
    if vault is None:
        return
    path = vault["path"]
    try:
        if not path or not os.path.isfile(path):
            raise VaultMissing("The vault is not connected.")
        current = os.path.getsize(path)
        target = int(vault["capacity_bytes"])
        if target <= current:
            _set_vault(vault_id, state="ready", progress_bytes=0)
            return
        zero = b"\0" * COPY_CHUNK
        done = current
        with open(path, "ab") as handle:
            while done < target:
                amount = min(len(zero), target - done)
                handle.write(zero[:amount])
                done += amount
                _set_vault(vault_id, progress_bytes=done)
            handle.flush()
            os.fsync(handle.fileno())
        header = _read_header(path)
        header["capacity"] = target
        with open(path, "r+b") as handle:
            _write_header(handle, header)
            handle.flush()
            os.fsync(handle.fileno())
        _set_vault(vault_id, state="ready", capacity_bytes=target,
                   progress_bytes=0, error=None, connected=1)
    except Exception as exc:
        # The file may be partly grown; the header still has the old capacity,
        # which is safe. Put the row back to ready at its usable size.
        try:
            size = os.path.getsize(path) if path and os.path.isfile(path) else None
            header = _read_header(path) if size else None
            usable = int(header["capacity"]) if header else None
            # A half-written growth must not keep phantom bytes on the device.
            if usable and size and size > usable:
                try:
                    os.truncate(path, usable)
                except OSError:
                    pass
        except Exception:
            usable = None
        _set_vault(vault_id, state="ready", progress_bytes=0,
                   capacity_bytes=usable or vault["capacity_bytes"],
                   error=(str(exc).strip() or "Could not expand the vault.")[:400])


def _finish_vault_delete(vault_id):
    vault = _raw_vault(vault_id)
    if vault is None:
        return
    path = vault["path"]
    with _lock, _conn() as conn:
        item_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM items WHERE vault_id=?", (vault_id,)).fetchall()]
        conn.execute("DELETE FROM items WHERE vault_id=?", (vault_id,))
        conn.execute("DELETE FROM vaults WHERE id=?", (vault_id,))
        conn.execute("DELETE FROM foreign_vaults WHERE path=?", (path,))
        conn.commit()
    for item_id in item_ids:
        _drop_item_files(item_id)
    if path:
        _remove(path)
    _cancelled_vaults.discard(vault_id)


def _push_one(item_id):
    row = _raw_item(item_id)
    if row is None:
        return
    vault = _raw_vault(row["vault_id"])
    source = os.path.join(_files_dir(), row["id"], row["local_video"] or "")
    try:
        if vault is None:
            raise VaultMissing("The vault was removed.")
        if vault["state"] != "ready" or not vault["connected"]:
            raise VaultMissing(f"Connect the device that holds “{vault['name']}”.")
        if not row["local_video"] or not os.path.isfile(source):
            raise ValueError("The local clip file is missing.")
        path = vault["path"]
        if not path or not os.path.isfile(path):
            raise VaultMissing("The vault file is not there anymore.")

        def cancelled():
            return item_id in _cancelled or _cancel_requested(item_id)

        size = os.path.getsize(source)
        need = _padded_size(size)
        with open(path, "r+b") as handle:
            header = _read_header(path)
            offset = _allocate(header, need)
            sha, copied = _copy_to_vault(
                handle, offset, source,
                lambda done, _total: (done % (8 * 1024 * 1024) < COPY_CHUNK
                                      and _set_item(item_id, progress_bytes=done)),
                cancelled)
            if row["sha256"] and sha != row["sha256"]:
                raise ValueError(
                    "The copied bytes do not match the archived file's hash; "
                    "the local copy was kept.")
            record = {
                "id": item_id,
                "name": row["title"] or os.path.basename(source),
                "size": copied,
                "sha256": sha,
                "created_at": row["archived_at"],
                "deleted": False,
                "alloc": need,
            }
            handle.seek(offset)
            handle.write(_entry_bytes(record))
            handle.flush()
            os.fsync(handle.fileno())
            _write_header(handle, header)
            handle.flush()
            os.fsync(handle.fileno())
            used = _used_bytes(header)

        _set_item(item_id, state="vaulted", vault_entry_off=offset,
                  vault_entry_size=need, sha256=sha, progress_bytes=0,
                  error=None, cancel_requested=0)
        _set_vault(vault["id"], used_bytes=used, last_seen=_now())
        _remove(source)
        if row["delete_after"]:
            delete_items([item_id])
    except _Cancelled:
        _set_item(item_id, state="local", progress_bytes=0, cancel_requested=0,
                  error=None, vault_id=None)
        if _delete_after(item_id):
            _drop_item_files(item_id)
            with _lock, _conn() as conn:
                conn.execute("DELETE FROM items WHERE id=?", (item_id,))
                conn.commit()
    except Exception as exc:
        _set_item(item_id, state="local", progress_bytes=0, cancel_requested=0,
                  error=(str(exc).strip() or "Could not write to the vault.")[:400])
        if _delete_after(item_id):
            _drop_item_files(item_id)
            with _lock, _conn() as conn:
                conn.execute("DELETE FROM items WHERE id=?", (item_id,))
                conn.commit()
    finally:
        with _lock:
            _cancelled.discard(item_id)


def _cancel_requested(item_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT cancel_requested FROM items WHERE id=?",
                           (item_id,)).fetchone()
        return bool(row and row["cancel_requested"])


def _delete_after(item_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT delete_after FROM items WHERE id=?",
                           (item_id,)).fetchone()
        return bool(row and row["delete_after"])


def _delete_pending(item_id):
    row = _raw_item(item_id)
    if row is None:
        return
    vault = _raw_vault(row["vault_id"])
    if vault is None or not vault["connected"]:
        return
    try:
        _remove_vault_entry(vault, row)
    except Exception:
        return
    _drop_item_files(item_id)
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()


# --------------------------------------------------------------------------- #
# Playback: a slice of a container file
# --------------------------------------------------------------------------- #
def stream_source(item_id):
    """``(path, offset, size, name)`` for one archived item, or ``None``."""
    row = _raw_item(item_id)
    if row is None:
        return None
    name = (row["title"] or "clip")[:80]
    if row["state"] == "local":
        path = os.path.join(_files_dir(), row["id"], row["local_video"] or "")
        if not os.path.isfile(path):
            return None
        return path, 0, os.path.getsize(path), name
    if row["state"] != "vaulted":
        return None
    vault = _raw_vault(row["vault_id"])
    if vault is None or not vault["connected"] or not os.path.isfile(vault["path"] or ""):
        return None
    offset = row["vault_entry_off"]
    if offset is None:
        _set_item(item_id, state="missing",
                  error="The vault entry has no recorded location.")
        return None
    try:
        with open(vault["path"], "rb") as handle:
            entry = _read_entry(handle, int(offset))
    except OSError:
        return None
    if not entry or entry.get("deleted"):
        _set_item(item_id, state="missing",
                  error="The vault entry is gone from the container.")
        return None
    return vault["path"], int(offset) + ENTRY_HEADER, int(row["size_bytes"] or 0), name


def poster_path(item_id):
    row = _raw_item(item_id)
    if row is None or not row["local_poster"]:
        return None
    path = os.path.join(_files_dir(), row["id"], row["local_poster"])
    return path if os.path.isfile(path) else None


def byte_range(header, size):
    """``(start, end)`` for one HTTP Range header, or ``None`` for the whole file.

    Multi-range requests are answered with their first range: a browser's
    ``<video>`` never sends one, and 206 with a single part is a valid answer.
    """
    if not header or not str(header).strip().lower().startswith("bytes="):
        return None
    spec = str(header).split("=", 1)[1].split(",")[0].strip()
    if "-" not in spec:
        raise ValueError("bad range")
    raw_start, raw_end = spec.split("-", 1)
    try:
        if raw_start == "":
            suffix = int(raw_end)
            if suffix <= 0:
                raise ValueError("bad range")
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
    except (TypeError, ValueError):
        raise ValueError("bad range")
    end = min(end, size - 1)
    if start < 0 or start > end or start >= size:
        raise ValueError("bad range")
    return start, end


# --------------------------------------------------------------------------- #
# Auto-archive rule
# --------------------------------------------------------------------------- #
def _posted_at(flags):
    """When the clip went out: the newest platform mark, else the legacy mark."""
    times = [value for value in (flags.get("platform_times") or {}).values() if value]
    return max(times) if times else flags.get("used_at")


def _posted_platforms(flags):
    """The platforms a clip is marked posted on, as a set."""
    return {name for name, on in (flags.get("platforms") or {}).items() if on}


def _auto_cutoff(settings, now):
    return now - int(settings.get("auto_archive_days") or 0) * 86400


def auto_archive_once(now=None):
    """Archive clips posted on **both** platforms longer ago than the delay.

    One-platform clips are deliberately left alone: they still wait for the
    matching staged button (:func:`staged_archives`), so the auto rule never
    removes a clip the user only put out in one place. Times come from
    ``clip_state``'s persisted platform marks, so the delay elapses whether or
    not the app was running.
    """
    settings = get_settings()
    if not settings.get("auto_archive_enabled"):
        return 0
    now = now or _now()
    cutoff = _auto_cutoff(settings, now)
    archived = 0
    for key, flags in clip_state.snapshot().items():
        if flags.get("archived"):
            continue
        if _posted_platforms(flags) != set(clip_state.PLATFORMS):
            continue
        posted = _posted_at(flags)
        if not posted or posted > cutoff:
            continue
        try:
            job_id, index = key.rsplit(":", 1)
            archive_clip(job_id, int(index))
            archived += 1
        except Exception:
            continue
    return archived


def staged_archives(now=None):
    """Single-platform clips waiting for the user's permission, by platform.

    A clip posted on only YouTube or only Facebook is never moved by the rule:
    it is listed here as soon as its one mark exists, and the gallery draws one
    button per non-empty group. Nothing leaves the library until that button is
    pressed. The answer is derived from the persisted posting marks, so it
    survives restarts and days when the app was closed.
    """
    settings = get_settings()
    result = {
        "enabled": bool(settings.get("auto_archive_enabled")),
        "days": int(settings.get("auto_archive_days") or 0),
        "facebook": [],
        "youtube": [],
    }
    if not result["enabled"]:
        return result
    for key, flags in clip_state.snapshot().items():
        if flags.get("archived"):
            continue
        posted_on = _posted_platforms(flags)
        if len(posted_on) != 1:
            continue
        platform = next(iter(posted_on))
        if platform not in result:
            continue
        if not _posted_at(flags):
            continue
        try:
            job_id, index = key.rsplit(":", 1)
            index = int(index)
        except (TypeError, ValueError):
            continue
        # A stale mark for a swept job must not inflate the button count.
        if not _clip_file(_job_dir(job_id), index):
            continue
        result[platform].append({"job_id": job_id, "index": index})
    return result


def archive_staged(platform, now=None):
    """Run the staged group for one platform (the button behind the count)."""
    platform = str(platform or "").strip().lower()
    if platform not in clip_state.PLATFORMS:
        raise ValueError("platform must be facebook or youtube")
    staged = staged_archives(now=now)
    refs = staged.get(platform) or []
    result = archive_clips(refs)
    return {"platform": platform, "staged": len(refs), **result}


# --------------------------------------------------------------------------- #
# Background maintenance
# --------------------------------------------------------------------------- #
def start():
    """Start the scan/auto-archive loop once per process (app lifespan)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    ensure()
    threading.Thread(target=_maintenance_loop, daemon=True,
                     name="archive-maintenance").start()
    _kick()


def _maintenance_loop():
    last_auto = 0.0
    legacy = False
    while True:
        try:
            if not legacy:
                import_legacy_archived()
                legacy = True
            scan()
            _kick()
            if _now() - last_auto >= AUTO_ARCHIVE_INTERVAL:
                last_auto = _now()
                auto_archive_once()
        except Exception:
            pass
        time.sleep(SCAN_INTERVAL)
