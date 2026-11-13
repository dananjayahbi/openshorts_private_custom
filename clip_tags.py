"""The five tags every clip carries.

The moment picker writes the copy (title, hook, descriptions) and, since the
tags request, a tag list too. Small/local models are inconsistent: they return
three tags, or one tag twice, or a tag with a leading #. Rather than ship a clip
with a half-empty tag row, this normalises the answer and tops it up from what
the clip already says: hashtags the model wrote into its own descriptions, then
the significant words of its title. The result is always exactly five unique,
comma-separated tags — the shape the gallery copies into a post.
"""
import re

LIMIT = 5

# Words that would make useless tags on any clip.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "he", "her", "him", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "me", "my", "no", "not", "of", "on", "or",
    "our", "out", "she", "so", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "up", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "you",
    "your", "about", "after", "before", "over", "under", "more", "most",
    "get", "got", "make", "made", "can", "could", "would", "should", "do",
    "does", "did", "one", "two", "new", "video", "clip", "shorts", "short",
}

# Only when the clip says nothing usable at all (very short/odd answers).
_FILLER = ("viral", "trending", "creator", "shorts", "fyp")


def _clean_tag(value) -> str:
    text = str(value or "").strip().lstrip("#").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .,;:!?\"'()[]{}")
    return text[:40].strip()


def _split(value):
    if isinstance(value, (list, tuple, set)):
        return [v for v in value]
    if isinstance(value, str):
        return re.split(r"[,;\n]+", value)
    return []


def _hashtags(*texts):
    found = []
    for text in texts:
        found.extend(re.findall(r"#([\w][\w\-]{0,39})", str(text or "")))
    return found


def _title_words(title):
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]{2,}", str(title or ""))
    return [w for w in words if w.lower() not in _STOPWORDS]


def five(tags=None, title="", descriptions=()) -> str:
    """Exactly five unique, lowercase, comma-separated tags."""
    out = []
    seen = set()

    def add(value):
        tag = _clean_tag(value).lower()
        if not tag or tag in seen:
            return
        seen.add(tag)
        out.append(tag)

    for raw in _split(tags):
        add(raw)
        if len(out) >= LIMIT:
            break

    if len(out) < LIMIT:
        for raw in _hashtags(*(descriptions or ())):
            add(raw)
            if len(out) >= LIMIT:
                break

    if len(out) < LIMIT:
        for raw in _title_words(title):
            add(raw)
            if len(out) >= LIMIT:
                break

    for raw in _FILLER:
        if len(out) >= LIMIT:
            break
        add(raw)

    return ", ".join(out[:LIMIT])
