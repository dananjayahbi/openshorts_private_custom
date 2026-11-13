"""Stop a job — queued or running — and remove what it wrote.

A stop used to mean "keep going, then stop": there was no way to end a running
render, and a failed run's partial clips/source stayed on disk until the
retention sweep. The endpoint kills the process tree (main.py plus its ffmpeg
children), takes a queued job off the heap, and purges the job dir, source
upload and gallery review keys once the process lets go.
"""
import os

import pytest


@pytest.fixture()
def app_module():
    return pytest.importorskip("app")


@pytest.fixture(autouse=True)
def _restore_jobs():
    """These tests add rows to the module-level job table; put it back."""
    app_module = pytest.importorskip("app")
    saved = dict(app_module.jobs)
    yield
    app_module.jobs.clear()
    app_module.jobs.update(saved)


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


class _FakeProc:
    def __init__(self, alive=True):
        self.pid = 4242
        self.alive = alive
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.killed = True
        self.alive = False


def _job(status="processing", **extra):
    job = {"status": status, "logs": [], "output_dir": "x"}
    job.update(extra)
    return job


def test_cancelling_a_running_job_marks_it_and_kills_the_tree(client, app_module, monkeypatch):
    app_module.jobs["j-running"] = _job()
    proc = _FakeProc()
    monkeypatch.setitem(app_module._job_procs, "j-running", proc)
    calls = {}

    def fake_kill(p):
        calls["proc"] = p
        p.kill()
        return True

    monkeypatch.setattr(app_module, "_kill_job_process", fake_kill)
    purged = []

    async def fake_purge(job_id):
        purged.append(job_id)

    monkeypatch.setattr(app_module, "_purge_cancelled_job", fake_purge)

    res = client.post("/api/jobs/j-running/cancel")

    assert res.status_code == 200
    body = res.json()
    assert body["cancelled"] is True and body["killed"] is True
    assert app_module.jobs["j-running"]["status"] == "cancelled"
    assert app_module.jobs["j-running"]["cancel_requested"] is True
    assert calls["proc"] is proc
    assert app_module.jobs["j-running"]["logs"][-1].startswith("🛑")


def test_cancelling_a_queued_job_takes_it_off_the_heap(client, app_module, monkeypatch):
    app_module.jobs["j-queued"] = _job("queued")
    app_module.job_queue.put_nowait((1, 999_999, "j-queued"))
    before = app_module.job_queue._unfinished_tasks

    async def fake_purge(job_id):
        return None

    monkeypatch.setattr(app_module, "_purge_cancelled_job", fake_purge)
    res = client.post("/api/jobs/j-queued/cancel")

    assert res.status_code == 200
    assert res.json()["queued"] is True
    assert all(entry[2] != "j-queued" for entry in app_module.job_queue._queue)
    # Each entry was put once; the removed one still settles its accounting.
    assert app_module.job_queue._unfinished_tasks == before - 1


def test_a_finished_job_is_not_touched(client, app_module, monkeypatch):
    app_module.jobs["j-done"] = _job("completed")

    async def boom(job_id):
        raise AssertionError("must not purge a completed job")

    monkeypatch.setattr(app_module, "_purge_cancelled_job", boom)
    res = client.post("/api/jobs/j-done/cancel")

    assert res.status_code == 200
    assert res.json()["cancelled"] is False
    assert app_module.jobs["j-done"]["status"] == "completed"


def test_unknown_job_is_404(client):
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_finish_job_keeps_cancelled_status(app_module):
    app_module.jobs["j-cancel"] = _job("cancelled", cancel_requested=True)
    app_module._finish_job("j-cancel", -1, "unused")
    assert app_module.jobs["j-cancel"]["status"] == "cancelled"


def test_purge_removes_the_job_dir_upload_and_review_state(app_module, tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    uploads = tmp_path / "uploads"
    job_dir = videos / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "clip.mp4").write_bytes(b"partial")
    uploads.mkdir()
    (uploads / "job-1_source.mp4").write_bytes(b"source")
    (uploads / "another_job_source.mp4").write_bytes(b"keep")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr("storage.STORAGE_DIR", str(tmp_path))

    import clip_state
    clip_state.set_flags("job-1", 0, used=True)
    assert clip_state.flags("job-1", 0)["used"] is True

    removed = app_module._purge_job_assets("job-1")

    assert not job_dir.exists()
    assert not (uploads / "job-1_source.mp4").exists()
    assert (uploads / "another_job_source.mp4").exists()
    assert clip_state.flags("job-1", 0)["used"] is False
    assert len(removed) == 2


def test_job_kill_uses_taskkill_tree_on_windows(app_module, monkeypatch):
    proc = _FakeProc()
    calls = []

    class Result:
        returncode = 0

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(app_module.os, "name", "nt")
    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    assert app_module._kill_job_process(proc) is True
    assert calls and calls[0][:2] == ["taskkill", "/PID"]
    assert "/T" in calls[0] and "/F" in calls[0]


def test_the_ui_has_stop_on_both_screens():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(repo, "dashboard", "src", "App.jsx"), encoding="utf-8").read()
    batch = open(os.path.join(repo, "dashboard", "src", "components", "BatchQueue.jsx"),
                 encoding="utf-8").read()
    assert "/api/jobs/${id}/cancel" in app or "/api/jobs/${jobId}/cancel" in app
    assert "stopSingleJob" in app
    assert "cancelServerJob(current.jobId)" in app
    assert "stopping" in batch
