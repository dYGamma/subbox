"""Share link to sing-box outbound.

Deliberately free of I/O and configuration: a string goes in, a dict comes
out. That purity is what makes this module testable against the dialects
real panels emit, which is where breakage comes from.
"""
from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def b64decode_loose(data: str) -> str:
    """Decode base64 that may be URL-safe and may be missing its padding."""
    data = "".join(data.split()).replace("-", "+").replace("_", "/")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data).decode("utf-8", "replace")


def _is_ipv4(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(
        p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _tls_block(q: dict, default_sni: str) -> dict:
    sni = q.get("sni", [q.get("peer", [default_sni])[0]])[0] or default_sni
    tls: dict[str, Any] = {"enabled": True, "server_name": sni}
    if q.get("allowInsecure", ["0"])[0] in ("1", "true"):
        tls["insecure"] = True
    if alpn := q.get("alpn", [""])[0]:
        tls["alpn"] = alpn.split(",")
    if fp := q.get("fp", [""])[0]:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    if q.get("security", [""])[0] == "reality":
        tls["reality"] = {
            "enabled": True,
            "public_key": q.get("pbk", [""])[0],
            "short_id": q.get("sid", [""])[0],
        }
    return tls


def _transport_block(q: dict) -> dict | None:
    net = q.get("type", ["tcp"])[0]
    if net in ("tcp", "raw", ""):
        return None
    if net == "ws":
        t: dict[str, Any] = {"type": "ws", "path": q.get("path", ["/"])[0]}
        if host := q.get("host", [""])[0]:
            t["headers"] = {"Host": host}
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": q.get("serviceName", [""])[0]}
    if net in ("http", "h2"):
        t = {"type": "http", "path": q.get("path", ["/"])[0]}
        if host := q.get("host", [""])[0]:
            t["host"] = host.split(",")
        return t
    if net == "httpupgrade":
        return {
            "type": "httpupgrade",
            "path": q.get("path", ["/"])[0],
            "host": q.get("host", [""])[0],
        }
    return None


def _require_host(u) -> str:
    if not u.hostname:
        raise ValueError("link has no host")
    return u.hostname


def parse_vless(link: str) -> dict:
    u = urlparse(link)
    q = parse_qs(u.query)
    host = _require_host(u)
    ob: dict[str, Any] = {
        "type": "vless",
        "server": host,
        "server_port": u.port or 443,
        "uuid": unquote(u.username or ""),
        "packet_encoding": "xudp",
    }
    if flow := q.get("flow", [""])[0]:
        ob["flow"] = flow
    if q.get("security", [""])[0] in ("tls", "reality", "xtls"):
        ob["tls"] = _tls_block(q, host)
    if tr := _transport_block(q):
        ob["transport"] = tr
    return ob


def parse_trojan(link: str) -> dict:
    u = urlparse(link)
    q = parse_qs(u.query)
    host = _require_host(u)
    ob: dict[str, Any] = {
        "type": "trojan",
        "server": host,
        "server_port": u.port or 443,
        "password": unquote(u.username or ""),
        "tls": _tls_block(q, host),
    }
    if tr := _transport_block(q):
        ob["transport"] = tr
    return ob


def parse_vmess(link: str) -> dict:
    raw = json.loads(b64decode_loose(link[len("vmess://"):]))
    add = raw.get("add") or ""
    if not add:
        raise ValueError("vmess payload has no address")
    q = {
        "type": [raw.get("net", "tcp")],
        "host": [raw.get("host", "")],
        "path": [raw.get("path", "/")],
        "serviceName": [raw.get("path", "")],
        "sni": [raw.get("sni") or raw.get("host") or add],
        "security": [raw.get("tls", "")],
        "fp": [raw.get("fp", "")],
        "alpn": [raw.get("alpn", "")],
    }
    ob: dict[str, Any] = {
        "type": "vmess",
        "server": add,
        "server_port": int(raw.get("port", 443)),
        "uuid": raw.get("id"),
        "security": raw.get("scy") or "auto",
        "alter_id": int(raw.get("aid", 0) or 0),
        "packet_encoding": "xudp",
    }
    if raw.get("tls") in ("tls", "reality"):
        ob["tls"] = _tls_block(q, add)
    if tr := _transport_block(q):
        ob["transport"] = tr
    ob["_name"] = raw.get("ps", "")
    return ob


def parse_hysteria2(link: str) -> dict:
    u = urlparse(link)
    q = parse_qs(u.query)
    host = _require_host(u)
    password = unquote(u.username or "")
    if u.password:
        password += ":" + unquote(u.password)
    sni = q.get("sni", [host])[0] or host
    ob: dict[str, Any] = {
        "type": "hysteria2",
        "server": host,
        "server_port": u.port or 443,
        "password": password,
        "tls": {"enabled": True, "server_name": sni},
    }
    # These endpoints are routinely published on a bare IP with a self-signed
    # certificate. The link says so via insecure=1, but many panels omit it,
    # so an SNI equal to a bare IP means the same thing.
    if q.get("insecure", ["0"])[0] in ("1", "true") or (
            sni == host and _is_ipv4(host)):
        ob["tls"]["insecure"] = True
    if alpn := q.get("alpn", [""])[0]:
        ob["tls"]["alpn"] = alpn.split(",")
    obfs_pw = q.get("obfs-password", [q.get("obfsPassword", [""])[0]])[0]
    if q.get("obfs", [""])[0] and obfs_pw:
        ob["obfs"] = {"type": q["obfs"][0], "password": obfs_pw}
    return ob


def parse_ss(link: str) -> dict:
    body = link[len("ss://"):].split("#", 1)[0].split("?", 1)[0]
    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        if ":" not in userinfo:
            userinfo = b64decode_loose(userinfo)
    else:
        userinfo, hostport = b64decode_loose(body).rsplit("@", 1)
    method, password = userinfo.split(":", 1)
    host, port = hostport.rsplit(":", 1)
    if not host:
        raise ValueError("link has no host")
    return {
        "type": "shadowsocks",
        "server": host,
        "server_port": int(port),
        "method": method,
        "password": unquote(password),
    }


PARSERS: dict[str, Callable[[str], dict]] = {
    "vless": parse_vless,
    "vmess": parse_vmess,
    "trojan": parse_trojan,
    "hysteria2": parse_hysteria2,
    "hy2": parse_hysteria2,
    "ss": parse_ss,
}

SUPPORTED = frozenset(PARSERS)


def parse_link(link: str) -> dict | None:
    """Return an outbound dict, or None when the link cannot be used.

    Never raises. A single malformed node in a subscription must not abort
    the whole sync.
    """
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    parser = PARSERS.get(scheme)
    if parser is None:
        return None
    name = unquote(link.split("#", 1)[1]) if "#" in link else ""
    try:
        ob = parser(link.split("#", 1)[0])
    except Exception:
        return None
    name = name or ob.pop("_name", "") or ""
    ob.pop("_name", None)
    ob["tag"] = name or f"{scheme}-{ob.get('server')}-{ob.get('server_port')}"
    return ob


def dedupe_tags(outbounds: list[dict]) -> None:
    """Make tags unique in place. sing-box rejects duplicate outbound tags."""
    seen: dict[str, int] = {}
    for ob in outbounds:
        tag = ob["tag"]
        if tag in seen:
            seen[tag] += 1
            ob["tag"] = f"{tag} #{seen[tag]}"
        else:
            seen[tag] = 1
