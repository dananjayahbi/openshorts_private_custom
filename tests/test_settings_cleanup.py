"""Settings only offers what this local build actually uses.

The hosted product's settings (Upload-Post social publishing, ElevenLabs
dubbing, fal.ai AI Shorts) were still rendered after those features were
dropped from this fork, and their dead ends ("configure it in Settings") pointed
at fields that no longer existed. These source-level guards keep the cleanup.

They read JSX like the other dashboard-contract tests; there is no JS test
runner in this repo.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(path):
    with open(os.path.join(SRC, path), encoding="utf-8") as f:
        return f.read()


def test_settings_keeps_only_the_pipeline_key_and_agent_howto():
    # The sections moved into SettingsPage when the provider chain and prompt
    # editors were added. Keys are configured per provider now (no dedicated
    # Gemini card), so the guard checks the real control surfaces.
    page = _read("components/SettingsPage.jsx")
    assert "AI providers" in page
    assert "system prompts" in page
    assert "<McpConnectCard" in page
    for gone in ("Social Integration", "Video Translation", "AI Shorts (UGC Videos)"):
        assert gone not in page, gone
        assert gone not in _read("App.jsx"), gone
    # The fal.ai state existed only for the removed AI Shorts card.
    assert "falKey" not in _read("App.jsx")


def test_the_agent_is_not_labelled_byok():
    """The keyless MCP flow is the whole point: no user key is required."""
    app = _read("App.jsx")
    agent = [line for line in app.splitlines() if "label: 'AI Agent'" in line][0]
    assert "byok" not in agent


def test_publish_and_dub_buttons_only_exist_when_configured():
    card = _read("components/ResultCard.jsx")
    # The modal/button pair is gated; a bare button would open a dead end.
    assert "{canPost && (" in card
    assert "{elevenLabsKey && (" in card


def test_studio_publishing_is_a_notice_not_a_dead_end():
    studio = _read("components/ThumbnailStudio.jsx")
    assert "Publishing is off" in studio
    assert "Go to Settings" not in studio
