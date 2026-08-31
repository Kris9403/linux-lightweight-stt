from stt import power
from stt.power import active_profile, on_power_saver


class _Run:
    def __init__(self, stdout):
        self.stdout = stdout


def test_returns_none_when_powerprofilesctl_is_missing(monkeypatch):
    monkeypatch.setattr(power.shutil, "which", lambda _: None)
    assert active_profile() is None
    assert on_power_saver() is False


def test_reads_and_strips_the_profile(monkeypatch):
    monkeypatch.setattr(power.shutil, "which", lambda _: "/usr/bin/powerprofilesctl")
    monkeypatch.setattr(power.subprocess, "run", lambda *a, **k: _Run("power-saver\n"))
    assert active_profile() == "power-saver"
    assert on_power_saver() is True


def test_balanced_is_not_power_saver(monkeypatch):
    monkeypatch.setattr(power.shutil, "which", lambda _: "/usr/bin/powerprofilesctl")
    monkeypatch.setattr(power.subprocess, "run", lambda *a, **k: _Run("balanced\n"))
    assert on_power_saver() is False


def test_subprocess_failure_is_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(power.shutil, "which", lambda _: "/usr/bin/powerprofilesctl")

    def boom(*a, **k):
        raise OSError("no dbus")

    monkeypatch.setattr(power.subprocess, "run", boom)
    with caplog.at_level("WARNING", logger="stt"):
        assert active_profile() is None
    assert "could not read power profile" in caplog.text
