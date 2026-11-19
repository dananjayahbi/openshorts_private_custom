"""Archive: permanent clip store, SQLite index, external storage vaults.

No device or network is touched: every vault is a temp folder, and the worker
is replaced by direct calls so the tests describe the state machine instead of
waiting on a thread. The HTTP/UI wiring is checked as source contracts.
"""
import hashlib
import json
import os
import time

import pytest

import archive
import clip_state
import storage


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def arch(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE_DIR", str(root))
    monkeypatch.setattr(storage, "VIDEOS_DIR", str(root / "videos"))
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(root / "archive"))
    monkeypatch.setattr(archive, "FILES_DIR", str(root / "archive" / "files"))
    monkeypatch.setattr(archive, "DB_FILE", str(root / "archive" / "archive.db"))
    monkeypatch.setattr(archive, "MIN_VAULT_BYTES", 1)
    monkeypatch.setattr(archive, "RESERVE_HEADROOM", 0)
    monkeypatch.setattr(archive, "_kick", lambda: None)
    os.makedirs(storage.VIDEOS_DIR, exist_ok=True)
    archive.ensure()
    return root


def _make_clip(root, job_id="job-1", index=0):
    job = root / "videos" / job_id
    job.mkdir(parents=True, exist_ok=True)
    (job / f"{job_id}_metadata.json").write_text(json.dumps({
        "shorts": [{
            "start": 12.5, "end": 42.5,
            "viral_hook_text": "The hook",
            "youtube_title": "A good title",
            "youtube_description": "A description for YouTube.",
            "tags": ["one", "two", "three"],
            "predicted_score": 81,
        }],
    }), encoding="utf-8")
    (job / f"clip_{index + 1}.mp4").write_bytes(b"video-bytes" * 4096)
    (job / f"poster_clip_{index + 1}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    return job


def _make_vault(root, name="Backup", capacity=None):
    folder = root / "usb"
    folder.mkdir(parents=True, exist_ok=True)
    capacity = capacity or (archive.DATA_START + 3 * 1024 * 1024)
    created = archive.create_vault(str(folder), name, capacity)
    archive._create_one(created["id"])
    return archive.list_vaults()["vaults"][0], folder


# --------------------------------------------------------------------------- #
# Vaults
# --------------------------------------------------------------------------- #
def test_creating_a_vault_really_occupies_its_size(arch):
    vault, _folder = _make_vault(arch, capacity=archive.DATA_START + 2 * 1024 * 1024)
    path = vault["path"]
    assert os.path.getsize(path) == vault["capacity_bytes"]
    header = archive._read_header(path)
    assert header["id"] == vault["id"]
    assert header["name"] == "Backup"
    assert header["capacity"] == vault["capacity_bytes"]
    assert header["next"] == archive.DATA_START
    assert vault["state"] == "ready"
    assert vault["connected"] is True
    assert vault["usable_bytes"] == 2 * 1024 * 1024


def test_vault_names_are_unique_and_sizes_are_bounded(arch):
    folder = arch / "usb"
    folder.mkdir()
    archive.create_vault(str(folder), "Backup", archive.DATA_START + 1024 * 1024)
    with pytest.raises(ValueError):
        archive.create_vault(str(folder), "backup", archive.DATA_START + 1024 * 1024)
    with pytest.raises(ValueError):
        archive.create_vault(str(folder), "Small", 10)


def test_a_vault_can_grow_but_not_shrink(arch):
    vault, _folder = _make_vault(arch)
    bigger = vault["capacity_bytes"] + 1024 * 1024
    updated = archive.update_vault(vault["id"], size_bytes=bigger)
    assert updated["state"] == "expanding"
    archive._expand_one(vault["id"])
    grown = archive.list_vaults()["vaults"][0]
    assert grown["capacity_bytes"] == bigger
    assert os.path.getsize(grown["path"]) == bigger
    assert archive._read_header(grown["path"])["capacity"] == bigger
    with pytest.raises(ValueError):
        archive.update_vault(vault["id"], size_bytes=bigger - 1)


# --------------------------------------------------------------------------- #
# Archiving clips
# --------------------------------------------------------------------------- #
def test_archiving_moves_the_files_out_of_the_job_folder(arch):
    job = _make_clip(arch)
    item = archive.archive_clip("job-1", 0)

    assert not (job / "clip_1.mp4").exists()
    assert not (job / "poster_clip_1.jpg").exists()
    assert os.path.isfile(os.path.join(archive.FILES_DIR, item["id"], "video.mp4"))
    assert item["title"] == "A good title"
    assert item["duration"] == 30.0
    assert item["size_bytes"] > 0
    assert item["state"] == "local"
    assert item["playable"] is True
    assert item["tags"] == ["one", "two", "three"]
    assert item["platforms"] == {"facebook": False, "youtube": False}
    assert clip_state.flags("job-1", 0)["archived"] is True


def test_archiving_is_idempotent(arch):
    _make_clip(arch)
    first = archive.archive_clip("job-1", 0)
    second = archive.archive_clip("job-1", 0)
    assert first["id"] == second["id"]
    assert archive.list_items()["total"] == 1


def test_the_index_filters_sorts_and_pages_server_side(arch):
    for job in ("job-a", "job-b"):
        _make_clip(arch, job_id=job)
        archive.archive_clip(job, 0)

    page = archive.list_items(limit=1, page=2, sort="oldest")
    assert page["total"] == 2
    assert page["pages"] == 2
    assert len(page["items"]) == 1
    assert archive.list_items(q="good title")["total"] == 2
    assert archive.list_items(q="nothing matches")["total"] == 0
    assert archive.list_items(state="vaulted")["total"] == 0
    assert archive.list_items(vault="local")["total"] == 2


def test_unarchive_puts_the_clip_back_in_the_gallery(arch):
    job = _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    archive.unarchive(item["id"])
    assert (job / "clip_1.mp4").exists()
    assert (job / "poster_clip_1.jpg").exists()
    assert archive.list_items()["total"] == 0
    assert clip_state.flags("job-1", 0)["archived"] is False


def test_unarchive_restores_the_posted_marks_the_gallery_pruned(arch):
    _make_clip(arch)
    clip_state.set_flags("job-1", 0, platforms={"youtube": True})
    item = archive.archive_clip("job-1", 0)
    # The gallery's scan prunes state for clips with no file in the job dir.
    clip_state.prune([])
    assert clip_state.flags("job-1", 0)["used"] is False

    archive.unarchive(item["id"])
    flags = clip_state.flags("job-1", 0)
    assert flags["platforms"]["youtube"] is True
    assert flags["used"] is True
    assert flags["archived"] is False


def test_unarchive_refuses_once_the_job_folder_is_gone(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    import shutil
    shutil.rmtree(arch / "videos" / "job-1")
    with pytest.raises(ValueError, match="gallery"):
        archive.unarchive(item["id"])


def test_returning_a_vaulted_clip_to_the_gallery_frees_the_vault(arch):
    job = _make_clip(arch)
    original = (job / "clip_1.mp4").read_bytes()
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    assert archive.list_vaults()["vaults"][0]["used_bytes"] > 0

    archive.unarchive(item["id"])

    assert (job / "clip_1.mp4").read_bytes() == original
    assert (job / "poster_clip_1.jpg").exists()
    assert archive.list_items()["total"] == 0
    assert archive.get_item(item["id"]) is None
    assert archive.list_vaults()["vaults"][0]["used_bytes"] == 0
    assert not os.path.isdir(os.path.join(archive.FILES_DIR, item["id"]))
    assert clip_state.flags("job-1", 0)["archived"] is False


def test_returning_a_vaulted_clip_needs_the_vault_connected(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    archive._set_vault(vault["id"], connected=0)

    with pytest.raises(ValueError, match="Connect"):
        archive.unarchive(item["id"])
    assert archive.get_item(item["id"])["state"] == "vaulted"


# --------------------------------------------------------------------------- #
# Verified moves and playback
# --------------------------------------------------------------------------- #
def test_push_is_a_verified_move_and_the_bytes_still_play(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, folder = _make_vault(arch)

    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])

    moved = archive.get_item(item["id"])
    assert moved["state"] == "vaulted"
    assert moved["vault_id"] == vault["id"]
    assert moved["vault_connected"] is True
    assert moved["playable"] is True
    assert not os.path.isfile(os.path.join(archive.FILES_DIR, item["id"], "video.mp4"))

    path, offset, size, _name = archive.stream_source(item["id"])
    with open(path, "rb") as handle:
        handle.seek(offset)
        payload = handle.read(size)
    assert payload == b"video-bytes" * 4096
    assert moved["sha256"] == hashlib.sha256(payload).hexdigest()

    stored = archive.list_vaults()["vaults"][0]
    assert stored["used_bytes"] > 0
    assert stored["items"] == 1
    assert archive.list_items(vault=vault["id"])["total"] == 1


def test_a_full_vault_leaves_the_local_copy_alone(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    # One usable block is not enough for the entry header plus the video.
    vault, _folder = _make_vault(arch, capacity=archive.DATA_START + 2 * archive.BLOCK)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    after = archive.get_item(item["id"])
    assert after["state"] == "local"
    assert "full" in (after["error"] or "").lower()
    assert os.path.isfile(os.path.join(archive.FILES_DIR, item["id"], "video.mp4"))


def test_pushing_again_reuses_the_freed_space(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    used = archive.list_vaults()["vaults"][0]["used_bytes"]
    assert archive.delete_items([item["id"]])["deleted"] == [item["id"]]
    assert archive.list_vaults()["vaults"][0]["used_bytes"] == 0

    # A fresh clip archives and pushes into the freed range.
    _make_clip(arch, job_id="job-2")
    second = archive.archive_clip("job-2", 0)
    archive.push_items([second["id"]], vault["id"])
    archive._push_one(second["id"])
    assert archive.get_item(second["id"])["state"] == "vaulted"
    assert archive.list_vaults()["vaults"][0]["used_bytes"] == used


def test_playback_marks_an_entry_that_vanished_from_the_vault(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    raw = archive._raw_item(item["id"])

    # Corrupt the entry header while leaving the container and index alone.
    with open(vault["path"], "r+b") as handle:
        handle.seek(int(raw["vault_entry_off"]))
        handle.write(b"not-an-entry")
    assert archive.stream_source(item["id"]) is None
    assert archive.get_item(item["id"])["state"] == "missing"
    assert archive.list_items(state="missing")["total"] == 1


def test_restore_copies_back_and_frees_the_vault(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])

    result = archive.restore_items([item["id"]])
    assert result["restored"] == [item["id"]]
    local = archive.get_item(item["id"])
    assert local["state"] == "local"
    assert os.path.isfile(os.path.join(archive.FILES_DIR, item["id"], "video.mp4"))
    assert archive.list_vaults()["vaults"][0]["used_bytes"] == 0


# --------------------------------------------------------------------------- #
# Deleting, offline queues and reconnects
# --------------------------------------------------------------------------- #
def test_deleting_a_vaulted_clip_offline_is_queued_until_reconnect(arch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])

    archive._set_vault(vault["id"], connected=0)
    result = archive.delete_items([item["id"]])
    assert result["queued"] == [item["id"]]
    assert archive.get_item(item["id"])["state"] == "pending_delete"

    archive._set_vault(vault["id"], connected=1)
    archive._delete_pending(item["id"])
    assert archive.get_item(item["id"]) is None
    assert archive.list_vaults()["vaults"][0]["used_bytes"] == 0


def test_scan_reconnects_a_known_vault_after_it_is_unplugged(arch):
    vault, folder = _make_vault(arch)
    archive._set_vault(vault["id"], connected=0)
    assert archive.list_vaults()["vaults"][0]["connected"] is False
    archive.scan([str(folder)])
    assert archive.list_vaults()["vaults"][0]["connected"] is True


def test_scan_records_an_unknown_vault_for_adoption(arch, tmp_path, monkeypatch):
    _vault, folder = _make_vault(arch)
    original = str(folder)

    # A fresh install: new archive index, same device.
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "second" / "archive"))
    monkeypatch.setattr(archive, "FILES_DIR", str(tmp_path / "second" / "archive" / "files"))
    monkeypatch.setattr(archive, "DB_FILE", str(tmp_path / "second" / "archive" / "archive.db"))
    archive.ensure()
    archive.scan([original])

    listing = archive.list_vaults()
    assert listing["vaults"] == []
    assert len(listing["unrecognized"]) == 1
    assert listing["unrecognized"][0]["name"] == "Backup"


def test_adopting_a_vault_imports_its_entries(arch, tmp_path, monkeypatch):
    _make_clip(arch)
    item = archive.archive_clip("job-1", 0)
    vault, _folder = _make_vault(arch)
    archive.push_items([item["id"]], vault["id"])
    archive._push_one(item["id"])
    vault_path = archive.list_vaults()["vaults"][0]["path"]

    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "second" / "archive"))
    monkeypatch.setattr(archive, "FILES_DIR", str(tmp_path / "second" / "archive" / "files"))
    monkeypatch.setattr(archive, "DB_FILE", str(tmp_path / "second" / "archive" / "archive.db"))
    archive.ensure()

    adopted = archive.adopt_vault(vault_path)
    assert adopted["imported"] == 1
    assert adopted["vault"]["items"] == 1
    imported = archive.list_items()["items"][0]
    assert imported["state"] == "vaulted"
    assert imported["playable"] is True
    assert archive.stream_source(imported["id"]) is not None


# --------------------------------------------------------------------------- #
# Auto-archive rule
# --------------------------------------------------------------------------- #
def test_auto_archive_waits_for_the_delay_and_the_posted_mark(arch):
    _make_clip(arch, job_id="posted")
    _make_clip(arch, job_id="unposted")
    clip_state.set_flags(
        "posted", 0, platforms={"youtube": True, "facebook": True})

    assert archive.auto_archive_once() == 0          # off by default
    archive.set_settings(enabled=True, days=7)
    now = time.time()
    assert archive.auto_archive_once(now=now) == 0   # not old enough
    assert archive.auto_archive_once(now=now + 8 * 86400) == 1
    titles = [item["job_id"] for item in archive.list_items()["items"]]
    assert titles == ["posted"]


def test_single_platform_clips_wait_for_the_staged_buttons(arch):
    for job in ("yt-only", "fb-only", "both"):
        _make_clip(arch, job_id=job)
    clip_state.set_flags("yt-only", 0, platforms={"youtube": True})
    clip_state.set_flags("fb-only", 0, platforms={"facebook": True})
    clip_state.set_flags("both", 0, platforms={"youtube": True, "facebook": True})
    archive.set_settings(enabled=True, days=7)

    now = time.time()
    # One-platform clips are staged immediately; they never move on their own.
    fresh = archive.staged_archives(now=now)
    assert [ref["job_id"] for ref in fresh["youtube"]] == ["yt-only"]
    assert [ref["job_id"] for ref in fresh["facebook"]] == ["fb-only"]

    later = now + 8 * 86400
    staged = archive.staged_archives(now=later)
    assert [ref["job_id"] for ref in staged["youtube"]] == ["yt-only"]
    assert [ref["job_id"] for ref in staged["facebook"]] == ["fb-only"]
    assert staged["days"] == 7

    # The unattended rule takes the both-platform clip only.
    assert archive.auto_archive_once(now=later) == 1
    assert {item["job_id"] for item in archive.list_items()["items"]} == {"both"}

    result = archive.archive_staged("youtube", now=later)
    assert result["staged"] == 1
    assert [item["job_id"] for item in result["archived"]] == ["yt-only"]
    assert {item["job_id"] for item in archive.list_items()["items"]} == {"both", "yt-only"}

    remaining = archive.staged_archives(now=later)
    assert remaining["youtube"] == []
    assert [ref["job_id"] for ref in remaining["facebook"]] == ["fb-only"]


def test_staged_buttons_are_off_when_auto_archive_is_off(arch):
    _make_clip(arch, job_id="yt-only")
    clip_state.set_flags("yt-only", 0, platforms={"youtube": True})
    archive.set_settings(enabled=False, days=7)
    staged = archive.staged_archives(now=time.time() + 30 * 86400)
    assert staged["enabled"] is False
    assert staged["youtube"] == []


def test_bulk_archive_moves_only_the_selected_clips(arch):
    for job in ("selected", "untouched"):
        _make_clip(arch, job_id=job)
    result = archive.archive_clips([{"job_id": "selected", "index": 0}])
    assert [item["job_id"] for item in result["archived"]] == ["selected"]
    assert result["failed"] == []
    assert archive.list_items()["total"] == 1
    assert (arch / "videos" / "untouched" / "clip_1.mp4").exists()
    assert not (arch / "videos" / "selected" / "clip_1.mp4").exists()


# --------------------------------------------------------------------------- #
# Folder picker
# --------------------------------------------------------------------------- #
def test_range_requests_seek_and_reject_impossible_windows():
    assert archive.byte_range(None, 100) is None
    assert archive.byte_range("bytes=0-9", 100) == (0, 9)
    assert archive.byte_range("bytes=90-", 100) == (90, 99)
    assert archive.byte_range("bytes=-10", 100) == (90, 99)
    assert archive.byte_range("bytes=90-200", 100) == (90, 99)
    assert archive.byte_range("bytes=0-9,20-29", 100) == (0, 9)
    for bad in ("bytes=100-", "bytes=9-2", "bytes=abc-def", "nonsense=0-1"):
        if bad == "nonsense=0-1":
            assert archive.byte_range(bad, 100) is None
        else:
            with pytest.raises(ValueError):
                archive.byte_range(bad, 100)


def test_legacy_archived_flags_are_moved_once(arch):
    _make_clip(arch)
    clip_state.set_flags("job-1", 0, archived=True)
    assert archive.import_legacy_archived() == 1
    item = archive.list_items()["items"][0]
    assert item["job_id"] == "job-1"
    assert not (arch / "videos" / "job-1" / "clip_1.mp4").exists()
    assert archive.import_legacy_archived() == 0


def test_browse_lists_only_real_folders(arch):
    base = arch / "usb"
    (base / "Vaults").mkdir(parents=True)
    (base / "photo.jpg").write_bytes(b"x")
    (base / ".hidden").mkdir()
    listing = archive.browse(str(base))
    assert [entry["name"] for entry in listing["directories"]] == ["Vaults"]
    assert listing["parent"] is not None
    with pytest.raises(ValueError):
        archive.browse(str(base / "missing"))


# --------------------------------------------------------------------------- #
# API and page wiring
# --------------------------------------------------------------------------- #
def test_the_archive_page_and_api_are_wired():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def read(*parts):
        with open(os.path.join(repo, *parts), encoding="utf-8") as handle:
            return handle.read()

    routes = read("dashboard", "src", "lib", "routes.js")
    assert "archive: '/archive'" in routes
    app = read("dashboard", "src", "App.jsx")
    assert "label: 'Archive'" in app
    assert "<Archive" in app

    page = read("dashboard", "src", "components", "Archive.jsx")
    for endpoint in ("/api/archive/items", "/api/archive/vaults",
                     "/api/archive/vaults/scan", "/api/archive/items/push",
                     "/api/archive/items/delete", "/api/archive/settings"):
        assert endpoint in page, endpoint
    assert "Connect" in page and "vault" in page.lower()
    # A vaulted clip can return to the gallery in one action (Feature update #13).
    assert "player.state === 'vaulted' && player.vault_connected" in page

    server = read("app.py")
    for route in ('@app.get("/api/archive/items")',
                  '@app.post("/api/archive/clips")',
                  '@app.get("/api/gallery/archive-staged")',
                  '@app.post("/api/gallery/archive-staged")',
                  '@app.get("/api/archive/vaults")',
                  '@app.post("/api/archive/vaults")',
                  '@app.post("/api/archive/items/push")',
                  '@app.post("/api/archive/items/delete")',
                  '@app.get("/api/archive/items/{item_id}/video")',
                  '@app.get("/api/archive/settings")'):
        assert route in server, route
