// Per-clip copy for the two platforms this install uses (mirrors clip_copy.py).
//
// The picker used to write a TikTok caption and an Instagram caption. New jobs
// carry `facebook_title` (post title + two blank lines + five hashtags),
// `youtube_title` (clean, no hashtags) and `youtube_description` (250-500
// chars). Clips rendered before that change still have the old keys, so every
// reader goes through these helpers instead of touching a field directly.

const HASHTAG_RE = /(^|\s)#[\w-]+/g;

const text = (value) => String(value || '').trim();

export function stripHashtags(value) {
  return text(value).replace(HASHTAG_RE, ' ').replace(/[ \t]+/g, ' ').trim();
}

export function youtubeTitle(clip) {
  const raw = clip?.youtube_title
    || clip?.video_title_for_youtube_short
    || clip?.title
    || '';
  return stripHashtags(raw).replace(/\s+/g, ' ').slice(0, 100);
}

export function youtubeDescription(clip) {
  const raw = clip?.youtube_description
    || clip?.video_description_for_instagram
    || clip?.video_description_for_tiktok
    || '';
  const clean = stripHashtags(raw).replace(/\n{3,}/g, '\n\n');
  if (clean.length <= 500) return clean;
  const cut = clean.slice(0, 500);
  const space = cut.lastIndexOf(' ');
  return (space > 250 ? cut.slice(0, space) : cut).trim();
}

export function facebookTitle(clip) {
  return clip?.facebook_title || youtubeTitle(clip) || text(clip?.viral_hook_text);
}

export function clipTags(clip) {
  return text(clip?.tags);
}
