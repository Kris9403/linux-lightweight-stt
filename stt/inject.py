"""Type transcribed text at the cursor.

Order of preference (GNOME Wayland reality):
  1. ydotool  — uinput, reaches native Wayland apps. Needs ydotoold running.
  2. paste    — wl-copy + ydotool Ctrl+V; used for long / non-ASCII text.
  3. xdotool  — X11 sessions only (Xwayland-only on Wayland, so refused there).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

# ydotool key codes: leftctrl=29, v=47
_CTRL_V = ["29:1", "47:1", "47:0", "29:0"]


class NoInjectorError(RuntimeError):
    pass


def _ydotool_socket() -> Path | None:
    env = os.environ.get("YDOTOOL_SOCKET")
    if env:
        return Path(env)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / ".ydotool_socket"
    return None


def _ydotool_usable() -> bool:
    if not shutil.which("ydotool"):
        return False
    sock = _ydotool_socket()
    return sock is not None and sock.exists()


def _session_is_x11() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "x11"


def probe(cfg: Config) -> "Injector":
    forced = cfg.inject_method if cfg.inject_method != "auto" else None
    have_clipboard = bool(shutil.which("wl-copy") and shutil.which("wl-paste"))

    if forced == "xdotool" or (not forced and _session_is_x11() and shutil.which("xdotool")):
        if not shutil.which("xdotool"):
            raise NoInjectorError("inject_method=xdotool but xdotool is not installed")
        log.info("injector: xdotool")
        return Injector("xdotool", can_paste=True, paste_threshold=cfg.paste_threshold)

    if forced in ("ydotool", "paste") or (not forced and _ydotool_usable()):
        if not shutil.which("ydotool"):
            raise NoInjectorError("inject_method=%s but ydotool is not installed" % forced)
        log.info("injector: ydotool (clipboard paste %s)", "on" if have_clipboard else "off")
        return Injector("ydotool", can_paste=have_clipboard, paste_threshold=cfg.paste_threshold)

    raise NoInjectorError(
        "no usable text injector. On Wayland install ydotool and start ydotoold "
        "(run setup.sh); on X11 install xdotool."
    )


def _mostly_non_ascii(text: str) -> bool:
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii * 4 >= len(text)


class Injector:
    def __init__(self, method: str, *, can_paste: bool, paste_threshold: int = 50):
        self.method = method
        self.can_paste = can_paste
        self.paste_threshold = paste_threshold

    def send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.can_paste and (len(text) > self.paste_threshold or _mostly_non_ascii(text)):
            self._paste(text)
        else:
            self._type(text)

    def _type(self, text: str) -> None:
        if self.method == "xdotool":
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], check=True)
        else:
            # ydotool defaults to 20ms delay + 20ms hold per key (~40ms/char),
            # which types visibly slowly. Drop it to near-instant.
            subprocess.run(
                ["ydotool", "type", "--key-delay", "0", "--key-hold", "2", "--", text],
                check=True,
            )

    def _paste(self, text: str) -> None:
        saved = self._clipboard_get()
        self._clipboard_set(text)
        try:
            if self.method == "xdotool":
                subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)
            else:
                subprocess.run(["ydotool", "key", *_CTRL_V], check=True)
            time.sleep(0.15)
        finally:
            if saved is not None:
                self._clipboard_set(saved)

    @staticmethod
    def _clipboard_get() -> str | None:
        try:
            out = subprocess.run(
                ["wl-paste", "--no-newline"], capture_output=True, timeout=2
            )
            return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None
        except Exception:
            return None

    @staticmethod
    def _clipboard_set(text: str) -> None:
        subprocess.run(["wl-copy", "--", text], check=True)


def _main() -> int:
    import sys

    from .config import load

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    text = " ".join(sys.argv[1:]) or "lightweight-stt inject smoke test ☃"
    try:
        inj = probe(load())
    except NoInjectorError as e:
        print(f"no injector: {e}", file=sys.stderr)
        return 1
    print(f"method={inj.method} can_paste={inj.can_paste} -> sending {text!r}")
    inj.send(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
