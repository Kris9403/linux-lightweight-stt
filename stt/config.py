"""Load ~/.config/lightweight-stt/config.toml over built-in defaults."""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".config" / "lightweight-stt" / "config.toml"
_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    mode: str = "hybrid"                  # hybrid | hold | toggle | streaming
    tap_ms: int = 350                    # hybrid: press shorter than this = a toggle tap
    hotkey: str | list[str] = "KEY_F23"  # evdev KEY_* name, or a list of them
    hotkey_language: dict[str, str] = field(default_factory=dict)  # KEY_* -> language
    hotkey_translate: list[str] = field(default_factory=list)      # KEY_* that translate to English
    hotkey_format: dict[str, str] = field(default_factory=dict)    # KEY_* -> snake | camel | raw
    mute_hotkey: str = ""                # KEY_* that pauses/resumes the listener ("" = off)
    cough_hotkey: str = ""              # KEY_* to hold to drop audio while you cough ("" = off)
    device: str = "NPU"                   # OpenVINO device
    language: str = "en"                  # default for keys without an override
    keyboard: str = "auto"               # auto | /dev/input/eventN
    audio_device: int | str | None = None  # sounddevice index/name; None = system default
    inject_method: str = "auto"          # auto | ydotool | paste | xdotool
    paste_threshold: int = 50            # chars: longer -> clipboard paste path
    paste_settle_ms: int = 150          # pause after Ctrl+V before restoring the clipboard
    indicator: str = "both"             # notify | beep | both | off
    trailing_space: bool = True
    min_speech_ms: int = 300
    vad_silence_ms: int = 700           # streaming: quiet gap that ends a segment
    vad_threshold: float = 0.025        # streaming: RMS level counted as speech
    history: bool = True                 # append each insertion to a history file
    privacy: bool = False               # keep transcripts out of the logs and history
    latency_stats: bool = False         # log transcribe time per utterance + a summary on exit
    battery_saver: str = ""             # "pause" -> stop listening while the power profile is power-saver
    hallucinations: list[str] = field(default_factory=list)  # extra silence artifacts to drop
    vocabulary: list[str] = field(default_factory=list)      # names/jargon hints (GPU/CPU only)
    commands: dict[str, str] = field(default_factory=dict)   # spoken phrase -> action
    profiles: dict[str, dict] = field(default_factory=dict)  # name -> overrides (language/trailing_space/llm_cleanup/format/commands)
    apps: dict[str, str] = field(default_factory=dict)       # focused-window app-id substring -> profile name
    llm_cleanup: bool = False            # post-process transcripts through an LLM
    llm_endpoint: str = "http://localhost:11434/v1"   # any OpenAI-compatible server
    llm_model: str = "llama3.2"
    num_beams: int = 1                   # beam search width; >1 is GPU/CPU only
    cache_dir: str = "~/.cache/lightweight-stt/ov"
    model_dir: str = str(_REPO_ROOT / "whisper-small-ov")


_ENUMS = {
    "mode": {"hybrid", "hold", "toggle", "streaming"},
    "device": {"NPU", "GPU", "CPU"},
    "inject_method": {"auto", "ydotool", "paste", "xdotool"},
    "indicator": {"notify", "beep", "both", "off"},
    "battery_saver": {"", "pause"},
}
_POSITIVE = ("tap_ms", "paste_threshold", "paste_settle_ms", "min_speech_ms",
             "vad_silence_ms", "num_beams", "vad_threshold")
_FORMATS = {"snake", "camel", "raw"}
_PROFILE_KEYS = {"language", "trailing_space", "llm_cleanup", "format", "commands"}


def _clean_profiles(profiles: dict) -> dict:
    out: dict = {}
    for name, prof in profiles.items():
        if not isinstance(prof, dict):
            log.warning("config profiles.%s is not a table — ignoring", name)
            continue
        kept = {}
        for key, value in prof.items():
            if key not in _PROFILE_KEYS:
                log.warning("config profiles.%s.%s is not overridable per app — ignoring "
                            "(allowed: %s)", name, key, sorted(_PROFILE_KEYS))
            elif key == "format" and value not in _FORMATS:
                log.warning("config profiles.%s.format=%r is not one of %s — ignoring",
                            name, value, sorted(_FORMATS))
            else:
                kept[key] = value
        out[name] = kept
    return out


def _validate(cfg: Config) -> Config:
    """Replace out-of-range enum/number values with the default, warning once
    each — so one typo in the TOML doesn't surface as odd behaviour later."""
    default = Config()
    fixed: dict = {}
    for key, allowed in _ENUMS.items():
        if getattr(cfg, key) not in allowed:
            fixed[key] = getattr(default, key)
            log.warning("config %s=%r is not one of %s — using %r",
                        key, getattr(cfg, key), sorted(allowed), fixed[key])
    for key in _POSITIVE:
        v = getattr(cfg, key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            fixed[key] = getattr(default, key)
            log.warning("config %s=%r must be a positive number — using %r",
                        key, v, fixed[key])
    bad = {k: v for k, v in cfg.hotkey_format.items() if v not in _FORMATS}
    if bad:
        fixed["hotkey_format"] = {k: v for k, v in cfg.hotkey_format.items() if v in _FORMATS}
        log.warning("config hotkey_format has unknown modes %s — dropping them (use %s)",
                    bad, sorted(_FORMATS))
    if cfg.profiles:
        clean = _clean_profiles(cfg.profiles)
        if clean != cfg.profiles:
            fixed["profiles"] = clean
    profiles = fixed.get("profiles", cfg.profiles)
    good_apps = {a: p for a, p in cfg.apps.items() if p in profiles}
    if good_apps != cfg.apps:
        fixed["apps"] = good_apps
        log.warning("config apps points at profiles that don't exist — dropping %s",
                    {a: p for a, p in cfg.apps.items() if a not in good_apps})
    return replace(cfg, **fixed) if fixed else cfg


def load(path: Path | None = None) -> Config:
    path = path or DEFAULT_PATH

    overrides: dict = {}
    if path.is_file():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        known = {f.name for f in fields(Config)}
        for key, value in raw.items():
            if key in known:
                overrides[key] = value
            else:
                log.warning("ignoring unknown config key: %s", key)

    cfg = _validate(replace(Config(), **overrides))
    return replace(cfg, cache_dir=str(Path(cfg.cache_dir).expanduser()))
