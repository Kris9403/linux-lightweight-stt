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


def is_hallucination(text: str) -> bool:
    return _normalise(text) in _SILENCE_ARTIFACTS


class Transcriber:
    def __init__(
        self,
        model_dir: str,
        device: str = "NPU",
        language: str = "en",
        cache_dir: str | None = None,
        min_speech_ms: int = 300,
    ):
        self._lang_token = f"<|{language}|>"
        self._min_speech_ms = min_speech_ms
        kwargs = {"CACHE_DIR": cache_dir} if cache_dir else {}
        log.info("loading Whisper on %s (cache=%s)", device, cache_dir or "off")
        self._pipe = ov_genai.WhisperPipeline(model_dir, device, **kwargs)
        log.info("Whisper ready")

    def transcribe(self, pcm: np.ndarray) -> str:
        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        if is_too_short(pcm, self._min_speech_ms):
            return ""
        result = self._pipe.generate(
            pcm,
            language=self._lang_token,
            task="transcribe",
            return_timestamps=False,
        )
        text = (result.texts[0] if result.texts else "").strip()
        if is_hallucination(text):
            return ""
        return text
