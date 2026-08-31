import logging
from pathlib import Path

from stt.config import load


def test_load_without_file_returns_defaults():
    cfg = load(path=Path("/nonexistent/config.toml"))
    assert cfg.mode == "hybrid"
    assert cfg.tap_ms == 350
    assert cfg.hotkey == "KEY_F23"
    assert cfg.device == "NPU"
    assert cfg.language == "en"
    assert cfg.keyboard == "auto"
    assert cfg.inject_method == "auto"
    assert cfg.paste_threshold == 50
    assert cfg.indicator == "both"
    assert cfg.trailing_space is True
    assert cfg.min_speech_ms == 300
    assert cfg.audio_device is None
    assert cfg.paste_settle_ms == 150
    assert cfg.hallucinations == []


def test_partial_file_merges_over_defaults(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('mode = "toggle"\ntrailing_space = false\n')

    cfg = load(path=cfg_file)

    assert cfg.mode == "toggle"          # from file
    assert cfg.trailing_space is False   # from file
    assert cfg.hotkey == "KEY_F23"       # still default
    assert cfg.device == "NPU"           # still default


def test_extra_hallucinations_load_from_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('hallucinations = ["Bye.", "fan hum"]\n')
    assert load(path=f).hallucinations == ["Bye.", "fan hum"]


def test_hotkey_accepts_a_list(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('hotkey = ["KEY_F23", "KEY_SCROLLLOCK"]\n')
    assert load(path=f).hotkey == ["KEY_F23", "KEY_SCROLLLOCK"]


def test_per_hotkey_language_loads(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('hotkey = "KEY_F23"\n[hotkey_language]\nKEY_SCROLLLOCK = "hi"\n')
    cfg = load(path=f)
    assert cfg.hotkey_language == {"KEY_SCROLLLOCK": "hi"}
    assert cfg.language == "en"          # default untouched


def test_hotkey_language_defaults_empty():
    assert load(path=Path("/nonexistent/c.toml")).hotkey_language == {}


def test_hotkey_translate_loads(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('hotkey_translate = ["KEY_SCROLLLOCK"]\n')
    assert load(path=f).hotkey_translate == ["KEY_SCROLLLOCK"]


def test_vocabulary_loads(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('vocabulary = ["Kubernetes", "Anthropic"]\n')
    assert load(path=f).vocabulary == ["Kubernetes", "Anthropic"]


def test_commands_table_loads(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[commands]\n"new line" = "\\n"\n"scratch that" = "<undo>"\n')
    assert load(path=f).commands == {"new line": "\n", "scratch that": "<undo>"}


def test_num_beams_defaults_to_one_and_loads(tmp_path):
    assert load(path=Path("/nonexistent/c.toml")).num_beams == 1
    f = tmp_path / "c.toml"
    f.write_text("num_beams = 5\n")
    assert load(path=f).num_beams == 5


def test_audio_device_accepts_index_and_name(tmp_path):
    idx = tmp_path / "i.toml"
    idx.write_text("audio_device = 7\n")
    assert load(path=idx).audio_device == 7

    name = tmp_path / "n.toml"
    name.write_text('audio_device = "alsa_input.pci-0000_80_1f.3.analog-stereo"\n')
    assert load(path=name).audio_device == "alsa_input.pci-0000_80_1f.3.analog-stereo"


def test_unknown_key_is_ignored_with_warning(tmp_path, caplog):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('mode = "hold"\nbogus_key = 123\n')

    with caplog.at_level(logging.WARNING):
        cfg = load(path=cfg_file)

    assert cfg.mode == "hold"
    assert not hasattr(cfg, "bogus_key")
    assert any("bogus_key" in r.message for r in caplog.records)


def test_cache_dir_is_expanded(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('cache_dir = "~/somewhere/ov"\n')

    cfg = load(path=cfg_file)

    assert cfg.cache_dir == str(Path.home() / "somewhere" / "ov")


def test_default_cache_dir_is_expanded():
    cfg = load(path=Path("/nonexistent/config.toml"))
    assert "~" not in cfg.cache_dir
    assert cfg.cache_dir.startswith(str(Path.home()))
