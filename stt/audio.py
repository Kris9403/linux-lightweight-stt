"""Microphone capture.

A fresh `sd.InputStream` is opened on start() and torn down on stop(). Holding
one stream open for the life of the process does not survive suspend/resume or a
PipeWire restart — the callback silently stops firing — so each utterance gets
its own stream. Opening one costs a few tens of milliseconds, unnoticeable for
push-to-talk.
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class EndpointDetector:
    """RMS-energy voice-activity endpointing. Feed it audio chunk by chunk;
    `feed()` returns True the moment speech has been heard and then followed by
    `silence_ms` of quiet. No model, no dependency."""

    def __init__(self, samplerate: int = SAMPLE_RATE, threshold: float = 0.015,
                 silence_ms: int = 700, min_speech_ms: int = 300):
        self.threshold = threshold
        self._silence_needed = samplerate * silence_ms // 1000
        self._speech_needed = samplerate * min_speech_ms // 1000
        self.reset()

    def reset(self) -> None:
        self._speech_total = 0
        self._silence_run = 0
        self._had_speech = False

    def feed(self, chunk: np.ndarray) -> bool:
        if chunk.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        if rms >= self.threshold:
            self._speech_total += chunk.size
            self._silence_run = 0
            if self._speech_total >= self._speech_needed:
                self._had_speech = True
        else:
            self._silence_run += chunk.size
            if self._had_speech and self._silence_run >= self._silence_needed:
                self.reset()
                return True
        return False


class Recorder:
    def __init__(self, samplerate: int = SAMPLE_RATE, max_seconds: int = 30,
                 device: int | str | None = None, vad: "EndpointDetector | None" = None):
        self.samplerate = samplerate
        self.device = device
        self._cap = samplerate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._vad = vad
        self.on_endpoint: Callable[[], None] | None = None

    def start(self) -> None:
        self._chunks.clear()
        if self._vad is not None:
            self._vad.reset()
        self._teardown()
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def _drain(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        pcm = np.concatenate(self._chunks)
        self._chunks.clear()
        return pcm[-self._cap:]

    def take(self) -> np.ndarray:
        """Return the audio buffered so far and clear it — the stream keeps
        running. Used for continuous mode between endpoints."""
        return self._drain()

    def stop(self) -> np.ndarray:
        self._teardown()
        return self._drain()

    def close(self) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001 — a dead stream must not block a restart
                pass
            self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.warning("audio stream status: %s", status)
        chunk = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        self._chunks.append(chunk)
        if self._vad is not None and self._vad.feed(chunk) and self.on_endpoint:
            self.on_endpoint()
