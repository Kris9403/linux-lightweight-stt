import pytest

from stt import indicator
from stt.indicator import Indicator, NOTIFY_ID


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(indicator.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    return calls


def _progs(calls):
    return [c[0] for c in calls]


def test_notify_mode_calls_notify_send_with_stable_replace_id(spawned):
    Indicator("notify").set("listening")
    assert _progs(spawned) == ["notify-send"]
    assert "-r" in spawned[0] and str(NOTIFY_ID) in spawned[0]


def test_replace_id_is_identical_across_states(spawned):
    ind = Indicator("notify")
    ind.set("listening")
    ind.set("ready")
    ids = [c[c.index("-r") + 1] for c in spawned]
    assert ids == [str(NOTIFY_ID), str(NOTIFY_ID)]


def test_beep_mode_plays_sound_and_sends_no_notification(spawned):
    Indicator("beep").set("listening")
    assert _progs(spawned) == ["canberra-gtk-play"]


def test_both_mode_notifies_and_beeps(spawned):
    Indicator("both").set("listening")
    assert set(_progs(spawned)) == {"notify-send", "canberra-gtk-play"}


def test_off_mode_is_silent(spawned):
    Indicator("off").set("listening")
    Indicator("off").set("error")
    assert spawned == []


def test_processing_state_does_not_beep(spawned):
    Indicator("both").set("processing")
    assert _progs(spawned) == ["notify-send"]


def test_popen_is_used_not_run(monkeypatch):
    monkeypatch.setattr(
        indicator.subprocess, "run",
        lambda *a, **k: pytest.fail("indicator must not block on subprocess.run"),
    )
    monkeypatch.setattr(indicator.subprocess, "Popen", lambda *a, **k: None)
    Indicator("both").set("ready")
