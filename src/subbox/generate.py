"""Assembling a sing-box config and putting it in place safely."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import config, links, paths, subscription

SELECTOR_TAG = "proxy"
URLTEST_TAG = "auto"


class GenerateError(Exception):
    """The config could not be built or could not be installed."""


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _cidr(host: str) -> str | None:
    """Return host/prefix when host is a literal address, else None.

    The prefix length comes from the address family: a hardcoded /32 would
    silently mis-route an IPv6 node's own address.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    return f"{host}/{address.max_prefixlen}"


def build(nodes: list[dict], cfg: dict) -> dict:
    if not nodes:
        raise GenerateError("subscription produced no usable nodes")

    # sing-box refuses to start when this directory is missing, and the error
    # it prints does not name the directory.
    paths.cache_dir().mkdir(parents=True, exist_ok=True, mode=0o700)

    tags = [ob["tag"] for ob in nodes]
    server_cidrs = sorted({c for c in (_cidr(ob["server"]) for ob in nodes) if c})

    outbounds: list[dict[str, Any]] = [
        {
            "type": "selector",
            "tag": SELECTOR_TAG,
            "outbounds": [URLTEST_TAG] + tags,
            "default": URLTEST_TAG,
            "interrupt_exist_connections": False,
        },
        {
            "type": "urltest",
            "tag": URLTEST_TAG,
            "outbounds": tags,
            "url": cfg["probe"]["latency_url"],
            "interval": "3m",
            "tolerance": 60,
            "idle_timeout": "30m",
        },
        *nodes,
        {"type": "direct", "tag": "direct"},
    ]

    rules: list[dict[str, Any]] = [
        {"action": "sniff"},
        {"ip_is_private": True, "action": "route", "outbound": "direct"},
    ]
    if server_cidrs:
        # Without this the tunnel would try to reach its own server through
        # itself.
        rules.append({
            "ip_cidr": server_cidrs,
            "action": "route",
            "outbound": "direct",
        })

    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "dns-proxy", "type": "https", "server": "1.1.1.1",
                 "detour": SELECTOR_TAG},
                {"tag": "dns-local", "type": "local"},
            ],
            "rules": [{"domain_suffix": [".invalid"], "server": "dns-local"}],
            "final": "dns-proxy",
            "strategy": "prefer_ipv4",
            "independent_cache": True,
        },
        "inbounds": [{
            "type": "mixed",
            "tag": "mixed-in",
            "listen": cfg["proxy"]["listen_addr"],
            "listen_port": cfg["proxy"]["listen_port"],
        }],
        "outbounds": outbounds,
        "route": {
            "rules": rules,
            "final": SELECTOR_TAG,
            # This is a loopback proxy, not a TUN. Letting sing-box pick an
            # interface makes it bind to whatever VPN tunnel happens to be up,
            # which black-holes its own dials.
            "auto_detect_interface": False,
            # Node hostnames resolve locally, so bringing the tunnel up does
            # not depend on the tunnel already being up.
            "default_domain_resolver": {"server": "dns-local"},
        },
        "experimental": {
            "cache_file": {
                "enabled": True,
                "path": str(paths.cache_db()),
                "store_rdrc": True,
            },
            "clash_api": {
                "external_controller": f"127.0.0.1:{cfg['proxy']['clash_port']}",
                "secret": config.clash_secret(),
                "default_mode": "rule",
            },
        },
    }


def check(path: Path) -> tuple[bool, str]:
    """Ask sing-box whether it would accept this file."""
    binary = shutil.which("sing-box")
    if not binary:
        return True, "sing-box not in PATH, validation skipped"
    proc = subprocess.run(
        [binary, "check", "-c", str(path)],
        capture_output=True, text=True, timeout=30, check=False)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _prune(path: Path, keep: int) -> None:
    prefix = path.name + ".bak-"
    backups = sorted(p for p in path.parent.iterdir()
                     if p.name.startswith(prefix))
    for old in backups[:-keep] if len(backups) > keep else []:
        old.unlink()


def _write_private(path: Path, text: str) -> None:
    """Create a file no other user can read, then fill it.

    The generated config carries every node's uuid or password plus the
    Clash API secret, so it is as sensitive as the subscription URL. Going
    through os.open means it is never briefly world-readable, which a
    write-then-chmod would allow.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    path.chmod(0o600)  # O_CREAT mode does not apply to an existing file


def write(document: dict, path: Path | None = None, keep: int = 5) -> Path:
    """Validate, then atomically replace, keeping a bounded backup history."""
    path = path or paths.singbox_config()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.parent / (path.name + ".new")
    _write_private(tmp, json.dumps(document, ensure_ascii=False, indent=2) + "\n")

    ok, message = check(tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise GenerateError(f"sing-box rejected the generated config: {message}")

    if path.exists():
        backup = path.parent / f"{path.name}.bak-{_stamp()}"
        shutil.copy2(path, backup)
        backup.chmod(0o600)  # a backup of a credential file is still one
        _prune(path, keep)
    tmp.replace(path)
    return path


def sync(cfg: dict) -> list[dict]:
    """Fetch, parse, build, validate, install. Returns the nodes installed."""
    url = cfg["subscription"]["url"].strip()
    if not url:
        raise GenerateError("no subscription URL configured; run `subbox setup`")
    raw = subscription.links_from(url, insecure=cfg["subscription"]["insecure"])
    nodes = [ob for ob in (links.parse_link(link) for link in raw) if ob]
    links.dedupe_tags(nodes)
    write(build(nodes, cfg))
    return nodes
