"""Optional post-processing: send a transcript to a local OpenAI-compatible LLM
endpoint (Ollama, llama.cpp server, LM Studio, …) to strip fillers and fix
punctuation.

Fail-open: any error (endpoint down, timeout, bad response) returns the original
text unchanged, with a warning.
"""
from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You clean up dictated text. Remove filler words (um, uh, like, you know), "
    "fix punctuation and capitalization, and drop false starts. Keep the wording "
    "and meaning otherwise — do not rephrase or summarise. Reply with only the "
    "cleaned text."
)


def clean_text(text: str, endpoint: str, model: str, *, timeout: float = 6.0,
               system: str = SYSTEM_PROMPT) -> str:
    if not text.strip():
        return text
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        out = data["choices"][0]["message"]["content"].strip()
        return out or text
    except Exception as e:  # noqa: BLE001 — never let cleanup break dictation
        log.warning("llm cleanup skipped: %s", e)
        return text
