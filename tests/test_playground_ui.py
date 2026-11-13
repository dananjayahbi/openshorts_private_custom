"""Dashboard contracts for the Playground, Style Profiles and pre-render captions.

There is no JS test runner in this repo; these read the JSX like the other
dashboard-contract tests. They guard the wiring that is invisible to the Python
suite: the pages are mounted, the profile is handed to the generator, and the
caption look actually travels with /api/process.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as f:
        return f.read()


def test_playground_and_profiles_are_in_the_nav_and_rendered():
    app = _read("App.jsx")
    assert "id: 'playground'" in app and "label: 'Playground'" in app
    assert "id: 'profiles'" in app and "label: 'Style Profiles'" in app
    assert "activeTab === 'playground'" in app and "<Playground" in app
    assert "activeTab === 'profiles'" in app and "<StyleProfiles" in app


def test_generator_gets_the_profile_and_the_caption_look():
    app = _read("App.jsx")
    assert "profilePrefill" in app and "initialProfile={profilePrefill}" in app
    build = app.split("const buildProcessRequest", 1)[1].split("const handleProcess", 1)[0]
    assert "caption_style:" in build
    assert "style_profile_id:" in build
    # Captions default on; the panel can turn them off explicitly.
    assert "captions: data.captions === false ? '0' : '1'" in build


def test_playground_exposes_the_full_caption_editor_and_saves_a_profile():
    page = _read("components", "Playground.jsx")
    controls = _read("components", "CaptionControls.jsx")
    assert "CaptionControls" in page and "CaptionStage" in page
    for control in ("preset", "font", "position", "size", "animation",
                    "uppercase", "reveal", "shadow", "background box",
                    "max characters"):
        assert control in controls.lower(), control
    assert "/api/style-profiles" in page
    assert "output_format" in page and "auto_hook_style" in page
    assert "layout" in page


def test_manual_caption_panel_is_visible_before_a_render():
    media = _read("components", "MediaInput.jsx")
    # Visible without opening advanced: a profile choice + captions toggle.
    assert "style profile" in media
    assert "burn captions into the clips" in media
    assert "/api/style-profiles" in media
    assert "CaptionControls" in media and "CaptionStage" in media
    # The look and the profile id travel with the request.
    assert "captionStyle" in media and "styleProfileId" in media
    assert "captions: captionsOn" in media


def test_profiles_page_can_use_edit_and_delete():
    page = _read("components", "StyleProfiles.jsx")
    assert "onUse" in page and "onEdit" in page
    assert "method: 'DELETE'" in page
    assert "CaptionStage" in page
