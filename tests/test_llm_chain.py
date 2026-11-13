"""The five-level LLM fallback chain (llm_backend.py).

The chain is the feature that makes a failed provider a retry elsewhere instead
of a failed job. These tests pin the parts the pipeline relies on:

* levels come from Storage/settings.json (isolated per test by conftest),
* a provider failure moves to the next level in the same call,
* "configured" means at least one level can actually answer,
* the Settings API validates and persists five slots,
* main._run_gemini_stage delegates to the chain (and keeps its retry policy).
"""
import json

import httpx
import pytest

import gemini_worker
import llm_backend
import settings_store


def _completion(payload):
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def _levels(*specs):
    """Five slots; ``specs`` fill levels 1..n, the rest stay disabled."""
    out = []
    for index in range(5):
        spec = specs[index] if index < len(specs) else {}
        out.append({
            "level": index + 1,
            "enabled": bool(spec) and spec.get("enabled", True),
            "provider": spec.get("provider", "openai"),
            "model": spec.get("model", "test-model"),
            "base_url": spec.get("base_url", ""),
            "api_key": spec.get("api_key", ""),
            "timeout": 30,
        })
    return out


class TestChainConfig:
    def test_always_five_slots_for_the_ui(self):
        llm_backend.save_levels(_levels({"base_url": "http://one.test/v1"}))
        levels = llm_backend.levels_for_ui()
        assert len(levels) == 5
        assert levels[0]["enabled"] is True
        assert levels[0]["model"] == "test-model"
        assert all(lv["enabled"] is False for lv in levels[1:])

    def test_first_slot_is_provider_neutral(self, monkeypatch):
        """No vendor is privileged: a fresh install starts on a blank
        OpenAI-compatible slot, not a Gemini one."""
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        levels = llm_backend.levels_for_ui()
        assert levels[0]["provider"] == "openai"
        assert levels[0]["base_url"] == ""
        assert levels[0]["model"] == ""
        assert levels[0]["apiKeyFromEnv"] is False

    def test_disabled_levels_are_never_tried(self):
        llm_backend.save_levels(_levels(
            {"base_url": "http://off.test/v1", "enabled": False},
            {"base_url": "http://on.test/v1"},
        ))
        assert len(llm_backend.levels()) == 1
        assert llm_backend.levels()[0]["base_url"] == "http://on.test/v1"

    def test_openai_level_without_a_base_url_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            llm_backend.save_levels(_levels({"provider": "openai", "base_url": ""}))
        assert "base URL" in str(exc.value)

    def test_a_gemini_level_without_a_key_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        llm_backend.save_levels(_levels({"provider": "gemini", "api_key": ""}))
        assert llm_backend.configured() is False
        assert llm_backend.describe() is None

    def test_a_gemini_level_with_a_key_is_configured(self):
        llm_backend.save_levels(_levels({"provider": "gemini", "api_key": "k"}))
        assert llm_backend.configured() is True
        assert llm_backend.gemini_key() == "k"
        assert llm_backend.active() is False  # not an OpenAI-compatible level

    def test_settings_file_round_trips(self):
        llm_backend.save_levels(_levels({"base_url": "http://one.test/v1"}))
        stored = settings_store.section("llm")["levels"]
        assert stored[0]["base_url"] == "http://one.test/v1"
        assert settings_store.path().endswith("settings.json")
        assert json.loads(open(settings_store.path(), encoding="utf-8").read())["llm"]


class TestFallback:
    def test_second_level_answers_after_the_first_fails(self, monkeypatch):
        llm_backend.save_levels(_levels(
            {"base_url": "http://dead.test/v1", "model": "dead-model"},
            {"base_url": "http://live.test/v1", "model": "live-model"},
        ))

        seen = []

        def _handler(request):
            seen.append(str(request.url))
            body = json.loads(request.content)
            assert body["model"] == "live-model"
            return _completion({"windows": []})

        # Route by URL instead of call order: the first host refuses.
        def client_factory(**kwargs):
            class Router(httpx.BaseTransport):
                def handle_request(self, request):
                    if "dead.test" in str(request.url):
                        raise httpx.ConnectError("connection refused", request=request)
                    return _handler(request)
            return httpx.Client(transport=Router(), **kwargs)

        monkeypatch.setattr(llm_backend, "_client", client_factory)
        parsed, cost = llm_backend.generate_json("prompt", gemini_worker.ScoreResponse)
        assert parsed == {"windows": []}
        assert cost["local"] is True
        assert seen == ["http://live.test/v1/chat/completions"]

    def test_a_malformed_answer_falls_through_too(self, monkeypatch):
        llm_backend.save_levels(_levels(
            {"base_url": "http://bad.test/v1"},
            {"base_url": "http://good.test/v1"},
        ))

        def client_factory(**kwargs):
            class Router(httpx.BaseTransport):
                def handle_request(self, request):
                    if "bad.test" in str(request.url):
                        return _completion({"windows": "not a list"})
                    return _completion({"windows": []})
            return httpx.Client(transport=Router(), **kwargs)

        monkeypatch.setattr(llm_backend, "_client", client_factory)
        parsed, _ = llm_backend.generate_json("prompt", gemini_worker.ScoreResponse)
        assert parsed == {"windows": []}

    def test_gemini_then_openai_fallback(self, monkeypatch):
        llm_backend.save_levels(_levels(
            {"provider": "gemini", "api_key": "g"},
            {"base_url": "http://live.test/v1"},
        ))
        calls = []

        def fake_gemini(level, prompt, schema, model=None, images=None):
            calls.append("gemini")
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        def fake_openai(level, prompt, schema, model=None, images=None):
            calls.append("openai")
            return {"windows": []}, {"local": True, "total_cost": 0.0}

        monkeypatch.setattr(llm_backend, "_generate_gemini", fake_gemini)
        monkeypatch.setattr(llm_backend, "_generate_openai", fake_openai)
        parsed, _ = llm_backend.generate_json("p", gemini_worker.ScoreResponse)
        assert parsed == {"windows": []}
        assert calls == ["gemini", "openai"]

    def test_no_configured_level_says_so(self):
        llm_backend.save_levels(_levels())
        with pytest.raises(RuntimeError) as exc:
            llm_backend.generate_json("p", gemini_worker.ScoreResponse)
        assert "No AI provider is configured" in str(exc.value)

    def test_all_levels_failing_raises_the_last_error(self, monkeypatch):
        llm_backend.save_levels(_levels(
            {"base_url": "http://one.test/v1"},
            {"base_url": "http://two.test/v1"},
        ))

        def client_factory(**kwargs):
            class Always(httpx.BaseTransport):
                def handle_request(self, request):
                    return httpx.Response(503, text="busy")
            return httpx.Client(transport=Always(), **kwargs)

        monkeypatch.setattr(llm_backend, "_client", client_factory)
        with pytest.raises(RuntimeError) as exc:
            llm_backend.generate_json("p", gemini_worker.ScoreResponse)
        assert "503" in str(exc.value)

    def test_vision_calls_fall_through_and_carry_the_frames(self, monkeypatch):
        llm_backend.save_levels(_levels(
            {"provider": "gemini", "api_key": "g"},
            {"base_url": "http://vision.test/v1"},
        ))
        seen = {}

        def fake_gemini(level, prompt, schema, model=None, images=None):
            raise RuntimeError("400 does not support images")

        def fake_openai(level, prompt, schema, model=None, images=None):
            seen["images"] = images
            return {"windows": []}, {"local": True}

        monkeypatch.setattr(llm_backend, "_generate_gemini", fake_gemini)
        monkeypatch.setattr(llm_backend, "_generate_openai", fake_openai)
        out = llm_backend.generate_vision_json(
            "p", gemini_worker.ScoreResponse, [b"jpeg-1", b"jpeg-2"])
        assert out == {"windows": []}
        assert seen["images"] == [b"jpeg-1", b"jpeg-2"]


class TestMainDelegates:
    def test_stage_walks_the_chain_and_retries(self, monkeypatch):
        main = pytest.importorskip("main")
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fake_generate(prompt, schema, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("ConnectError: connection refused")
            return {"windows": []}, {"total_cost": 0.0}

        monkeypatch.setattr(llm_backend, "generate_json", fake_generate)
        parsed, _ = main._run_gemini_stage(None, "unused", "prompt",
                                           gemini_worker.ScoreResponse)
        assert calls["n"] == 2
        assert parsed == {"windows": []}


class TestSettingsApi:
    @pytest.fixture()
    def client(self):
        app_module = pytest.importorskip("app")
        from fastapi.testclient import TestClient
        return TestClient(app_module.app)

    def test_get_returns_five_slots(self, client):
        body = client.get("/api/settings/llm").json()
        assert len(body["levels"]) == 5
        assert {p["id"] for p in body["providers"]} == {"gemini", "openai"}

    def test_put_persists_and_reports_configured(self, client):
        levels = _levels({"base_url": "http://one.test/v1"})
        body = client.put("/api/settings/llm", json={"levels": levels})
        assert body.status_code == 200
        assert body.json()["configured"] is True
        again = client.get("/api/settings/llm").json()["levels"]
        assert again[0]["base_url"] == "http://one.test/v1"

    def test_put_rejects_an_openai_level_without_a_url(self, client):
        res = client.put("/api/settings/llm", json={
            "levels": _levels({"provider": "openai", "base_url": ""})})
        assert res.status_code == 400
        assert "base URL" in res.json()["detail"]

    def test_config_exposes_configured_without_keys(self, client):
        llm_backend.save_levels(_levels(
            {"base_url": "http://one.test/v1", "api_key": "secret-key"}))
        cfg = client.get("/api/config").json()
        assert cfg["llmConfigured"] is True
        assert "secret-key" not in json.dumps(cfg)
