from stt import doctor
from stt.doctor import Check, check_input_group, check_ydotool, run


def test_check_reports_fix_when_group_missing(monkeypatch):
    monkeypatch.setattr(doctor, "_in_group", lambda name: False)
    c = check_input_group()
    assert c.ok is False
    assert "usermod -aG input" in c.fix


def test_check_has_no_fix_when_group_present(monkeypatch):
    monkeypatch.setattr(doctor, "_in_group", lambda name: True)
    c = check_input_group()
    assert c.ok is True and c.fix is None


def test_check_ydotool_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _b: None)
    assert check_ydotool().ok is False


def test_run_exit_code_and_output(monkeypatch, capsys):
    passing = [Check("a", True), Check("b", True, optional=True)]
    monkeypatch.setattr(doctor, "CHECKS", [lambda: passing[0], lambda: passing[1]])
    monkeypatch.setattr(doctor, "CHECKS_WITH_CFG", [])
    monkeypatch.setattr(doctor, "load", lambda: object())
    assert run() == 0
    assert "ready" in capsys.readouterr().out


def test_run_fails_hard_on_non_optional_failure(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "CHECKS", [lambda: Check("x", False, fix="do the thing")])
    monkeypatch.setattr(doctor, "CHECKS_WITH_CFG", [])
    monkeypatch.setattr(doctor, "load", lambda: object())
    assert run() == 1
    out = capsys.readouterr().out
    assert "to fix:" in out and "do the thing" in out


def test_run_tolerates_optional_failure(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [lambda: Check("opt", False, optional=True)])
    monkeypatch.setattr(doctor, "CHECKS_WITH_CFG", [])
    monkeypatch.setattr(doctor, "load", lambda: object())
    assert run() == 0
