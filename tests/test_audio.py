import numpy as np

from stt.audio import Recorder


def _frame(n, value=0.1):
    return np.full((n, 1), value, dtype=np.float32)


def test_stop_without_recording_returns_empty():
    rec = Recorder()
    out = rec.stop()
    assert out.dtype == np.float32
    assert out.size == 0


def test_records_frames_between_start_and_stop():
    rec = Recorder(samplerate=16000)
    rec.start()
    rec._callback(_frame(1600), 1600, None, None)
    rec._callback(_frame(800), 800, None, None)
    out = rec.stop()
    assert out.shape == (2400,)
    assert np.allclose(out, 0.1)


def test_frames_outside_recording_are_dropped():
    rec = Recorder()
    rec._callback(_frame(1600), 1600, None, None)   # before start
    rec.start()
    rec._callback(_frame(1600), 1600, None, None)
    rec.stop()
    rec._callback(_frame(1600), 1600, None, None)   # after stop
    assert rec.stop().size == 0


def test_start_clears_previous_utterance():
    rec = Recorder()
    rec.start()
    rec._callback(_frame(1600), 1600, None, None)
    rec.start()                                     # restart, no stop
    rec._callback(_frame(800), 800, None, None)
    assert rec.stop().shape == (800,)


def test_buffer_is_capped_at_max_seconds():
    rec = Recorder(samplerate=1000, max_seconds=2)   # cap = 2000 samples
    rec.start()
    for _ in range(5):
        rec._callback(_frame(1000), 1000, None, None)
    out = rec.stop()
    assert out.shape == (2000,)
