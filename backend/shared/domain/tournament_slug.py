"""Slug generation for the public tournament URL (``/tournaments/{slug}``)."""

from __future__ import annotations

import re

__all__ = ("slugify",)

# Common practical Cyrillic -> Latin transliteration (not GOST-strict, just
# readable): tournament names in this community are frequently Russian, and a
# plain ASCII-strip would collapse most of them to nothing.
_CYRILLIC_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, transliterate Cyrillic, and hyphenate; ``"tournament"`` if empty."""
    transliterated = "".join(_CYRILLIC_MAP.get(ch, ch) for ch in text.lower())
    slug = _NON_SLUG_CHARS.sub("-", transliterated).strip("-")
    return slug or "tournament"
