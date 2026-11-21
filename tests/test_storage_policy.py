"""Storage policy: a split state/media root and no silent deletions.

The old default (24 h retention + a 10 GB output cap measured only on
``Storage/videos``) deleted a day of finished renders while the user was
generating more. These pin both halves of the fix:

* state (settings, thumbnails) can stay on the app drive while the media tree
  moves to an external disk, and a missing disk is reported, never raised;
* 0 means "keep forever" for the retention sweeps and the size caps.
"""
import json
import os
import subprocess
import sys
import time

import pytest

import storage

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# Two roots
# --------------------------------------------------------------------------- #
def _paths(tmp_path, with_media):
    state = tmp_path / "state"
    media = tmp_path / "media"
    env = {**os.environ, "OPENSHORTS_STORAGE": str(state)}
    env.pop("OPENSHORTS_MEDIA", None)
    if with_media:
        env["OPENSHORTS_MEDIA"] = str(media)
    code = (
        "import json, storage;"
        "storage.ensure();"
        "print(json.dumps({"
        "'videos': storage.VIDEOS_DIR, 'thumbnails': storage.THUMBNAILS_DIR,"
        "'uploads': storage.UPLOADS_DIR, 'collector': storage.COLLECTOR_DIR,"
        "'archive': storage.ARCHIVE_DIR, 'status': storage.status(),"
        "'exists': __import__('os').path.isdir(storage.VIDEOS_DIR)}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, env=env,
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_media_can_live_on_another_drive_while_state_stays_local(tmp_path):
    paths = _paths(tmp_path, with_media=True)
    assert paths["exists"] is True
    assert os.path.commonpath([paths["videos"], str(tmp_path / "media")]) \
        == str(tmp_path / "media")
    assert os.path.commonpath([paths["uploads"], str(tmp_path / "media")]) \
        == str(tmp_path / "media")
    assert os.path.commonpath([paths["collector"], str(tmp_path / "media")]) \
        == str(tmp_path / "media")
    assert os.path.commonpath([paths["archive"], str(tmp_path / "media")]) \
        == str(tmp_path / "media")
    # Small state never leaves the app drive.
    assert os.path.commonpath([paths["thumbnails"], str(tmp_path / "state")]) \
        == str(tmp_path / "state")
    assert paths["status"]["online"] is True
    assert paths["status"]["separate"] is True


def test_without_a_media_root_everything_stays_in_one_tree(tmp_path):
    paths = _paths(tmp_path, with_media=False)
    assert os.path.commonpath([paths["videos"], str(tmp_path / "state")]) \
        == str(tmp_path / "state")
    assert paths["status"]["separate"] is False
    assert paths["status"]["online"] is True


def test_a_missing_media_drive_is_offline_and_never_raises(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("drive letters are a Windows concept")
    if os.path.isdir("Z:\\"):
        pytest.skip("Z: exists on this machine")
    monkeypatch.setattr(storage, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(storage, "MEDIA_DIR", "Z:\\OpenShorts\\Storage")
    assert storage.media_available() is False
    assert storage.ensure_media() is False
    assert "not connected" in storage.MEDIA_OFFLINE_MESSAGE


# --------------------------------------------------------------------------- #
# 0 = keep forever
# --------------------------------------------------------------------------- #
def _old(path, age=7200):
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def _job(root, name="job-1"):
    job = root / name
    job.mkdir(parents=True)
    meta = job / f"{name}_metadata.json"
    meta.write_text("{}", encoding="utf-8")
    _old(meta)
    _old(job)
    return job


def test_zero_retention_keeps_finished_jobs(tmp_path, monkeypatch):
    app = pytest.importorskip("app")
    videos = tmp_path / "videos"
    monkeypatch.setattr(app, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(app, "THUMBNAILS_DIR", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(app, "JOB_RETENTION_SECONDS", 0)
    job = _job(videos)
    app._sweep_expired_job_dirs(time.time() + 10 ** 6)
    assert job.is_dir(), "a finished render must never age out when retention is 0"


def test_zero_retention_keeps_upload_sources(tmp_path, monkeypatch):
    app = pytest.importorskip("app")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "job-1_source.mp4"
    source.write_bytes(b"source")
    _old(source)
    monkeypatch.setattr(app, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(app, "JOB_RETENTION_SECONDS", 0)
    app._sweep_expired_uploads(time.time() + 10 ** 6)
    assert source.is_file()


def test_zero_caps_never_trim_output_or_uploads(tmp_path, monkeypatch):
    app = pytest.importorskip("app")
    videos = tmp_path / "videos"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    job = _job(videos)
    source = uploads / "job-1_source.mp4"
    source.write_bytes(b"x" * 4096)
    monkeypatch.setattr(app, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(app, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(app, "OUTPUT_MAX_GB", 0)
    monkeypatch.setattr(app, "UPLOADS_MAX_GB", 0)
    app._enforce_output_size_cap()
    app._enforce_uploads_size_cap()
    assert job.is_dir() and source.is_file()


def test_a_positive_retention_still_cleans_up(tmp_path, monkeypatch):
    """The knob keeps working: 0 is a policy, not a broken sweep."""
    app = pytest.importorskip("app")
    videos = tmp_path / "videos"
    monkeypatch.setattr(app, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(app, "THUMBNAILS_DIR", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(app, "JOB_RETENTION_SECONDS", 60)
    job = _job(videos, "job-old")
    app._sweep_expired_job_dirs(time.time())
    assert not job.exists()


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
def test_config_reports_the_media_root(monkeypatch):
    app = pytest.importorskip("app")
    from fastapi.testclient import TestClient

    body = TestClient(app.app).get("/api/config").json()
    assert "storage" in body
    assert {"media", "state", "online", "separate"} <= set(body["storage"])
    # 0 is reported as 0; the dashboard renders it as "keep everything".
    assert body["outputMaxGb"] == app.OUTPUT_MAX_GB
    assert body["uploadsMaxGb"] == app.UPLOADS_MAX_GB


def test_a_render_is_refused_with_503_when_the_media_drive_is_missing(monkeypatch):
    app = pytest.importorskip("app")
    monkeypatch.setattr(app.storage, "media_available", lambda: False)
    with pytest.raises(app.HTTPException) as exc:
        app._require_media()
    assert exc.value.status_code == 503
    assert "media drive" in str(exc.value.detail).lower()
