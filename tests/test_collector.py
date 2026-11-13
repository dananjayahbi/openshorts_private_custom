"""Collector: the shelf of videos to clip later (collector.py).

The network is never touched here: metadata probing and thumbnail fetching are
faked, so the tests cover the store (files, index, queue, deletion) and the
"link is not downloaded" promise without depending on YouTube.
"""
import io
import os

import pytest

import collector
from media_auth import is_servable


class FakeUpload:
    """The slice of FastAPI's UploadFile that collector.add_upload uses."""

    def __init__(self, data):
        self.file = io.BytesIO(data)


def _probe_ok(_path):
    return 60.0


def _thumb_ok(_path, out):
    with open(out, "wb") as f:
        f.write(b"\xff\xd8jpeg")


def _file_on_disk(root, public_url):
    """``/collector/thumbs/x.jpg`` -> the path inside the temp tree."""
    rel = public_url[len("/collector/"):]
    return os.path.join(str(root), *rel.split("/"))


@pytest.fixture()
def shelf(tmp_path, monkeypatch):
    root = tmp_path / "collector"
    files = root / "files"
    thumbs = root / "thumbs"
    for path in (root, files, thumbs):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(collector, "COLLECTOR_DIR", str(root))
    monkeypatch.setattr(collector, "FILES_DIR", str(files))
    monkeypatch.setattr(collector, "THUMBS_DIR", str(thumbs))
    monkeypatch.setattr(collector, "INDEX_FILE", str(root / "items.json"))
    collector.ensure()
    return root


class TestUpload:
    def test_stores_file_thumbnail_and_duration(self, shelf):
        item = collector.add_upload(
            "My Clip.mp4", FakeUpload(b"x" * 1000), 1024 * 1024,
            _probe_ok, _thumb_ok)

        assert item["ready"] is True and item["state"] == "ready"
        assert item["duration"] == 60.0
        assert item["size_bytes"] == 1000
        assert item["thumbnail"].startswith("/collector/thumbs/")
        raw = collector.get(item["id"])
        assert os.path.isfile(os.path.join(str(shelf), *raw["file"].split("/")))
        assert os.path.isfile(_file_on_disk(shelf, item["thumbnail"]))
        # The index (items.json) is not a media file: the mount must refuse it.
        assert is_servable("items.json") is False
        assert is_servable(raw["file"]) is True

    def test_a_too_large_file_is_removed(self, shelf):
        with pytest.raises(ValueError):
            collector.add_upload("big.mp4", FakeUpload(b"x" * 2000), 1000,
                                 _probe_ok, _thumb_ok)
        assert os.listdir(os.path.join(str(shelf), "files")) == []
        assert collector.list_items() == []

    def test_an_empty_file_is_removed(self, shelf):
        with pytest.raises(ValueError):
            collector.add_upload("empty.mp4", FakeUpload(b""), 1000,
                                 _probe_ok, _thumb_ok)
        assert collector.list_items() == []

    def test_the_extension_is_normalised(self, shelf):
        item = collector.add_upload("clip.MKV", FakeUpload(b"v"), 1000,
                                    _probe_ok, _thumb_ok)
        assert collector.get(item["id"])["file"].endswith(".mkv")


class TestUrlItems:
    def test_metadata_only_never_downloads_video(self, shelf, monkeypatch):
        def probe(url):
            return {"title": "A talk", "duration": 120, "channel": "C",
                    "webpage_url": url, "thumbnail": None}
        monkeypatch.setattr(collector, "_probe_url", probe)

        item = collector.add_url("https://example.com/v")

        assert item["source"] == "url"
        assert item["state"] == "remote" and item["ready"] is False
        assert item["duration"] == 120.0
        assert os.listdir(os.path.join(str(shelf), "files")) == []

    def test_probe_errors_are_reported(self, shelf, monkeypatch):
        def probe(_url):
            raise ValueError("That is a playlist; paste one video's link.")
        monkeypatch.setattr(collector, "_probe_url", probe)
        with pytest.raises(ValueError):
            collector.add_url("https://example.com/playlist")


class TestQueueAndDelete:
    def _item(self, shelf):
        return collector.add_upload("q.mp4", FakeUpload(b"v"), 1000,
                                    _probe_ok, _thumb_ok)

    def test_queue_toggle_and_mark_job(self, shelf):
        item = self._item(shelf)
        assert collector.queued_items() == []
        collector.set_queued(item["id"], True)
        assert [i["id"] for i in collector.queued_items()] == [item["id"]]

        collector.mark_job(item["id"], "job-1")
        row = collector.get(item["id"])
        assert row["job_id"] == "job-1"
        assert row["queued"] is False        # leaving the queue when it starts
        assert collector.queued_items() == []

    def test_delete_removes_file_and_thumbnail(self, shelf):
        item = self._item(shelf)
        raw = collector.get(item["id"])
        file_path = os.path.join(str(shelf), *raw["file"].split("/"))
        thumb_path = _file_on_disk(shelf, item["thumbnail"])
        assert os.path.exists(file_path) and os.path.exists(thumb_path)

        assert collector.delete(item["id"]) is True

        assert collector.get(item["id"]) is None
        assert not os.path.exists(file_path)
        assert not os.path.exists(thumb_path)
        assert collector.delete(item["id"]) is False

    def test_ids_are_uuid_shaped(self, shelf):
        assert collector.get("../../etc/passwd") is None
        assert collector.get("not-a-uuid") is None
        assert collector.set_queued("..", True) is None
