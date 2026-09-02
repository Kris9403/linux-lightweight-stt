"""Reshape a transcript into a code-style identifier.

Used by `hotkey_format` — a key can lay down `snake_case` or `camelCase` names,
or `raw` (lowercased, punctuation stripped) for when Whisper's inline
punctuation and capitalisation get in the way.
"""
from __future__ import annotations

import re

_WORDS = re.compile(r"[A-Za-z0-9]+")


def apply_format(text: str, mode: str | None) -> str:
    if not mode:
        return text
    if mode == "raw":
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text)).strip().lower()
    words = _WORDS.findall(text)
    if not words:
        return ""
    if mode == "snake":
        return "_".join(w.lower() for w in words)
    if mode == "camel":
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])
    return text   # unknown mode -> leave it alone
