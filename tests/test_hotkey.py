import pytest
from evdev import ecodes

from stt import hotkey
from stt.hotkey import Listener
from stt.config import Config


class Rec:
    def __init__(self):
        self.events = []

    def press(self):
        self.events.append("press")

    def release(self):
        self.events.append("release")


def make(mode="hold", hotkey="KEY_F23"):
    rec = Rec()
    lis = Listener(Config(mode=mode, hotkey=hotkey), rec.press, rec.release)
    return lis, rec


F23 = ecodes.ecodes["KEY_F23"]
SLK = ecodes.ecodes["KEY_SCROLLLOCK"]
META = ecodes.ecodes["KEY_LEFTMETA"]


class FakeDev:
    def __init__(self, name, keys=(ecodes.KEY_A,), path="/dev/input/event0"):
        self.name = name
        self.path = path
        self._keys = list(keys)
        self.closed = False

    def capabilities(self):
        return {ecodes.EV_KEY: self._keys}

    def close(self):
        self.closed = True


def test_unknown_hotkey_name_raises():
    with pytest.raises(ValueError):
        Listener(Config(hotkey="KEY_NOPE"), lambda: None, lambda: None)


def test_unknown_name_in_hotkey_list_raises():
    with pytest.raises(ValueError):
        Listener(Config(hotkey=["KEY_F23", "KEY_NOPE"]), lambda: None, lambda: None)


def test_hold_fires_press_on_keydown_release_on_keyup():
    lis, rec = make("hold")
    lis._handle(F23, 1)
    lis._handle(F23, 0)
    assert rec.events == ["press", "release"]


def test_hold_ignores_autorepeat():
    lis, rec = make("hold")
    lis._handle(F23, 1)
    lis._handle(F23, 2)
    lis._handle(F23, 0)
    assert rec.events == ["press", "release"]


def test_other_keycodes_are_ignored():
    lis, rec = make("hold")
    lis._handle(META, 1)
    lis._handle(META, 0)
    assert rec.events == []


def test_toggle_alternates_on_each_keydown():
    lis, rec = make("toggle")
    lis._handle(F23, 1)
    lis._handle(F23, 0)
    lis._handle(F23, 1)
    lis._handle(F23, 1)
    assert rec.events == ["press", "release", "press"]


def test_any_key_in_the_list_triggers():
    lis, rec = make("hold", hotkey=["KEY_F23", "KEY_SCROLLLOCK"])
    lis._handle(SLK, 1)          # external-keyboard key
    lis._handle(SLK, 0)
    lis._handle(F23, 1)          # laptop key
    lis._handle(F23, 0)
    assert rec.events == ["press", "release", "press", "release"]


def test_is_keyboard_filter():
    kbd = FakeDev("Some Keyboard", keys=[ecodes.KEY_A, F23])
    mouse = FakeDev("Some Mouse", keys=[ecodes.BTN_LEFT])
    assert Listener._is_keyboard(kbd) is True
    assert Listener._is_keyboard(mouse) is False


def test_is_keyboard_excludes_our_own_virtual_device():
    virt = FakeDev("ydotoold virtual device", keys=[ecodes.KEY_A])
    assert Listener._is_keyboard(virt) is False


def test_sync_devices_adds_hotplugged_and_drops_removed(monkeypatch):
    lis, _ = make("hold")
    devs = {"/dev/input/event5": FakeDev("laptop kbd", path="/dev/input/event5")}

    monkeypatch.setattr(hotkey.evdev, "list_devices", lambda: list(devs))
    monkeypatch.setattr(hotkey.evdev, "InputDevice", lambda p: devs[p])
    monkeypatch.setattr(lis._sel, "register", lambda *a, **k: None)
    monkeypatch.setattr(lis._sel, "unregister", lambda *a, **k: None)

    lis._sync_devices()
    assert set(lis._devices) == {"/dev/input/event5"}

    devs["/dev/input/event20"] = FakeDev("usb kbd", path="/dev/input/event20")
    lis._sync_devices()
    assert set(lis._devices) == {"/dev/input/event5", "/dev/input/event20"}

    removed = devs.pop("/dev/input/event20")
    lis._sync_devices()
    assert set(lis._devices) == {"/dev/input/event5"}
    assert removed.closed is True
