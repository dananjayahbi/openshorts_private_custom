"""Batch queue: per-video logs, failure diagnosis, and retry.

The queue is a browser-side loop over /api/process. Before this, a queued video
showed only "processing", so a failure that came from the AI provider (empty or
truncated answer) was indistinguishable from a broken source, and the row gave
no reason. These are source contracts: there is no JS test runner in the repo,
and the wiring is what keeps regressing.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as f:
        return f.read()


def test_each_row_keeps_the_job_log_tail():
    app = _read("App.jsx")
    # waitForJob hands every status payload to the caller.
    assert "waitForJob = async (id, onSnapshot)" in app
    assert "onSnapshot?.(state)" in app
    # The batch loop stores logs/timestamps/progress on the row.
    assert "logs: lastLogs" in app
    assert "logTimes: Array.isArray(state.log_times)" in app
    assert "lastLogs = Array.isArray(state.logs) ? state.logs : lastLogs" in app


def test_a_failed_row_shows_the_pipeline_line_not_just_job_failed():
    app = _read("App.jsx")
    assert "const tail = [...lastLogs].reverse()" in app
    assert "error: tail ? String(tail).slice(0, 300)" in app


def test_batch_queue_renders_a_terminal_per_video():
    page = _read("components", "BatchQueue.jsx")
    assert "RowLogs" in page
    assert "row.logs" in page
    assert "row.logTimes" in page
    # The row that is working is expanded automatically.
    assert "runningIndex" in page and "setOpen" in page
    # A collapsed row still carries its last output line.
    assert "lastLine" in page


def test_failed_rows_can_be_retried_without_rerunning_the_whole_queue():
    app = _read("App.jsx")
    page = _read("components", "BatchQueue.jsx")
    assert "retryFailedBatch" in app
    assert "onRetryFailed" in page
    assert "retry failed" in page
    # Retry keeps rows that already succeeded: only failed/cancelled indices run.
    assert "row.state === 'failed' || row.state === 'cancelled'" in app


def test_the_batch_loop_cannot_be_started_twice():
    app = _read("App.jsx")
    assert "batchRunRef" in app
    assert "if (batchRunRef.current) return;" in app
