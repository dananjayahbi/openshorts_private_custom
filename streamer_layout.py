"""Streamer split layout: streamer cam on top, viral clip on the bottom.

A streamed source has a box (a webcam, a green-screen inset, a fixed cam)
somewhere in the frame. The user marks that box once, before the render, on the
original source at its true aspect ratio. The box's own shape decides the split:
the top panel keeps the marked aspect exactly, and the viral clip takes all the
height that is left. Every rendered clip is still the same 9:16 output:

    +---------------------------+
    |   streamer crop 1080xTop  |   the marked box, scaled to its panel
    +---------------------------+
    |   viral clip 1080xBottom  |   the reframe, rendered natively at the
    |                           |   remaining shape (full bleed, no fill)
    +---------------------------+

A 9:8 box is the even 50/50 split (1080x960 + 1080x960). A 16:9 box takes about
32% (1080x608) and gives the clip the other ~68% (1080x1312); a square box takes
56%, and so on. Top + Bottom always add up to the 1080x1920 delivery.

The share is clamped to 15%-85% so neither panel can swallow the frame, and the
marker is validated against that range. The box is stored as fractions of the
source frame (``x``, ``y``, ``w``, ``h``), so it survives any source resolution
and any output scale.

The bottom panel is reframed at its own shape instead of the 9:16 delivery
frame, so it fills its half edge to edge. Fitting a 9:16 reframe inside a wider
panel left blurred bands either side of the picture; there is nothing left to
fill once the reframe targets the panel shape itself.

Caption/hook burning happens *after* this pass in ``main.py``, so the existing
style and position are untouched: the text simply sits on top of the composed
frame the same way it would have sat on the plain reframe.
"""
import json
import math
import os
import subprocess

VERTICAL_ASPECT = 9.0 / 16.0
# The 50/50 split the marker starts from: half of a 9:16 frame is 9:8.
DEFAULT_MARKER_ASPECT = 9.0 / 8.0
# A panel never takes the whole frame: both halves stay at least 15% tall.
MIN_TOP_SHARE = 0.15
MAX_TOP_SHARE = 0.85
# The marker shapes those bounds allow, measured in source pixels.
MIN_MARKER_ASPECT = VERTICAL_ASPECT / MAX_TOP_SHARE   # ~0.662, a tall box
MAX_MARKER_ASPECT = VERTICAL_ASPECT / MIN_TOP_SHARE   # 3.75, a very wide box
MIN_SIDE = 0.02          # reject a click, not a box
BLUR_SIGMA = 24          # legacy fit path only; the native bottom needs no fill


class StreamerRectError(ValueError):
    """The caller's rectangle is not a usable box on the source."""


def _number(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise StreamerRectError(f"{name} must be a number")
    if not math.isfinite(number):
        raise StreamerRectError(f"{name} must be finite")
    return number


def clean_rect(raw):
    """Validate/normalise a ``{x, y, w, h}`` rectangle (fractions of the frame).

    Accepts the dashboard's object or its JSON string form. Returns a rounded
    dict so the value written to metadata and sent to the renderer is stable.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise StreamerRectError("streamer rectangle must be valid JSON")
    if not isinstance(raw, dict):
        raise StreamerRectError("streamer rectangle must be an object")
    values = {key: _number(raw.get(key), key) for key in ("x", "y", "w", "h")}
    if values["w"] < MIN_SIDE or values["h"] < MIN_SIDE:
        raise StreamerRectError("streamer rectangle is too small")
    if values["x"] < -1e-6 or values["y"] < -1e-6:
        raise StreamerRectError("streamer rectangle starts outside the video")
    if values["x"] + values["w"] > 1.0001 or values["y"] + values["h"] > 1.0001:
        raise StreamerRectError("streamer rectangle ends outside the video")
    return {key: round(min(max(value, 0.0), 1.0), 6) for key, value in values.items()}


def marker_aspect(src_w, src_h, rect):
    """Pixel aspect (width / height) of the marked box on this source.

    The same normalized box on a 16:9 source and a 4:3 source is not the same
    shape, so the split is derived from the box measured in real pixels.
    """
    if not src_w or not src_h or not rect.get("h"):
        return DEFAULT_MARKER_ASPECT
    return (rect["w"] * src_w) / (rect["h"] * src_h)


def top_share(src_w, src_h, rect):
    """Share (0..1) of the delivered height the streamer panel takes.

    A box's shape fixes its panel: the width is always the output width, so a
    panel of aspect ``r`` is ``VERTICAL_ASPECT / r`` of the 9:16 height. Clamped
    so a very tall or very wide box cannot erase the other panel.
    """
    aspect = marker_aspect(src_w, src_h, rect)
    if aspect <= 0:
        return 0.5
    share = VERTICAL_ASPECT / aspect
    return min(MAX_TOP_SHARE, max(MIN_TOP_SHARE, share))


def bottom_aspect(rect, src_w=None, src_h=None):
    """Pixel aspect the bottom panel must be rendered at.

    The clip gets the height the streamer box did not use, so its shape is the
    9:16 delivery divided by that remaining share: 9:8 (1.125) for the default
    50/50 box, ~0.823 (1080x1312) for a 16:9 box, 1.0 when the box is square.
    """
    share = top_share(src_w, src_h, rect)
    return VERTICAL_ASPECT / max(1e-6, 1.0 - share)


def aspect_ok(src_w, src_h, rect):
    """Whether the marked box's shape fits the allowed split range.

    The browser clamps free resize to the same bounds, but API callers can send
    anything. A 2% window covers the rounding of a box drawn at a limit; a box
    outside it would leave one panel with almost no height, so the renderer
    keeps the normal clip instead.
    """
    if not src_w or not src_h:
        return True
    aspect = marker_aspect(src_w, src_h, rect)
    return (MIN_MARKER_ASPECT * 0.98 <= aspect
            <= MAX_MARKER_ASPECT * 1.02)


def probe_size(path):
    """``(width, height)`` of the first video stream, or ``(0, 0)``."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        return int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0, 0


def has_audio(path):
    """Whether the reframed clip carries an audio stream.

    Silent sources are supported by the pipeline; adding ``-af``/``-map 1:a?``
    to a file with no audio makes ffmpeg fail the whole pass instead.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout or "{}")
        return bool(data.get("streams"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def crop_box(rect, src_w, src_h):
    """Integer, even ``(w, h, x, y)`` crop inside the source frame."""
    if src_w <= 0 or src_h <= 0:
        raise StreamerRectError("could not read the source video size")
    width = max(2, int(round(rect["w"] * src_w / 2.0)) * 2)
    height = max(2, int(round(rect["h"] * src_h / 2.0)) * 2)
    width = min(width, src_w - (src_w % 2))
    height = min(height, src_h - (src_h % 2))
    x = int(round(rect["x"] * src_w))
    y = int(round(rect["y"] * src_h))
    x = min(max(0, x), src_w - width)
    y = min(max(0, y), src_h - height)
    return width, height, x, y


def split_heights(out_w, out_h, rect, src_w, src_h):
    """Even ``(top, bottom)`` pixel heights for this marker on this output.

    Both are even (x264/NVENC reject odd ones) and always add up to ``out_h``,
    so the composed frame is exactly the 9:16 delivery whatever the box shape.
    """
    out_h = max(4, int(out_h) - (int(out_h) % 2))
    share = top_share(src_w, src_h, rect)
    top = int(round(out_h * share / 2.0)) * 2
    top = max(2, min(top, out_h - 2))
    return top, out_h - top


def is_bottom_frame(width, height, expected_aspect, tol=0.02):
    """Whether this frame already has the bottom panel's expected shape.

    That is what streamer mode renders now, so the composer can stack it
    straight onto its panel. Anything else - an older render, a non-streamer
    clip - keeps the legacy fit-over-blur path.
    """
    if not width or not height or not expected_aspect:
        return False
    return abs(width / float(height) - expected_aspect) <= expected_aspect * tol


def build_filtergraph(out_w, out_h, rect, src_w, src_h, bottom_is_half=False):
    """The ffmpeg graph: source crop -> top panel, reframe -> bottom panel.

    Input 0 is the source (cut to the clip's time range), input 1 is the
    reframe. The panel heights come from the marked box's aspect, so a 16:9 box
    leaves most of the frame to the clip and a 9:8 box splits it evenly.

    ``bottom_is_half`` is the normal streamer path: input 1 was rendered at the
    bottom panel's shape, so it is scaled straight onto it - full bleed, no
    blurred fill. The legacy path (``False``) fits a 9:16 reframe at its real
    aspect over a blurred copy of itself; it survives for clips rendered before
    the bottom panel took its own shape, and any caller that hands us a frame
    of the wrong shape.
    """
    out_w = max(2, int(out_w) - (int(out_w) % 2))
    out_h = max(4, int(out_h) - (int(out_h) % 2))
    top_h, bottom_h = split_heights(out_w, out_h, rect, src_w, src_h)
    cw, ch, cx, cy = crop_box(rect, src_w, src_h)
    if bottom_is_half:
        bottom = (f"[1:v]scale={out_w}:{bottom_h}:"
                  f"force_original_aspect_ratio=increase,"
                  f"crop={out_w}:{bottom_h},setsar=1[bottom];")
    else:
        bottom = (
            f"[1:v]split=2[bg][fg];"
            f"[bg]scale={out_w}:{bottom_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{bottom_h},gblur=sigma={BLUR_SIGMA}[bg2];"
            f"[fg]scale=-2:{bottom_h},setsar=1[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2[bottom];"
        )
    return (
        f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
        f"scale={out_w}:{top_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{top_h},setsar=1[top];"
        + bottom +
        f"[top][bottom]vstack=inputs=2[v]"
    )


def apply(clip_path, source_path, start, end, rect, src_w=None, src_h=None):
    """Compose the split layout over ``clip_path`` in place.

    Returns True on success. On any failure the original reframed clip is left
    untouched (a normal clip is better than a missing one), and the reason is
    printed for the job log.
    """
    import ffmpeg_utils

    clean = clean_rect(rect)
    if not src_w or not src_h:
        src_w, src_h = probe_size(source_path)
    if not aspect_ok(src_w, src_h, clean):
        print("\u26a0\ufe0f Streamer box shape is outside the 15%-85% split range "
              "- keeping the normal clip.")
        return False
    out_w, out_h = probe_size(clip_path)
    if out_w <= 0 or out_h <= 0:
        print("\u26a0\ufe0f Streamer layout: could not read the reframed clip size.")
        return False
    # The bottom panel is rendered at the shape the marker leaves, so it fills
    # its panel with no fill. The delivered size stays the normal 9:16 one.
    native_bottom = is_bottom_frame(out_w, out_h,
                                    bottom_aspect(clean, src_w, src_h))
    if native_bottom:
        import reframe_v2
        out_w, out_h = reframe_v2.delivery_size(src_w, src_h, VERTICAL_ASPECT)
    duration = max(0.1, float(end) - float(start))
    tmp = f"{clip_path}.streamer.tmp.mp4"
    graph = build_filtergraph(out_w, out_h, clean, src_w, src_h,
                              bottom_is_half=native_bottom)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{max(0.0, float(start)):.3f}",
        "-t", f"{duration:.3f}",
        "-i", source_path,
        "-i", clip_path,
        "-filter_complex", graph,
        "-map", "[v]",
        *ffmpeg_utils.video_encode_args(ffmpeg_utils.QUALITY_FAST),
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
    ]
    if has_audio(clip_path):
        cmd[-4:-4] = ["-map", "1:a?", *ffmpeg_utils.audio_encode_args()]
    cmd.append(tmp)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
        if result.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            detail = (result.stderr or "").strip().splitlines()
            print(f"\u26a0\ufe0f Streamer layout failed: "
                  f"{detail[-1] if detail else 'ffmpeg error'}")
            return False
        os.replace(tmp, clip_path)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"\u26a0\ufe0f Streamer layout failed: {exc}")
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
