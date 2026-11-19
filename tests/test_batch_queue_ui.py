"""Batch queue = the single-video flow in a loop.

The queue used to have its own screen (BatchQueue.jsx: one collapsible terminal
per video). It now does what the task asked: pull the first video and process it
exactly like a manual run — same processing screen, same log tail, same clip
cards — then save the clips to the gallery, clear the job, show "Preparing the
environment for the next video", and pull the next one. Above the ordinary
screen there is only a slim progress line.

These are source contracts: there is no JS test runner in the repo.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_queue_drives_the_single_video_state():
    app = _read("App.jsx")
    # waitForJob hands every status payload to the loop.
    assert "waitForJob = async (id, onSnapshot)" in app
    assert "onSnapshot?.(state)" in app
    # The same state the manual flow writes, from every snapshot.
    assert "if (state.result) setResults(state.result)" in app
    assert "if (state.logs) {" in app
    assert "setLogs(state.logs)" in app
    assert "setLogTimes(Array.isArray(state.log_times) ? state.log_times : [])" in app
    # Completion is the ordinary results screen, not a queue screen.
    assert "setStatus('complete')" in app
    assert "Clips saved to the gallery" in app


def test_the_queue_screen_is_the_processing_screen_not_a_second_ui():
    app = _read("App.jsx")
    assert "BatchQueue" not in app  # import and render are gone
    assert "{activeTab === 'dashboard' && (status === 'processing'" in app
    # Only the slim progress line is extra.
    assert 'className="readout shrink-0">queue</span>' in app
    assert "queueCurrent" in app and "queueDone" in app


def test_it_says_preparing_the_environment_between_videos():
    app = _read("App.jsx")
    assert "Preparing the environment for the next video…" in app
    assert "Next: ${label}" in app
    # The previous job's result/source is cleared before the next submission.
    for cleared in ("setResults(null)", "setJobId(null)", "setProjectState(null)"):
        assert cleared in app


def test_a_failed_video_still_shows_the_pipeline_line():
    app = _read("App.jsx")
    assert "const tail = [...lastLogs].reverse()" in app
    assert "const error = tail ? String(tail).slice(0, 300)" in app
    assert "setJobError(error)" in app


def test_failed_rows_can_be_retried_without_rerunning_the_whole_queue():
    app = _read("App.jsx")
    assert "retryFailedBatch" in app
    assert "retry failed" in app
    # Retry keeps rows that already succeeded: only failed/cancelled indices run.
    assert "row.state === 'failed' || row.state === 'cancelled'" in app


def test_the_batch_loop_cannot_be_started_twice():
    app = _read("App.jsx")
    assert "batchRunRef" in app
    assert "if (batchRunRef.current) return;" in app
    # The single-job poller must not race the loop's own waitForJob.
    assert "if (batchRunRef.current) return undefined;" in app