"""Download Manager: temp downloads, per-video chunk lengths, Collector output.

The network and ffmpeg are never touched here: link validation, the download
worker's start and the split worker are stubbed, so the tests cover the store,
the part maths, config bounds and the Collector hand-off. The UI/API wiring is
checked as source contracts, like the other dashboard tests.
"""
import os

import pytest

import collector
import downloads


@pytest.fixture()
def dl(tmp_path, monkeypatch):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr(downloads, "DOWNLOADS_DIR", str(root))
    monkeypatch.setattr(downloads, "INDEX_FILE", str(root / "items.json"))
    monkeypatch.setattr(downloads, "_start_downloads", lambda: None)
    monkeypatch.setattr(downloads, "_start_splits", lambda: None)
    downloads.ensure()
    return root


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


def test_a_link_is_one_queued_item(dl, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    added = downloads.add_urls(["https://www.youtube.com/watch?v=abc"])
    assert len(added) == 1
    assert added[0]["state"] == "queued"
    assert added[0]["url"] == "https://www.youtube.com/watch?v=abc"
    assert downloads.list_items()[0]["id"] == added[0]["id"]


def test_unsafe_or_empty_links_are_refused(dl):
    with pytest.raises(Exception):
        downloads.add_urls(["file:///etc/passwd"])
    with pytest.raises(ValueError):
        downloads.add_urls([])


def test_duplicate_links_are_added_once(dl, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    added = downloads.add_urls(["https://example.com/a", "https://example.com/a"])
    assert len(added) == 1


def test_part_count_is_the_remainder_aware_maths():
    # 1.5 h in 20-minute parts: 4 x 20 + 10, as the task describes.
    assert downloads._chunk_count(90 * 60, 20 * 60) == 5
    assert downloads._chunk_count(2 * 60 * 60, 60 * 60) == 2
    assert downloads._chunk_count(30, 60 * 60) == 1
    assert downloads._chunk_count(None, 1200) is None


def test_chunk_length_configuration_is_bounded(dl, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    item = downloads.add_urls(["https://example.com/a"])[0]
    assert downloads.configure(item["id"], 90 * 60)["chunk_seconds"] == 5400
    with pytest.raises(ValueError):
        downloads.configure(item["id"], 10)  # under a minute
    with pytest.raises(ValueError):
        downloads.configure(item["id"], 48 * 60 * 60)  # over a day


def test_split_marks_ready_items_and_keeps_each_length(dl, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    first = downloads.add_urls(["https://example.com/a"])[0]
    second = downloads.add_urls(["https://example.com/b"])[0]
    downloads._update(first["id"], state="ready", duration=90 * 60)
    downloads._update(second["id"], state="ready", duration=90 * 60)
    downloads.start_split_all([{"id": first["id"], "chunk_seconds": 20 * 60},
                               {"id": second["id"], "chunk_seconds": 60 * 60}])
    by_id = {i["id"]: i for i in downloads.list_items()}
    assert by_id[first["id"]]["state"] == "split_queued"
    assert by_id[first["id"]]["parts_expected"] == 5
    assert by_id[second["id"]]["parts_expected"] == 2


def test_delete_removes_the_temp_tree_but_not_the_shelf(dl, shelf, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    item = downloads.add_urls(["https://example.com/a"])[0]
    downloads._update(item["id"], state="ready")
    source = downloads._dir(item["id"])
    os.makedirs(source, exist_ok=True)
    with open(os.path.join(source, "source.mp4"), "wb") as f:
        f.write(b"video")
    assert downloads.delete(item["id"]) is True
    assert not os.path.exists(source)
    assert downloads.list_items() == []


def test_delete_refuses_while_the_item_is_working(dl, monkeypatch):
    monkeypatch.setattr("security_utils.assert_public_url", lambda url: url)
    item = downloads.add_urls(["https://example.com/a"])[0]
    downloads._update(item["id"], state="downloading")
    with pytest.raises(ValueError):
        downloads.delete(item["id"])


def test_a_split_part_lands_on_the_collector_shelf(shelf, tmp_path):
    part = tmp_path / "part_000.mp4"
    part.write_bytes(b"video bytes")
    item = collector.add_file(
        str(part), "Long video - part 01", source_url="https://example.com/a",
        duration_probe=lambda _p: 1200.0,
        thumb_probe=lambda _p, out: open(out, "wb").write(b"\xff\xd8jpeg"),
        move=True)
    assert item["state"] == "ready"
    assert item["source"] == "download"
    assert item["title"] == "Long video - part 01"
    assert item["duration"] == 1200.0
    assert not part.exists()  # moved into the shelf
    assert collector.list_items()[0]["id"] == item["id"]


def test_the_page_routes_and_api_are_wired():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def read(*parts):
        with open(os.path.join(repo, *parts), encoding="utf-8") as f:
            return f.read()

    routes = read("dashboard", "src", "lib", "routes.js")
    assert "downloads: '/download-manager'" in routes
    app = read("dashboard", "src", "App.jsx")
    assert "label: 'Download Manager'" in app
    assert "<DownloadManager" in app

    page = read("dashboard", "src", "components", "DownloadManager.jsx")
    for endpoint in ("'/api/downloads'", "/api/downloads/${item.id}/split",
                     "'/api/downloads/split-all'", "method: 'PATCH'",
                     "method: 'DELETE'"):
        assert endpoint in page, endpoint
    # Each video has its own part length before the queue starts.
    assert "chunkInputs" in page and "part length" in page
    assert "start split queue" in page

    server = read("app.py")
    for route in ('@app.get("/api/downloads")', '@app.post("/api/downloads")',
                  '@app.patch("/api/downloads/{item_id}")',
                  '@app.post("/api/downloads/split-all")',
                  '@app.post("/api/downloads/{item_id}/split")',
                  '@app.delete("/api/downloads/{item_id}")'):
        assert route in server, route