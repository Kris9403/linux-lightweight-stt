from pathlib import Path

from stt import status
from stt.config import Config


def _stub(monkeypatch, cfg, *, running=True, sock="/run/ydotool.sock",
          profile="balanced", groups=("render", "input"), history="3 entries"):
    monkeypatch.setattr(status, "load", lambda: cfg)
    monkeypatch.setattr(status, "_daemon_running", lambda: running)
    monkeypatch.setattr(status, "active_profile", lambda: profile)
    monkeypatch.setattr(status, "_in_group", lambda g: g in groups)
    monkeypatch.setattr(status, "_history_summary",
                        lambda privacy: "off (privacy)" if privacy else history)
    monkeypatch.setattr(status, "_ydotool_socket",
                        lambda: Path(sock) if sock else None)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "is_file", lambda self: True)


def test_snapshot_reports_the_core_rows(monkeypatch, capsys):
    _stub(monkeypatch, Config(device="NPU", language="en", mode="hybrid"))
    assert status.run() == 0
    out = capsys.readouterr().out
    assert "daemon" in out and "running" in out
    assert "device" in out and "NPU" in out
    assert "power profile" in out and "balanced" in out


def test_auto_language_and_llm_cleanup_are_shown(monkeypatch, capsys):
    _stub(monkeypatch, Config(language="auto", llm_cleanup=True,
                              llm_endpoint="http://localhost:11434/v1", llm_model="llama3.2"))
    status.run()
    out = capsys.readouterr().out
    assert "auto-detect" in out
    assert "llama3.2" in out


def test_privacy_hides_history(monkeypatch, capsys):
    _stub(monkeypatch, Config(privacy=True))
    status.run()
    assert "off (privacy)" in capsys.readouterr().out


def test_daemon_state_unknown_without_ss(monkeypatch, capsys):
    _stub(monkeypatch, Config(), running=None)
    status.run()
    assert "unknown (ss not installed)" in capsys.readouterr().out


def test_history_summary_reads_the_last_line(monkeypatch, tmp_path):
    log = tmp_path / "lightweight-stt" / "history.log"
    log.parent.mkdir(parents=True)
    log.write_text("2026-01-01T09:00:00\ten\tfirst\n2026-01-02T10:00:00\ten\tsecond\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    out = status._history_summary(privacy=False)
    assert out == "2 entries, last 2026-01-02T10:00:00"
