import numpy as np
import pytest

from stt.main import single_instance_lock, handle_utterance, AlreadyRunning


class FakeRecorder:
    def __init__(self, pcm):
        self._pcm = pcm

    def stop(self):
        return self._pcm


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.seen = None

    def transcribe(self, pcm):
        self.seen = pcm
        return self.text


class FakeInjector:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class FakeIndicator:
    def __init__(self):
        self.states = []

    def set(self, state):
        self.states.append(state)


def _run(text, trailing_space=True):
    rec = FakeRecorder(np.zeros(16000, dtype=np.float32))
    tr = FakeTranscriber(text)
    inj = FakeInjector()
    ind = FakeIndicator()
    handle_utterance(rec, tr, inj, ind, trailing_space)
    return inj, ind


def test_single_instance_lock_blocks_a_second_acquire():
    first = single_instance_lock("lightweight-stt-test-xyz")
    with pytest.raises(AlreadyRunning):
        single_instance_lock("lightweight-stt-test-xyz")
    first.close()


def test_transcribed_text_is_injected_with_trailing_space():
    inj, ind = _run("hello world")
    assert inj.sent == ["hello world "]
    assert ind.states == ["processing", "ready"]


def test_trailing_space_can_be_disabled():
    inj, _ = _run("hello world", trailing_space=False)
    assert inj.sent == ["hello world"]


def test_empty_transcription_injects_nothing():
    inj, ind = _run("")
    assert inj.sent == []
    assert ind.states == ["processing", "ready"]
