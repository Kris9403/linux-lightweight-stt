import numpy as np
import pytest

from stt.config import load as load_config
from stt.transcribe import Transcriber, is_too_short, is_hallucination


@pytest.fixture(scope="module")
def transcriber():
    cfg = load_config()  # defaults: NPU, en, warm CACHE_DIR
    return Transcriber(
        model_dir=cfg.model_dir,
        device=cfg.device,
        language=cfg.language,
        cache_dir=cfg.cache_dir,
        min_speech_ms=cfg.min_speech_ms,
    )


# --- pure gate logic (no model) ---

def test_is_too_short_flags_sub_threshold_audio():
    pcm = np.zeros(1600, dtype=np.float32)          # 100 ms @ 16 kHz
    assert is_too_short(pcm, min_speech_ms=300) is True


def test_is_too_short_passes_long_enough_audio():
    pcm = np.zeros(8000, dtype=np.float32)          # 500 ms @ 16 kHz
    assert is_too_short(pcm, min_speech_ms=300) is False


@pytest.mark.parametrize("text", [
    " you",
    "You",
    "Thank you.",
    "  Thanks for watching!  ",
    "bye.",
])
def test_is_hallucination_catches_known_silence_artifacts(text):
    assert is_hallucination(text) is True


@pytest.mark.parametrize("text", [
    "the quick brown fox",
    "you know what I mean",
    "thank you for the coffee this morning",
    "buy the dip",
])
def test_is_hallucination_leaves_real_speech_alone(text):
    assert is_hallucination(text) is False


# --- integration: real Whisper on the NPU ---

def test_transcriber_returns_empty_for_below_threshold_audio(transcriber):
    pcm = np.zeros(1600, dtype=np.float32)          # 100 ms — length gate
    assert transcriber.transcribe(pcm) == ""


def test_transcriber_suppresses_silence_hallucination(transcriber):
    # 1 s of silence is past the length gate; the model emits " you",
    # which the blocklist must strip to "".
    pcm = np.zeros(16000, dtype=np.float32)
    assert transcriber.transcribe(pcm) == ""


def test_transcriber_accepts_float64_input(transcriber):
    # sounddevice can hand us float64; must not raise.
    pcm = np.zeros(16000, dtype=np.float64)
    assert transcriber.transcribe(pcm) == ""
