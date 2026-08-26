"""Global hotkey listener over every keyboard via evdev.

Watches only the configured key. In HOLD mode a keydown starts and a keyup
stops; in TOGGLE mode each keydown flips. Autorepeat (value 2) and every other
keycode are ignored — including the LEFTMETA/LEFTSHIFT that the Copilot key
sends alongside F23. Devices are re-scanned if one disappears.
"""
from __future__ import annotations

import logging
import selectors
import threading

import evdev
from evdev import ecodes

log = logging.getLogger(__name__)


class Listener:
    def __init__(self, cfg, on_press, on_release):
        try:
            self.hotkey_code = ecodes.ecodes[cfg.hotkey]
        except KeyError:
            raise ValueError(f"unknown hotkey: {cfg.hotkey!r}")
        self.mode = cfg.mode
        self._keyboard = cfg.keyboard
        self._on_press = on_press
        self._on_release = on_release
        self._toggle_on = False
        self._sel = selectors.DefaultSelector()
        self._devices: dict[int, evdev.InputDevice] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- state machine (unit-tested directly) ---

    def _handle(self, code: int, value: int) -> None:
        if code != self.hotkey_code:
            return
        if self.mode == "hold":
            if value == 1:
                self._on_press()
            elif value == 0:
                self._on_release()
        else:  # toggle / streaming
            if value == 1:
                self._toggle_on = not self._toggle_on
                (self._on_press if self._toggle_on else self._on_release)()

    @staticmethod
    def _is_keyboard(dev) -> bool:
        caps = dev.capabilities()
        return ecodes.EV_KEY in caps and ecodes.KEY_A in caps.get(ecodes.EV_KEY, [])

    # --- device I/O ---

    def _discover(self) -> list[evdev.InputDevice]:
        paths = evdev.list_devices() if self._keyboard == "auto" else [self._keyboard]
        found = []
        for path in paths:
            try:
                dev = evdev.InputDevice(path)
            except (OSError, PermissionError):
                continue
            if self._keyboard != "auto" or self._is_keyboard(dev):
                found.append(dev)
        return found

    def _register_all(self) -> None:
        for dev in self._discover():
            self._sel.register(dev, selectors.EVENT_READ)
            self._devices[dev.fd] = dev

    def run(self) -> None:
        self._register_all()
        if not self._devices:
            raise RuntimeError(
                "no readable keyboard devices — is your user in the 'input' group?"
            )
        log.info("hotkey: watching %d device(s) for %s", len(self._devices), self._key_name())
        while not self._stop.is_set():
            for key, _ in self._sel.select(timeout=0.5):
                dev = key.fileobj
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY:
                            self._handle(event.code, event.value)
                except OSError:
                    log.warning("hotkey: device %s went away, rescanning", dev.path)
                    self._sel.unregister(dev)
                    self._devices.pop(dev.fd, None)
                    self._register_all()
        for dev in self._devices.values():
            dev.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _key_name(self) -> str:
        return ecodes.KEY.get(self.hotkey_code, str(self.hotkey_code))
