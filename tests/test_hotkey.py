import pytest
from evdev import ecodes

from stt import hotkey
from stt.hotkey import Listener
from stt.config import Config


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(hotkey.time, "monotonic", lambda: now[0])
    return now


class Rec:
    def __init__(self):
        self.events = []       # ("press"/"release", lang)

    def press(self, lang):
        self.events.append(("press", lang))

    def release(self, lang):
        self.events.append(("release", lang))

    @property
    def names(self):
        return [e[0] for e in self.events]


def make(mode="hold", hotkey="KEY_F23", **cfg):
    rec = Rec()
    lis = Listener(Config(mode=mode, hotkey=hotkey, **cfg), rec.press, rec.release)
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
    assert rec.names == ["press", "release"]


def test_hold_ignores_autorepeat():
    lis, rec = make("hold")
    lis._handle(F23, 1)
    lis._handle(F23, 2)
    lis._handle(F23, 0)
    assert rec.names == ["press", "release"]


def test_other_keycodes_are_ignored():
    lis, rec = make("hold")
    lis._handle(META, 1)
    lis._handle(META, 0)
    assert rec.names == []


def test_toggle_alternates_on_each_keydown():
    lis, rec = make("toggle")
    lis._handle(F23, 1)
    lis._handle(F23, 0)
    lis._handle(F23, 1)
    lis._handle(F23, 1)
    assert rec.names == ["press", "release", "press"]


def test_any_key_in_the_list_triggers():
    lis, rec = make("hold", hotkey=["KEY_F23", "KEY_SCROLLLOCK"])
    lis._handle(SLK, 1)          # external-keyboard key
    lis._handle(SLK, 0)
    lis._handle(F23, 1)          # laptop key
    lis._handle(F23, 0)
    assert rec.names == ["press", "release", "press", "release"]


def test_hybrid_long_press_behaves_like_hold(clock):
    lis, rec = make("hybrid")
    lis._handle(F23, 1)
    clock[0] += 1.0                       # held 1 s
    lis._handle(F23, 0)
    assert rec.names == ["press", "release"]


def test_hybrid_quick_taps_behave_like_toggle(clock):
    lis, rec = make("hybrid")
    lis._handle(F23, 1); clock[0] += 0.1; lis._handle(F23, 0)   # tap -> start
    assert rec.names == ["press"]
    clock[0] += 5.0
    lis._handle(F23, 1); clock[0] += 0.1; lis._handle(F23, 0)   # tap -> stop
    assert rec.names == ["press", "release"]


def test_hybrid_tap_then_hold_release_stops(clock):
    lis, rec = make("hybrid")
    lis._handle(F23, 1); clock[0] += 0.1; lis._handle(F23, 0)   # tap -> start (latched)
    lis._handle(F23, 1); clock[0] += 2.0; lis._handle(F23, 0)   # hold -> stop
    assert rec.names == ["press", "release"]


def test_hybrid_ignores_autorepeat_during_hold(clock):
    lis, rec = make("hybrid")
    lis._handle(F23, 1)
    lis._handle(F23, 2); lis._handle(F23, 2)
    clock[0] += 1.0
    lis._handle(F23, 0)
    assert rec.names == ["press", "release"]


def test_each_key_carries_its_own_language():
    lis, rec = make("hold", hotkey="KEY_F23",
                    hotkey_language={"KEY_SCROLLLOCK": "hi"})
    lis._handle(F23, 1); lis._handle(F23, 0)
    lis._handle(SLK, 1); lis._handle(SLK, 0)
    assert rec.events == [
        ("press", "en"), ("release", "en"),
        ("press", "hi"), ("release", "hi"),
    ]


def test_hotkey_language_key_is_listened_for_without_being_in_hotkey():
    lis, _ = make("hold", hotkey="KEY_F23", hotkey_language={"KEY_SCROLLLOCK": "hi"})
    assert SLK in lis.hotkey_codes


def test_release_language_matches_the_key_that_started(clock):
    lis, rec = make("hybrid", hotkey="KEY_F23",
                    hotkey_language={"KEY_SCROLLLOCK": "hi"})
    lis._handle(SLK, 1)          # start Hindi
    clock[0] += 1.0
    lis._handle(SLK, 0)
    assert rec.events == [("press", "hi"), ("release", "hi")]


def test_session_locked_to_its_key_ignores_the_other(clock):
    lis, rec = make("hybrid", hotkey=["KEY_F23", "KEY_SCROLLLOCK"])
    lis._handle(F23, 1); clock[0] += 0.1; lis._handle(F23, 0)   # tap -> latched, F23 owns it
    lis._handle(SLK, 1); clock[0] += 0.1; lis._handle(SLK, 0)   # other key -> ignored
    assert rec.names == ["press"]
    lis._handle(F23, 1); clock[0] += 0.1; lis._handle(F23, 0)   # same key -> stop
    assert rec.names == ["press", "release"]


def test_toggle_second_press_of_a_different_key_does_not_cross_toggle():
    lis, rec = make("toggle", hotkey=["KEY_F23", "KEY_SCROLLLOCK"])
    lis._handle(F23, 1)         # start
    lis._handle(SLK, 1)         # different key -> ignored, not a stop
    assert rec.names == ["press"]
    lis._handle(F23, 1)         # same key -> stop
    assert rec.names == ["press", "release"]


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
