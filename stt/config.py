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
    device: str = "NPU"                   # OpenVINO device
    language: str = "en"
    keyboard: str = "auto"               # auto | /dev/input/eventN
    audio_device: int | str | None = None  # sounddevice index/name; None = system default
    inject_method: str = "auto"          # auto | ydotool | paste | xdotool
    paste_threshold: int = 50            # chars: longer -> clipboard paste path
    paste_settle_ms: int = 150          # pause after Ctrl+V before restoring the clipboard
    indicator: str = "both"             # notify | beep | both | off
    trailing_space: bool = True
    min_speech_ms: int = 300
    hallucinations: list[str] = field(default_factory=list)  # extra silence artifacts to drop
    cache_dir: str = "~/.cache/lightweight-stt/ov"
    model_dir: str = str(_REPO_ROOT / "whisper-small-ov")


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

    cfg = replace(Config(), **overrides)
    return replace(cfg, cache_dir=str(Path(cfg.cache_dir).expanduser()))
