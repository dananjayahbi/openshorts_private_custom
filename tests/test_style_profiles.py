"""Pre-generation caption styles, Style Profiles, and the playground contract.

The dashboard used to offer caption styling only AFTER a render. These tests
pin the plumbing that moves it before the render:

* ``caption_style.clean`` accepts the same fields/ranges the burn understands,
* a profile stores look + output + prompt overrides and can be applied by id,
* the pipeline reads ``AUTO_CAPTION_STYLE_JSON`` and keeps the effective look
  on each clip for later hook/edit/recut passes.
"""
import json

import pytest

import caption_style
import style_profiles


class TestCaptionStyle:
    def test_defaults_are_clamped_and_unknown_fields_dropped(self):
        cleaned = caption_style.clean({
            "font_size": 999, "border_width": -3, "bg_opacity": 4,
            "position": "middle", "effect": "glow", "font_name": "Anton",
            "font_color": "ffffff", "banana": "x",
        })
        assert cleaned["font_size"] == 120
        assert cleaned["border_width"] == 0
        assert cleaned["bg_opacity"] == 1.0
        assert cleaned["position"] == "middle"
        assert cleaned["font_color"] == "#ffffff"
        assert "banana" not in cleaned

    def test_bad_colors_and_enums_are_dropped(self):
        cleaned = caption_style.clean({
            "font_color": "javascript:alert(1)", "position": "everywhere",
            "effect": "explode", "uppercase": "yes",
        })
        assert "font_color" not in cleaned
        assert "position" not in cleaned
        assert "effect" not in cleaned
        assert cleaned["uppercase"] is True

    def test_json_string_and_empty_input(self):
        assert caption_style.clean('{"font_name": "Impact"}')["font_name"] == "Impact"
        assert caption_style.clean("{not json") is None
        assert caption_style.clean({}) is None
        assert caption_style.clean(None) is None


class TestProfiles:
    def test_create_list_update_delete(self):
        profile = style_profiles.create({
            "name": "Gaming vertical",
            "caption": {"style": "karaoke", "font_name": "Impact", "font_size": 56},
            "output": {"output_format": "vertical", "auto_hook": True,
                       "auto_hook_style": "pill", "target_clips": 5},
        })
        assert profile["id"] and profile["name"] == "Gaming vertical"
        assert profile["caption"]["font_name"] == "Impact"
        assert profile["output"]["target_clips"] == 5

        listed = style_profiles.list_profiles()
        assert [p["id"] for p in listed] == [profile["id"]]

        updated = style_profiles.update(profile["id"], {"name": "Gaming square",
                                                        "output": {"output_format": "square"}})
        assert updated["name"] == "Gaming square"
        assert updated["output"]["output_format"] == "square"
        # An output patch replaces the bundle rather than merging stale keys.
        assert "target_clips" not in updated["output"]

        assert style_profiles.delete(profile["id"]) is True
        assert style_profiles.get(profile["id"]) is None

    def test_unknown_hook_style_is_dropped(self):
        profile = style_profiles.create({
            "name": "x", "output": {"auto_hook": True, "auto_hook_style": "sparkles"}})
        assert "auto_hook_style" not in profile["output"]

    def test_profile_prompts_are_validated(self):
        with pytest.raises(style_profiles.ProfileError):
            style_profiles.create({
                "name": "broken",
                "prompts": {"score": "no placeholders"},
            })

    def test_a_name_is_required(self):
        with pytest.raises(style_profiles.ProfileError):
            style_profiles.create({"name": "   "})

    def test_update_missing_profile_raises(self):
        with pytest.raises(style_profiles.ProfileError) as exc:
            style_profiles.update("nope", {"name": "x"})
        assert "not found" in str(exc.value)


class TestPipelineMerge:
    def test_env_style_overrides_the_shipped_default(self, monkeypatch):
        main = pytest.importorskip("main")
        monkeypatch.setenv("AUTO_CAPTION_STYLE_JSON", json.dumps({
            "style": "karaoke", "position": "top", "font_name": "Impact",
            "font_size": 70, "uppercase": False, "reveal": True,
            "shadow": 3, "bg_opacity": 0.4, "max_chars": 3,
        }))
        style = main.caption_style_from_env()
        assert style["position"] == "top"
        assert style["font_name"] == "Impact"
        assert style["font_size"] == 70
        assert style["uppercase"] is False
        assert style["reveal"] is True
        assert style["shadow"] == 3
        assert style["bg_opacity"] == 0.4
        assert style["max_chars"] == 3

    def test_missing_max_chars_is_derived_from_the_font(self, monkeypatch):
        main = pytest.importorskip("main")
        monkeypatch.setenv("AUTO_CAPTION_STYLE_JSON", json.dumps({
            "font_name": "Montserrat ExtraBold", "font_size": 44}))
        style = main.caption_style_from_env()
        assert style["max_chars"] == 9  # line_budget for the wide font

    def test_no_override_keeps_the_shipped_look(self, monkeypatch):
        main = pytest.importorskip("main")
        monkeypatch.delenv("AUTO_CAPTION_STYLE_JSON", raising=False)
        style = main.caption_style_from_env()
        assert style["font_name"] == "Anton"
        assert style["position"] == "bottom"
        assert style["max_chars"] == 16


class TestApi:
    @pytest.fixture()
    def client(self):
        app_module = pytest.importorskip("app")
        from fastapi.testclient import TestClient
        return TestClient(app_module.app)

    def test_crud(self, client):
        created = client.post("/api/style-profiles", json={
            "name": "Reels clean",
            "caption": {"style": "karaoke", "font_name": "Montserrat ExtraBold",
                        "font_size": 34, "effect": "none"},
            "output": {"output_format": "vertical"},
        })
        assert created.status_code == 200
        profile = created.json()
        assert profile["caption"]["font_name"] == "Montserrat ExtraBold"

        listed = client.get("/api/style-profiles").json()["profiles"]
        assert listed[0]["id"] == profile["id"]

        patched = client.patch(f"/api/style-profiles/{profile['id']}",
                               json={"name": "Reels clean v2"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "Reels clean v2"

        assert client.delete(f"/api/style-profiles/{profile['id']}").status_code == 200
        assert client.get("/api/style-profiles").json()["profiles"] == []

    def test_bad_prompt_is_a_400(self, client):
        res = client.post("/api/style-profiles", json={
            "name": "x", "prompts": {"score": "nope"}})
        assert res.status_code == 400
        assert "windows_json" in res.json()["detail"]

    def test_unknown_profile_on_process_is_a_404(self, client):
        res = client.post("/api/process", json={
            "url": "https://example.com/v", "acknowledged": True,
            "style_profile_id": "does-not-exist",
        })
        assert res.status_code == 404
        assert "Style profile" in res.json()["detail"]

    def test_caption_style_payload_does_not_shadow_the_module(self, client):
        # Regression: the form parameter is named caption_style, which used to
        # shadow the caption_style module inside the endpoint (500).
        res = client.post("/api/process", json={
            "acknowledged": True,
            "caption_style": {"font_name": "Impact", "position": "top"},
        })
        assert res.status_code == 400
        assert "Must provide" in res.json()["detail"]
