"""Per-platform clip copy (clip_copy.py).

This install publishes to Facebook and YouTube only, so the moment picker no
longer writes a TikTok/Instagram caption. Every clip instead carries:

* ``facebook_title``: the post body, two blank lines, exactly five hashtags;
* ``youtube_title``: clean, no hashtags, 100 chars max;
* ``youtube_description``: 250-500 characters, no hashtags;
* ``tags``: five comma-separated words for YouTube's tag field.

Old metadata files still have the pre-split keys; the readers fall back to them.
"""
import os
import re

import clip_copy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(REPO, "gemini_worker.py")


def _prompt(name):
    """The prompt constant's text, without importing the heavy worker module."""
    with open(WORKER, encoding="utf-8") as f:
        source = f.read()
    match = re.search(rf'{name} = """(.*?)"""', source, re.S)
    assert match, name
    return match.group(1)


def test_facebook_post_has_five_hashtags_after_two_blank_lines():
    post = clip_copy.facebook_post("Our plane broke down. What happened next?",
                                   "world record, travel, adventure, streamer, expedia")
    assert post == ("Our plane broke down. What happened next?\n\n\n"
                    "#worldrecord #travel #adventure #streamer #expedia")


def test_facebook_post_keeps_exactly_five_and_unique_tags():
    post = clip_copy.facebook_post("Title", "one, one, two, three, four, five, six")
    marks = re.findall(r"#\w+", post)
    assert len(marks) == 5
    assert len(set(marks)) == 5


def test_youtube_title_has_no_hashtags_and_fits():
    clip = {"youtube_title": "The fix #shorts #viral that changed everything"}
    assert clip_copy.youtube_title(clip) == "The fix that changed everything"
    assert len(clip_copy.youtube_title({"youtube_title": "x" * 200})) == 100


def test_youtube_description_strips_hashtags_and_is_short():
    clip = {"youtube_description": "A sentence. " * 60 + "#shorts #viral"}
    out = clip_copy.youtube_description(clip)
    assert len(out) <= clip_copy.YOUTUBE_DESCRIPTION_MAX
    assert "#" not in out


def test_apply_builds_the_new_shape_and_drops_old_captions():
    clip = {
        "youtube_title": "The moment the plane broke",
        "youtube_description": "We were supposed to stream five countries in one day. "
                               "Then the plane broke down. Here is what happened next.",
        "tags": "travel, worldrecord, adventure, streamer, expedia",
        "video_description_for_tiktok": "legacy caption #old",
        "video_description_for_instagram": "legacy caption #old",
    }
    clip_copy.apply(clip)
    assert clip["youtube_title"] == "The moment the plane broke"
    assert clip["facebook_title"].startswith("The moment the plane broke\n\n\n#")
    assert len(re.findall(r"#\w+", clip["facebook_title"])) == 5
    assert clip["youtube_description"] == (
        "We were supposed to stream five countries in one day. "
        "Then the plane broke down. Here is what happened next.")
    assert clip["tags"] == "travel, worldrecord, adventure, streamer, expedia"
    assert "video_description_for_tiktok" not in clip
    assert "video_description_for_instagram" not in clip


def test_apply_reads_old_metadata_without_rewriting_the_job():
    clip = {
        "video_title_for_youtube_short": "Old title #shorts",
        "video_description_for_instagram": "Old caption. #travel #adventure",
    }
    clip_copy.apply(clip)
    assert clip["youtube_title"] == "Old title"
    assert "#" not in clip["youtube_description"]
    assert clip["facebook_title"].startswith("Old title")


def test_the_detail_and_visual_prompts_ask_for_the_new_copy():
    for prompt in (_prompt("DETAIL_PROMPT_TEMPLATE"),
                   _prompt("VISUAL_PROMPT_TEMPLATE")):
        assert "facebook_title" in prompt
        assert "youtube_title" in prompt
        assert "youtube_description" in prompt
        assert "video_description_for_tiktok" not in prompt
        assert "video_description_for_instagram" not in prompt
        assert "TikTok" not in prompt
        assert "Instagram" not in prompt
    # The rendered detail prompt still formats (all placeholders present).
    rendered = _prompt("DETAIL_PROMPT_TEMPLATE").format(
        video_duration=60, language="en", min_clips=1, max_clips=2,
        min_secs=15, max_secs=60, windows_json="[]")
    assert "250-500" in rendered