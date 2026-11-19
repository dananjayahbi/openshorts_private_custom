"""No 15-clip ceiling in the generator.

The clip count used to be capped at 15 in four places: the dashboard input, the
API's ``target_clips`` validation, the MCP tool schema, and the shortlist /
detail bands. An hours-long source is supposed to be able to yield 100s of
clips, so the shortlist scales with duration (and with an explicit target) and
the detail pass is split into batches instead of one call with a fixed 15.

These are source contracts, like the other dashboard/pipeline tests; the
numeric behaviour is covered by tests/test_clip_selection.py.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def test_dashboard_number_input_has_no_max():
    page = _read("dashboard", "src", "components", "MediaInput.jsx")
    block = page.split('value={targetClips}', 1)[0].rsplit('<input', 1)[1]
    assert 'type="number"' in block
    assert 'max="15"' not in block
    assert "100s of clips" in page


def test_api_accepts_a_target_above_fifteen():
    app = _read("app.py")
    assert '_gen_control(target_clips, "target_clips", 1, None, integer=True)' in app
    assert "_gen_control(target_clips, \"target_clips\", 1, 15" not in app


def test_mcp_schema_has_no_maximum():
    mcp = _read("mcp_server.py")
    block = mcp.split('"target_clips": {', 1)[1].split("},", 1)[0]
    assert '"minimum": 1' in block
    assert '"maximum": 15' not in block
    assert "No upper limit" in block


def test_detail_pass_is_batched_and_scales_the_shortlist():
    main = _read("main.py")
    assert "def requested_clip_target()" in main
    assert "def detail_window_batch()" in main
    assert "shortlist_target(video_duration, requested_clip_target())" in main
    assert "batches = [shortlist[i:i + DETAIL_BATCH]" in main
    assert "clip_count_targets(len(batch), respect_env=False)" in main


def test_clip_count_helper_has_no_twelve_clip_clamp():
    src = _read("clip_selection.py")
    assert "min(12" not in src
    assert "min(10, int(seconds // 90)" not in src