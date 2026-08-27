"""Status feedback: an in-place desktop notification and/or a short sound.

Both are fire-and-forget (subprocess.Popen, never waited on) so the hotkey
thread is never blocked. Every notification uses the same replace-id, so
LISTENING -> PROCESSING -> READY update one notification rather than stacking.

LISTENING and PROCESSING are held on screen (never expire) so "I'm recording"
is unmistakable while the key is down; READY / ERROR / OFF are transient and
fade on their own.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

NOTIFY_ID = 9942

# state -> (summary, sound event or None, icon, urgency, sticky)
_STATES = {
    "listening":  ("Listening…",   "message",        "audio-input-microphone", "normal",   True),
    "processing": ("Transcribing…", None,            "content-loading-symbolic", "low",     True),
    "ready":      ("Ready",         "complete",       "audio-input-microphone", "low",      False),
    "error":      ("Speech-to-text error", "dialog-warning", "dialog-error",   "critical", False),
    "off":        ("Off",           None,             "audio-input-microphone", "low",      False),
}


class Indicator:
    def __init__(self, mode: str = "both"):
        self.mode = mode
        self._notify = mode in ("notify", "both")
        self._beep = mode in ("beep", "both")

    def set(self, state: str, detail: str | None = None) -> None:
        summary, sound, icon, urgency, sticky = _STATES.get(
            state, (state.title(), None, "dialog-information", "normal", False)
        )
        if detail:
            summary = f"{summary} · {detail}"
        if self._notify:
            cmd = ["notify-send", "-r", str(NOTIFY_ID), "-u", urgency, "-i", icon]
            if sticky:
                cmd += ["-t", "0"]
            else:
                cmd += ["-t", "2000", "-h", "int:transient:1"]
            cmd += ["lightweight-stt", summary]
            self._spawn(cmd)
        if self._beep and sound:
            self._spawn(["canberra-gtk-play", "-i", sound])

    @staticmethod
    def _spawn(cmd: list[str]) -> None:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log.debug("indicator: %s not installed", cmd[0])
