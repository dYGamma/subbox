import json

import pytest

from subbox import cli, config, doctor, paths

NODE_LINK = ("vless://00000000-0000-0000-0000-000000000000@203.0.113.7:443"
             "?security=tls&sni=a.example.invalid#Main")


@pytest.fixture
def configured(monkeypatch):
    cfg = config.load()
    cfg["subscription"]["url"] = "https://panel.example.invalid/sub/x"
    config.save(cfg)
    monkeypatch.setattr(cli.subscription, "links_from",
                        lambda url, insecure=False: [NODE_LINK])
    monkeypatch.setattr(cli.units, "restart", lambda unit: (0, ""))
    monkeypatch.setattr(cli.units, "available", lambda: True)
    return cfg


def test_version_flag(capsys):
    """argparse exits rather than returning; that is the contract."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "subbox" in capsys.readouterr().out


def test_sync_writes_a_config_and_restarts(configured, capsys):
    assert cli.main(["sync"]) == cli.OK
    doc = json.loads(paths.singbox_config().read_text())
    assert [o["tag"] for o in doc["outbounds"] if o["type"] == "vless"] == ["Main"]
    assert "Main" in capsys.readouterr().out


def test_sync_without_a_subscription_exits_unconfigured(capsys):
    assert cli.main(["sync"]) == cli.UNCONFIGURED
    assert "subbox setup" in capsys.readouterr().err


def test_sync_never_prints_the_subscription_url(configured, capsys):
    cli.main(["sync"])
    assert "/sub/x" not in capsys.readouterr().out


def test_sync_leaves_the_live_config_alone_on_failure(configured, monkeypatch, capsys):
    cli.main(["sync"])
    before = paths.singbox_config().read_text()
    monkeypatch.setattr(cli.generate, "check", lambda path: (False, "rejected"))
    assert cli.main(["sync"]) == cli.PROBLEM
    assert paths.singbox_config().read_text() == before
    assert "rejected" in capsys.readouterr().err


def test_pac_regenerates_the_file(configured):
    assert cli.main(["pac"]) == cli.OK
    assert "FindProxyForURL" in paths.pac_file().read_text()


def test_status_json_is_machine_readable(configured, monkeypatch, capsys):
    monkeypatch.setattr(cli.probe, "port_listening", lambda port, **kw: True)
    monkeypatch.setattr(cli.units, "is_active", lambda unit: True)
    assert cli.main(["status", "--json"]) == cli.OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["proxy_port"] == configured["proxy"]["listen_port"]
    assert payload["proxy_listening"] is True


def test_status_quiet_prints_nothing(configured, monkeypatch, capsys):
    monkeypatch.setattr(cli.probe, "port_listening", lambda port, **kw: True)
    monkeypatch.setattr(cli.units, "is_active", lambda unit: True)
    assert cli.main(["status", "--quiet"]) == cli.OK
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_status_exit_codes_are_a_contract(configured, monkeypatch):
    """The SessionStart hook branches on these; they are API."""
    monkeypatch.setattr(cli.probe, "port_listening", lambda port, **kw: False)
    assert cli.main(["status", "--quiet"]) == cli.PROBLEM


def test_status_unconfigured_exit_code():
    assert cli.main(["status", "--quiet"]) == cli.UNCONFIGURED


def test_doctor_reports_failures_with_a_nonzero_code(monkeypatch, capsys):
    monkeypatch.setattr(cli.doctor, "run", lambda cfg: [
        doctor.Check("Something", doctor.FAIL, "broken", "fix it")])
    assert cli.main(["doctor"]) == cli.PROBLEM
    out = capsys.readouterr().out
    assert "broken" in out
    assert "fix it" in out


def test_doctor_passes_cleanly(monkeypatch):
    monkeypatch.setattr(cli.doctor, "run", lambda cfg: [
        doctor.Check("Something", doctor.PASS, "fine")])
    assert cli.main(["doctor"]) == cli.OK


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit) as exc:
        cli.main(["nonsense"])
    assert exc.value.code != 0
