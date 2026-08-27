"""Check the things that actually break lightweight-stt on a fresh machine.

    python -m stt.doctor

Each line is a check; failures print the exact command to fix them. Exit code
is non-zero if any non-optional check failed.
"""
from __future__ import annotations

import grp
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import load
from .inject import _ydotool_socket


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str | None = None
    optional: bool = False


def _in_group(name: str) -> bool:
    try:
        gids = set(os.getgroups())
        return grp.getgrnam(name).gr_gid in gids or name in {
            grp.getgrgid(g).gr_name for g in gids
        }
    except KeyError:
        return False


def check_input_group() -> Check:
    ok = _in_group("input")
    return Check("member of 'input' group", ok,
                 fix=None if ok else "sudo usermod -aG input $USER   (then log out and back in)")


def check_render_group() -> Check:
    ok = _in_group("render")
    return Check("member of 'render' group (NPU access)", ok,
                 fix=None if ok else "sudo usermod -aG render $USER   (then log out and back in)")


def check_npu_node() -> Check:
    p = Path("/dev/accel/accel0")
    if not p.exists():
        return Check("Intel NPU device node", False, "/dev/accel/accel0 missing",
                     "install the intel-npu-level-zero driver for your kernel")
    return Check("Intel NPU device node", os.access(p, os.R_OK | os.W_OK),
                 "" if os.access(p, os.R_OK | os.W_OK) else "present but not accessible",
                 None if os.access(p, os.R_OK | os.W_OK) else "sudo usermod -aG render $USER")


def check_openvino_npu() -> Check:
    try:
        import openvino as ov

        devs = ov.Core().available_devices
    except Exception as e:  # noqa: BLE001
        return Check("OpenVINO runtime", False, str(e)[:80], "pip install -r requirements.txt")
    ok = "NPU" in devs
    return Check("OpenVINO sees the NPU", ok, f"devices: {', '.join(devs)}",
                 None if ok else "NPU driver not loaded — reboot after installing it")


def check_model(cfg) -> Check:
    d = Path(cfg.model_dir)
    ok = (d / "openvino_encoder_model.xml").is_file() and (d / "openvino_decoder_model.xml").is_file()
    return Check("Whisper model exported", ok, str(d),
                 None if ok else "./convert.sh")


def check_ydotool() -> Check:
    if not shutil.which("ydotool"):
        return Check("ydotool installed", False, fix="sudo apt install ydotool")
    return Check("ydotool installed", True)


def check_ydotoold() -> Check:
    sock = _ydotool_socket()
    ok = sock is not None and sock.exists()
    return Check("ydotoold running", ok, str(sock) if sock else "no socket path",
                 None if ok else "systemctl --user enable --now ydotool   (or run setup.sh)")


def check_uinput() -> Check:
    ok = os.access("/dev/uinput", os.W_OK)
    return Check("/dev/uinput writable", ok,
                 fix=None if ok else "run setup.sh (installs the uaccess udev rule) then re-plug or reboot")


def check_clipboard() -> Check:
    ok = bool(shutil.which("wl-copy") and shutil.which("wl-paste"))
    return Check("wl-clipboard (paste path)", ok, optional=True,
                 fix=None if ok else "sudo apt install wl-clipboard")


def check_mic(cfg) -> Check:
    name = "microphone captures audio"
    try:
        import time

        import numpy as np
        import sounddevice as sd

        chunks: list = []
        # time-boxed: sd.rec()+wait() blocks forever if the device delivers nothing
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                            device=cfg.audio_device,
                            callback=lambda d, *_: chunks.append(d.copy())):
            time.sleep(0.6)
    except Exception as e:  # noqa: BLE001
        return Check(name, False, str(e)[:80],
                     "check `audio_device` in config, or `wpctl status` for the right source")
    if not chunks:
        return Check(name, False, "device opened but delivered no audio",
                     "restart the service; if it persists check `wpctl status`")
    peak = float(np.abs(np.concatenate(chunks)).max())
    if peak < 1e-4:
        return Check(name, False, f"silent (peak {peak:.4f})",
                     "unmute: wpctl set-mute @DEFAULT_SOURCE@ 0 ; wpctl set-volume @DEFAULT_SOURCE@ 0.3")
    return Check(name, True, f"peak {peak:.3f}")


def check_notify() -> Check:
    ok = bool(shutil.which("notify-send"))
    return Check("notify-send (indicator)", ok, optional=True,
                 fix=None if ok else "sudo apt install libnotify-bin")


CHECKS = [
    check_input_group, check_render_group, check_npu_node, check_openvino_npu,
    check_ydotool, check_ydotoold, check_uinput, check_clipboard, check_notify,
]
CHECKS_WITH_CFG = [check_model, check_mic]


def run() -> int:
    cfg = load()
    results = [c() for c in CHECKS] + [c(cfg) for c in CHECKS_WITH_CFG]

    width = max(len(r.name) for r in results)
    fixes = []
    for r in results:
        mark = "\033[32m✓\033[0m" if r.ok else ("\033[33m!\033[0m" if r.optional else "\033[31m✗\033[0m")
        line = f"  {mark}  {r.name.ljust(width)}"
        if r.detail:
            line += f"   {r.detail}"
        print(line)
        if not r.ok and r.fix:
            fixes.append((r.name, r.fix))

    if fixes:
        print("\nto fix:")
        for name, fix in fixes:
            print(f"  # {name}\n  {fix}\n")

    hard_fail = any(not r.ok and not r.optional for r in results)
    print("not ready — see above" if hard_fail else "ready")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(run())
