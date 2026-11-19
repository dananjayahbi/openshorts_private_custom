"""Per-platform copy for one clip: Facebook post, YouTube title/description, tags.

The moment picker used to write a TikTok caption and an Instagram caption for
every clip. This install publishes to Facebook and YouTube only, so the copy is
shaped for those two:

* ``facebook_title`` — a one- or two-sentence post, then two blank lines and
  exactly five hashtags (Facebook shows them inline with the post).
* ``youtube_title`` — a clean title, 100 chars max, no hashtags. YouTube has a
  separate hashtag field, and a hashtag in the title just wastes characters.
* ``youtube_description`` — a short 250-500 character summary.
* ``tags`` — exactly five comma-separated words, for YouTube's tag field.

Old job metadata on disk still carries ``video_title_for_youtube_short`` /
``video_description_for_tiktok`` / ``video_description_for_instagram``. The
read helpers below fall back to those, so archived clips keep their copy
without rewriting every metadata file.
"""
import re

import clip_tags

FACEBOOK_HASHTAGS = 5
YOUTUBE_TITLE_MAX = 100
YOUTUBE_DESCRIPTION_MAX = 500

_HASHTAGS_RE = re.compile(r"(?<!\w)#[\w\-]+")


def _text(value) -> str:
    return str(value or "").strip()


def _one_line(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).strip()


def strip_hashtags(value) -> str:
    """Remove hashtag tokens (and the space before each) from copy."""
    text = _HASHTAGS_RE.sub("", _text(value))
    return re.sub(r"[ \t]+", " ", text).strip()


def hashtags(tags) -> list:
    """The five tags as Facebook hashtags: #lowercase, no spaces."""
    out = []
    for raw in _text(tags).split(","):
        word = re.sub(r"[^0-9A-Za-z_]", "", raw.strip().lstrip("#").replace(" ", ""))
        if not word:
            continue
        tag = "#" + word[0].lower() + word[1:]
        if tag.lower() not in {t.lower() for t in out}:
            out.append(tag)
        if len(out) >= FACEBOOK_HASHTAGS:
            break
    return out


def facebook_post(title, tags) -> str:
    """Title, two blank lines, five hashtags — the Facebook post shape."""
    body = strip_hashtags(title) or "New clip"
    marks = hashtags(tags)
    return f"{body}\n\n\n{' '.join(marks)}" if marks else body


def youtube_title(clip) -> str:
    """Clean YouTube title, falling back to pre-split metadata."""
    title = (clip.get("youtube_title")
             or clip.get("video_title_for_youtube_short")
             or clip.get("title"))
    title = _one_line(strip_hashtags(title))
    return title[:YOUTUBE_TITLE_MAX]


def _legacy_description(clip) -> str:
    return (clip.get("video_description_for_instagram")
            or clip.get("video_description_for_tiktok") or "")


def youtube_description(clip) -> str:
    """Short YouTube description, with hashtags removed."""
    text = (clip.get("youtube_description") or _legacy_description(clip))
    text = strip_hashtags(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= YOUTUBE_DESCRIPTION_MAX:
        return text.strip()
    cut = text[:YOUTUBE_DESCRIPTION_MAX]
    space = cut.rfind(" ")
    return (cut[:space] if space > YOUTUBE_DESCRIPTION_MAX // 2 else cut).rstrip()


def facebook_title(clip) -> str:
    """Full Facebook post text, for pre-split metadata too."""
    stored = clip.get("facebook_title")
    if stored:
        # A model may have written its own hashtags; keep exactly five.
        return facebook_post(stored, clip_tags.five(
            clip.get("tags"), youtube_title(clip), (stored,)))
    return facebook_post(
        youtube_title(clip) or clip.get("viral_hook_text"),
        clip.get("tags") or "")


def apply(clip) -> dict:
    """Normalise one freshly generated clip's copy in place.

    Called after the five tags are settled, so the Facebook post is built from
    the same tags YouTube gets. The two per-network captions are dropped: the
    picker no longer writes them and nothing should read them from new jobs.
    """
    title = youtube_title(clip)
    description = youtube_description(clip)
    clip["tags"] = clip_tags.five(
        clip.get("tags"), title, (clip.get("facebook_title"), description))
    clip["youtube_title"] = title
    clip["youtube_description"] = description
    clip["facebook_title"] = facebook_post(
        clip.get("facebook_title") or title or clip.get("viral_hook_text"),
        clip["tags"])
    clip.pop("title_for_facebook", None)
    clip.pop("title_for_youtube", None)
    clip.pop("description_for_youtube", None)
    clip.pop("video_description_for_tiktok", None)
    clip.pop("video_description_for_instagram", None)
    return clip
