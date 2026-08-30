"""OpenVINO Whisper wrapper: NPU + disk cache, pinned language, hallucination gate.

API facts (openvino-genai 2026.2, verified on-box):
  - use WhisperPipeline (no ASRPipeline)
  - generate() takes a numpy float32 array directly; ov.Tensor is rejected
  - language must be the "<|xx|>" token form, not "xx"
  - WhisperPipeline(path, "NPU", CACHE_DIR=...) -> 10.9 s cold, 1.6 s warm
  - silence transcribes as " you" -> the blocklist below must catch it
"""
from __future__ import annotations

import logging

import numpy as np
import openvino_genai as ov_genai

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Normalised (lowercased, stripped, trailing punctuation removed) forms that
# Whisper emits for silence / noise. Only matched as an *exact whole* result.
_SILENCE_ARTIFACTS = frozenset({
    "you",
    "thank you",
    "thanks for watching",
    "please subscribe",
    "bye",
    "bye bye",
})


def is_too_short(pcm: np.ndarray, min_speech_ms: int) -> bool:
    return len(pcm) < SAMPLE_RATE * min_speech_ms // 1000


def _normalise(text: str) -> str:
    return text.strip().lower().rstrip(".!?").strip()


def is_hallucination(text: str, blocklist: frozenset[str] | set[str] = _SILENCE_ARTIFACTS) -> bool:
    return _normalise(text) in blocklist


def vocab_hotwords(vocabulary: list[str] | None, device: str) -> str | None:
    """Join a vocabulary list into a hotwords string, or None. The NPU's static
    decoder context can't take extra prompt tokens, so it's dropped there."""
    if not vocabulary:
        return None
    if device == "NPU":
        log.warning("custom vocabulary is ignored on the NPU (static shape limit); "
                    'set device = "GPU" or "CPU" to use it')
        return None
    return " ".join(vocabulary)


def resolve_beams(num_beams: int, device: str) -> int:
    """Beam search doesn't run on the NPU (static batch dim) — force greedy there."""
    if num_beams > 1 and device == "NPU":
        log.warning("beam search (num_beams=%d) isn't supported on the NPU; using greedy. "
                    'set device = "GPU" or "CPU" for beam search', num_beams)
        return 1
    return max(1, num_beams)


class Transcriber:
    def __init__(
        self,
        model_dir: str,
        device: str = "NPU",
        language: str = "en",
        cache_dir: str | None = None,
        min_speech_ms: int = 300,
        extra_hallucinations: list[str] | None = None,
        vocabulary: list[str] | None = None,
        num_beams: int = 1,
    ):
        self._lang_token = f"<|{language}|>"
        self._min_speech_ms = min_speech_ms
        self._hotwords = vocab_hotwords(vocabulary, device)
        self._num_beams = resolve_beams(num_beams, device)
        self._blocklist = _SILENCE_ARTIFACTS | {
            _normalise(h) for h in (extra_hallucinations or [])
        }
        kwargs = {"CACHE_DIR": cache_dir} if cache_dir else {}
        log.info("loading Whisper on %s (cache=%s)", device, cache_dir or "off")
        self._pipe = ov_genai.WhisperPipeline(model_dir, device, **kwargs)
        log.info("Whisper ready")

    def transcribe(self, pcm: np.ndarray, language: str | None = None,
                   translate: bool = False) -> str:
        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        if is_too_short(pcm, self._min_speech_ms):
            return ""
        lang_token = f"<|{language}|>" if language else self._lang_token
        extra = {"hotwords": self._hotwords} if self._hotwords else {}
        if self._num_beams > 1:
            extra["num_beams"] = self._num_beams
        result = self._pipe.generate(
            pcm,
            language=lang_token,
            task="translate" if translate else "transcribe",
            return_timestamps=False,
            **extra,
        )
        text = (result.texts[0] if result.texts else "").strip()
        if is_hallucination(text, self._blocklist):
            return ""
        return text
