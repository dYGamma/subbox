import pytest

from subbox import links

VLESS_REALITY = (
    "vless://00000000-0000-0000-0000-000000000000@node.example.invalid:443"
    "?security=reality&sni=www.microsoft.com&fp=chrome"
    "&pbk=aGVsbG8&sid=ab12&flow=xtls-rprx-vision&type=tcp#Main%20443"
)
VLESS_WS = (
    "vless://00000000-0000-0000-0000-000000000000@node.example.invalid:8443"
    "?security=tls&type=ws&path=%2Fws&host=cdn.example.invalid#WS%20node"
)
VLESS_GRPC = (
    "vless://00000000-0000-0000-0000-000000000000@node.example.invalid:2053"
    "?security=tls&type=grpc&serviceName=grpcsvc#GRPC"
)
TROJAN = "trojan://hunter2@node.example.invalid:443?sni=a.example.invalid#Trojan"
HY2 = "hysteria2://hunter2@node.example.invalid:36712?insecure=1#Hysteria2"
HY2_OBFS = (
    "hysteria2://hunter2@node.example.invalid:51712"
    "?obfs=salamander&obfs-password=obfspw&sni=a.example.invalid#Hy2%20obfs"
)
SS_PLAIN = "ss://aes-256-gcm:hunter2@node.example.invalid:51643#Shadowsocks"
SS_B64 = "ss://YWVzLTI1Ni1nY206aHVudGVyMg==@node.example.invalid:51643#SS%20b64"
VMESS = (
    "vmess://eyJ2IjoiMiIsInBzIjoiVm1lc3Mgbm9kZSIsImFkZCI6Im5vZGUuZXhhbXBsZS5pbnZh"
    "bGlkIiwicG9ydCI6IjQ0MyIsImlkIjoiMDAwMDAwMDAtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAw"
    "MDAwIiwiYWlkIjoiMCIsIm5ldCI6IndzIiwicGF0aCI6Ii92bWVzcyIsImhvc3QiOiJjZG4uZXhh"
    "bXBsZS5pbnZhbGlkIiwidGxzIjoidGxzIn0="
)


def test_vless_reality():
    ob = links.parse_link(VLESS_REALITY)
    assert ob["type"] == "vless"
    assert ob["server"] == "node.example.invalid"
    assert ob["server_port"] == 443
    assert ob["uuid"] == "00000000-0000-0000-0000-000000000000"
    assert ob["flow"] == "xtls-rprx-vision"
    assert ob["tls"]["enabled"] is True
    assert ob["tls"]["server_name"] == "www.microsoft.com"
    assert ob["tls"]["utls"] == {"enabled": True, "fingerprint": "chrome"}
    assert ob["tls"]["reality"] == {
        "enabled": True, "public_key": "aGVsbG8", "short_id": "ab12"}
    assert "transport" not in ob
    assert ob["tag"] == "Main 443"


def test_vless_websocket_transport():
    ob = links.parse_link(VLESS_WS)
    assert ob["transport"] == {
        "type": "ws", "path": "/ws", "headers": {"Host": "cdn.example.invalid"}}
    assert ob["tls"]["server_name"] == "node.example.invalid"


def test_vless_grpc_transport():
    ob = links.parse_link(VLESS_GRPC)
    assert ob["transport"] == {"type": "grpc", "service_name": "grpcsvc"}


def test_trojan():
    ob = links.parse_link(TROJAN)
    assert ob["type"] == "trojan"
    assert ob["password"] == "hunter2"
    assert ob["tls"]["server_name"] == "a.example.invalid"


def test_hysteria2_marks_insecure():
    ob = links.parse_link(HY2)
    assert ob["type"] == "hysteria2"
    assert ob["server_port"] == 36712
    assert ob["tls"]["insecure"] is True


def test_hysteria2_bare_ip_sni_implies_insecure():
    """Panels routinely omit insecure=1 when the SNI is the server IP itself."""
    ob = links.parse_link("hysteria2://pw@203.0.113.7:36712#IP node")
    assert ob["tls"]["insecure"] is True


def test_hysteria2_obfs():
    ob = links.parse_link(HY2_OBFS)
    assert ob["obfs"] == {"type": "salamander", "password": "obfspw"}
    assert ob["tls"].get("insecure") is not True


def test_shadowsocks_plain_and_base64_userinfo_agree():
    plain = links.parse_link(SS_PLAIN)
    b64 = links.parse_link(SS_B64)
    for ob in (plain, b64):
        assert ob["type"] == "shadowsocks"
        assert ob["method"] == "aes-256-gcm"
        assert ob["password"] == "hunter2"
        assert ob["server_port"] == 51643


def test_vmess_websocket():
    ob = links.parse_link(VMESS)
    assert ob["type"] == "vmess"
    assert ob["uuid"] == "00000000-0000-0000-0000-000000000000"
    assert ob["alter_id"] == 0
    assert ob["transport"]["type"] == "ws"
    assert ob["tls"]["server_name"] == "cdn.example.invalid"
    assert ob["tag"] == "Vmess node"


def test_tag_falls_back_when_fragment_missing():
    ob = links.parse_link("trojan://pw@node.example.invalid:443")
    assert ob["tag"] == "trojan-node.example.invalid-443"


@pytest.mark.parametrize("link", [
    "ssh://node.example.invalid",         # unsupported scheme
    "vless://",                            # no host
    "vmess://not-base64!!",               # undecodable payload
    "",
])
def test_unparseable_links_return_none_rather_than_raising(link):
    """One bad node must never abort a whole subscription sync."""
    assert links.parse_link(link) is None


def test_dedupe_tags_disambiguates_collisions():
    obs = [{"tag": "Node"}, {"tag": "Node"}, {"tag": "Other"}, {"tag": "Node"}]
    links.dedupe_tags(obs)
    assert [o["tag"] for o in obs] == ["Node", "Node #2", "Other", "Node #3"]
