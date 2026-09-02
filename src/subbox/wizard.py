"""Interactive first-run configuration.

`ask` and `out` are injected so the whole flow is testable without a tty.
"""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from . import config, doctor, generate, links, pac, paths, probe, subscription, units

DEFAULT_DOMAINS = [
    "anthropic.com", "claude.ai",
    "openai.com", "chatgpt.com", "oaistatic.com",
    "gemini.google.com", "generativelanguage.googleapis.com",
]

RU_DOMAINS = DEFAULT_DOMAINS + [
    "instagram.com", "cdninstagram.com", "fbcdn.net",
    "facebook.com", "fb.com", "fb.me", "fbsbx.com",
    "meta.com", "meta.ai", "threads.net", "threads.com",
    "whatsapp.com", "whatsapp.net",
    "twitter.com", "x.com", "twimg.com", "t.co",
    "reddit.com", "redd.it", "redditstatic.com", "redditmedia.com",
    "tiktok.com", "tiktokv.com", "tiktokcdn.com", "byteoversea.com",
    "bytedance.com", "snssdk.com", "amemv.com", "musical.ly",
]

Ask = Callable[[str], str]
Out = Callable[..., None]


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/…"


def _yes(answer: str, default: bool = True) -> bool:
    answer = answer.strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "д", "да")


def _ask_int(ask: Ask, out: Out, prompt: str, default: int) -> int:
    while True:
        raw = ask(f"{prompt} [{default}]: ").strip()
        if not raw:
            candidate = default
        elif raw.isdigit():
            candidate = int(raw)
        else:
            out("  not a number, try again")
            continue
        if not 1 <= candidate <= 65535:
            out("  a port must be between 1 and 65535")
            continue
        if probe.port_listening(candidate):
            out(f"  port {candidate} is already in use by something else")
            continue
        return candidate


def _ask_subscription(ask: Ask, out: Out, cfg: dict) -> list[dict] | None:
    """Returns parsed nodes, or None if the user gave up."""
    while True:
        url = ask("Subscription URL from your panel: ").strip()
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            out("  that is not an http or https URL")
            continue

        insecure = cfg["subscription"]["insecure"]
        try:
            raw = subscription.links_from(url, insecure=insecure)
        except subscription.TlsError as exc:
            out(f"  {exc}")
            out("  Continuing without verification lets anyone on the network "
                "path intercept your subscription.")
            if not _yes(ask("  Fetch it without verifying the certificate? [y/N]: "),
                        default=False):
                continue
            insecure = True
            try:
                raw = subscription.links_from(url, insecure=True)
            except subscription.SubscriptionError as exc2:
                out(f"  {exc2}")
                continue
        except subscription.SubscriptionError as exc:
            out(f"  {exc}")
            continue

        nodes = [ob for ob in (links.parse_link(link) for link in raw) if ob]
        links.dedupe_tags(nodes)
        if not nodes:
            out(f"  {_safe_url(url)} returned no usable nodes")
            continue

        out(f"  found {len(nodes)} node(s):")
        for node in nodes:
            out(f"    {node['tag']:<28} {node['type']:<12} "
                f"{node['server']}:{node['server_port']}")
        cfg["subscription"]["url"] = url
        cfg["subscription"]["insecure"] = insecure
        return nodes


def _ask_pac(ask: Ask, out: Out, cfg: dict) -> None:
    cfg["pac"]["enabled"] = _yes(
        ask("Serve a PAC file so a browser routes only chosen domains? [Y/n]: "))
    if not cfg["pac"]["enabled"]:
        return
    cfg["pac"]["port"] = _ask_int(ask, out, "PAC server port", cfg["pac"]["port"])
    out("Which domains should go through the proxy?")
    out("  1) AI assistants only (default)")
    out(f"  2) broader list ({len(RU_DOMAINS)} domains, includes social networks)")
    out("  3) enter your own")
    choice = ask("Choice [1]: ").strip() or "1"
    if choice == "2":
        cfg["pac"]["domains"] = list(RU_DOMAINS)
    elif choice == "3":
        raw = ask("Domains, comma separated: ")
        cfg["pac"]["domains"] = [d.strip() for d in raw.split(",") if d.strip()]
    else:
        cfg["pac"]["domains"] = list(DEFAULT_DOMAINS)


def _start_services(out: Out, cfg: dict) -> None:
    if not units.available():
        out("systemctl not found; start sing-box yourself with the generated "
            f"config at {paths.singbox_config()}")
        return
    wanted = [units.PROXY_UNIT]
    if cfg["pac"]["enabled"]:
        wanted.append(units.PAC_UNIT)
    for unit in wanted:
        if not units.is_installed(unit):
            out(f"{unit} is not installed; run `make install` first")
            continue
        units.enable(unit)
        code, message = units.restart(unit)
        out(f"started {unit}" if code == 0
            else f"could not start {unit}: {message.strip()}")


def run(ask: Ask = input, out: Out = print, cfg: dict | None = None) -> int:
    cfg = cfg if cfg is not None else config.load()
    paths.ensure_dirs()

    out("subbox setup")
    out("Paste the subscription URL your panel gave you. It is a credential, "
        "so it is stored in a file only you can read.")
    nodes = _ask_subscription(ask, out, cfg)
    if nodes is None:
        out("Nothing entered, so nothing was changed.")
        return 2

    cfg["proxy"]["listen_port"] = _ask_int(
        ask, out, "Local proxy port", cfg["proxy"]["listen_port"])
    _ask_pac(ask, out, cfg)

    errors = config.validate(cfg)
    if errors:
        for error in errors:
            out(f"  {error}")
        return 1

    config.save(cfg)
    out(f"wrote {paths.config_file()} (mode 0600)")

    generate.write(generate.build(nodes, cfg))
    out(f"wrote {paths.singbox_config()}")
    if cfg["pac"]["enabled"]:
        out(f"wrote {pac.write(cfg)}")

    _start_services(out, cfg)

    out("")
    for check in doctor.run(cfg):
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}[check.status]
        out(f"[{mark}] {check.name}: {check.detail}")
        if check.fix and check.status != "pass":
            out(f"         fix: {check.fix}")
    out("")
    out("Point applications at "
        f"http://{cfg['proxy']['listen_addr']}:{cfg['proxy']['listen_port']}")
    if cfg["pac"]["enabled"]:
        out(f"Browser PAC URL: http://127.0.0.1:{cfg['pac']['port']}/proxy.pac")
    return 0
