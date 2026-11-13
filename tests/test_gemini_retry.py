"""Retry behaviour of the moment-picker stage.

Prod (22-jul-2026) lost 3 jobs to the model answering 200 with an empty body.
That raises while parsing, not while calling, so it used to escape the retry
loop and kill the job on the first blip.

The provider chain now lives in ``llm_backend.generate_json``; the three-attempt
transient policy lives in ``main._run_gemini_stage`` and is shared by every
provider. These tests pin that policy without touching the network.
"""
import pytest

# main pulls in cv2/torch/mediapipe at import time; the minimal CI env lacks
# them, so skip there. Runs fully in the container/local where deps exist.
main = pytest.importorskip("main")

import gemini_worker
import llm_backend


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)


def _sequence(monkeypatch, outcomes):
    """generate_json: raise/return each outcome in turn, then keep the last."""
    calls = {"n": 0}

    def fake_generate(prompt, schema, model=None):
        index = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        outcome = outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, {"total_cost": 0.0}

    monkeypatch.setattr(llm_backend, "generate_json", fake_generate)
    return calls


def test_recovers_from_a_single_empty_body(monkeypatch):
    calls = _sequence(monkeypatch, [
        RuntimeError("empty response body"),
        {"windows": [{"id": "w0", "score": 90}]},
    ])
    parsed, _cost = main._run_gemini_stage(None, "m", "prompt",
                                           gemini_worker.ScoreResponse)
    assert calls["n"] == 2
    assert parsed["windows"][0]["score"] == 90


def test_recovers_from_two_consecutive_blips(monkeypatch):
    calls = _sequence(monkeypatch, [
        RuntimeError("empty response body"),
        RuntimeError("empty response body"),
        {"windows": [{"id": "w0", "score": 80}]},
    ])
    parsed, _ = main._run_gemini_stage(None, "m", "prompt",
                                       gemini_worker.ScoreResponse)
    assert calls["n"] == 3
    assert parsed["windows"]


def test_gives_up_after_three_attempts(monkeypatch):
    calls = _sequence(monkeypatch, [RuntimeError("empty response body")])
    with pytest.raises(Exception) as exc:
        main._run_gemini_stage(None, "m", "prompt", gemini_worker.ScoreResponse)
    assert calls["n"] == 3
    assert "empty response body" in str(exc.value)


def test_non_transient_errors_are_not_retried(monkeypatch):
    calls = _sequence(monkeypatch, [ValueError("400 INVALID_ARGUMENT: bad request")])
    with pytest.raises(ValueError):
        main._run_gemini_stage(None, "m", "prompt", gemini_worker.ScoreResponse)
    assert calls["n"] == 1


def test_succeeds_without_retrying_when_the_first_call_is_fine(monkeypatch):
    calls = _sequence(monkeypatch, [{"windows": []}])
    main._run_gemini_stage(None, "m", "prompt", gemini_worker.ScoreResponse)
    assert calls["n"] == 1


def test_policy_block_fails_fast_without_retrying(monkeypatch):
    # Prod 23-jul-2026: PROHIBITED_CONTENT is deterministic — 3 retries just
    # burned quota and reported a misleading "empty response body".
    calls = _sequence(monkeypatch, [gemini_worker.GeminiBlockedError("PROHIBITED_CONTENT")])
    with pytest.raises(gemini_worker.GeminiBlockedError) as exc:
        main._run_gemini_stage(None, "m", "prompt", gemini_worker.ScoreResponse)
    assert calls["n"] == 1
    assert "PROHIBITED_CONTENT" in str(exc.value)


def test_blocked_finish_reason_also_raises():
    class _Cand:
        class _FR:
            name = "SAFETY"
        finish_reason = _FR()
        content = None

    class _Resp:
        prompt_feedback = None
        candidates = [_Cand()]

    with pytest.raises(gemini_worker.GeminiBlockedError):
        gemini_worker.raise_if_blocked(_Resp())


def test_clean_response_is_not_flagged_as_blocked():
    class _Resp:
        prompt_feedback = None
        candidates = []

    gemini_worker.raise_if_blocked(_Resp())  # must not raise
