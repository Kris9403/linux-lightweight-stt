import numpy as np
import pytest

from stt.main import single_instance_lock, handle_utterance, emit_segment, AlreadyRunning


class FakeRecorder:
    def __init__(self, pcm):
        self._pcm = pcm

    def stop(self):
        return self._pcm


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.seen = None
        self.seen_language = None
        self.seen_translate = None

    def transcribe(self, pcm, language=None, translate=False):
        self.seen = pcm
        self.seen_language = language
        self.seen_translate = translate
        return self.text


class FakeInjector:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class FakeIndicator:
    def __init__(self):
        self.states = []

    def set(self, state, detail=None):
        self.states.append(state)


def _run(text, trailing_space=True, language=None, translate=False, record=None, redact=False):
    rec = FakeRecorder(np.zeros(16000, dtype=np.float32))
    tr = FakeTranscriber(text)
    inj = FakeInjector()
    ind = FakeIndicator()
    handle_utterance(rec, tr, inj, ind, trailing_space, language=language,
                     translate=translate, record=record, redact=redact)
    return inj, ind, tr


def test_single_instance_lock_blocks_a_second_acquire():
    first = single_instance_lock("lightweight-stt-test-xyz")
    with pytest.raises(AlreadyRunning):
        single_instance_lock("lightweight-stt-test-xyz")
    first.close()


def test_transcribed_text_is_injected_with_trailing_space():
    inj, ind, _ = _run("hello world")
    assert inj.sent == ["hello world "]
    assert ind.states == ["processing", "ready"]


def test_trailing_space_can_be_disabled():
    inj, _, _ = _run("hello world", trailing_space=False)
    assert inj.sent == ["hello world"]


def test_empty_transcription_injects_nothing():
    inj, ind, _ = _run("")
    assert inj.sent == []
    assert ind.states == ["processing", "ready"]


def test_utterance_language_reaches_the_transcriber():
    _, _, tr = _run("bonjour", language="fr")
    assert tr.seen_language == "fr"


def test_translate_flag_reaches_the_transcriber():
    _, _, tr = _run("hello", language="hi", translate=True)
    assert tr.seen_translate is True


def test_history_file_gets_each_insertion(tmp_path):
    hist = tmp_path / "history.log"
    _run("first line", record=hist)
    _run("second line", language="fr", record=hist)
    lines = hist.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("\tfirst line") and "\t\t" in lines[0]     # no language
    assert lines[1].endswith("\tsecond line") and "\tfr\t" in lines[1]


def test_history_not_written_without_a_path(tmp_path):
    _run("nope", record=None)          # just must not raise
    assert list(tmp_path.iterdir()) == []


def test_empty_transcription_is_not_recorded(tmp_path):
    hist = tmp_path / "h.log"
    _run("", record=hist)
    assert not hist.exists()


def test_emit_segment_transcribes_a_raw_pcm_and_types_it(tmp_path):
    tr = FakeTranscriber("segment text")
    inj = FakeInjector()
    ind = FakeIndicator()
    hist = tmp_path / "h.log"
    emit_segment(np.zeros(16000, dtype=np.float32), tr, inj, ind, True,
                 language="fr", translate=True, record=hist)
    assert inj.sent == ["segment text "]
    assert tr.seen_translate is True and tr.seen_language == "fr"
    assert "\tfr→en\tsegment text" in hist.read_text()
    assert ind.states[-1] == "ready"


def test_redact_keeps_the_transcript_out_of_logs_and_history(tmp_path, caplog):
    import logging
    hist = tmp_path / "h.log"
    with caplog.at_level(logging.INFO, logger="stt"):
        inj, _, _ = _run("my secret passphrase", record=hist, redact=True)
    assert inj.sent == ["my secret passphrase "]   # still typed
    assert not hist.exists()                        # not recorded
    assert "secret passphrase" not in caplog.text   # not logged
    assert "20 chars" in caplog.text                # length instead
