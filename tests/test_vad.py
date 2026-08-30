import numpy as np

from stt.audio import EndpointDetector


def feed_seconds(d, seconds, level, chunk_ms=100, sr=16000):
    """Feed `seconds` of constant-level audio in chunk_ms pieces. Returns the
    list of feed() results."""
    n = sr * chunk_ms // 1000
    out = []
    for _ in range(int(seconds * 1000 / chunk_ms)):
        out.append(d.feed(np.full(n, level, dtype=np.float32)))
    return out


def test_pure_silence_never_endpoints():
    d = EndpointDetector()
    assert not any(feed_seconds(d, 3.0, 0.0))


def test_quiet_noise_floor_never_endpoints():
    # jittery near-threshold noise (this mic's real problem) must not trigger
    d = EndpointDetector(threshold=0.025)
    rng = np.random.default_rng(0)
    fired = False
    for _ in range(200):
        chunk = rng.uniform(0.0, 0.018, 1600).astype(np.float32)
        fired |= d.feed(chunk)
    assert fired is False


def test_speech_then_silence_endpoints_exactly_once():
    d = EndpointDetector(silence_ms=700, min_speech_ms=300)
    assert not any(feed_seconds(d, 1.0, 0.1))          # 1 s speech, no endpoint yet
    results = feed_seconds(d, 2.0, 0.0)                # 2 s silence
    assert results.count(True) == 1


def test_no_endpoint_before_min_speech():
    d = EndpointDetector(silence_ms=300, min_speech_ms=500)
    feed_seconds(d, 0.2, 0.1)                          # only 200 ms of speech
    assert not any(feed_seconds(d, 2.0, 0.0))


def test_isolated_loud_frames_during_silence_do_not_reset():
    # single 30 ms spikes (the real noise-floor problem) must not restart the
    # countdown — that needs SPEECH_RESET_FRAMES consecutive frames
    d = EndpointDetector(silence_ms=600, min_speech_ms=200, frame_ms=30)
    feed_seconds(d, 0.4, 0.1)                          # real speech
    frame = 480
    seq = []
    for i in range(40):                               # 40 silent frames = 1.2 s
        seq.append(0.2 if i % 7 == 0 else 0.0)        # a lone spike every 210 ms
    fired = any(d.feed(np.full(frame, lv, dtype=np.float32)) for lv in seq)
    assert fired is True


def test_refires_after_reset():
    d = EndpointDetector(silence_ms=500, min_speech_ms=200)
    feed_seconds(d, 0.4, 0.1)
    assert any(feed_seconds(d, 1.0, 0.0))
    feed_seconds(d, 0.4, 0.1)
    assert any(feed_seconds(d, 1.0, 0.0))
