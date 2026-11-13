"""Gallery review state (used / archived) and its HTTP surface.

The gallery is derived from job dirs, so these flags live in a JSON sidecar
(``clip_state.py``). The tests cover the store on its own and the endpoint
contract the dashboard depends on: flags ride along with every clip, filters
happen before the page is cut, and "archive all used" is one call.
"""
import json
import os

import pytest

import clip_state
import storage


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))
    return tmp_path


class TestStore:
    def test_defaults_are_unused_and_unarchived(self, store):
        assert clip_state.flags("job-1", 0) == {
            "used": False, "archived": False,
            "used_at": None, "archived_at": None,
            "platforms": {"facebook": False, "youtube": False},
            "platform_times": {},
        }

    def test_flags_round_trip_and_untoggle_cleans_up(self, store):
        clip_state.set_flags("job-1", 1, used=True)
        assert clip_state.flags("job-1", 1)["used"] is True
        assert clip_state.flags("job-1", 1)["used_at"]

        clip_state.set_flags("job-1", 1, used=False)
        assert clip_state.flags("job-1", 1)["used"] is False
        # Nothing left for that key: the file holds no dead entries.
        assert json.loads((store / "clip_state.json").read_text()) in ({},)

    def test_archiving_keeps_the_used_flag(self, store):
        clip_state.set_flags("job-1", 0, used=True)
        flags = clip_state.set_flags("job-1", 0, archived=True)
        assert flags["used"] is True and flags["archived"] is True

    def test_archive_used_only_touches_used_clips(self, store):
        clip_state.set_flags("job-1", 0, used=True)
        clip_state.set_flags("job-1", 1, used=False)
        clip_state.set_flags("job-2", 0, used=True, archived=True)  # already done

        assert clip_state.archive_used() == 1
        assert clip_state.flags("job-1", 0)["archived"] is True
        assert clip_state.flags("job-1", 1)["archived"] is False
        assert clip_state.archive_used() == 0

    def test_snapshot_is_one_read(self, store):
        clip_state.set_flags("job-1", 0, used=True)
        snap = clip_state.snapshot()
        assert snap["job-1:0"]["used"] is True
        assert "job-1:0" in snap

    def test_prune_drops_clips_that_no_longer_exist(self, store):
        clip_state.set_flags("gone", 0, used=True)
        clip_state.set_flags("kept", 0, used=True)
        assert clip_state.prune([("kept", 0)]) == 1
        assert clip_state.flags("gone", 0)["used"] is False
        assert clip_state.flags("kept", 0)["used"] is True


class TestPlatforms:
    def test_a_clip_can_be_posted_on_one_platform_only(self, store):
        flags = clip_state.set_flags("job-1", 0, platforms={"facebook": True})
        assert flags["platforms"] == {"facebook": True, "youtube": False}
        assert flags["used"] is True
        assert flags["platform_times"]["facebook"]

        # YouTube on too: still used, both remembered.
        flags = clip_state.set_flags("job-1", 0, platforms={"youtube": True})
        assert flags["platforms"] == {"facebook": True, "youtube": True}

        # Facebook off: YouTube alone keeps it used.
        flags = clip_state.set_flags("job-1", 0, platforms={"facebook": False})
        assert flags["platforms"] == {"facebook": False, "youtube": True}
        assert flags["used"] is True

        # The last platform off: the clip is unused again, and the entry is
        # clean (no dead platform keys left).
        flags = clip_state.set_flags("job-1", 0, platforms={"youtube": False})
        assert flags["used"] is False
        assert flags["platforms"] == {"facebook": False, "youtube": False}
        assert json.loads((store / "clip_state.json").read_text()) in ({},)

    def test_a_legacy_used_flag_counts_and_converts_on_toggle(self, store):
        clip_state.set_flags("job-1", 0, used=True)
        assert clip_state.flags("job-1", 0)["used"] is True
        assert clip_state.flags("job-1", 0)["platforms"] == {"facebook": False, "youtube": False}

        flags = clip_state.set_flags("job-1", 0, platforms={"youtube": True})
        assert flags["platforms"]["youtube"] is True and flags["used"] is True

        flags = clip_state.set_flags("job-1", 0, platforms={"youtube": False})
        assert flags["used"] is False

    def test_archive_used_archives_platform_marked_clips(self, store):
        clip_state.set_flags("job-1", 0, platforms={"facebook": True})
        clip_state.set_flags("job-1", 1, platforms={"youtube": False})
        assert clip_state.archive_used() == 1
        assert clip_state.flags("job-1", 0)["archived"] is True
        assert clip_state.flags("job-1", 1)["archived"] is False

    def test_snapshot_carries_platforms(self, store):
        clip_state.set_flags("job-1", 0, platforms={"youtube": True})
        snap = clip_state.snapshot()["job-1:0"]
        assert snap["platforms"]["youtube"] is True
        assert snap["used"] is True


@pytest.fixture()
def gallery(tmp_path, monkeypatch):
    """Two job dirs with fake clips + metadata, and a TestClient over app."""
    app_module = pytest.importorskip("app")
    from fastapi.testclient import TestClient

    videos = tmp_path / "videos"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))

    def job(job_id, clips):
        d = videos / job_id
        d.mkdir(parents=True)
        (d / f"{job_id}_metadata.json").write_text(json.dumps({"shorts": [
            {"start": 0, "end": 10, "video_title_for_youtube_short": t} for t in clips
        ]}))
        for i in range(len(clips)):
            (d / f"{job_id}_clip_{i + 1}.mp4").write_bytes(b"x")

    job("job-a", ["A0", "A1"])
    job("job-b", ["B0"])
    return TestClient(app_module.app)


def _titles(resp):
    return [c["title"] for c in resp.json()["clips"]]


class TestGalleryApi:
    def test_flags_ride_along_with_every_clip(self, gallery):
        body = gallery.get("/api/gallery/clips").json()
        assert {c["job_id"] for c in body["clips"]} == {"job-a", "job-b"}
        assert body["clips"][0]["used"] is False
        assert body["clips"][0]["archived"] is False
        assert body["counts"] == {"used": 0, "unused": 3, "archived": 0}

    def test_marking_used_shows_in_the_right_filters(self, gallery):
        r = gallery.patch("/api/gallery/clip/job-a/0", json={"used": True})
        assert r.status_code == 200 and r.json()["used"] is True

        assert _titles(gallery.get("/api/gallery/clips")) == ["B0", "A0", "A1"]
        assert _titles(gallery.get("/api/gallery/clips?usage=used")) == ["A0"]
        assert "A0" not in _titles(gallery.get("/api/gallery/clips?usage=unused"))

    def test_platforms_are_separate_and_drive_the_used_tab(self, gallery):
        r = gallery.patch("/api/gallery/clip/job-a/0", json={"platform": "facebook", "posted": True})
        assert r.status_code == 200
        body = r.json()
        assert body["platforms"] == {"facebook": True, "youtube": False}
        assert body["used"] is True
        assert _titles(gallery.get("/api/gallery/clips?usage=used")) == ["A0"]

        # YouTube still pending: the clip can be marked there independently.
        body = gallery.patch("/api/gallery/clip/job-a/0",
                             json={"platforms": {"youtube": True}}).json()
        assert body["platforms"] == {"facebook": True, "youtube": True}

        # Taking it off Facebook leaves YouTube, so it stays used.
        body = gallery.patch("/api/gallery/clip/job-a/0",
                             json={"platform": "facebook", "posted": False}).json()
        assert body["platforms"] == {"facebook": False, "youtube": True}
        assert body["used"] is True

        # Last platform off: it is unused again, not archived.
        body = gallery.patch("/api/gallery/clip/job-a/0",
                             json={"platform": "youtube", "posted": False}).json()
        assert body["used"] is False
        assert body["platforms"] == {"facebook": False, "youtube": False}
        assert _titles(gallery.get("/api/gallery/clips?usage=used")) == []

    def test_an_unknown_platform_is_rejected(self, gallery):
        res = gallery.patch("/api/gallery/clip/job-a/0",
                            json={"platform": "tiktok", "posted": True})
        assert res.status_code == 400
        assert "facebook" in res.json()["detail"]

    def test_flags_carry_platform_names(self, gallery):
        clip = gallery.patch("/api/gallery/clip/job-a/0",
                             json={"platforms": {"youtube": True}}).json()
        for key in ("platforms", "platform_times", "used", "archived"):
            assert key in clip

    def test_delete_one_clip_removes_its_files_and_state(self, gallery, tmp_path, monkeypatch):
        import storage as storage_mod
        job_dir = tmp_path / "videos" / "job-a"
        # Every copy of that index goes: raw, captioned and watermark twins.
        (job_dir / "subtitled_job-a_clip_1.mp4").write_bytes(b"x")
        (job_dir / "wm_job-a_clip_1.mp4").write_bytes(b"x")
        (job_dir / "job-a_clip_1.mp4.layout.json").write_text("{}")
        monkeypatch.setattr(storage_mod, "STORAGE_DIR", str(tmp_path))
        clip_state.set_flags("job-a", 0, platforms={"youtube": True})

        res = gallery.delete("/api/gallery/clip/job-a/0")

        assert res.status_code == 200
        assert res.json()["deleted"] == 1
        assert not (job_dir / "job-a_clip_1.mp4").exists()
        assert not (job_dir / "subtitled_job-a_clip_1.mp4").exists()
        assert not (job_dir / "wm_job-a_clip_1.mp4").exists()
        assert not (job_dir / "job-a_clip_1.mp4.layout.json").exists()
        # The other clip of the same job is untouched.
        assert (job_dir / "job-a_clip_2.mp4").exists()
        assert clip_state.flags("job-a", 0)["used"] is False
        # The gallery no longer lists index 0.
        assert "A0" not in _titles(gallery.get("/api/gallery/clips?view=all"))

    def test_delete_missing_or_invalid_clip(self, gallery):
        assert gallery.delete("/api/gallery/clip/job-a/9").status_code == 404
        assert gallery.delete("/api/gallery/clip/../x/0").status_code in (400, 404)

    def test_bulk_delete_and_idempotency(self, gallery, tmp_path):
        res = gallery.post("/api/gallery/delete", json={"clips": [
            {"job_id": "job-a", "index": 0},
            {"job_id": "job-a", "index": 1},
        ]})
        assert res.status_code == 200
        assert res.json()["deleted"] == 2
        assert _titles(gallery.get("/api/gallery/clips?view=all")) == ["B0"]

        # Running it again deletes nothing (the files are gone), not a 500.
        again = gallery.post("/api/gallery/delete", json={"clips": [
            {"job_id": "job-a", "index": 0},
        ]})
        assert again.status_code == 200
        assert again.json()["deleted"] == 0

    def test_bulk_delete_validates_every_reference(self, gallery):
        assert gallery.post("/api/gallery/delete", json={"clips": []}).status_code == 400
        bad = gallery.post("/api/gallery/delete", json={"clips": [
            {"job_id": "job-a", "index": "nope"}]})
        assert bad.status_code == 400

    def test_archive_moves_a_clip_out_of_the_library(self, gallery):
        gallery.patch("/api/gallery/clip/job-a/1", json={"archived": True})

        assert "A1" not in _titles(gallery.get("/api/gallery/clips"))
        assert _titles(gallery.get("/api/gallery/clips?view=archived")) == ["A1"]
        assert "A1" in _titles(gallery.get("/api/gallery/clips?view=all"))
        counts = gallery.get("/api/gallery/clips").json()["counts"]
        assert counts == {"used": 0, "unused": 2, "archived": 1}

    def test_archive_all_used_is_one_call(self, gallery):
        gallery.patch("/api/gallery/clip/job-a/0", json={"used": True})
        gallery.patch("/api/gallery/clip/job-b/0", json={"used": True})

        assert gallery.post("/api/gallery/archive-used").json() == {"archived": 2}
        assert _titles(gallery.get("/api/gallery/clips")) == ["A1"]
        assert sorted(_titles(gallery.get("/api/gallery/clips?view=archived"))) == ["A0", "B0"]

    def test_restore_puts_a_clip_back(self, gallery):
        gallery.patch("/api/gallery/clip/job-a/0", json={"archived": True, "used": True})
        gallery.patch("/api/gallery/clip/job-a/0", json={"archived": False})
        assert "A0" in _titles(gallery.get("/api/gallery/clips?usage=used"))

    def test_unknown_clip_and_last_page_are_honest(self, gallery):
        assert gallery.patch("/api/gallery/clip/job-a/9", json={"used": True}).status_code == 404
        assert gallery.patch("/api/gallery/clip/../../x/0", json={"used": True}).status_code == 404

        first = gallery.get("/api/gallery/clips?limit=2").json()
        assert len(first["clips"]) == 2 and first["has_more"] is True
        second = gallery.get("/api/gallery/clips?limit=2&offset=2").json()
        assert len(second["clips"]) == 1 and second["has_more"] is False
