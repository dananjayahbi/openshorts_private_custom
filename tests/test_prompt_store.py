"""Editable prompts (prompt_store.py) and their Settings API.

The Settings page shows the exact text used today and can save an edit. The
contract that makes that safe:

* the module constants stay the defaults (nothing is duplicated),
* an edit must keep every placeholder the call site passes,
* a Style Profile can override prompts for one job via the environment,
* the API refuses a broken edit with a readable reason instead of letting the
  next job fail deep inside the pipeline.
"""
import os

import pytest

import prompt_store


class TestRegistry:
    def test_all_prompts_are_seeded_with_the_current_text(self):
        prompts = {p["id"]: p for p in prompt_store.all_prompts()}
        assert {"score", "detail", "visual", "layout", "screen_content",
                "hook_grounding", "burned_subtitles"} <= set(prompts)
        score = prompts["score"]
        assert score["template"] == score["default"]
        assert score["overridden"] is False
        assert "{windows_json}" in score["template"]

    def test_default_is_the_module_constant(self):
        import gemini_worker
        assert prompt_store.text("layout") == gemini_worker.LAYOUT_CHOICE_PROMPT
        assert prompt_store.text("screen_content") == gemini_worker.SHOT_CONTENT_PROMPT

    def test_render_formats_the_same_string_as_before(self):
        import gemini_worker
        out = prompt_store.render(
            "score", video_duration=10, language="en", windows_json="[]")
        assert out == gemini_worker.SCORE_PROMPT_TEMPLATE.format(
            video_duration=10, language="en", windows_json="[]")

    def test_edit_round_trips_and_render_uses_it(self):
        prompt_store.set_overrides({
            "score": "CUSTOM {video_duration} {windows_json} in {language}"})
        assert prompt_store.effective("score") == \
            "CUSTOM {video_duration} {windows_json} in {language}"
        assert prompt_store.render(
            "score", video_duration=1, language="de", windows_json="[]") == "CUSTOM 1 [] in de"
        assert (prompt_store.all_prompts()[0]["overridden"] in (True, False))
        edited = {p["id"]: p for p in prompt_store.all_prompts()}["score"]
        assert edited["overridden"] is True
        assert edited["default"].startswith("\nYou are a senior short-form video strategist")

    def test_reset_restores_the_default(self):
        prompt_store.set_overrides({"detail": "x {video_duration} {language} "
                                             "{min_clips} {max_clips} {min_secs} "
                                             "{max_secs} {windows_json}"})
        assert prompt_store.all_prompts()[1]["overridden"] is True
        prompt_store.reset(["detail"])
        assert {p["id"]: p for p in prompt_store.all_prompts()}["detail"]["overridden"] is False

    def test_clearing_a_value_removes_the_override(self):
        prompt_store.set_overrides({"layout": "edited"})
        prompt_store.set_overrides({"layout": "   "})
        assert prompt_store.text("layout").startswith("\nThese frames are sampled")


class TestValidation:
    def test_missing_placeholder_is_refused(self):
        with pytest.raises(prompt_store.PromptError) as exc:
            prompt_store.set_overrides({"score": "no variables at all"})
        assert "windows_json" in str(exc.value)

    def test_unknown_placeholder_is_refused(self):
        with pytest.raises(prompt_store.PromptError) as exc:
            prompt_store.set_overrides({
                "score": "{video_duration} {language} {windows_json} {oops}"})
        assert "oops" in str(exc.value)

    def test_malformed_braces_are_refused(self):
        with pytest.raises(prompt_store.PromptError):
            prompt_store.set_overrides({"score": "{video_duration"})

    def test_empty_text_is_refused_by_validation(self):
        with pytest.raises(prompt_store.PromptError):
            prompt_store.validate("detail", "   ")

    def test_clearing_an_edit_removes_the_override(self):
        prompt_store.set_overrides({"detail": "x {video_duration} {language} "
                                             "{min_clips} {max_clips} {min_secs} "
                                             "{max_secs} {windows_json}"})
        prompt_store.set_overrides({"detail": "  "})
        assert {p["id"]: p for p in prompt_store.all_prompts()}["detail"]["overridden"] is False

    def test_frame_prompt_takes_no_placeholders(self):
        with pytest.raises(prompt_store.PromptError):
            prompt_store.set_overrides({"layout": "look at {frames}"})


class TestJobOverrides:
    def test_a_profile_override_beats_the_settings_one(self, monkeypatch):
        prompt_store.set_overrides({"layout": "from settings"})
        monkeypatch.setenv("PROMPT_OVERRIDES_JSON", '{"layout": "from the profile"}')
        assert prompt_store.text("layout") == "from the profile"

    def test_broken_json_is_ignored(self, monkeypatch):
        monkeypatch.setenv("PROMPT_OVERRIDES_JSON", "{not json")
        assert prompt_store.text("layout").startswith("\nThese frames are sampled")


class TestApi:
    @pytest.fixture()
    def client(self):
        app_module = pytest.importorskip("app")
        from fastapi.testclient import TestClient
        return TestClient(app_module.app)

    def test_get_lists_prompts_with_defaults(self, client):
        body = client.get("/api/settings/prompts").json()
        ids = {p["id"] for p in body["prompts"]}
        assert "score" in ids and "detail" in ids
        assert body["overridden"] == []

    def test_put_saves_and_reset_clears(self, client):
        new = ("CUSTOM {video_duration} {language} {windows_json}")
        res = client.put("/api/settings/prompts", json={"prompts": {"score": new}})
        assert res.status_code == 200
        assert "score" in res.json()["overridden"]
        assert prompt_store.effective("score") == new

        res = client.post("/api/settings/prompts/reset", json={"ids": ["score"]})
        assert res.status_code == 200
        assert res.json()["overridden"] == []

    def test_put_rejects_a_missing_placeholder(self, client):
        res = client.put("/api/settings/prompts", json={"prompts": {"score": "nope"}})
        assert res.status_code == 400
        assert "windows_json" in res.json()["detail"]

    def test_reset_all_clears_every_override(self, client):
        client.put("/api/settings/prompts", json={"prompts": {"layout": "edited layout"}})
        res = client.post("/api/settings/prompts/reset", json={"ids": None})
        assert res.status_code == 200
        assert res.json()["overridden"] == []
