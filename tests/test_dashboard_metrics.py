"""Numbers the home dashboard shows: the storage meter and upload posters.

The storage card used to say "0.32 / 310.5 GB": used was this app's folder but
total was the whole drive, so a disk with 22 GB left looked almost empty. The
contract now is used = Storage folder, total = what is actually available.

Collector uploads also take their poster 30 s in, not at 2 s (which landed on
intro/title cards).
"""
import os

import pytest


@pytest.fixture()
def app_module():
    return pytest.importorskip("app")


class TestOverviewStorage:
    def test_total_is_the_space_actually_available(self, app_module, monkeypatch):
        from fastapi.testclient import TestClient

        gb = 1024 ** 3
        monkeypatch.setattr(
            app_module.shutil, "disk_usage",
            lambda _p: type("U", (), {"total": 310 * gb, "used": 288 * gb, "free": 22 * gb})())
        monkeypatch.setattr(app_module, "_dir_size", lambda _p: int(0.32 * gb))

        storage = TestClient(app_module.app).get("/api/overview").json()["storage"]

        assert storage["usedGb"] == 0.32        # the Storage folder
        assert storage["totalGb"] == 22.0       # available, not the 310 GB drive
        assert storage["freeGb"] == 22.0
        assert storage["capacityGb"] == 310.0   # the raw drive size, for the caption


class TestCollectorPosterFrame:
    def _at(self, app_module, monkeypatch, duration):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd

            class Ok:
                returncode = 0
            return Ok()

        monkeypatch.setattr(app_module, "_media_duration_seconds", lambda _p: duration)
        monkeypatch.setattr(app_module.subprocess, "run", fake_run)
        app_module._collector_thumb("in.mp4", "out.jpg")
        cmd = seen["cmd"]
        return float(cmd[cmd.index("-ss") + 1])

    def test_long_uploads_skip_the_intro(self, app_module, monkeypatch, tmp_path):
        assert self._at(app_module, monkeypatch, 480) == 30.0

    def test_short_uploads_use_the_middle(self, app_module, monkeypatch, tmp_path):
        assert self._at(app_module, monkeypatch, 10) == 5.0

    def test_unreadable_duration_falls_back_to_the_start(self, app_module, monkeypatch, tmp_path):
        assert self._at(app_module, monkeypatch, 0) == 0.5
