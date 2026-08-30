import numpy as np

from stt.audio import EndpointDetector


def speech(n=1600, level=0.1):
    return np.full(n, level, dtype=np.float32)


def silence(n=1600):
    return np.zeros(n, dtype=np.float32)


def test_pure_silence_never_endpoints():
    d = EndpointDetector(samplerate=16000)
    assert not any(d.feed(silence()) for _ in range(50))


def test_endpoints_once_after_speech_then_enough_silence():
    d = EndpointDetector(samplerate=16000, silence_ms=700, min_speech_ms=300)
    fired = [d.feed(speech()) for _ in range(4)]          # 0.4 s speech
    assert not any(fired)
    fired = [d.feed(silence()) for _ in range(10)]        # 1.0 s silence
    assert fired.count(True) == 1
    assert fired.index(True) == 6                          # ~0.7 s in (7*1600 samples)


def test_brief_noise_below_min_speech_does_not_endpoint():
    d = EndpointDetector(samplerate=16000, silence_ms=400, min_speech_ms=300)
    d.feed(speech(n=1600))                                 # only 0.1 s — not "speech"
    assert not any(d.feed(silence()) for _ in range(20))


def test_can_endpoint_again_after_firing():
    d = EndpointDetector(samplerate=16000, silence_ms=500, min_speech_ms=200)
    for _ in range(3):
        d.feed(speech())
    assert any(d.feed(silence()) for _ in range(6))        # first endpoint
    for _ in range(3):
        d.feed(speech())
    assert any(d.feed(silence()) for _ in range(6))        # second endpoint
