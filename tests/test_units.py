import subprocess

import pytest

from subbox import units


@pytest.fixture
def fake_systemctl(monkeypatch):
    calls: list[list[str]] = []
    responses: dict[tuple[str, ...], tuple[int, str]] = {}

    def run(cmd, capture_output, text, timeout, check):
        calls.append(cmd)
        key = tuple(cmd[2:])
        code, out = responses.get(key, (0, ""))
        return subprocess.CompletedProcess(cmd, code, out, "")

    monkeypatch.setattr(units.subprocess, "run", run)
    monkeypatch.setattr(units.shutil, "which", lambda name: "/usr/bin/systemctl")
    return calls, responses


def test_unit_names_never_collide_with_the_predecessor_stack():
    """sing-box.service and ai-pac.service belong to someone else's install."""
    assert units.PROXY_UNIT == "subbox.service"
    assert units.PAC_UNIT == "subbox-pac.service"


def test_every_call_is_user_scoped(fake_systemctl):
    calls, _ = fake_systemctl
    units.restart(units.PROXY_UNIT)
    assert calls[0][:2] == ["systemctl", "--user"]


def test_is_active_reads_the_exit_code(fake_systemctl):
    calls, responses = fake_systemctl
    responses[("is-active", units.PROXY_UNIT)] = (0, "active\n")
    assert units.is_active(units.PROXY_UNIT) is True
    responses[("is-active", units.PROXY_UNIT)] = (3, "inactive\n")
    assert units.is_active(units.PROXY_UNIT) is False


def test_state_reports_the_word(fake_systemctl):
    _, responses = fake_systemctl
    responses[("is-active", units.PAC_UNIT)] = (3, "failed\n")
    assert units.state(units.PAC_UNIT) == "failed"


def test_main_pid_normalises_zero_to_a_dash(fake_systemctl):
    _, responses = fake_systemctl
    key = ("show", units.PROXY_UNIT, "--property=MainPID", "--value")
    responses[key] = (0, "0\n")
    assert units.main_pid(units.PROXY_UNIT) == "-"
    responses[key] = (0, "4321\n")
    assert units.main_pid(units.PROXY_UNIT) == "4321"


def test_is_installed_checks_unit_files(fake_systemctl):
    _, responses = fake_systemctl
    key = ("list-unit-files", units.PROXY_UNIT)
    responses[key] = (0, "UNIT FILE      STATE\nsubbox.service enabled\n")
    assert units.is_installed(units.PROXY_UNIT) is True
    responses[key] = (1, "0 unit files listed.\n")
    assert units.is_installed(units.PROXY_UNIT) is False


def test_missing_systemctl_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(units.shutil, "which", lambda name: None)
    assert units.available() is False
    code, out = units.start(units.PROXY_UNIT)
    assert code != 0
    assert "systemctl" in out


def test_timeout_is_reported_not_raised(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=1)

    monkeypatch.setattr(units.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(units.subprocess, "run", boom)
    code, out = units.restart(units.PROXY_UNIT)
    assert code == 124
    assert "timed out" in out
