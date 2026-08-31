"""A one-shot snapshot of how lightweight-stt is set up and whether its pieces
are reachable.

    python -m stt.status

Reads the config and the environment only — it never touches the NPU or the
running daemon, so it's safe to run any time.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import load
from .doctor import _in_group
from .inject import _ydotool_socket
from .power import active_profile


def _daemon_running() -> bool | None:
    """True/False from `ss`, or None when `ss` isn't available."""
    if not shutil.which("ss"):
        return None
    try:
        out = subprocess.run(["ss", "-xa"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return "@lightweight-stt" in out.stdout


def _history_summary(privacy: bool) -> str:
    if privacy:
        return "off (privacy)"
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    p = Path(base) / "lightweight-stt" / "history.log"
    if not p.is_file():
        return "nothing yet"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return "empty"
    return f"{len(lines)} entries, last {lines[-1].split(chr(9))[0]}"


def run() -> int:
    cfg = load()
    sock = _ydotool_socket()
    running = _daemon_running()
    model_ok = Path(cfg.model_dir, "openvino_encoder_model.xml").is_file()

    rows = [
        ("daemon", {True: "running", False: "not running",
                    None: "unknown (ss not installed)"}[running]),
        ("mode", cfg.mode),
        ("hotkey", str(cfg.hotkey)),
        ("device", cfg.device),
        ("language", f"{cfg.language} (auto-detect)" if cfg.language == "auto" else cfg.language),
        ("model", cfg.model_dir if model_ok else f"{cfg.model_dir}  (not exported — ./convert.sh)"),
        ("groups", ", ".join(g for g in ("render", "input") if _in_group(g)) or "none (run setup.sh)"),
        ("ydotoold", f"up ({sock})" if sock and sock.exists()
         else "down (systemctl --user start ydotool)"),
        ("power profile", active_profile() or "unknown (no power-profiles-daemon)"),
        ("battery_saver", cfg.battery_saver or "off"),
        ("llm cleanup", f"{cfg.llm_endpoint} ({cfg.llm_model})" if cfg.llm_cleanup else "off"),
        ("latency stats", "on" if cfg.latency_stats else "off"),
        ("history", _history_summary(cfg.privacy)),
    ]

    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        print(f"  {key.ljust(width)}   {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
