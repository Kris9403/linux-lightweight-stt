from stt import audio
from stt.audio import Recorder


def test_recorder_defaults_to_system_device():
    assert Recorder().device is None


def test_open_passes_configured_device_to_input_stream(monkeypatch):
    seen = {}

    class FakeStream:
        def __init__(self, **kw):
            seen.update(kw)

        def start(self):
            seen["started"] = True

    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        type("sd", (), {"InputStream": FakeStream}))
    Recorder(samplerate=16000, device="alsa_input.foo").open()

    assert seen["device"] == "alsa_input.foo"
    assert seen["samplerate"] == 16000
    assert seen["started"] is True
