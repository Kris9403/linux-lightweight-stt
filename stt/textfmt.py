"""Reshape a transcript into a code-style identifier.

Used by `hotkey_format` — a key can lay down `snake_case` or `camelCase` names,
or `raw` (words only, lowercased, no punctuation) for when Whisper's inline
punctuation gets in the way.
"""
from __future__ import annotations

import re

_WORDS = re.compile(r"[A-Za-z0-9]+")


def apply_format(text: str, mode: str | None) -> str:
    if not mode:
        return text
    words = _WORDS.findall(text)
    if not words:
        return ""
    if mode == "snake":
        return "_".join(w.lower() for w in words)
    if mode == "camel":
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])
    if mode == "raw":
        return " ".join(w.lower() for w in words)
    return text   # unknown mode -> leave it alone
