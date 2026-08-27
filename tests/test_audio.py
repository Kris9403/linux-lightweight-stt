import numpy as np
import pytest

from stt import audio
from stt.audio import Recorder


def _frame(n, value=0.1):
    return np.full((n, 1), value, dtype=np.float32)


class FakeStream:
    instances = []

    def __init__(self, **kw):
        self.kw = kw
        self.started = False
        self.closed = False
        FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_sd(monkeypatch):
    FakeStream.instances = []
    monkeypatch.setitem(
        __import__("sys").modules, "sounddevice", type("sd", (), {"InputStream": FakeStream})
    )


def test_stop_without_recording_returns_empty():
    out = Recorder().stop()
    assert out.dtype == np.float32 and out.size == 0


def test_records_frames_between_start_and_stop():
    rec = Recorder(samplerate=16000)
    rec.start()
    rec._callback(_frame(1600), 1600, None, None)
    rec._callback(_frame(800), 800, None, None)
    out = rec.stop()
    assert out.shape == (2400,)
    assert np.allclose(out, 0.1)


def test_start_opens_a_stream_and_stop_tears_it_down():
    rec = Recorder(device="mic-x")
    rec.start()
    assert FakeStream.instances[-1].started is True
    assert FakeStream.instances[-1].kw["device"] == "mic-x"
    rec.stop()
    assert FakeStream.instances[-1].closed is True


def test_each_start_opens_a_fresh_stream():
    rec = Recorder()
    rec.start()
    rec.stop()
    rec.start()
    rec.stop()
    assert len(FakeStream.instances) == 2
    assert all(s.closed for s in FakeStream.instances)


def test_start_clears_previous_utterance():
    rec = Recorder()
    rec.start()
    rec._callback(_frame(1600), 1600, None, None)
    rec.start()
    rec._callback(_frame(800), 800, None, None)
    assert rec.stop().shape == (800,)


def test_buffer_is_capped_at_max_seconds():
    rec = Recorder(samplerate=1000, max_seconds=2)   # cap = 2000 samples
    rec.start()
    for _ in range(5):
        rec._callback(_frame(1000), 1000, None, None)
    assert rec.stop().shape == (2000,)
