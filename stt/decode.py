"""Decode any audio/video file (or blob) to 16 kHz mono float32 via ffmpeg."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def ffmpeg_to_pcm(src: str | bytes, timeout: int = 120) -> np.ndarray:
    """`src` may be a file path or raw bytes. Returns mono float32 @ 16 kHz."""
    tmp_path = None
    if isinstance(src, (bytes, bytearray)):
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
            tmp.write(src)
            tmp_path = tmp.name
        path = tmp_path
    else:
        path = src
    try:
        out = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", str(SAMPLE_RATE), "-ac", "1",
             "-f", "f32le", "-"],
            capture_output=True,
            timeout=timeout,
        )
        if out.returncode != 0:
            raise ValueError(f"ffmpeg failed: {out.stderr[-200:]}")
        return np.frombuffer(out.stdout, dtype=np.float32)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
