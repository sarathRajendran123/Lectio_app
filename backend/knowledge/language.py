"""Which language a course or a request is written in (German or English), from common function words. No database."""
import re

_GERMAN = {"der", "die", "das", "und", "ist", "sind", "nicht", "mit", "von", "den", "für", "auf", "ein", "eine", "einen", "wird", "werden",
           "sie", "können", "kann", "studierenden", "zu", "im", "bei", "nach", "über", "auch", "oder", "als", "wie", "dem", "des", "zur", "zum"}
_ENGLISH = {"the", "and", "is", "are", "not", "with", "of", "to", "for", "on", "a", "an", "will", "be", "able", "students", "can", "in",
            "by", "after", "about", "also", "or", "as", "how", "their", "this", "that", "they"}
NAMES = {"de": "German", "en": "English"}


def detect(texts) -> str | None:
    """"de", "en", or None when there is too little text or neither language clearly dominates."""
    words = re.findall(r"[^\W\d_]+", " ".join(t or "" for t in texts).lower())
    german, english = sum(w in _GERMAN for w in words), sum(w in _ENGLISH for w in words)
    if german + english < 3:
        return None
    if german >= 2 * english:
        return "de"
    if english >= 2 * german:
        return "en"
    return None


def instruction(code: str | None, fallback: str = "the language of the request") -> str:
    """One sentence for the model: which language the draft must be written in."""
    name = NAMES.get(code)
    return (f"Write the whole draft in {name}, the language of the course's stated objectives; keep technical terms "
            "as the sources use them." if name else f"Write the draft in {fallback}.")
