"""Microphone capture: one always-open input stream feeding a bounded buffer.

start() / stop() bracket an utterance for hold- and toggle-to-talk. The buffer
is capped so a stuck 'recording' state can't grow without limit. on_endpoint is
a placeholder for a future VAD hook and is currently never called.
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class Recorder:
    def __init__(self, samplerate: int = SAMPLE_RATE, max_seconds: int = 30):
        self.samplerate = samplerate
        self._cap = samplerate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._stream = None
        self.on_endpoint: Callable[[], None] | None = None

    def open(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.warning("audio stream status: %s", status)
        if self._recording:
            self._chunks.append(np.asarray(indata, dtype=np.float32).reshape(-1).copy())

    def start(self) -> None:
        self._chunks.clear()
        self._recording = True

    def stop(self) -> np.ndarray:
        self._recording = False
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        pcm = np.concatenate(self._chunks)
        self._chunks.clear()
        return pcm[-self._cap:]
