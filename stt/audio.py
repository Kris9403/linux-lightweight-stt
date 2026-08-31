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
    """RMS-energy voice-activity endpointing, no model.

    Audio is analysed in fixed ~30 ms frames (so tiny 2 ms driver callbacks or
    huge ones both work) — the framing alone averages out sub-frame noise ticks.
    A run of `_SPEECH_RESET_FRAMES` consecutive speech frames is required to
    clear the silence countdown, so a lone noisy frame doesn't. `feed()` returns
    True the moment speech has been heard and then followed by `silence_ms` of
    quiet.
    """

    _SPEECH_RESET_FRAMES = 3   # ~90 ms of sustained speech clears the countdown

    def __init__(self, samplerate: int = SAMPLE_RATE, threshold: float = 0.025,
                 silence_ms: int = 700, min_speech_ms: int = 300, frame_ms: int = 30):
        self.threshold = threshold
        self._frame = max(1, samplerate * frame_ms // 1000)
        self._silence_frames_needed = max(1, silence_ms // frame_ms)
        self._speech_frames_needed = max(1, min_speech_ms // frame_ms)
        self._tail = np.zeros(0, dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        self._speech_run = 0
        self._silence_run = 0
        self._had_speech = False
        self._tail = self._tail[:0]

    def feed(self, chunk: np.ndarray) -> bool:
        if chunk is None or len(chunk) == 0:
            return False
        buf = np.concatenate([self._tail, np.asarray(chunk, dtype=np.float32).reshape(-1)])
        fired = False
        n = self._frame
        for i in range(0, len(buf) - n + 1, n):
            if self._step(buf[i:i + n]):
                fired = True
        self._tail = buf[len(buf) - (len(buf) % n):] if len(buf) % n else buf[:0]
        return fired

    def _step(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        if rms > self.threshold:
            self._speech_run += 1
            if self._speech_run >= self._speech_frames_needed:   # sustained speech
                self._had_speech = True
            if self._speech_run >= self._SPEECH_RESET_FRAMES:
                self._silence_run = 0
        else:
            self._speech_run = 0
            if self._had_speech:
                self._silence_run += 1
                if self._silence_run >= self._silence_frames_needed:
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
        self.paused = False
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
            blocksize=self.samplerate // 10,   # ~100 ms callbacks, not 2 ms
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

    def set_paused(self, paused: bool) -> None:
        """While paused, incoming audio is discarded (the "cough key"). Pausing
        also dumps whatever is buffered; resuming resets the endpointer so the
        gap doesn't count as a pause."""
        self.paused = paused
        if paused:
            self._chunks.clear()
        elif self._vad is not None:
            self._vad.reset()

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
        if self.paused:
            return
        chunk = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        self._chunks.append(chunk)
        if self._vad is not None and self._vad.feed(chunk) and self.on_endpoint:
            self.on_endpoint()
