"""Status feedback: an in-place desktop notification and/or a short sound.

Both are fire-and-forget (subprocess.Popen, never waited on) so the hotkey
thread is never blocked. The notification always uses the same replace-id, so
LISTENING -> PROCESSING -> READY update one notification rather than stacking.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

NOTIFY_ID = 9942

# state -> (notification summary, freedesktop sound event or None)
_STATES = {
    "ready": ("Ready", "complete"),
    "listening": ("Listening…", "message"),
    "processing": ("Transcribing…", None),
    "error": ("Speech-to-text error", "dialog-warning"),
    "off": ("Off", None),
}


class Indicator:
    def __init__(self, mode: str = "both"):
        self.mode = mode
        self._notify = mode in ("notify", "both")
        self._beep = mode in ("beep", "both")

    def set(self, state: str) -> None:
        summary, sound = _STATES.get(state, (state.title(), None))
        if self._notify:
            self._spawn(
                ["notify-send", "-r", str(NOTIFY_ID), "-h", "int:transient:1",
                 "lightweight-stt", summary]
            )
        if self._beep and sound:
            self._spawn(["canberra-gtk-play", "-i", sound])

    @staticmethod
    def _spawn(cmd: list[str]) -> None:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log.debug("indicator: %s not installed", cmd[0])
