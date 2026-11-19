"""Gallery review state (used / archived) and its HTTP surface.

The gallery is derived from job dirs, so these flags live in a JSON sidecar
(``clip_state.py``). The tests cover the store on its own and the endpoint
contract the dashboard depends on: flags ride along with every clip, filters
happen before the page is cut, and "archive all used" is one call.
"""
import json
import os
import time

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

    import archive

    videos = tmp_path / "videos"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "VIDEOS_DIR", str(videos))
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(archive, "FILES_DIR", str(tmp_path / "archive" / "files"))
    monkeypatch.setattr(archive, "DB_FILE", str(tmp_path / "archive" / "archive.db"))
    monkeypatch.setattr(archive, "_kick", lambda: None)
    archive.ensure()

    def job(job_id, clips):
        d = videos / job_id
        d.mkdir(parents=True)
        (d / f"{job_id}_metadata.json").write_text(json.dumps({"shorts": [
            {"start": 0, "end": 10, "video_title_for_youtube_short": t} for t in clips
        ]}))
        for i in range(len(clips)):
            (d / f"{job_id}_clip_{i + 1}.mp4").write_bytes(b"x" * 2048)

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

        # Archiving is a move into the permanent store now: the clip is gone
        # from every gallery view and its card lives on the Archive page.
        assert "A1" not in _titles(gallery.get("/api/gallery/clips"))
        assert _titles(gallery.get("/api/gallery/clips?view=archived")) == []
        assert "A1" not in _titles(gallery.get("/api/gallery/clips?view=all"))
        counts = gallery.get("/api/gallery/clips").json()["counts"]
        assert counts == {"used": 0, "unused": 2, "archived": 0}

        archived = gallery.get("/api/archive/items").json()
        assert archived["total"] == 1
        assert archived["items"][0]["title"] == "A1"
        assert archived["items"][0]["state"] == "local"

    def test_archive_all_used_is_one_call(self, gallery):
        gallery.patch("/api/gallery/clip/job-a/0", json={"used": True})
        gallery.patch("/api/gallery/clip/job-b/0", json={"used": True})

        body = gallery.post("/api/gallery/archive-used").json()
        assert body["archived"] == 2 and body["moved"] == 2
        assert body["failed"] == []
        assert _titles(gallery.get("/api/gallery/clips")) == ["A1"]
        assert _titles(gallery.get("/api/gallery/clips?view=archived")) == []
        assert gallery.get("/api/archive/items").json()["total"] == 2

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


class TestGalleryPosters:
    """The grid paints JPEG stills; the clip's <video> exists only in the modal.

    Loading the MP4 in every tile made browser download managers open a shelf
    of MP4 downloads, so the API now hands out a cached poster frame.
    """

    def test_a_cached_poster_rides_along(self, gallery, tmp_path):
        poster = tmp_path / "videos" / "job-a" / "poster_clip_1.jpg"
        poster.write_bytes(b"jpeg")
        body = gallery.get("/api/gallery/clips").json()
        a0 = next(c for c in body["clips"]
                  if c["job_id"] == "job-a" and c["index"] == 0)
        assert a0["poster"] == "/videos/job-a/poster_clip_1.jpg"

    def test_the_poster_size_rides_along_for_the_tile_ratio(self, gallery, tmp_path):
        # The card paints the tile at the clip's aspect ratio; without the size
        # it would have to assume a shape before the JPEG loads.
        from PIL import Image
        poster = tmp_path / "videos" / "job-a" / "poster_clip_1.jpg"
        Image.new("RGB", (640, 1138), "black").save(poster, "JPEG")
        body = gallery.get("/api/gallery/clips").json()
        a0 = next(c for c in body["clips"]
                  if c["job_id"] == "job-a" and c["index"] == 0)
        assert (a0["poster_width"], a0["poster_height"]) == (640, 1138)

    def test_a_missing_poster_is_written_once_and_reused(self, gallery, monkeypatch, tmp_path):
        app_module = pytest.importorskip("app")
        # The fixture's clips are placeholders too small to extract from; make
        # these three look like real renders (the ffmpeg call is faked below).
        for job_id in ("job-a", "job-b"):
            for clip in (tmp_path / "videos" / job_id).glob("*clip_*.mp4"):
                clip.write_bytes(b"x" * (20 * 1024))
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            with open(cmd[-1], "wb") as f:
                f.write(b"\xff\xd8\xff\xd9")
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr(app_module.subprocess, "run", fake_run)

        first = gallery.get("/api/gallery/clips?limit=2").json()
        assert len(first["clips"]) == 2
        assert all(c["poster"].startswith("/videos/") for c in first["clips"])
        assert len(calls) == 2

        second = gallery.get("/api/gallery/clips?limit=2").json()
        assert [c["poster"] for c in second["clips"]] == [c["poster"] for c in first["clips"]]
        assert len(calls) == 2, "a cached poster must not re-run ffmpeg"

    def test_deleting_a_clip_deletes_its_poster(self, gallery, tmp_path):
        poster = tmp_path / "videos" / "job-a" / "poster_clip_1.jpg"
        poster.write_bytes(b"jpeg")
        res = gallery.delete("/api/gallery/clip/job-a/0")
        assert res.status_code == 200
        assert "poster_clip_1.jpg" in res.json()["files"]
        assert not poster.exists()


def _set_durations(tmp_path, job_id, durations):
    meta = tmp_path / "videos" / job_id / f"{job_id}_metadata.json"
    data = json.loads(meta.read_text())
    for clip, seconds in zip(data["shorts"], durations):
        clip["end"] = clip["start"] + seconds
    meta.write_text(json.dumps(data))


def _set_job_mtime(tmp_path, job_id, seconds_ago):
    when = time.time() - seconds_ago
    meta = tmp_path / "videos" / job_id / f"{job_id}_metadata.json"
    os.utime(meta, (when, when))


class TestGalleryPagingAndFilters:
    """Server-side paging and filters: they narrow the whole library, not the
    page in hand (the old endpoint cut the page while it was still counting)."""

    def test_pages_are_cut_by_the_server(self, gallery):
        first = gallery.get("/api/gallery/clips?limit=1&page=1").json()
        assert (first["page"], first["pages"], first["total"], first["offset"]) == (1, 3, 3, 0)
        assert first["has_more"] is True

        second = gallery.get("/api/gallery/clips?limit=1&page=2").json()
        assert (second["page"], second["pages"], second["offset"]) == (2, 3, 1)
        assert _titles(gallery.get("/api/gallery/clips?limit=1&page=2")) == ["A0"]

        last = gallery.get("/api/gallery/clips?limit=1&page=3").json()
        assert last["has_more"] is False

    def test_a_page_past_the_end_is_clamped_not_an_error(self, gallery):
        body = gallery.get("/api/gallery/clips?limit=2&page=99").json()
        assert body["page"] == 2
        assert body["pages"] == 2
        assert len(body["clips"]) == 1

    def test_offset_still_works_for_older_callers(self, gallery):
        body = gallery.get("/api/gallery/clips?limit=1&offset=2").json()
        assert (body["page"], body["offset"]) == (3, 2)

    def test_sort_longest_and_oldest(self, gallery, tmp_path):
        _set_durations(tmp_path, "job-a", [5, 40])
        _set_durations(tmp_path, "job-b", [15])
        assert _titles(gallery.get("/api/gallery/clips?sort=longest"))[:1] == ["A1"]
        assert _titles(gallery.get("/api/gallery/clips?sort=shortest"))[:1] == ["A0"]
        _set_job_mtime(tmp_path, "job-a", 3 * 86400)
        _set_job_mtime(tmp_path, "job-b", 60)
        assert _titles(gallery.get("/api/gallery/clips?sort=oldest"))[-1] == "B0"

    def test_rendered_date_presets(self, gallery, tmp_path):
        _set_job_mtime(tmp_path, "job-a", 2 * 86400)
        _set_job_mtime(tmp_path, "job-b", 60)
        assert _titles(gallery.get("/api/gallery/clips?date=today")) == ["B0"]
        assert "B0" not in _titles(gallery.get("/api/gallery/clips?date=yesterday"))

    def test_custom_date_range_is_inclusive_and_validated(self, gallery):
        today = time.strftime("%Y-%m-%d")
        body = gallery.get(f"/api/gallery/clips?date=custom&date_from={today}&date_to={today}").json()
        assert body["total"] == 3
        bad = gallery.get("/api/gallery/clips?date=custom&date_from=2026-13-01&date_to=2026-12-01")
        assert bad.status_code == 400
        backwards = gallery.get("/api/gallery/clips?date=custom&date_from=2026-12-02&date_to=2026-12-01")
        assert backwards.status_code == 400

    def test_platform_filter_uses_the_separate_marks(self, gallery):
        gallery.patch("/api/gallery/clip/job-a/0", json={"platform": "facebook", "posted": True})
        gallery.patch("/api/gallery/clip/job-b/0", json={"platform": "youtube", "posted": True})
        assert _titles(gallery.get("/api/gallery/clips?platform=facebook")) == ["A0"]
        assert _titles(gallery.get("/api/gallery/clips?platform=youtube")) == ["B0"]
        assert _titles(gallery.get("/api/gallery/clips?platform=both")) == []
        assert _titles(gallery.get("/api/gallery/clips?platform=none")) == ["A1"]
        counts = gallery.get("/api/gallery/clips?platform=youtube").json()["counts"]
        assert counts == {"used": 1, "unused": 0, "archived": 0}

    def test_search_matches_title_and_tags(self, gallery):
        assert _titles(gallery.get("/api/gallery/clips?q=A1")) == ["A1"]
        assert _titles(gallery.get("/api/gallery/clips?q=job-a")) == ["A0", "A1"]
        assert gallery.get("/api/gallery/clips?q=nothing-here").json()["total"] == 0

    def test_filters_and_paging_agree(self, gallery, tmp_path):
        _set_durations(tmp_path, "job-a", [5, 40])
        body = gallery.get("/api/gallery/clips?sort=longest&limit=1&page=2").json()
        assert body["pages"] == 3
        assert len(body["clips"]) == 1

    def test_writing_a_poster_does_not_reorder_the_library(self, gallery, tmp_path):
        # Posters live inside the job dir; the ordering must come from the
        # metadata's mtime or viewing an old job would make it "newest".
        before = _titles(gallery.get("/api/gallery/clips"))
        (tmp_path / "videos" / "job-a" / "poster_clip_1.jpg").write_bytes(b"jpeg")
        assert _titles(gallery.get("/api/gallery/clips")) == before

    def test_a_date_filter_does_not_prune_marks_outside_the_window(self, gallery, tmp_path):
        gallery.patch("/api/gallery/clip/job-a/0", json={"used": True})
        _set_job_mtime(tmp_path, "job-a", 3 * 86400)
        assert gallery.get("/api/gallery/clips?date=today").json()["total"] == 1
        # The used clip was not in the result, but its mark must survive.
        assert _titles(gallery.get("/api/gallery/clips?usage=used")) == ["A0"]


class TestLockedClipDelete:
    """Windows keeps a handle open while a player/download manager reads the
    file. That must surface as "close it and retry", not as "already gone"."""

    def test_single_delete_reports_the_file_in_use(self, gallery, monkeypatch, tmp_path):
        app_module = pytest.importorskip("app")
        monkeypatch.setattr(app_module, "_remove_tree", lambda *a, **k: False)
        clip = tmp_path / "videos" / "job-a" / "job-a_clip_1.mp4"
        res = gallery.delete("/api/gallery/clip/job-a/0")
        assert res.status_code == 409
        assert "still open" in res.json()["detail"]
        assert clip.exists()

    def test_bulk_delete_keeps_only_the_blocked_refs(self, gallery, monkeypatch, tmp_path):
        app_module = pytest.importorskip("app")
        monkeypatch.setattr(app_module, "_remove_tree", lambda *a, **k: False)
        res = gallery.post("/api/gallery/delete", json={"clips": [
            {"job_id": "job-a", "index": 0},
            {"job_id": "job-b", "index": 0},
        ]})
        assert res.status_code == 200
        body = res.json()
        assert body["deleted"] == 0
        assert {(f["job_id"], f["index"]) for f in body["failed"]} == {("job-a", 0), ("job-b", 0)}
        assert (tmp_path / "videos" / "job-a" / "job-a_clip_1.mp4").exists()

    def test_flags_survive_a_blocked_delete(self, gallery, monkeypatch):
        app_module = pytest.importorskip("app")
        gallery.patch("/api/gallery/clip/job-a/0", json={"used": True})
        monkeypatch.setattr(app_module, "_remove_tree", lambda *a, **k: False)
        assert gallery.delete("/api/gallery/clip/job-a/0").status_code == 409
        assert _titles(gallery.get("/api/gallery/clips?usage=used")) == ["A0"]


