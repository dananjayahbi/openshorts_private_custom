"""Overnight queue: per-video streamer marks, failure isolation, one retry pass.

Source contracts for the dashboard loop (the rolling batch). The backend already
renders one job at a time; what matters here is that one bad video cannot stop
the queue, that the failures are retried once at the end, and that a wedged job
is stopped instead of being waited on forever.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


APP = _read(SRC, "App.jsx")
MEDIA = _read(SRC, "components", "MediaInput.jsx")


def test_a_failure_is_flagged_and_the_next_video_is_loaded():
    # Every failure path records the row and falls through to the next loop
    # iteration: no re-raise, no break (only an explicit stop breaks).
    assert "failed.add(i)" in APP
    assert "patch(i, { state: 'failed'" in APP
    assert "break;" in APP  # the cancel path
    assert APP.count("continue;") > 0


def test_failures_are_retried_once_at_the_end_then_ignored():
    assert "autoRetry = false" in APP
    assert "Retrying ${retryIndices.length} failed video(s) once" in APP
    assert "runBatchRows(items, options, retryIndices, { autoRetry: false })" in APP
    # The retry pass runs inside the same run, after the first pass finished.
    first = APP.index("if (autoRetry && !cancelled")
    inner = APP.index("autoRetry: false })", first)
    assert first < inner


def test_a_wedged_job_is_cancelled_and_skipped():
    assert "STALL_MS" in APP
    assert "lastActivity" in APP
    assert "return 'stalled'" in APP
    assert "No progress for" in APP
    assert "cancelServerJob(id)" in APP


def test_the_queue_summary_shows_failures_and_can_be_opened():
    assert "batchDetails" in APP
    assert "queueFailed" in APP
    assert "row.state === 'failed'" in APP
    assert "row.error" in APP


def test_the_machine_is_kept_awake_while_the_queue_runs():
    assert "navigator.wakeLock" in APP
    assert "wakeLock.request('screen')" in APP


def test_every_bulk_row_carries_its_own_two_boxes():
    assert "bulkQueue" in MEDIA
    assert "marks[entry.key]" in MEDIA
    assert "openMarkerFor" in MEDIA
    # A URL only downloads once for the marker; the job reuses that Collector id.
    assert "preparedId" in MEDIA
    assert "type: 'collector', payload: mark.preparedId" in MEDIA
    assert "streamer: streamed ? (mark.rect || null) : null" in MEDIA
    assert "streamerAvoid: streamed ? (mark.avoid || null) : null" in MEDIA
    # The shared batch options must not carry a crop at all.
    assert "streamer: null, streamerAvoid: null" in MEDIA
    # Submitting a streamed queue with an unmarked row is refused up front.
    assert "still need a streamer box" in MEDIA


def test_a_bulk_row_can_reuse_the_previous_marks():
    assert "copy previous" in MEDIA
    assert "previous?.rect" in MEDIA
    # ...but never the previous URL's prepared Collector id.
    assert "preparedId: previous" not in MEDIA
