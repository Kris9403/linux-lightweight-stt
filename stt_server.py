"""
STT microservice — OpenVINO Whisper Small on NPU.

Endpoints:
  POST /transcribe   body: raw float32 little-endian PCM @ 16 kHz mono
                     OR multipart field 'audio' (any ffmpeg-decodable format)
  GET  /health
"""
from __future__ import annotations
import io
import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import openvino_genai as ov_genai

MODEL_DIR = str(Path(__file__).parent / "whisper-small-ov")
DEVICE = "NPU"
SAMPLE_RATE = 16000
MIN_SAMPLES = 1600       # 0.1 s — discard micro-blips
MAX_SAMPLES = 30 * SAMPLE_RATE  # 30 s hard cap

_pipe: ov_genai.WhisperPipeline | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipe
    print(f"[stt] Loading Whisper Small on {DEVICE}…")
    _pipe = ov_genai.WhisperPipeline(MODEL_DIR, DEVICE)
    print("[stt] Ready.")
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
            [
                "ffmpeg", "-y", "-i", tmp_path,
                "-ar", str(SAMPLE_RATE),
                "-ac", "1",
                "-f", "f32le",
                "-",
            ],
            capture_output=True,
            timeout=15,
        )
        if out.returncode != 0:
            raise ValueError(f"ffmpeg failed: {out.stderr[-200:]}")
        return np.frombuffer(out.stdout, dtype=np.float32)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _run_inference(audio: np.ndarray) -> tuple[str, int]:
    if _pipe is None:
        raise RuntimeError("Model not loaded")
    audio = audio[:MAX_SAMPLES]
    t0 = time.monotonic()
    result = _pipe.generate(audio.tolist())
    ms = round((time.monotonic() - t0) * 1000)
    text = (result.texts[0] if result.texts else "").strip()
    return text, ms


@app.get("/health")
async def health():
    return {"status": "ready" if _pipe else "loading", "device": DEVICE}


@app.post("/transcribe")
async def transcribe(request: Request):
    """
    Two accepted formats:
    1. Content-Type: application/octet-stream  — raw float32 PCM @ 16 kHz mono
    2. Content-Type: multipart/form-data       — field 'audio' with browser blob
    """
    if _pipe is None:
        raise HTTPException(503, "Model still loading")

    content_type = request.headers.get("content-type", "")

    if "multipart" in content_type or "form-data" in content_type:
        # Parse manually to avoid UploadFile overhead on large blobs
        form = await request.form()
        audio_file = form.get("audio")
        if audio_file is None:
            raise HTTPException(400, "Missing 'audio' field in form data")
        raw = await audio_file.read()
        try:
            audio = _ffmpeg_to_pcm(raw)
        except Exception as e:
            raise HTTPException(422, f"Audio decode failed: {e}")
    else:
        # Raw PCM float32
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "Empty body")
        audio = np.frombuffer(raw, dtype=np.float32)

    if len(audio) < MIN_SAMPLES:
        return {"text": "", "ms": 0}

    try:
        text, ms = _run_inference(audio)
    except Exception as e:
        raise HTTPException(500, f"Inference failed: {e}")

    return {"text": text, "ms": ms}
