"""Write a starter config file with the common options shown at their defaults.

    python -m stt.init

Every line is commented out, so a fresh run behaves exactly like having no
config at all — uncomment what you want to change. Refuses if the file already
exists.
"""
from __future__ import annotations

import sys

from .config import DEFAULT_PATH

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


def run() -> int:
    if DEFAULT_PATH.exists():
        print(f"{DEFAULT_PATH} already exists — leaving it alone", file=sys.stderr)
        return 1
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PATH.write_text(TEMPLATE)
    print(f"wrote {DEFAULT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
