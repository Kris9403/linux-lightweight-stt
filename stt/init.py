"""Write a starter config file with the common options shown at their defaults.

    python -m stt.init            # all lines commented — behaves like no config
    python -m stt.init --detect   # also fill in device / inject_method from this machine

Refuses if the file already exists.
"""
from __future__ import annotations

import logging
import sys

from .config import DEFAULT_PATH

log = logging.getLogger("stt")

TEMPLATE = """\
# lightweight-stt config. Everything is optional — uncomment a line to change it.
# Full reference: https://github.com/Kris9403/linux-lightweight-stt#config

# --- how the hotkey behaves ---
# mode = "hybrid"              # hybrid | hold | toggle | streaming
# tap_ms = 350                 # hybrid: a press shorter than this is a toggle tap
# hotkey = "KEY_F23"           # evdev KEY_* name, or a list: ["KEY_F23", "KEY_SCROLLLOCK"]
# keyboard = "auto"            # auto, or pin one /dev/input/eventN
# mute_hotkey = ""             # KEY_* that pauses/resumes the whole listener
# cough_hotkey = ""            # KEY_* to hold to drop audio while you clear your throat

# --- per-key language / format ---
# hotkey_translate = []        # KEY_* whose output is translated to English
# [hotkey_language]
# KEY_SCROLLLOCK = "hi"        # that key dictates in Hindi
# [hotkey_format]
# KEY_SCROLLLOCK = "snake"     # snake | camel | raw — reshape that key's output

# --- model ---
# device = "NPU"               # NPU | GPU | CPU
# language = "en"              # Whisper language, or "auto" to detect per utterance
# num_beams = 1                # >1 is GPU/CPU only
# vocabulary = []              # names / jargon to bias toward (GPU/CPU only)
# hallucinations = []          # extra silence artifacts to drop

# --- audio ---
# audio_device = ""            # sounddevice index or name substring; unset = system default
# follow_default_mic = false   # streaming: reopen the mic when the system default changes
# min_speech_ms = 300
# vad_silence_ms = 700         # streaming: quiet gap that ends a phrase
# vad_threshold = 0.025        # streaming: RMS level counted as speech

# --- output ---
# inject_method = "auto"       # auto | ydotool | paste | xdotool
# paste_threshold = 50         # chars above which the clipboard path is used
# paste_settle_ms = 150
# trailing_space = true
# indicator = "both"           # notify | beep | both | off

# --- commands ---
# [commands]
# "new line" = "\\n"
# "press tab" = "<key:tab>"
# "scratch that" = "<undo>"

# --- per-application profiles (wlroots only; needs a shell extension on GNOME) ---
# [profiles.coding]
# trailing_space = false
# format = "snake"            # language | trailing_space | llm_cleanup | format | commands
# llm_cleanup = false
# [apps]
# "code" = "coding"           # focused-window app-id substring -> profile name
# "Alacritty" = "coding"

# --- post-processing ---
# llm_cleanup = false
# llm_endpoint = "http://localhost:11434/v1"
# llm_model = "llama3.2"

# --- logging / power ---
# history = true
# privacy = false              # keep transcripts out of logs, history, and llm_cleanup
# latency_stats = false
# battery_saver = ""           # "pause" to stop listening in power-saver mode

# --- paths (rarely needed) ---
# cache_dir = "~/.cache/lightweight-stt/ov"
# model_dir = "whisper-small-ov"
"""


def _detect() -> dict[str, str]:
    """Best-effort: which OpenVINO device to prefer, and which injector works.
    Anything that errors is just left out."""
    found: dict[str, str] = {}
    try:
        import openvino as ov

        devs = ov.Core().available_devices
        found["device"] = next((d for d in ("NPU", "GPU", "CPU") if d in devs), "CPU")
    except Exception as e:  # noqa: BLE001
        log.warning("could not query OpenVINO devices: %s", e)
    try:
        from .config import load
        from .inject import NoInjectorError, probe

        found["inject_method"] = probe(load()).method
    except NoInjectorError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("could not probe the injector: %s", e)
    return found


def _with_detected(text: str, found: dict[str, str]) -> str:
    """Uncomment the `# key = "..."` line for each detected value and set it, and
    add a note near the top."""
    import re

    for key, value in found.items():
        text = re.sub(rf'(?m)^# ({re.escape(key)}) = "[^"]*"',
                      rf'\1 = "{value}"', text, count=1)
    if found:
        note = "# detected here: " + ", ".join(f"{k}={v}" for k, v in found.items())
        text = text.replace("\n", "\n" + note + "\n", 1)
    return text


def run(detect: bool = False) -> int:
    if DEFAULT_PATH.exists():
        print(f"{DEFAULT_PATH} already exists — leaving it alone", file=sys.stderr)
        return 1
    text = _with_detected(TEMPLATE, _detect()) if detect else TEMPLATE
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PATH.write_text(text)
    print(f"wrote {DEFAULT_PATH}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(run(detect="--detect" in sys.argv))
