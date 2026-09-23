# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [semantic](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-23

First release.

### Added

- `subbox setup`, an interactive first run that fetches the subscription at the
  first question so the node list appears before anything else is asked.
- Share link parsing for vless, vmess, trojan, hysteria2 and shadowsocks,
  covering TLS, Reality, WebSocket, gRPC, HTTP-upgrade and obfuscation.
- Generated sing-box configuration, validated with `sing-box check` before it
  replaces the running one, with bounded backups.
- `subbox` dashboard: live node, service state, exit address, node switching
  and latency measurement over the Clash API.
- `subbox doctor`, which names the symptom rather than only the setting.
- PAC server for per-domain browser routing, serving one file with the content
  type browsers expect.
- `subbox status` with documented exit codes: 0 up, 1 down, 2 unconfigured.
- Arch package and a `make install` path for other distributions.
- Optional Claude Code integration under `integrations/claude-code/`.

### Security

- `config.toml`, the generated `sing-box.json` and its backups, and
  `clash.secret` are all created `0600`. The generated configuration carries
  node passwords and the Clash API secret, so it is as sensitive as the
  subscription URL.
- Skipping TLS verification when fetching a subscription is opt-in and states
  its cost.
- Error messages carry the subscription host but never its path, because the
  path is the account token.

## Release checklist

1. Bump `__version__` in `src/subbox/__init__.py`.
2. Move `Unreleased` entries into a new version section, dated.
3. `make check && make lint`.
4. `git tag v<version> && git push --tags`.
5. In `packaging/`: `updpkgsums`, then `makepkg --printsrcinfo > .SRCINFO`.
6. Submit to the AUR.
