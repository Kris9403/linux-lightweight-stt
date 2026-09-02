import tomllib
from dataclasses import fields

from stt import init
from stt.config import Config, load


def test_writes_the_template_when_none_exists(tmp_path, monkeypatch, capsys):
    dest = tmp_path / "config.toml"
    monkeypatch.setattr(init, "DEFAULT_PATH", dest)
    assert init.run() == 0
    assert dest.is_file()
    assert "wrote" in capsys.readouterr().out


def test_refuses_to_overwrite_an_existing_file(tmp_path, monkeypatch, capsys):
    dest = tmp_path / "config.toml"
    dest.write_text("mode = 'toggle'\n")
    monkeypatch.setattr(init, "DEFAULT_PATH", dest)
    assert init.run() == 1
    assert dest.read_text() == "mode = 'toggle'\n"          # untouched
    assert "already exists" in capsys.readouterr().err


def test_template_names_every_config_key():
    for f in fields(Config):
        assert f.name in init.TEMPLATE, f"{f.name} missing from the starter template"


def test_written_template_is_valid_toml_and_loads_as_defaults(tmp_path, monkeypatch, caplog):
    dest = tmp_path / "config.toml"
    monkeypatch.setattr(init, "DEFAULT_PATH", dest)
    init.run()
    assert tomllib.loads(dest.read_text()) == {}            # all commented
    with caplog.at_level("WARNING"):
        cfg = load(path=dest)
    assert cfg.mode == "hybrid" and cfg.device == "NPU"     # untouched defaults
    assert caplog.records == []


def test_with_detected_uncomments_and_sets_the_detected_keys():
    out = init._with_detected(init.TEMPLATE, {"device": "GPU", "inject_method": "ydotool"})
    parsed = tomllib.loads(out)
    assert parsed == {"device": "GPU", "inject_method": "ydotool"}
    assert "# detected here: device=GPU" in out


def test_detect_flag_writes_the_detected_values(tmp_path, monkeypatch):
    dest = tmp_path / "config.toml"
    monkeypatch.setattr(init, "DEFAULT_PATH", dest)
    monkeypatch.setattr(init, "_detect", lambda: {"device": "CPU"})
    assert init.run(detect=True) == 0
    assert tomllib.loads(dest.read_text()) == {"device": "CPU"}


def test_detect_with_nothing_found_falls_back_to_the_plain_template(tmp_path, monkeypatch):
    dest = tmp_path / "config.toml"
    monkeypatch.setattr(init, "DEFAULT_PATH", dest)
    monkeypatch.setattr(init, "_detect", lambda: {})
    init.run(detect=True)
    assert dest.read_text() == init.TEMPLATE
