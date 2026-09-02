"""Read the app id / class of the currently focused window.

Works on wlroots compositors (Sway, Hyprland) through their IPC CLIs. GNOME has
no equivalent without a shell extension, so this returns None there and
per-application profiles simply don't kick in.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess

log = logging.getLogger("stt")


def _focused_sway() -> str | None:
    def walk(node):
        if node.get("focused"):
            return node.get("app_id") or node.get("window_properties", {}).get("class")
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            hit = walk(child)
            if hit:
                return hit
        return None

    out = _cli(["swaymsg", "-t", "get_tree"])
    if out is None:
        return None
    try:
        return walk(json.loads(out))
    except (ValueError, AttributeError):
        return None


def _focused_hyprland() -> str | None:
    out = _cli(["hyprctl", "activewindow", "-j"])
    if out is None:
        return None
    try:
        return json.loads(out).get("class") or None
    except (ValueError, AttributeError):
        return None


def _cli(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s failed: %s", cmd[0], e)
        return None
    return r.stdout if r.returncode == 0 else None


def active_app() -> str | None:
    """The focused window's app_id / class, lowercased. None if it can't be read
    (no wlroots IPC, e.g. on GNOME)."""
    if shutil.which("swaymsg"):
        app = _focused_sway()
    elif shutil.which("hyprctl"):
        app = _focused_hyprland()
    else:
        return None
    return app.lower() if app else None
