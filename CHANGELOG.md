# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [semantic](https://semver.org/).

## [Unreleased]

## [0.1.3] - 2026-09-23

The services could not start at all after a home-directory install.

### Fixed

- A systemd user unit does not inherit your shell's `PATH`, and the default
  one excludes `~/.local/bin`. Both units called their binaries through `env`,
  so a `subbox` or `sing-box` installed into a home prefix was invisible and
  the services failed instantly. The units now carry a `PATH` containing the
  install prefix, substituted at install time.
- The wizard reported `started subbox.service` for a service that was already
  dead. `Type=simple` makes `systemctl restart` succeed as soon as the process
  is forked, before a failed `exec` surfaces, so the wizard contradicted its
  own diagnostics seconds later. It now waits for the unit to settle and says
  plainly when it did not, with the command that explains why.
- `make uninstall` deleted unit files without stopping the services, leaving
  them running with nothing left to manage them. It now disables and stops
  them first.
- The domain-set question did not say what choosing a list would do. It now
  states that only those domains are proxied and how to change the list later.

### Added

- Removal is documented in both READMEs.

## [0.1.2] - 2026-09-23

Wizard usability and credential handling, from watching a first real run.

### Fixed

- Every question now says what it is for. `Local proxy port [1080]:` on its
  own does not tell anyone what to type, or that Enter accepts the value in
  brackets; both are now stated.

### Security

- The subscription URL is no longer echoed while it is pasted. It is an
  account, and echoing left it in terminal scrollback and in any screenshot.
  Nothing is lost: the wizard fetches it immediately and prints the node list,
  which confirms the paste better than seeing the characters. Piped input and
  terminals that cannot hide echo fall back to a plain read.

## [0.1.1] - 2026-09-23

Installation fixes, all found by a first install on Debian.

### Fixed

- The installer told Debian and Ubuntu users to run `sudo apt install
  sing-box`. No such package exists there; only Arch, Alpine and nixpkgs carry
  it. Each package manager now gets advice that is true for it.
- The installer told them to run `sudo apt install python`. The package is
  `python3`; package names are now mapped per distribution.
- `make install` required `pip`, which Debian and Ubuntu ship separately as
  `python3-pip` and which PEP 668 restricts. Installation no longer uses pip,
  wheels or a build backend at all: subbox is pure standard library, so
  installing it copies files and writes a launcher that knows where they went.
  This also removes the `--prefix` import-path trap, so any prefix now works.
- The launcher checks the interpreter version first, so an old Python produces
  a sentence instead of a `ModuleNotFoundError` for `tomllib`.

### Added

- `./install.sh --fetch-sing-box` downloads the official static `sing-box`
  release for the detected architecture into the prefix, without root. This
  makes a working install possible on distributions that do not package it.
- `./install.sh --help`.

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
