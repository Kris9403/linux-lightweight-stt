import pytest
from evdev import ecodes

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
META = ecodes.ecodes["KEY_LEFTMETA"]


def test_unknown_hotkey_name_raises():
    with pytest.raises(ValueError):
        Listener(Config(hotkey="KEY_NOPE"), lambda: None, lambda: None)


def test_hold_fires_press_on_keydown_release_on_keyup():
    lis, rec = make("hold")
    lis._handle(F23, 1)
    lis._handle(F23, 0)
    assert rec.events == ["press", "release"]


def test_hold_ignores_autorepeat():
    lis, rec = make("hold")
    lis._handle(F23, 1)
    lis._handle(F23, 2)
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
    lis._handle(F23, 1)     # -> press
    lis._handle(F23, 0)     # keyup ignored
    lis._handle(F23, 1)     # -> release
    lis._handle(F23, 1)     # -> press
    assert rec.events == ["press", "release", "press"]


def test_is_keyboard_filter():
    kbd = type("D", (), {"capabilities": lambda self: {ecodes.EV_KEY: [ecodes.KEY_A, F23]}})()
    mouse = type("D", (), {"capabilities": lambda self: {ecodes.EV_KEY: [ecodes.BTN_LEFT]}})()
    assert Listener._is_keyboard(kbd) is True
    assert Listener._is_keyboard(mouse) is False
