import logging
from pathlib import Path

from stt.config import load


def test_load_without_file_returns_defaults():
    cfg = load(path=Path("/nonexistent/config.toml"))
    assert cfg.mode == "hold"
    assert cfg.hotkey == "KEY_F23"
    assert cfg.device == "NPU"
    assert cfg.language == "en"
    assert cfg.keyboard == "auto"
    assert cfg.inject_method == "auto"
    assert cfg.paste_threshold == 50
    assert cfg.indicator == "both"
    assert cfg.trailing_space is True
    assert cfg.min_speech_ms == 300


def test_partial_file_merges_over_defaults(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('mode = "toggle"\ntrailing_space = false\n')

    cfg = load(path=cfg_file)

    assert cfg.mode == "toggle"          # from file
    assert cfg.trailing_space is False   # from file
    assert cfg.hotkey == "KEY_F23"       # still default
    assert cfg.device == "NPU"           # still default


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
