"""Optional timing for transcription latency.

Turned on with `latency_stats = true`. Each utterance's transcribe time is
logged as it happens, and a one-line summary (count, mean, min, max, p95) is
logged when the service stops.
"""
from __future__ import annotations

import logging

log = logging.getLogger("stt")


class Timings:
    def __init__(self) -> None:
        self._ms: list[float] = []

    def add(self, seconds: float) -> None:
        self._ms.append(seconds * 1000)

    def __len__(self) -> int:
        return len(self._ms)

    def summary(self) -> str:
        if not self._ms:
            return "no transcriptions timed"
        s = sorted(self._ms)
        mean = sum(s) / len(s)
        p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
        return (f"{len(s)} transcriptions — mean {mean:.0f} ms, "
                f"min {s[0]:.0f}, max {s[-1]:.0f}, p95 {p95:.0f}")

    def log_summary(self) -> None:
        log.info("latency: %s", self.summary())
