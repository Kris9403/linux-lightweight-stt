import json

from stt import appwatch
from stt.appwatch import active_app

_SWAY_TREE = {
    "nodes": [
        {"nodes": [
            {"app_id": None, "focused": False, "nodes": [
                {"app_id": "Alacritty", "focused": True, "nodes": []},
            ]},
        ]},
    ],
}


class _R:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_returns_none_without_any_wlroots_ipc(monkeypatch):
    monkeypatch.setattr(appwatch.shutil, "which", lambda _: None)
    assert active_app() is None


def test_reads_focused_app_id_from_sway(monkeypatch):
    monkeypatch.setattr(appwatch.shutil, "which", lambda b: b == "swaymsg")
    monkeypatch.setattr(appwatch.subprocess, "run",
                        lambda *a, **k: _R(json.dumps(_SWAY_TREE)))
    assert active_app() == "alacritty"           # lowercased


def test_reads_class_from_hyprland(monkeypatch):
    monkeypatch.setattr(appwatch.shutil, "which", lambda b: b == "hyprctl")
    monkeypatch.setattr(appwatch.subprocess, "run",
                        lambda *a, **k: _R(json.dumps({"class": "Code", "title": "x"})))
    assert active_app() == "code"


def test_none_when_the_cli_errors(monkeypatch):
    monkeypatch.setattr(appwatch.shutil, "which", lambda b: b == "swaymsg")
    monkeypatch.setattr(appwatch.subprocess, "run", lambda *a, **k: _R("", returncode=1))
    assert active_app() is None


def test_none_when_the_cli_is_missing(monkeypatch):
    monkeypatch.setattr(appwatch.shutil, "which", lambda b: b == "hyprctl")

    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(appwatch.subprocess, "run", boom)
    assert active_app() is None
