"""Every clip carries exactly five comma-separated tags.

The detail picker writes them in the same call as the title/hook (no extra
request). Small models are inconsistent, so ``clip_tags.five`` normalises and
tops up from the clip's own hashtags/title: exactly five unique tags, never an
empty tag row.
"""
import clip_tags
import gemini_worker


def test_a_model_answer_is_cleaned_and_kept():
    assert clip_tags.five("AI, automation, #workflow, shorts ,  productivity") == (
        "ai, automation, workflow, shorts, productivity")


def test_a_list_answer_works():
    assert clip_tags.five(["AI", "Claude", "MCP", "agents", "shorts"]) == (
        "ai, claude, mcp, agents, shorts")


def test_duplicates_and_extra_tags_are_dropped_then_filled():
    tags = clip_tags.five("ai, AI, ai, claude, mcp",
                          title="Connecting Claude to MCP",
                          descriptions=("Saved hours #automation #workflow",))
    parts = tags.split(", ")
    assert len(parts) == 5
    assert len(set(parts)) == 5
    assert parts[:2] == ["ai", "claude"]


def test_a_missing_answer_is_filled_from_the_clip_copy():
    tags = clip_tags.five(
        None,
        title="I automated my clips with AI",
        descriptions=("#shorts #youtubegrowth",),
    )
    assert len(tags.split(", ")) == 5
    assert "shorts" in tags and "youtubegrowth" in tags


def test_even_an_empty_clip_gets_five():
    parts = clip_tags.five(None).split(", ")
    assert len(parts) == 5 and len(set(parts)) == 5


def test_hashes_and_punctuation_are_removed():
    tags = clip_tags.five("##AI!, (Claude), MCP; shorts; agents")
    assert tags == "ai, claude, mcp, shorts, agents"


def test_both_schemas_carry_the_field():
    assert "tags" in gemini_worker.DetailClipModel.model_fields
    assert "tags" in gemini_worker.VisualClipModel.model_fields
    # The prompt asks for five, and the JSON sketch shows the field.
    prompt = gemini_worker.DETAIL_PROMPT_TEMPLATE
    assert "exactly FIVE comma-separated tags" in prompt
    assert '"tags": "<five comma-separated tags>"' in prompt


def test_the_gallery_and_mcp_expose_tags():
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_py = open(os.path.join(repo, "app.py"), encoding="utf-8").read()
    mcp_py = open(os.path.join(repo, "mcp_server.py"), encoding="utf-8").read()
    card = open(os.path.join(repo, "dashboard", "src", "components", "GalleryCard.jsx"),
                encoding="utf-8").read()
    modal = open(os.path.join(repo, "dashboard", "src", "components", "ClipModal.jsx"),
                 encoding="utf-8").read()
    assert '"tags"' in app_py
    assert 'clip.get("tags") or clip_tags.five(' in app_py
    assert '"tags": clip.get("tags") or ""' in mcp_py
    # The tags are shown (and copyable) in the full clip view.
    assert "clip.tags" in modal and "tags" in modal.lower()
    assert "GalleryCard" in card
