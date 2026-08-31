"""Live microphone level meter.

    python -m stt.meter

Prints a rolling RMS bar so you can pick a `vad_threshold` for streaming mode:
speak the way you normally would, watch where the level sits, then set the
threshold a little under that and comfortably above the quiet-room floor.
Ctrl-C to stop.
"""
from __future__ import annotations

import sys
import time

import numpy as np

from .audio import SAMPLE_RATE
from .config import load

_WIDTH = 40         # bar characters at full scale
_FULL_SCALE = 0.30  # RMS that fills the bar


def rms(frame) -> float:
    a = np.asarray(frame, dtype=np.float64).reshape(-1)
    if a.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(a))))


def bar(level: float, width: int = _WIDTH, full_scale: float = _FULL_SCALE) -> str:
    filled = max(0, min(width, round(level / full_scale * width)))
    return "#" * filled + "-" * (width - filled)


def run() -> int:
    cfg = load()
    import sounddevice as sd

    peak = 0.0

    def cb(indata, frames, time_info, status):
        nonlocal peak
        level = rms(indata)
        peak = max(peak * 0.95, level)
        sys.stdout.write(f"\r  {bar(level)}  rms {level:.4f}   peak {peak:.4f}   "
                         f"(vad_threshold = {cfg.vad_threshold})")
        sys.stdout.flush()

    print(f"mic: {cfg.audio_device or 'system default'} — Ctrl-C to stop")
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            device=cfg.audio_device, blocksize=SAMPLE_RATE // 10,
                            callback=cb):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    except Exception as e:  # noqa: BLE001
        print(f"\nmic error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
