import json
import shutil

import pytest

from subbox import config, generate, links, paths

NODES_RAW = [
    "vless://00000000-0000-0000-0000-000000000000@203.0.113.7:443"
    "?security=tls&sni=a.example.invalid#Main",
    "hysteria2://pw@203.0.113.7:36712?insecure=1#Hy2",
    "trojan://pw@b.example.invalid:443#Trojan",
]


@pytest.fixture
def nodes():
    parsed = [links.parse_link(link) for link in NODES_RAW]
    links.dedupe_tags(parsed)
    return parsed


def test_auto_detect_interface_is_false(nodes):
    """True makes sing-box bind its dials to whatever TUN is up, which
    black-holes them: 'dial tcp: i/o timeout' while nc to the same port works."""
    doc = generate.build(nodes, config.DEFAULTS)
    assert doc["route"]["auto_detect_interface"] is False


def test_default_domain_resolver_is_local(nodes):
    """Resolving node hostnames must not depend on the tunnel being up."""
    doc = generate.build(nodes, config.DEFAULTS)
    assert doc["route"]["default_domain_resolver"] == {"server": "dns-local"}


def test_cache_directory_is_created(nodes):
    """sing-box 1.13 refuses to start if the cache_file directory is missing."""
    generate.build(nodes, config.DEFAULTS)
    assert paths.cache_dir().is_dir()


def test_inbound_matches_configured_address_and_port(nodes):
    cfg = config.load()
    cfg["proxy"]["listen_addr"] = "127.0.0.1"
    cfg["proxy"]["listen_port"] = 11080
    doc = generate.build(nodes, cfg)
    inbound = doc["inbounds"][0]
    assert inbound["type"] == "mixed"
    assert inbound["listen"] == "127.0.0.1"
    assert inbound["listen_port"] == 11080


def test_clash_api_is_bound_to_loopback_with_a_secret(nodes):
    cfg = config.load()
    cfg["proxy"]["clash_port"] = 19090
    doc = generate.build(nodes, cfg)
    api = doc["experimental"]["clash_api"]
    assert api["external_controller"] == "127.0.0.1:19090"
    assert api["secret"] == config.clash_secret()
    assert api["secret"]


def test_selector_and_urltest_reference_every_node(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    by_tag = {o["tag"]: o for o in doc["outbounds"]}
    tags = [n["tag"] for n in nodes]
    assert by_tag[generate.SELECTOR_TAG]["outbounds"] == [generate.URLTEST_TAG] + tags
    assert by_tag[generate.SELECTOR_TAG]["default"] == generate.URLTEST_TAG
    assert by_tag[generate.URLTEST_TAG]["outbounds"] == tags
    assert by_tag[generate.URLTEST_TAG]["url"] == config.DEFAULTS["probe"]["latency_url"]


def test_server_ips_route_direct_to_avoid_a_loop(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    direct_cidrs = [
        cidr
        for rule in doc["route"]["rules"]
        for cidr in rule.get("ip_cidr", [])
        if rule.get("outbound") == "direct"
    ]
    assert "203.0.113.7/32" in direct_cidrs


def test_ipv6_server_gets_the_right_prefix_length():
    """A hardcoded /32 would silently mis-route an IPv6 node's own address."""
    node = links.parse_link("trojan://pw@[2001:db8::1]:443#v6")
    doc = generate.build([node], config.DEFAULTS)
    direct_cidrs = [
        cidr
        for rule in doc["route"]["rules"]
        for cidr in rule.get("ip_cidr", [])
        if rule.get("outbound") == "direct"
    ]
    assert "2001:db8::1/128" in direct_cidrs


def test_private_ranges_route_direct(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    assert any(r.get("ip_is_private") and r.get("outbound") == "direct"
               for r in doc["route"]["rules"])


def test_build_rejects_an_empty_node_list():
    with pytest.raises(generate.GenerateError):
        generate.build([], config.DEFAULTS)


def test_write_creates_the_file_and_no_backup_the_first_time(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    out = generate.write(doc)
    assert json.loads(out.read_text())["route"]["auto_detect_interface"] is False
    assert list(out.parent.glob("sing-box.json.bak-*")) == []


def test_write_backs_up_the_previous_config(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    generate.write(doc)
    generate.write(doc)
    assert len(list(paths.config_dir().glob("sing-box.json.bak-*"))) == 1


def test_write_prunes_old_backups(nodes, monkeypatch):
    doc = generate.build(nodes, config.DEFAULTS)
    stamps = iter([f"2026010{i}-000000" for i in range(1, 9)])
    monkeypatch.setattr(generate, "_stamp", lambda: next(stamps))
    for _ in range(8):
        generate.write(doc, keep=3)
    assert len(list(paths.config_dir().glob("sing-box.json.bak-*"))) == 3


def test_write_leaves_the_live_config_alone_when_validation_fails(nodes, monkeypatch):
    """A rejected config must never replace a working one."""
    good = generate.build(nodes, config.DEFAULTS)
    generate.write(good)
    original = paths.singbox_config().read_text()

    monkeypatch.setattr(generate, "check", lambda path: (False, "bad config"))
    with pytest.raises(generate.GenerateError):
        generate.write(good)

    assert paths.singbox_config().read_text() == original


def test_no_temp_file_survives_a_successful_write(nodes):
    generate.write(generate.build(nodes, config.DEFAULTS))
    assert list(paths.config_dir().glob("*.new")) == []


@pytest.mark.skipif(shutil.which("sing-box") is None,
                    reason="sing-box binary not installed")
def test_generated_config_is_accepted_by_sing_box(nodes):
    doc = generate.build(nodes, config.DEFAULTS)
    out = generate.write(doc)
    ok, message = generate.check(out)
    assert ok, message
