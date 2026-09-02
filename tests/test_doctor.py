import json
import shutil

import pytest

from subbox import config, doctor, generate, links, paths

NODE = links.parse_link(
    "vless://00000000-0000-0000-0000-000000000000@203.0.113.7:443"
    "?security=tls&sni=a.example.invalid#Main")


@pytest.fixture
def offline(monkeypatch):
    """Everything doctor touches, stubbed. No unit is queried, no packet sent."""
    monkeypatch.setattr(doctor.units, "available", lambda: True)
    monkeypatch.setattr(doctor.units, "is_installed", lambda unit: True)
    monkeypatch.setattr(doctor.units, "is_active", lambda unit: True)
    monkeypatch.setattr(doctor.probe, "port_listening", lambda port, **kw: True)
    monkeypatch.setattr(doctor.probe, "http_status",
                        lambda url, proxy=None, **kw: 204)
    monkeypatch.setattr(
        doctor.probe, "public_ip",
        lambda proxy=None, **kw: "203.0.113.7" if proxy else "198.51.100.4")


@pytest.fixture
def healthy(offline):
    cfg = config.load()
    cfg["subscription"]["url"] = "https://panel.example.invalid/sub/x"
    config.save(cfg)
    generate.write(generate.build([dict(NODE)], cfg))
    return cfg


def _named(checks, fragment):
    """First check whose name contains the fragment, case-insensitively."""
    return next(c for c in checks if fragment.lower() in c.name.lower())


def test_healthy_system_passes_everything(healthy):
    checks = doctor.run(healthy)
    assert doctor.worst(checks) == "pass"


def test_auto_detect_interface_true_is_a_failure(healthy):
    doc = json.loads(paths.singbox_config().read_text())
    doc["route"]["auto_detect_interface"] = True
    paths.singbox_config().write_text(json.dumps(doc))
    check = _named(doctor.run(healthy), "auto_detect_interface")
    assert check.status == "fail"
    assert "i/o timeout" in check.detail
    assert check.fix


def test_missing_domain_resolver_is_a_failure(healthy):
    doc = json.loads(paths.singbox_config().read_text())
    del doc["route"]["default_domain_resolver"]
    paths.singbox_config().write_text(json.dumps(doc))
    assert _named(doctor.run(healthy), "default_domain_resolver").status == "fail"


def test_missing_cache_directory_is_a_failure(healthy):
    shutil.rmtree(paths.cache_dir())
    check = _named(doctor.run(healthy), "cache")
    assert check.status == "fail"
    assert "refuses to start" in check.detail


def test_world_readable_config_is_a_failure(healthy):
    paths.config_file().chmod(0o644)
    check = _named(doctor.run(healthy), "permissions")
    assert check.status == "fail"
    assert "credential" in check.detail


def test_unconfigured_subscription_is_a_failure(offline):
    check = _named(doctor.run(config.load()), "subscription")
    assert check.status == "fail"
    assert "subbox setup" in check.fix


def test_proxy_blocked_but_direct_fine_names_the_exit(healthy, monkeypatch):
    monkeypatch.setattr(
        doctor.probe, "http_status",
        lambda url, proxy=None, **kw: 403 if proxy else 204)
    check = _named(doctor.run(healthy), "Reachability")
    assert check.status == "fail"
    assert "exit" in check.detail.lower()


def test_consumer_endpoint_as_reach_url_warns(healthy):
    healthy["probe"]["reach_url"] = "https://claude.ai/"
    check = _named(doctor.run(healthy), "probe endpoint")
    assert check.status == "warn"
    assert "403 to any client" in check.detail


def test_identical_exit_ips_mean_traffic_is_not_tunnelled(healthy, monkeypatch):
    monkeypatch.setattr(doctor.probe, "public_ip",
                        lambda proxy=None, **kw: "198.51.100.4")
    check = _named(doctor.run(healthy), "Exit address")
    assert check.status == "fail"


def test_units_not_installed_is_a_failure(healthy, monkeypatch):
    monkeypatch.setattr(doctor.units, "is_installed", lambda unit: False)
    assert _named(doctor.run(healthy), "Unit files").status == "fail"


def test_worst_ranks_fail_above_warn_above_pass():
    def mk(s):
        return doctor.Check("n", s, "d")

    assert doctor.worst([mk("pass"), mk("warn")]) == "warn"
    assert doctor.worst([mk("pass"), mk("warn"), mk("fail")]) == "fail"
    assert doctor.worst([mk("pass")]) == "pass"
    assert doctor.worst([]) == "pass"
