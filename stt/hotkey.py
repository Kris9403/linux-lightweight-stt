"""Global hotkey listener over every keyboard via evdev.

Watches the configured key(s) — `hotkey` may be one name or a list, so a laptop
key and an external-keyboard key can both trigger. In HOLD mode a keydown starts
and a keyup stops; in TOGGLE mode each keydown flips. Autorepeat (value 2) and
every other keycode are ignored — including the LEFTMETA/LEFTSHIFT the Copilot
key sends alongside F23.

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
    def __init__(self, cfg, on_press, on_release):
        names = [cfg.hotkey] if isinstance(cfg.hotkey, str) else list(cfg.hotkey)
        self.hotkey_codes: set[int] = set()
        for name in names:
            try:
                self.hotkey_codes.add(ecodes.ecodes[name])
            except KeyError:
                raise ValueError(f"unknown hotkey: {name!r}")
        self._names = names
        self.mode = cfg.mode
        self._keyboard = cfg.keyboard
        self._on_press = on_press
        self._on_release = on_release
        self._toggle_on = False
        self._sel = selectors.DefaultSelector()
        self._devices: dict[str, evdev.InputDevice] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- state machine (unit-tested directly) ---

    def _handle(self, code: int, value: int) -> None:
        if code not in self.hotkey_codes:
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
