"""Read the active power profile from power-profiles-daemon.

Used by the `battery_saver` option to pause dictation while the laptop is in
`power-saver` mode. Returns None when `powerprofilesctl` isn't on the system, so
callers can treat "unknown" as "nothing to do".
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("stt")


def active_profile() -> str | None:
    """'performance' | 'balanced' | 'power-saver', or None if unavailable."""
    if not shutil.which("powerprofilesctl"):
        return None
    try:
        out = subprocess.run(["powerprofilesctl", "get"], capture_output=True,
                             text=True, timeout=2)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("could not read power profile: %s", e)
        return None
    return out.stdout.strip() or None


def on_power_saver() -> bool:
    return active_profile() == "power-saver"
