"""Streamer split layout (New feature #8).

The geometry is pure math, so most of this file needs no media. The one
end-to-end test builds synthetic lavender/sine clips with ffmpeg and checks the
finished frame size and audio, never a user's video.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

import streamer_layout


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


# --------------------------------------------------------------------------- #
# Rectangle validation
# --------------------------------------------------------------------------- #
def test_a_valid_rectangle_is_normalised():
    rect = streamer_layout.clean_rect({"x": 0.1, "y": 0.2, "w": 0.25, "h": 0.5})
    assert rect == {"x": 0.1, "y": 0.2, "w": 0.25, "h": 0.5}


def test_the_rectangle_can_arrive_as_the_dashboard_json_string():
    rect = streamer_layout.clean_rect('{"x": 0.1, "y": 0.2, "w": 0.25, "h": 0.5}')
    assert rect["w"] == 0.25


@pytest.mark.parametrize("bad", [
    None,
    {},
    "not json",
    {"x": 0, "y": 0, "w": 0, "h": 0.5},
    {"x": 0, "y": 0, "w": 0.25, "h": 0},
    {"x": 0.9, "y": 0, "w": 0.25, "h": 0.5},
    {"x": 0, "y": 0.9, "w": 0.25, "h": 0.5},
    {"x": -0.1, "y": 0, "w": 0.25, "h": 0.5},
    {"x": "left", "y": 0, "w": 0.25, "h": 0.5},
])
def test_bad_rectangles_are_refused(bad):
    with pytest.raises(ValueError):
        streamer_layout.clean_rect(bad)


def test_any_cam_shape_inside_the_split_range_is_accepted():
    # 1920x1080 makes 0.5 x 0.5 a 960x540 box: a 16:9 webcam.
    assert streamer_layout.aspect_ok(1920, 1080, {"x": 0, "y": 0, "w": 0.5, "h": 0.5})
    # The default 9:8 box: half of the frame, the classic 50/50 split.
    assert streamer_layout.aspect_ok(
        1920, 1080, {"x": 0.3, "y": 0.2, "w": 0.31640625, "h": 0.5})
    # A square cam.
    assert streamer_layout.aspect_ok(
        1920, 1080, {"x": 0.2, "y": 0.2, "w": 0.28125, "h": 0.5})
    # A very tall box would leave the clip under 15%: refused.
    assert not streamer_layout.aspect_ok(
        1920, 1080, {"x": 0.4, "y": 0.05, "w": 0.2, "h": 0.9})
    # An ultrawide box would leave the streamer under 15%: refused.
    assert not streamer_layout.aspect_ok(
        1920, 1080, {"x": 0.02, "y": 0.02, "w": 0.95, "h": 0.15})


def test_the_crop_box_is_even_and_inside_the_frame():
    rect = {"x": 0.33, "y": 0.21, "w": 0.19, "h": 0.41}
    w, h, x, y = streamer_layout.crop_box(rect, 1918, 1078)
    assert (w, h, x, y) == (364, 442, 633, 226)
    assert w % 2 == 0 and h % 2 == 0
    assert x + w <= 1918 and y + h <= 1078


# --------------------------------------------------------------------------- #
# Filtergraph shape
# --------------------------------------------------------------------------- #
NINE_EIGHT = {"x": 0.3, "y": 0.2, "w": 0.31640625, "h": 0.5}
SIXTEEN_NINE = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}


def test_the_default_9_8_box_is_an_even_split_without_any_blur():
    graph = streamer_layout.build_filtergraph(
        1080, 1920, NINE_EIGHT, 1920, 1080, bottom_is_half=True)
    # Top half: the marked 9:8 source box, filling the 9:8 panel.
    assert "crop=608:540:576:216" in graph
    assert "scale=1080:960:force_original_aspect_ratio=increase" in graph
    # Bottom half: the 9:8 reframe scaled straight onto its panel. No blurred
    # fill, no overlay, no second scale of a 9:16 picture.
    assert "gblur" not in graph
    assert "overlay=" not in graph
    assert "scale=-2:960" not in graph
    assert graph.count("scale=1080:960:force_original_aspect_ratio=increase") == 2
    assert "vstack=inputs=2" in graph


def test_a_16_9_box_spares_most_of_the_frame_for_the_clip():
    graph = streamer_layout.build_filtergraph(
        1080, 1920, SIXTEEN_NINE, 1920, 1080, bottom_is_half=True)
    # 16:9 puts the streamer in 1080x608 and gives the clip 1080x1312.
    assert "scale=1080:608:force_original_aspect_ratio=increase" in graph
    assert "scale=1080:1312:force_original_aspect_ratio=increase" in graph
    assert "gblur" not in graph and "overlay=" not in graph
    assert "vstack=inputs=2" in graph


def test_the_legacy_blurred_fit_survives_for_a_mismatched_bottom():
    graph = streamer_layout.build_filtergraph(1080, 1920, NINE_EIGHT, 1920, 1080)
    # An older/9:16 reframe is still fitted at its real size over a blurred bed
    # rather than being cropped or stretched to fill.
    assert "gblur=sigma=24" in graph
    assert "scale=-2:960" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph
    assert "vstack=inputs=2" in graph


def test_split_heights_and_bottom_shape_follow_the_box():
    assert streamer_layout.split_heights(
        1080, 1920, NINE_EIGHT, 1920, 1080) == (960, 960)
    assert streamer_layout.split_heights(
        1080, 1920, SIXTEEN_NINE, 1920, 1080) == (608, 1312)
    assert abs(streamer_layout.bottom_aspect(SIXTEEN_NINE, 1920, 1080)
               - 1080 / 1312) < 1e-3
    # A box that would erase the clip is clamped to the 85% panel.
    tallest = {"x": 0.4, "y": 0.01, "w": 0.2, "h": 0.98}
    assert streamer_layout.split_heights(
        1080, 1920, tallest, 1920, 1080) == (1632, 288)


def test_the_caption_seam_is_the_border_between_the_panels():
    """``main`` records ``top_share(src_w, src_h, rect)`` as caption_seam.

    The source size comes first (``bottom_aspect`` takes the rect first), and
    passing the rect first crashed every streamer job before any clip was cut:
    ``AttributeError: 'int' object has no attribute 'get'``.
    """
    boxes = [NINE_EIGHT, SIXTEEN_NINE,
             {"x": 0.3, "y": 0.1, "w": 0.25, "h": 0.25}]
    for rect in boxes:
        # Positional, in main's argument order: a swapped call raises here.
        seam = streamer_layout.top_share(1920, 1080, rect)
        top, _ = streamer_layout.split_heights(1080, 1920, rect, 1920, 1080)
        assert abs(seam * 1920 - top) <= 2      # even-height rounding
        assert 0.0 < seam < 1.0


def test_bottom_frame_detection_matches_the_expected_panel_shape():
    expected = streamer_layout.bottom_aspect(SIXTEEN_NINE, 1920, 1080)
    assert streamer_layout.is_bottom_frame(1080, 1312, expected)
    assert streamer_layout.is_bottom_frame(1215, 1080, 9 / 8)  # 1080p 9:8
    assert not streamer_layout.is_bottom_frame(1080, 1920, 9 / 8)  # a 9:16 clip
    assert not streamer_layout.is_bottom_frame(1080, 1312, 9 / 8)
    assert not streamer_layout.is_bottom_frame(0, 0, 9 / 8)


# --------------------------------------------------------------------------- #
# Real composition (synthetic media only)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="needs ffmpeg/ffprobe")
def test_legacy_composition_keeps_the_clip_size_and_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("FFMPEG_ENCODER", "x264")
    source = str(tmp_path / "source.mp4")
    clip = str(tmp_path / "clip.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", source,
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=180x320:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip,
    ], check=True)

    rect = {"x": 0.2, "y": 0.1, "w": 0.31640625, "h": 0.5}
    assert streamer_layout.apply(clip, source, 0.0, 2.0, rect)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", clip,
    ], capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == (180, 320)
    audio = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "json", clip,
    ], capture_output=True, text=True, check=True)
    assert json.loads(audio.stdout)["streams"][0]["codec_type"] == "audio"
    assert os.path.getsize(clip) > 0
    assert not os.path.exists(clip + ".streamer.tmp.mp4")


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="needs ffmpeg/ffprobe")
def test_a_16_9_box_composes_a_full_bleed_bottom_panel(tmp_path, monkeypatch):
    """The flexible streamer path: a 16:9 box takes 1080x608, the clip gets
    1080x1312 rendered at that shape, and the compose has no fill at all."""
    monkeypatch.setenv("FFMPEG_ENCODER", "x264")
    source = str(tmp_path / "source.mp4")
    clip = str(tmp_path / "clip.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", source,
    ], check=True)
    # The bottom panel at its expected 1080:1312 shape, with a white stripe on
    # the very left edge: a full-bleed compose keeps it at x=0 of the panel.
    # The old fit-over-blur would centre the picture and put a blurred copy at
    # the edge instead.
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=green:s=270x328:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
        "-vf", "drawbox=x=0:y=0:w=6:h=328:color=white:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip,
    ], check=True)

    rect = {"x": 0.2, "y": 0.1, "w": 0.5, "h": 0.5}   # 16:9 on 320x180
    assert streamer_layout.aspect_ok(320, 180, rect)
    assert streamer_layout.is_bottom_frame(
        *streamer_layout.probe_size(clip),
        streamer_layout.bottom_aspect(rect, 320, 180))
    assert streamer_layout.apply(clip, source, 0.0, 2.0, rect)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", clip,
    ], capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    # delivery_size(320, 180, 9:16) floors the width at 1080.
    assert (stream["width"], stream["height"]) == (1080, 1920)
    audio = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "json", clip,
    ], capture_output=True, text=True, check=True)
    assert json.loads(audio.stdout)["streams"][0]["codec_type"] == "audio"
    assert os.path.getsize(clip) > 0

    import cv2
    frame = cv2.VideoCapture(clip).read()[1]
    assert frame is not None
    y = 1200                       # inside the clip panel (608..1920)
    left = frame[y, 8]             # edge of the panel
    middle = frame[y, 540]
    assert int(left.min()) > 170   # the white stripe, not a blurred green flank
    assert int(middle[1]) > 70 and int(middle[0]) < 90  # green (BGR)


def test_a_box_outside_the_split_range_keeps_the_normal_clip(tmp_path):
    source = str(tmp_path / "source.mp4")
    clip = str(tmp_path / "clip.mp4")
    with open(source, "wb") as handle:
        handle.write(b"not really a video")
    with open(clip, "wb") as handle:
        handle.write(b"keep me")
    # 0.2 x 0.9 on 1920x1080 is 384x972: so tall the clip would get <15%.
    assert not streamer_layout.apply(
        clip, source, 0, 10, {"x": 0.4, "y": 0.05, "w": 0.2, "h": 0.9},
        src_w=1920, src_h=1080)
    with open(clip, "rb") as handle:
        assert handle.read() == b"keep me"


# --------------------------------------------------------------------------- #
# Detection mask: the tracker must ignore the streamer's box
# --------------------------------------------------------------------------- #
def test_the_detection_frame_blanks_the_marked_streamer_box(monkeypatch):
    import numpy as np
    import main

    rect = {"x": 0.25, "y": 0.2, "w": 0.5, "h": 0.5}
    frame = np.full((100, 200, 3), 255, dtype=np.uint8)
    monkeypatch.setenv("STREAMER_MODE", "1")
    monkeypatch.setenv("STREAMER_RECT_JSON", json.dumps(rect))

    masked = main._mask_streamer_area(frame)

    assert masked.shape == frame.shape
    assert int(masked[20:70, 50:150].max()) == 0      # the box, and only it
    assert int(masked[0:19, :].max()) == 255
    assert int(masked[:, 0:49].max()) == 255
    assert int(masked[70:, :].max()) == 255
    assert int(masked[:, 150:].max()) == 255
    # The frame handed to the renderer must keep every pixel.
    assert int(frame.min()) == 255


def test_no_streamer_box_means_the_detection_frame_is_untouched(monkeypatch):
    import numpy as np
    import main

    frame = np.full((10, 10, 3), 7, dtype=np.uint8)
    monkeypatch.delenv("STREAMER_MODE", raising=False)
    monkeypatch.delenv("STREAMER_RECT_JSON", raising=False)
    assert main._mask_streamer_area(frame) is frame

    # A broken box is ignored rather than crashing a render.
    monkeypatch.setenv("STREAMER_MODE", "1")
    monkeypatch.setenv("STREAMER_RECT_JSON", "not json")
    assert main._mask_streamer_area(frame) is frame


def test_both_detectors_apply_the_streamer_mask():
    text = _read(REPO, "main.py")
    face = text[text.index("def detect_face_candidates"):
                text.index("def detect_person_yolo")]
    yolo = text[text.index("def detect_person_yolo"):
                text.index("def create_general_frame")]
    assert "_mask_streamer_area(" in face
    assert "_mask_streamer_area(" in yolo


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
def test_the_single_video_panel_has_the_marker_and_sends_the_box():
    media = _read(SRC, "components", "MediaInput.jsx")
    marker = _read(SRC, "components", "StreamerMarker.jsx")
    app = _read(SRC, "App.jsx")
    assert "streamed video" in media
    assert "StreamerMarker" in media and "<StreamerMarker" in media
    assert "mark streamer box" in media
    assert "/api/streamer/prepare" in media
    assert "streamer: (!bulk && streamed && streamerRect) ? streamerRect : null" in media
    # Bulk mode never offers it, matching "single video processes only".
    assert "if (next) setStreamed(false)" in media
    assert "streamer: data.streamer ? JSON.stringify(data.streamer)" in app

    # The marker resizes freely; the box shape (not a fixed 9:8 lock) splits.
    assert "DEFAULT_MARKER_ASPECT = 9 / 8" in marker
    assert "MIN_ASPECT" in marker and "MAX_ASPECT" in marker
    assert "streamer {aspectLabel(aspect)}" in marker
    assert "split ${Math.round(share * 100)}%" in marker
    assert "pointermove" in marker and "pointerup" in marker
    assert "onLoadedMetadata" in marker


def test_the_backend_validates_renders_and_tells_the_ai():
    server = _read(REPO, "app.py")
    main = _read(REPO, "main.py")
    worker = _read(REPO, "gemini_worker.py")
    assert '@app.post("/api/streamer/prepare")' in server
    assert '@app.get("/api/streamer/source/{item_id}")' in server
    assert 'env["STREAMER_MODE"] = "1"' in server
    assert "streamer_layout.clean_rect" in server
    assert "Streamer layout needs a vertical" in server
    assert "streamer_layout.apply(" in main
    assert "clip_final_path, input_video, start, end, streamer_rect" in main
    # The bottom panel is rendered at the shape the marked box leaves, with no
    # blurred filler, and an out-of-range box degrades to a normal clip.
    assert "streamer_bottom_aspect = _streamer.bottom_aspect(" in main
    assert "bottom_aspect = streamer_bottom_aspect" in main
    assert "reframe_aspect=bottom_aspect" in main
    assert "no_blur=bool(streamer_rect)" in main
    assert "_streamer.aspect_ok(*streamer_source_size, streamer_rect)" in main
    assert '"bottom_aspect": round(streamer_bottom_aspect, 6)' in main
    # Captions ride the seam between the panels, recorded for every restyle.
    assert "streamer_caption_seam = _streamer.top_share(" in main
    assert re.search(r"top_share\(\s*\*streamer_source_size, streamer_rect\)",
                     main), "top_share takes (src_w, src_h, rect)"
    assert '"caption_seam": round(streamer_caption_seam, 6)' in main
    assert "seam_share=streamer_caption_seam" in main
    assert "_streamer_caption_seam(clip_data)" in server
    assert "seam_share=None" in _read(REPO, "subtitles.py")
    assert "elif no_blur:" in _read(REPO, "reframe_v2.py")
    assert "streamer_prompt_note()" in main
    assert "STREAMER_NOTE" in worker
    assert 'os.getenv("STREAMER_MODE") == "1"' in worker
    # The split is composed before captions/hook: those lines come after it.
    composed = main.index("streamer_layout.apply(")
    captioned = main.index("auto_hook_clip(clip_final_path", composed)
    assert composed < captioned


def test_the_streamer_prompt_note_is_only_added_in_streamer_mode(monkeypatch):
    import main
    monkeypatch.delenv("STREAMER_MODE", raising=False)
    assert main.streamer_prompt_note() == ""
    monkeypatch.setenv("STREAMER_MODE", "1")
    note = main.streamer_prompt_note()
    assert "STREAMED SOURCE" in note
    assert "streamer" in note.lower()


def test_a_collector_item_exposes_its_local_preview(tmp_path, monkeypatch):
    import collector
    root = tmp_path / "collector"
    (root / "files").mkdir(parents=True)
    (root / "files" / "x.mp4").write_bytes(b"video")
    monkeypatch.setattr(collector, "COLLECTOR_DIR", str(root))
    item = collector.public({"id": "abc", "file": "files/x.mp4", "title": "Clip"})
    assert item["ready"] is True
    assert item["video"] == "/collector/files/x.mp4"
