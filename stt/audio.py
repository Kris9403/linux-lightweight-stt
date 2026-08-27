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


class Recorder:
    def __init__(self, samplerate: int = SAMPLE_RATE, max_seconds: int = 30,
                 device: int | str | None = None):
        self.samplerate = samplerate
        self.device = device
        self._cap = samplerate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self.on_endpoint: Callable[[], None] | None = None

    def start(self) -> None:
        self._chunks.clear()
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

    def stop(self) -> np.ndarray:
        self._teardown()
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        pcm = np.concatenate(self._chunks)
        self._chunks.clear()
        return pcm[-self._cap:]

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
        self._chunks.append(np.asarray(indata, dtype=np.float32).reshape(-1).copy())
