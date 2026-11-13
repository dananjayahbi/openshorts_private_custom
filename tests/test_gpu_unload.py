"""The Home dashboard's Unload VRAM action.

Jobs run in their own processes, but the API is long-lived and keeps models
from in-process passes (subtitle re-burn, thumbnail studio, clip editor). The
button drops those and reports the nvidia-smi before/after. It must refuse while
a job is running: that job owns a different process and unloading under it would
only fail the render.
"""
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


@pytest.fixture()
def client():
    app_module = pytest.importorskip("app")
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


def test_unload_reports_the_before_after_and_what_it_dropped(client, monkeypatch):
    app_module = pytest.importorskip("app")
    monkeypatch.setattr(app_module, "jobs", {})
    readings = iter([{"usedMb": 4200}, {"usedMb": 1800}])
    monkeypatch.setattr(app_module, "_gpu_snapshot",
                        lambda fresh=False: next(readings, {"usedMb": 0}))
    monkeypatch.setattr(app_module, "_unload_gpu_models", lambda: ["asr", "yolo"])

    res = client.post("/api/gpu/unload")

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["beforeMb"] == 4200 and body["afterMb"] == 1800
    assert body["freedMb"] == 2400
    assert body["released"] == ["asr", "yolo"]


def test_it_refuses_while_a_job_is_running(client, monkeypatch):
    app_module = pytest.importorskip("app")
    monkeypatch.setattr(app_module, "jobs", {"j1": {"status": "processing"}})

    def boom():
        raise AssertionError("must not unload under a running job")

    monkeypatch.setattr(app_module, "_unload_gpu_models", boom)
    res = client.post("/api/gpu/unload")
    assert res.status_code == 409
    assert "job is running" in res.json()["detail"].lower()


def test_the_helper_drops_in_process_models(monkeypatch):
    app_module = pytest.importorskip("app")
    import transcribe_backends

    monkeypatch.setattr(transcribe_backends, "release_models", lambda: None)

    closed = {"face": False}

    class FakeFace:
        def close(self):
            closed["face"] = True

    fake_main = types.SimpleNamespace(model=object(), face_detection=FakeFace())
    monkeypatch.setitem(sys.modules, "main", fake_main)

    released = app_module._unload_gpu_models()

    assert fake_main.model is None
    assert fake_main.face_detection is None
    assert closed["face"] is True
    assert "yolo" in released and "mediapipe" in released
    assert "asr" in released


def test_home_has_the_button_and_disables_it_during_a_job():
    with open(os.path.join(SRC, "components", "HomeDashboard.jsx"), encoding="utf-8") as f:
        page = f.read()
    assert "/api/gpu/unload" in page
    assert "unload vram" in page
    assert "jobRunning" in page and "activeJobs" in page
    assert "disabled={unloading || jobRunning}" in page
