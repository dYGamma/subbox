"""Diagnostics.

Most checks here exist because the underlying failure was diagnosed the
slow way once. The detail text says what the symptom looks like, because
recognising the symptom is the hard part.
"""
from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from urllib.parse import urlparse

from . import config, paths, probe, units

PASS, WARN, FAIL = "pass", "warn", "fail"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

# Endpoints that sit behind bot protection and answer 403 to every client.
CONSUMER_HOSTS = frozenset({
    "claude.ai", "www.claude.ai",
    "chatgpt.com", "www.chatgpt.com",
    "chat.openai.com",
    "gemini.google.com",
})


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def worst(checks: list[Check]) -> str:
    return max((c.status for c in checks), key=lambda s: _RANK[s], default=PASS)


def _permission_check() -> Check:
    """Every file subbox writes that holds a secret.

    Not just config.toml: the generated sing-box config carries each node's
    uuid or password and the Clash API secret.
    """
    sensitive = [paths.config_file(), paths.singbox_config(),
                 paths.clash_secret_file()]
    present = [p for p in sensitive if p.exists()]
    if not present:
        return Check("Credential file permissions", WARN,
                     "nothing has been written yet", "run `subbox setup`")
    loose = [p for p in present if stat.S_IMODE(p.stat().st_mode) & 0o077]
    if loose:
        return Check(
            "Credential file permissions", FAIL,
            "readable by other users: " + ", ".join(p.name for p in loose)
            + " — these hold the subscription URL, the node passwords and the "
              "Clash API secret, each a credential",
            "chmod 600 " + " ".join(str(p) for p in loose))
    return Check("Credential file permissions", PASS,
                 f"{len(present)} file(s) are 0600")


def _config_checks(cfg: dict) -> list[Check]:
    out: list[Check] = []

    if config.is_configured(cfg):
        out.append(Check("Subscription configured", PASS,
                         "a subscription URL is set"))
    else:
        out.append(Check("Subscription configured", FAIL,
                         "no subscription URL is set, so there are no nodes",
                         "run `subbox setup`"))

    errors = config.validate(cfg)
    out.append(Check("Config values", PASS, "all values are in range")
               if not errors else
               Check("Config values", FAIL, "; ".join(errors),
                     f"edit {paths.config_file()}"))

    out.append(_permission_check())

    host = urlparse(cfg["probe"]["reach_url"]).hostname or ""
    if host in CONSUMER_HOSTS:
        out.append(Check(
            "Probe endpoint", WARN,
            f"{host} sits behind bot protection and answers 403 to any client, "
            "proxied or not, which makes a healthy stack look broken",
            "point probe.reach_url at an API endpoint instead"))
    else:
        out.append(Check("Probe endpoint", PASS,
                         f"{host or 'unset'} is a usable probe target"))
    return out


def _generated_config_checks() -> list[Check]:
    path = paths.singbox_config()
    if not path.exists():
        return [Check("Generated config", FAIL,
                      "no sing-box config has been generated",
                      "run `subbox sync`")]
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("Generated config", FAIL, f"unreadable: {exc}",
                      "run `subbox sync` to regenerate")]

    route = doc.get("route", {})
    out = [Check("Generated config", PASS,
                 f"{len(doc.get('outbounds', []))} outbounds")]

    if route.get("auto_detect_interface") is False:
        out.append(Check("route.auto_detect_interface", PASS, "correctly false"))
    else:
        out.append(Check(
            "route.auto_detect_interface", FAIL,
            "true makes sing-box bind its own dials to whatever tunnel "
            "interface is up, which black-holes them; the symptom is "
            "'dial tcp <server>: i/o timeout' while a raw connection to the "
            "same port succeeds",
            "run `subbox sync` to regenerate with the correct value"))

    if route.get("default_domain_resolver"):
        out.append(Check("route.default_domain_resolver", PASS, "set"))
    else:
        out.append(Check(
            "route.default_domain_resolver", FAIL,
            "sing-box 1.13 requires it; without it, resolving node hostnames "
            "depends on the tunnel that is not up yet",
            "run `subbox sync` to regenerate"))

    cache = doc.get("experimental", {}).get("cache_file", {}).get("path")
    if cache and paths.cache_dir().is_dir():
        out.append(Check("Cache directory", PASS, str(paths.cache_dir())))
    else:
        out.append(Check(
            "Cache directory", FAIL,
            "sing-box refuses to start when the cache_file directory is "
            "missing, and the error it prints does not name the directory",
            f"mkdir -p {paths.cache_dir()}"))
    return out


def _service_checks(cfg: dict) -> list[Check]:
    if not units.available():
        return [Check("systemd", FAIL, "systemctl was not found",
                      "subbox manages sing-box through systemd user units")]

    out: list[Check] = []
    wanted = [units.PROXY_UNIT]
    if cfg["pac"]["enabled"]:
        wanted.append(units.PAC_UNIT)

    missing = [u for u in wanted if not units.is_installed(u)]
    out.append(Check("Unit files", PASS, "installed") if not missing else
               Check("Unit files", FAIL, f"not installed: {', '.join(missing)}",
                     "run `make install` or install the package"))

    for unit in wanted:
        if units.is_active(unit):
            out.append(Check(f"{unit} active", PASS, "running"))
        else:
            out.append(Check(f"{unit} active", FAIL, "not running",
                             f"systemctl --user start {unit}"))

    port = cfg["proxy"]["listen_port"]
    out.append(Check(f"Proxy port {port}", PASS, "listening")
               if probe.port_listening(port) else
               Check(f"Proxy port {port}", FAIL, "nothing is listening",
                     f"systemctl --user status {units.PROXY_UNIT}"))

    if cfg["pac"]["enabled"]:
        pac_port = cfg["pac"]["port"]
        out.append(Check(f"PAC port {pac_port}", PASS, "listening")
                   if probe.port_listening(pac_port) else
                   Check(f"PAC port {pac_port}", FAIL, "nothing is listening",
                         f"systemctl --user status {units.PAC_UNIT}"))
    return out


def _network_checks(cfg: dict) -> list[Check]:
    url = cfg["probe"]["reach_url"]
    ok = set(cfg["probe"]["reach_ok"])
    proxy = probe.proxy_url(cfg)

    direct = probe.http_status(url)
    through = probe.http_status(url, proxy=proxy)
    detail = f"direct {direct or 'unreachable'}, via proxy {through or 'unreachable'}"

    if through in ok:
        reach = Check("Reachability", PASS, detail)
    elif through is None:
        reach = Check("Reachability", FAIL, detail,
                      f"check that {proxy} is up: `subbox status`")
    elif direct in ok:
        reach = Check(
            "Reachability", FAIL,
            detail + " — the tunnel carries traffic but the exit address is "
                     "rejected by this endpoint",
            "switch to another node with `subbox` and press p")
    else:
        reach = Check("Reachability", FAIL,
                      detail + " — neither path reaches the endpoint",
                      "verify the endpoint is correct in probe.reach_url")

    direct_ip = probe.public_ip()
    proxy_ip = probe.public_ip(proxy=proxy)
    if proxy_ip and direct_ip and proxy_ip != direct_ip:
        exit_check = Check("Exit address", PASS,
                           f"direct {direct_ip}, via proxy {proxy_ip}")
    elif proxy_ip and proxy_ip == direct_ip:
        exit_check = Check(
            "Exit address", FAIL,
            f"both paths exit from {proxy_ip}, so traffic is not tunnelled",
            "the proxy is answering but not forwarding; check node health")
    else:
        exit_check = Check("Exit address", WARN,
                           "could not determine the exit address")
    return [reach, exit_check]


def run(cfg: dict) -> list[Check]:
    checks = _config_checks(cfg)
    checks += _generated_config_checks()
    checks += _service_checks(cfg)
    checks += _network_checks(cfg)
    return checks
