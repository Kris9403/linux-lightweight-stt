import pytest

from stt import inject
from stt.config import Config


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    """Neutral starting point: Wayland, runtime dir exists, nothing on PATH."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(inject.shutil, "which", lambda _b: None)
    return monkeypatch


def _have(*names):
    names = set(names)
    return lambda b: f"/usr/bin/{b}" if b in names else None


def test_probe_prefers_ydotool_when_daemon_socket_present(fake_env, tmp_path):
    (tmp_path / ".ydotool_socket").touch()
    fake_env.setattr(inject.shutil, "which", _have("ydotool", "wl-copy", "wl-paste"))

    inj = inject.probe(Config())

    assert inj.method == "ydotool"
    assert inj.can_paste is True


def test_probe_falls_back_to_xdotool_only_on_x11(fake_env):
    fake_env.setenv("XDG_SESSION_TYPE", "x11")
    fake_env.setattr(inject.shutil, "which", _have("xdotool"))

    inj = inject.probe(Config())

    assert inj.method == "xdotool"


def test_probe_raises_on_wayland_with_no_usable_injector(fake_env):
    fake_env.setattr(inject.shutil, "which", _have("xdotool"))  # xdotool useless on wayland

    with pytest.raises(inject.NoInjectorError):
        inject.probe(Config())


def test_probe_honours_forced_method(fake_env):
    fake_env.setattr(inject.shutil, "which", _have("xdotool", "ydotool"))

    inj = inject.probe(Config(inject_method="xdotool"))

    assert inj.method == "xdotool"


class _Calls(list):
    slept: list


@pytest.fixture
def calls(monkeypatch):
    recorded = _Calls()
    recorded.slept = []

    class R:
        returncode = 0
        stdout = b""

    monkeypatch.setattr(inject.subprocess, "run", lambda cmd, **kw: (recorded.append(cmd), R())[1])
    monkeypatch.setattr(inject.time, "sleep", lambda s: recorded.slept.append(s))
    return recorded


def test_send_ignores_empty_text(calls):
    inject.Injector("ydotool", can_paste=True).send("   ")
    assert calls == []


def test_send_short_ascii_types_via_ydotool(calls):
    inject.Injector("ydotool", can_paste=True, paste_threshold=50).send("hello there")
    assert calls == [
        ["ydotool", "type", "--key-delay", "4", "--key-hold", "12", "--", "hello there"]
    ]


def test_send_long_text_uses_clipboard_paste_and_restores(calls, monkeypatch):
    long = "x" * 80
    monkeypatch.setattr(inject.Injector, "_clipboard_get", staticmethod(lambda: "OLD"))

    inject.Injector("ydotool", can_paste=True, paste_threshold=50).send(long)

    assert [c[0] for c in calls].count("wl-copy") == 2    # set new, restore old
    assert calls[0] == ["wl-copy", "--", long]            # our text first
    assert calls[-1] == ["wl-copy", "--", "OLD"]          # original restored last
    assert any(c[:2] == ["ydotool", "key"] for c in calls)


def test_send_key_presses_the_named_key(calls):
    inject.Injector("ydotool", can_paste=True).send_key("enter")
    assert calls == [["ydotool", "key", "28:1", "28:0"]]


def test_send_key_unknown_name_raises(calls):
    with pytest.raises(ValueError):
        inject.Injector("ydotool", can_paste=True).send_key("hyperspace")


def test_undo_backspaces_the_last_insertion(calls):
    inj = inject.Injector("ydotool", can_paste=False, paste_threshold=99)
    inj.send("hello")                       # 5 chars
    calls.clear()
    inj.undo()
    assert calls == [["ydotool", "key"] + ["14:1", "14:0"] * 5]
    calls.clear()
    inj.undo()                              # nothing left to undo
    assert calls == []


def test_paste_settle_delay_is_configurable(calls, monkeypatch):
    monkeypatch.setattr(inject.Injector, "_clipboard_get", staticmethod(lambda: None))
    inject.Injector("ydotool", can_paste=True, paste_threshold=1, settle_ms=40).send("hello world")
    assert calls.slept == [0.04]


def test_send_non_ascii_heavy_uses_paste(calls, monkeypatch):
    monkeypatch.setattr(inject.Injector, "_clipboard_get", staticmethod(lambda: None))
    inject.Injector("ydotool", can_paste=True, paste_threshold=50).send("日本語のテスト")
    assert calls[0][0] == "wl-copy"


def test_send_long_text_types_when_paste_unavailable(calls):
    inject.Injector("ydotool", can_paste=False, paste_threshold=50).send("y" * 80)
    assert calls == [
        ["ydotool", "type", "--key-delay", "4", "--key-hold", "12", "--", "y" * 80]
    ]
