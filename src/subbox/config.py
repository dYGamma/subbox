"""Configuration: defaults, a TOML round trip, and the Clash API secret.

TOML is read with the standard library. Writing it needs a small emitter,
which is cheaper than taking a dependency and lets a generated file carry
the same comments a hand-written one would.
"""
from __future__ import annotations

import base64
import copy
import os
import tomllib
from pathlib import Path
from typing import Any

from . import paths

DEFAULTS: dict[str, dict[str, Any]] = {
    "subscription": {
        "url": "",
        "insecure": False,
    },
    "proxy": {
        "listen_addr": "127.0.0.1",
        "listen_port": 1080,
        "clash_port": 9090,
    },
    "pac": {
        "enabled": True,
        "port": 7777,
        "domains": [
            "anthropic.com",
            "claude.ai",
            "openai.com",
            "chatgpt.com",
        ],
    },
    "probe": {
        "reach_url": "https://www.gstatic.com/generate_204",
        "reach_ok": [204],
        "latency_url": "https://www.gstatic.com/generate_204",
    },
}

COMMENTS: dict[tuple[str, str], str] = {
    ("subscription", "url"): "Subscription URL from your panel. This is a credential.",
    ("subscription", "insecure"): (
        "Skip TLS verification when fetching the subscription. Only for panels\n"
        "on a bare IP with a self-signed certificate. The subscription body is a\n"
        "credential, so an unverified fetch is MITM-able."
    ),
    ("proxy", "listen_port"): "Local mixed HTTP+SOCKS5 port that applications point at.",
    ("proxy", "clash_port"): "Local Clash API port, used by the TUI to switch nodes.",
    ("pac", "enabled"): "Serve a PAC file so a browser can route only these domains.",
    ("pac", "domains"): "Domains sent through the proxy. Subdomains are matched too.",
    ("probe", "reach_url"): (
        "Endpoint used to answer 'does traffic actually get out'. Any URL works;\n"
        "what matters is knowing which status means healthy for that endpoint."
    ),
    ("probe", "reach_ok"): "Statuses from reach_url that mean the exit is healthy.",
    ("probe", "latency_url"): "Endpoint used for per-node latency measurement.",
}

SECTION_COMMENTS: dict[str, str] = {
    "subscription": "Where nodes come from.",
    "proxy": "The local proxy sing-box exposes.",
    "pac": "Optional PAC server for per-domain browser routing.",
    "probe": "How subbox decides whether the tunnel works.",
}


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    raise TypeError(f"cannot emit {type(value).__name__} to TOML")


def dumps(cfg: dict) -> str:
    out: list[str] = [
        "# subbox configuration.",
        "# Written by `subbox setup`; safe to edit by hand.",
        "",
    ]
    for section, values in cfg.items():
        if section in SECTION_COMMENTS:
            out.append(f"# {SECTION_COMMENTS[section]}")
        out.append(f"[{section}]")
        for key, value in values.items():
            comment = COMMENTS.get((section, key))
            if comment:
                out.extend(f"# {line}" for line in comment.split("\n"))
            out.append(f"{key} = {_fmt(value)}")
        out.append("")
    return "\n".join(out)


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for section, values in override.items():
        if isinstance(values, dict) and isinstance(result.get(section), dict):
            result[section].update(values)
        else:
            result[section] = values
    return result


def load(path: Path | None = None) -> dict:
    path = path or paths.config_file()
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    with path.open("rb") as fh:
        return _merge(DEFAULTS, tomllib.load(fh))


def save(cfg: dict, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(dumps(cfg))
    path.chmod(0o600)  # O_CREAT mode does not apply to an existing file


def is_configured(cfg: dict) -> bool:
    return bool(cfg["subscription"]["url"].strip())


def _port_error(label: str, value: Any) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return f"{label} must be an integer"
    if not 1 <= value <= 65535:
        return f"{label} must be between 1 and 65535, got {value}"
    return None


def validate(cfg: dict) -> list[str]:
    errors: list[str] = []
    ports: dict[str, int] = {}
    for label, value in (
        ("proxy.listen_port", cfg["proxy"]["listen_port"]),
        ("proxy.clash_port", cfg["proxy"]["clash_port"]),
        ("pac.port", cfg["pac"]["port"]),
    ):
        err = _port_error(label, value)
        if err:
            errors.append(err)
        else:
            ports[label] = value

    active = {k: v for k, v in ports.items() if k != "pac.port" or cfg["pac"]["enabled"]}
    if len(set(active.values())) != len(active):
        errors.append("ports must differ from each other: " + ", ".join(
            f"{k}={v}" for k, v in sorted(active.items())))

    url = cfg["subscription"]["url"].strip()
    if url and not url.startswith(("http://", "https://")):
        errors.append("subscription.url must be an http or https URL")

    if not cfg["probe"]["reach_ok"]:
        errors.append("probe.reach_ok must list at least one acceptable status")

    if cfg["pac"]["enabled"] and not cfg["pac"]["domains"]:
        errors.append("pac.domains is empty, so the PAC file would proxy nothing")

    return errors


def clash_secret() -> str:
    """Token for the local Clash API, created once, readable only by the user.

    The API can switch outbounds, so an unauthenticated listener would let any
    local process silently reroute this user's traffic.
    """
    path = paths.clash_secret_file()
    if path.exists():
        existing = path.read_text().strip()
        if existing:
            return existing
    secret = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(secret + "\n")
    path.chmod(0o600)
    return secret
