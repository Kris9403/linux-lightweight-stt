"""Global hotkey listener over every keyboard via evdev.

Watches the configured key(s) — `hotkey` may be one name or a list, plus any keys
named in `hotkey_language`, so a laptop key and an external-keyboard key can both
trigger. Each key carries a language (its `hotkey_language` entry, or the default
`language`), a translate flag (`hotkey_translate`), and an optional output
format (`hotkey_format` — snake/camel/raw), all passed to the callbacks so one
key can dictate English prose and another lay down `snake_case` identifiers.

Modes: HOLD (keydown starts, keyup stops), TOGGLE (each keydown flips), and
HYBRID — hold longer than `tap_ms` for push-to-talk, or quick-tap to latch
recording until the next tap. A session is locked to the key that started it:
events from any other hotkey are ignored until it ends. Autorepeat (value 2) and
every non-hotkey keycode are ignored — including the LEFTMETA/LEFTSHIFT the
Copilot key sends alongside F23.

The keyboard set is re-scanned every couple of seconds, so plugging or
unplugging a keyboard while running is picked up without a restart.
"""
from __future__ import annotations

import logging
import selectors
import threading
import time

import evdev
from evdev import ecodes

log = logging.getLogger(__name__)

_RESCAN_EVERY = 2.0  # seconds
# uinput devices we (or other tools) create — never watch our own injector
_VIRTUAL_HINTS = ("ydotoold", "virtual keyboard", "virtual device")


class Listener:
    def __init__(self, cfg, on_press, on_release, on_mute=None, on_cough=None):
        names = [cfg.hotkey] if isinstance(cfg.hotkey, str) else list(cfg.hotkey)
        names += [n for n in cfg.hotkey_language if n not in names]
        names += [n for n in cfg.hotkey_translate if n not in names]
        names += [n for n in cfg.hotkey_format if n not in names]
        self._default_lang = cfg.language
        self.hotkey_codes: set[int] = set()
        self._key_lang: dict[int, str] = {}
        self._key_translate: set[int] = set()
        self._key_format: dict[int, str] = {}
        for name in names:
            try:
                code = ecodes.ecodes[name]
            except KeyError:
                raise ValueError(f"unknown hotkey: {name!r}")
            self.hotkey_codes.add(code)
            self._key_lang[code] = cfg.hotkey_language.get(name, cfg.language)
            if name in cfg.hotkey_translate:
                self._key_translate.add(code)
            if name in cfg.hotkey_format:
                self._key_format[code] = cfg.hotkey_format[name]
        self._names = names
        self.mode = cfg.mode
        self._tap_max = cfg.tap_ms / 1000
        self._keyboard = cfg.keyboard
        self._on_press = on_press
        self._on_release = on_release
        self._on_mute = on_mute or (lambda _muted: None)
        self._on_cough = on_cough or (lambda _active: None)
        self._muted = False
        if cfg.mute_hotkey:
            try:
                self._mute_code: int | None = ecodes.ecodes[cfg.mute_hotkey]
            except KeyError:
                raise ValueError(f"unknown mute_hotkey: {cfg.mute_hotkey!r}")
        else:
            self._mute_code = None
        if cfg.cough_hotkey:
            try:
                self._cough_code: int | None = ecodes.ecodes[cfg.cough_hotkey]
            except KeyError:
                raise ValueError(f"unknown cough_hotkey: {cfg.cough_hotkey!r}")
        else:
            self._cough_code = None
        self._active_code: int | None = None   # keycode that owns the current session
        self._active_lang = cfg.language
        self._active_translate = False
        self._active_format: str | None = None
        self._latched = False                  # hybrid: a quick tap latched recording
        self._down_t = 0.0
        self._sel = selectors.DefaultSelector()
        self._devices: dict[str, evdev.InputDevice] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- state machine (unit-tested directly) ---

    def _handle(self, code: int, value: int) -> None:
        if code == self._mute_code:
            if value == 1:
                self._toggle_mute()
            return
        if code == self._cough_code:
            if value == 1:
                self._on_cough(True)
            elif value == 0:
                self._on_cough(False)
            return
        if self._muted or code not in self.hotkey_codes:
            return
        if self._active_code is not None and code != self._active_code:
            return  # a session is locked to another key

        if self.mode == "hold":
            if value == 1:
                self._begin(code)
            elif value == 0 and self._active_code == code:
                self._end()
        elif self.mode == "hybrid":
            self._handle_hybrid(code, value)
        else:  # toggle / streaming
            if value == 1:
                self._end() if self._active_code == code else self._begin(code)

    def _handle_hybrid(self, code: int, value: int) -> None:
        if value == 1:                       # keydown
            if self._active_code is None:
                self._latched = False
                self._down_t = time.monotonic()
                self._begin(code)
        elif value == 0 and self._active_code == code:   # keyup
            held_long = time.monotonic() - self._down_t >= self._tap_max
            if self._latched or held_long:
                self._end()
            else:                            # quick tap -> keep recording
                self._latched = True

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        if self._muted and self._active_code is not None:
            self._end()
        log.info("hotkey: %s", "muted" if self._muted else "unmuted")
        self._on_mute(self._muted)

    def set_muted(self, muted: bool) -> None:
        """Force the muted state (used by battery_saver). No-op if unchanged."""
        if muted != self._muted:
            self._toggle_mute()

    def _begin(self, code: int) -> None:
        self._active_code = code
        self._active_lang = self._key_lang.get(code, self._default_lang)
        self._active_translate = code in self._key_translate
        self._active_format = self._key_format.get(code)
        self._on_press(self._active_lang, self._active_translate, self._active_format)

    def _end(self) -> None:
        self._active_code = None
        self._latched = False
        self._on_release(self._active_lang, self._active_translate, self._active_format)

    @staticmethod
    def _is_keyboard(dev) -> bool:
        if any(h in dev.name.lower() for h in _VIRTUAL_HINTS):
            return False
        caps = dev.capabilities()
        return ecodes.EV_KEY in caps and ecodes.KEY_A in caps.get(ecodes.EV_KEY, [])

    # --- device I/O ---

    def _wanted_paths(self) -> list[str]:
        if self._keyboard != "auto":
            return [self._keyboard]
        paths = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except (OSError, PermissionError):
                continue
            if self._is_keyboard(dev):
                paths.append(path)
            dev.close()
        return paths

    def _sync_devices(self) -> None:
        wanted = set(self._wanted_paths())
        for path in wanted - self._devices.keys():
            try:
                dev = evdev.InputDevice(path)
            except (OSError, PermissionError):
                continue
            self._sel.register(dev, selectors.EVENT_READ)
            self._devices[path] = dev
            log.info("hotkey: + %s (%s)", path, dev.name)
        for path in self._devices.keys() - wanted:
            self._drop(self._devices[path])

    def _drop(self, dev) -> None:
        try:
            self._sel.unregister(dev)
        except (KeyError, ValueError):
            pass
        self._devices.pop(dev.path, None)
        dev.close()

    def run(self) -> None:
        self._sync_devices()
        if not self._devices:
            raise RuntimeError(
                "no readable keyboard devices — is your user in the 'input' group?"
            )
        log.info("hotkey: watching %d device(s) for %s",
                 len(self._devices), "/".join(self._names))
        next_scan = time.monotonic() + _RESCAN_EVERY
        while not self._stop.is_set():
            for key, _ in self._sel.select(timeout=0.5):
                dev = key.fileobj
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY:
                            self._handle(event.code, event.value)
                except OSError:
                    log.warning("hotkey: %s went away", dev.path)
                    self._drop(dev)
            if time.monotonic() >= next_scan:
                self._sync_devices()
                next_scan = time.monotonic() + _RESCAN_EVERY
        for dev in list(self._devices.values()):
            dev.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
