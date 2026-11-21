"""The app's storage roots: state on the app drive, media on the big drive.

Two roots, because they have different jobs:

``OPENSHORTS_STORAGE`` (default ``Storage``) — small, always-present state:
settings, style profiles, clip review flags, Thumbnail Studio sessions and the
cached gallery JPEGs. This must survive an external drive being unplugged.

``OPENSHORTS_MEDIA`` (default: the same as ``OPENSHORTS_STORAGE``) — the large
media tree: job renders, sources, downloads, Collector files and the archive.
Point it at a big disk (``D:\\OpenShorts\\Storage``); unplugging that disk
makes the media pages report "storage drive not connected" instead of losing
the library, and replugging it brings everything back because every path is
recomputed from the root.

Layout:

    <state>/settings.json, style_profiles.json, clip_state.json
    <state>/thumbnails/<session>/...       served at /thumbnails/...
    <media>/videos/<job_id>/...            job outputs, served at /videos/...
    <media>/uploads/                       transient sources (not served)
    <media>/downloads/<id>/...             full sources (not served)
    <media>/collector/                     the Collector shelf, served at /collector/
    <media>/archive/                       archived clips + archive.db

The legacy ``STORAGE_DIR`` name stays as the state root so the small stores
(``clip_state``, ``settings_store``, ``style_profiles``) keep resolving it at
call time, exactly as before.
"""
import os

# Small state: settings, profiles, flags, thumbnail sessions.
STATE_DIR = os.environ.get("OPENSHORTS_STORAGE", "Storage")
# Large media. Without OPENSHORTS_MEDIA everything stays in one tree, which
# keeps the container, the test suite and an old install working unchanged.
MEDIA_DIR = os.environ.get("OPENSHORTS_MEDIA") or STATE_DIR

# Backwards-compatible name: the state root.
STORAGE_DIR = STATE_DIR

# Media tree (big drive).
VIDEOS_DIR = os.path.join(MEDIA_DIR, "videos")
UPLOADS_DIR = os.path.join(MEDIA_DIR, "uploads")
DOWNLOADS_DIR = os.path.join(MEDIA_DIR, "downloads")
COLLECTOR_DIR = os.path.join(MEDIA_DIR, "collector")
ARCHIVE_DIR = os.path.join(MEDIA_DIR, "archive")

# Small tree (app drive). Gallery tiles live inside the job dirs on the media
# drive; Thumbnail Studio sessions are their own folder and stay local.
THUMBNAILS_DIR = os.path.join(STATE_DIR, "thumbnails")

STATE_SUBDIRS = (STATE_DIR, THUMBNAILS_DIR)
MEDIA_SUBDIRS = (VIDEOS_DIR, UPLOADS_DIR, DOWNLOADS_DIR, COLLECTOR_DIR, ARCHIVE_DIR)
SUBDIRS = STATE_SUBDIRS + MEDIA_SUBDIRS

MEDIA_OFFLINE_MESSAGE = (
    "The media drive is not connected. Plug it back in and retry — nothing "
    "was deleted.")


def _same_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False


def _drive_root(path):
    drive, _rest = os.path.splitdrive(os.path.abspath(path))
    return drive + os.sep if drive else os.sep


def media_available():
    """Whether the configured media root can be written to right now.

    A missing drive letter (``D:\\`` unplugged) is the only failure this
    treats as offline. A media root on the same disk as the state always
    counts as available once the app is running.
    """
    if _same_path(MEDIA_DIR, STATE_DIR):
        return True
    try:
        return os.path.isdir(_drive_root(MEDIA_DIR))
    except (OSError, ValueError):
        return False


def _ensure_one(path):
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def ensure_media():
    """Create the media tree when its drive is present. Never raises."""
    if not media_available():
        return False
    ok = True
    for path in MEDIA_SUBDIRS:
        ok = _ensure_one(path) and ok
    return ok


def ensure():
    """Create both trees; a missing media drive is not an error."""
    for path in STATE_SUBDIRS:
        _ensure_one(path)
    ensure_media()
    return STATE_DIR


def status():
    """What the dashboard needs to explain a missing drive."""
    return {
        "media": os.path.abspath(MEDIA_DIR),
        "state": os.path.abspath(STATE_DIR),
        "online": media_available(),
        "separate": not _same_path(MEDIA_DIR, STATE_DIR),
    }
