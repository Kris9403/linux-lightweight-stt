import numpy as np
from starlette.testclient import TestClient

import stt_server


def test_health_and_silence_transcription():
    with TestClient(stt_server.app) as client:
        health = client.get("/health").json()
        assert health["status"] == "ready"

        pcm = np.zeros(16000, dtype=np.float32).tobytes()
        body = client.post(
            "/transcribe",
            content=pcm,
            headers={"content-type": "application/octet-stream"},
        ).json()
        assert body["text"] == ""
        assert "ms" in body


def test_server_uses_shared_transcriber():
    # the inline WhisperPipeline copy is gone
    assert not hasattr(stt_server, "_run_inference")
    assert stt_server.Transcriber is not None
