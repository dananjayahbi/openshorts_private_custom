"""The app's media root: one ``Storage/`` tree, treated as a local CDN.

Every file the app produces or accepts lives under one directory, so the
library can be inspected, backed up, moved or served by any static server
without hunting through the codebase:

    Storage/videos/<job_id>/...       job outputs, served at /videos/<job_id>/...
    Storage/thumbnails/<session>/...   served at /thumbnails/...
    Storage/uploads/                   transient sources (not served)
    Storage/downloads/<id>/...         full sources fetched by Download Manager (not served)
    Storage/archive/                   archived clips + archive.db (not swept, not served)

Set ``OPENSHORTS_STORAGE`` to move the whole tree (absolute path is fine), for
example to a larger disk. The default is relative: the same line then works in
the container (cwd ``/app``) and natively (repo root), and the test suite can
chdir into a temporary tree.
"""
import os

STORAGE_DIR = os.environ.get("OPENSHORTS_STORAGE", "Storage")
VIDEOS_DIR = os.path.join(STORAGE_DIR, "videos")
THUMBNAILS_DIR = os.path.join(STORAGE_DIR, "thumbnails")
UPLOADS_DIR = os.path.join(STORAGE_DIR, "uploads")
DOWNLOADS_DIR = os.path.join(STORAGE_DIR, "downloads")
ARCHIVE_DIR = os.path.join(STORAGE_DIR, "archive")

# The directories the app writes to. ``videos`` is the only one that is
# served as video; keep the siblings so a sweep of one cannot touch another
# (uploads, thumbnails, downloads and archive have their own retention).
SUBDIRS = (VIDEOS_DIR, THUMBNAILS_DIR, UPLOADS_DIR, DOWNLOADS_DIR, ARCHIVE_DIR)


def ensure():
    """Create the tree; safe to call from every entry point."""
    for path in SUBDIRS:
        os.makedirs(path, exist_ok=True)
    return STORAGE_DIR
