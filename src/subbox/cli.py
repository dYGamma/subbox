"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import sys

from . import (
    __version__,
    config,
    doctor,
    generate,
    pac,
    paths,
    probe,
    subscription,
    units,
    wizard,
)

OK = 0
PROBLEM = 1
UNCONFIGURED = 2

_MARK = {doctor.PASS: "ok  ", doctor.WARN: "warn", doctor.FAIL: "FAIL"}


def _require_config(cfg: dict) -> int | None:
    if config.is_configured(cfg):
        return None
    print("subbox is not configured yet. Run `subbox setup`.", file=sys.stderr)
    return UNCONFIGURED


def cmd_setup(cfg: dict, args: argparse.Namespace) -> int:
    return wizard.run(cfg=cfg)


def cmd_sync(cfg: dict, args: argparse.Namespace) -> int:
    if (code := _require_config(cfg)) is not None:
        return code
    try:
        nodes = generate.sync(cfg)
    except (generate.GenerateError, subscription.SubscriptionError) as exc:
        print(str(exc), file=sys.stderr)
        return PROBLEM
    for node in nodes:
        print(f"  {node['tag']:<28} {node['type']:<12} "
              f"{node['server']}:{node['server_port']}")
    print(f"wrote {paths.singbox_config()} ({len(nodes)} nodes, validated)")

    if cfg["pac"]["enabled"]:
        pac.write(cfg)
    if not args.no_restart and units.available():
        code, out = units.restart(units.PROXY_UNIT)
        if code != 0:
            print(f"could not restart {units.PROXY_UNIT}: {out.strip()}",
                  file=sys.stderr)
            return PROBLEM
    return OK


def cmd_pac(cfg: dict, args: argparse.Namespace) -> int:
    out = pac.write(cfg)
    print(f"wrote {out} ({len(cfg['pac']['domains'])} domains)")
    if not args.no_restart and units.available() and cfg["pac"]["enabled"]:
        units.restart(units.PAC_UNIT)
    return OK


def cmd_serve_pac(cfg: dict, args: argparse.Namespace) -> int:
    pac.write(cfg)
    pac.serve(cfg)
    return OK


def _status_payload(cfg: dict) -> dict:
    proxy_port = cfg["proxy"]["listen_port"]
    return {
        "configured": config.is_configured(cfg),
        "proxy_unit": units.PROXY_UNIT,
        "proxy_unit_active": units.is_active(units.PROXY_UNIT),
        "proxy_port": proxy_port,
        "proxy_listening": probe.port_listening(proxy_port),
        "pac_enabled": cfg["pac"]["enabled"],
        "pac_port": cfg["pac"]["port"],
        "pac_listening": (probe.port_listening(cfg["pac"]["port"])
                          if cfg["pac"]["enabled"] else None),
        "config": str(paths.config_file()),
    }


def cmd_status(cfg: dict, args: argparse.Namespace) -> int:
    if not config.is_configured(cfg):
        if not args.quiet:
            print("not configured; run `subbox setup`", file=sys.stderr)
        return UNCONFIGURED
    payload = _status_payload(cfg)
    healthy = payload["proxy_listening"] and payload["proxy_unit_active"]
    if args.quiet:
        return OK if healthy else PROBLEM
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key:<20} {value}")
    return OK if healthy else PROBLEM


def cmd_doctor(cfg: dict, args: argparse.Namespace) -> int:
    checks = doctor.run(cfg)
    for check in checks:
        print(f"[{_MARK[check.status]}] {check.name}: {check.detail}")
        if check.fix and check.status != doctor.PASS:
            print(f"         fix: {check.fix}")
    return OK if doctor.worst(checks) != doctor.FAIL else PROBLEM


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subbox",
        description="Turn a proxy subscription into a running local sing-box proxy.")
    parser.add_argument("--version", action="version",
                        version=f"subbox {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="interactive first-run configuration")
    p_setup.set_defaults(func=cmd_setup)

    p_sync = sub.add_parser("sync", help="re-fetch the subscription and regenerate")
    p_sync.add_argument("--no-restart", action="store_true",
                        help="write the config but leave the service alone")
    p_sync.set_defaults(func=cmd_sync)

    p_pac = sub.add_parser("pac", help="regenerate the PAC file")
    p_pac.add_argument("--no-restart", action="store_true")
    p_pac.set_defaults(func=cmd_pac)

    p_serve = sub.add_parser("serve-pac",
                             help="serve the PAC file (used by the unit)")
    p_serve.set_defaults(func=cmd_serve_pac)

    p_status = sub.add_parser("status", help="report whether the proxy is up")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--quiet", action="store_true",
                          help="print nothing; report through the exit code")
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor", help="diagnose common problems")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = config.load()
    if not getattr(args, "func", None):
        from . import tui  # imported lazily: curses is not needed by any subcommand
        return tui.run(cfg)
    try:
        return args.func(cfg, args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
