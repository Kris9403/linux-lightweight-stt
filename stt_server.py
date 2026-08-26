"""
STT microservice — the same OpenVINO Whisper transcriber the CLI uses, over HTTP.

Endpoints:
  POST /transcribe   body: raw float32 little-endian PCM @ 16 kHz mono
                     OR multipart field 'audio' (any ffmpeg-decodable format)
  GET  /health
"""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from stt.config import load as load_config
from stt.transcribe import Transcriber

_cfg = load_config()
SAMPLE_RATE = 16000
MAX_SAMPLES = 30 * SAMPLE_RATE  # 30 s hard cap on a single request

_transcriber: Transcriber | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _transcriber
    print(f"[stt] loading Whisper on {_cfg.device}…")
    _transcriber = Transcriber(
        _cfg.model_dir, _cfg.device, _cfg.language, _cfg.cache_dir, _cfg.min_speech_ms
    )
    print("[stt] ready.")
    yield


app = FastAPI(title="STT API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _ffmpeg_to_pcm(data: bytes) -> np.ndarray:
    """Decode any audio format (webm, ogg, wav, …) to 16 kHz mono float32 via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        out = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-ar", str(SAMPLE_RATE), "-ac", "1",
             "-f", "f32le", "-"],
            capture_output=True,
            timeout=15,
        )
        if out.returncode != 0:
            raise ValueError(f"ffmpeg failed: {out.stderr[-200:]}")
        return np.frombuffer(out.stdout, dtype=np.float32)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/health")
async def health():
    return {"status": "ready" if _transcriber else "loading", "device": _cfg.device}


@app.post("/transcribe")
async def transcribe(request: Request):
    """
    Two accepted formats:
    1. Content-Type: application/octet-stream  — raw float32 PCM @ 16 kHz mono
    2. Content-Type: multipart/form-data       — field 'audio' with browser blob
    """
    if _transcriber is None:
        raise HTTPException(503, "model still loading")

    content_type = request.headers.get("content-type", "")

    if "multipart" in content_type or "form-data" in content_type:
        form = await request.form()
        audio_file = form.get("audio")
        if audio_file is None:
            raise HTTPException(400, "missing 'audio' field in form data")
        raw = await audio_file.read()
        try:
            audio = _ffmpeg_to_pcm(raw)
        except Exception as e:
            raise HTTPException(422, f"audio decode failed: {e}")
    else:
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "empty body")
        audio = np.frombuffer(raw, dtype=np.float32)

    audio = audio[:MAX_SAMPLES]
    try:
        t0 = time.monotonic()
        text = _transcriber.transcribe(audio)
        ms = round((time.monotonic() - t0) * 1000)
    except Exception as e:
        raise HTTPException(500, f"inference failed: {e}")

    return {"text": text, "ms": ms}
