"""Sorter review states and the Content Planner calendar.

The Sorter decides what a clip is for: accepted (the gallery's default view),
staged (maybe later), or deleted. The planner stores clip refs per day in the
small state tree and expands them with the same gallery metadata, so the
calendar can show title/poster/platform marks without duplicating the library.

No real media is touched: every fixture builds throwaway job directories.
"""
import json
import os

import pytest

import clip_state
import content_plan
import storage


# --------------------------------------------------------------------------- #
# content_plan store
# --------------------------------------------------------------------------- #
@pytest.fixture()
def plan_store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))
    return tmp_path


def test_a_plan_ref_round_trips_and_duplicates_are_ignored(plan_store):
    assert content_plan.add("2026-11-21", "job-a", 0)["added"] is True
    again = content_plan.add("2026-11-21", "job-a", 0)
    assert again["added"] is False and again["duplicate"] is True

    days = content_plan.days_between("2026-11-01", "2026-11-30")
    assert list(days) == ["2026-11-21"]
    assert days["2026-11-21"][0]["job_id"] == "job-a"
    assert days["2026-11-21"][0]["index"] == 0


def test_a_plan_ref_can_move_between_days(plan_store):
    content_plan.add("2026-11-21", "job-a", 0)
    result = content_plan.move("2026-11-21", "2026-11-22", "job-a", 0)
    assert result["moved"] is True
    days = content_plan.all_days()
    assert "2026-11-21" not in days
    assert days["2026-11-22"][0]["job_id"] == "job-a"
    # Moving it back to a day it is already on is a harmless no-op.
    content_plan.add("2026-11-22", "job-a", 0)
    assert content_plan.move("2026-11-22", "2026-11-22", "job-a", 0)["moved"] is True


def test_removing_the_last_ref_removes_the_day(plan_store):
    content_plan.add("2026-11-21", "job-a", 0)
    assert content_plan.remove("2026-11-21", "job-a", 0)["removed"] is True
    assert content_plan.all_days() == {}


def test_bad_dates_and_refs_are_refused(plan_store):
    for day in ("21-11-2026", "2026-13-01", "", None):
        with pytest.raises(ValueError):
            content_plan.add(day, "job-a", 0)
    with pytest.raises(ValueError):
        content_plan.add("2026-11-21", "../escape", 0)
    with pytest.raises(ValueError):
        content_plan.add("2026-11-21", "job-a", -1)


def test_the_plan_is_pruned_to_the_clips_that_still_exist(plan_store):
    content_plan.add("2026-11-21", "gone", 0)
    content_plan.add("2026-11-21", "kept", 0)
    content_plan.prune([("kept", 0)])
    days = content_plan.all_days()
    assert [ref["job_id"] for ref in days["2026-11-21"]] == ["kept"]


# --------------------------------------------------------------------------- #
# Planner API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def planner(tmp_path, monkeypatch):
    app_module = pytest.importorskip("app")
    from fastapi.testclient import TestClient

    videos = tmp_path / "videos"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(videos))
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(storage, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(storage, "MEDIA_DIR", str(tmp_path / "media"))

    def job(job_id, titles):
        folder = videos / job_id
        folder.mkdir(parents=True)
        (folder / f"{job_id}_metadata.json").write_text(json.dumps({"shorts": [
            {"start": 0, "end": 10, "video_title_for_youtube_short": title}
            for title in titles
        ]}))
        for index in range(len(titles)):
            (folder / f"{job_id}_clip_{index + 1}.mp4").write_bytes(b"x" * 2048)
            # A cached poster is newer than the clip, so the API does not try
            # to run ffmpeg over these fake bytes.
            (folder / f"poster_clip_{index + 1}.jpg").write_bytes(b"jpeg")

    job("job-a", ["A0", "A1"])
    job("job-b", ["B0"])
    return TestClient(app_module.app)


def test_planner_api_serves_the_same_card_as_the_gallery(planner):
    res = planner.post("/api/planner", json={
        "date": "2026-11-21", "job_id": "job-a", "index": 0,
    })
    assert res.status_code == 200
    assert res.json()["added"] is True

    body = planner.get("/api/planner?from=2026-11-01&to=2026-11-30").json()
    clips = body["days"]["2026-11-21"]
    assert len(clips) == 1
    clip = clips[0]
    assert clip["title"] == "A0"
    assert clip["status"] == "unreviewed"
    assert clip["planned_on"] == "2026-11-21"
    assert clip["poster"] == "/videos/job-a/poster_clip_1.jpg"
    assert {"facebook", "youtube"} <= set(clip["platforms"])
    assert body["total"] == 1


def test_planner_marks_follow_the_gallery_platform_toggles(planner):
    planner.patch("/api/gallery/clip/job-a/0",
                  json={"platform": "facebook", "posted": True})
    planner.post("/api/planner", json={
        "date": "2026-11-21", "job_id": "job-a", "index": 0,
    })
    clip = planner.get("/api/planner").json()["days"]["2026-11-21"][0]
    assert clip["platforms"]["facebook"] is True
    assert clip["used"] is True


def test_planner_add_is_idempotent_and_remove_clears_the_day(planner):
    body = {"date": "2026-11-21", "job_id": "job-a", "index": 0}
    assert planner.post("/api/planner", json=body).json()["added"] is True
    again = planner.post("/api/planner", json=body).json()
    assert again["added"] is False and again["duplicate"] is True

    removed = planner.post("/api/planner/remove", json=body).json()
    assert removed["removed"] is True
    assert planner.get("/api/planner").json()["days"] == {}


def test_planner_move_and_validation(planner):
    body = {"date": "2026-11-21", "job_id": "job-a", "index": 0}
    planner.post("/api/planner", json=body)
    moved = planner.post("/api/planner/move", json={
        "from": "2026-11-21", "to": "2026-11-23",
        "job_id": "job-a", "index": 0,
    }).json()
    assert moved["moved"] is True
    days = planner.get("/api/planner").json()["days"]
    assert "2026-11-23" in days and "2026-11-21" not in days

    assert planner.post("/api/planner", json={
        "date": "21/11/2026", "job_id": "job-a", "index": 0,
    }).status_code == 400
    assert planner.post("/api/planner", json={
        "date": "2026-11-21", "job_id": "job-a", "index": 99,
    }).status_code == 404
    assert planner.post("/api/planner/remove", json={
        "date": "nope", "job_id": "job-a", "index": 0,
    }).status_code == 400


# --------------------------------------------------------------------------- #
# Dashboard contracts
# --------------------------------------------------------------------------- #
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_the_gallery_opens_on_accepted_and_offers_the_other_states():
    gallery = _read("components", "Gallery.jsx")
    assert "status: 'accepted'" in gallery
    for value in ("accepted", "staged", "unreviewed", "all"):
        assert f"value: '{value}'" in gallery
    assert "status: filters.status" in gallery
    assert "statusCounts" in gallery
    # The empty accepted view points at the review queue.
    assert "onOpenSorter" in gallery
    assert "Review the new clips in the Sorter" in gallery


def test_the_clip_modal_can_change_the_sorter_status():
    modal = _read("components", "ClipModal.jsx")
    assert "review status" in modal
    assert "status: clip.status || 'unreviewed'" in modal
    assert "patch({ status: id }" in modal
    for value in ("accepted", "staged", "unreviewed"):
        assert f"['{value}'" in modal or f"['{value}'," in modal


def test_the_sorter_has_accept_reject_and_stage_and_uses_the_delete_endpoint():
    sorter = _read("components", "Sorter.jsx")
    assert "status: 'unreviewed'" in sorter
    assert "review(current, 'accepted')" in sorter
    assert "review(current, 'staged')" in sorter
    assert "requestReject(current)" in sorter
    assert "/api/gallery/delete" in sorter
    assert "ArrowLeft" in sorter and "ArrowRight" in sorter
    assert "ConfirmDeleteModal" in sorter
    # Deleting is the reject: the sorter never stores a rejected status.
    assert "'rejected'" not in sorter


def test_the_planner_is_a_month_calendar_that_opens_the_clip_modal():
    planner = _read("components", "ContentPlanner.jsx")
    assert "/api/planner" in planner
    assert "startOfWeek" in planner and "WEEKDAYS" in planner
    assert "ClipModal" in planner and "<ClipModal" in planner
    assert "platforms?.facebook" in planner and "platforms?.youtube" in planner
    assert "posted" in planner and "ring-2" in planner
    assert "openPicker" in planner
    assert "deleteLabel=\"remove from plan\"" in planner


def test_routes_replace_the_ai_agent_page_with_settings_and_add_the_two_pages():
    routes = _read("lib", "routes.js")
    assert "sorter: '/sorter'" in routes
    assert "planner: '/content-planner'" in routes
    assert "'ai-agent': '/ai-agent'" not in routes
    assert "tab === 'ai-agent') return 'settings'" in routes
