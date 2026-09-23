# subbox — design

**Date:** 2026-08-20
**Status:** approved, pending implementation plan
**Author:** Dmitry

---

## 1. Problem

A working sing-box client stack exists on one machine as loose scripts under
`~/.local/share/proxy-tui/`: a subscription-to-config generator, a curses TUI,
two user systemd units, a PAC file, and two Claude Code integration shims. It
solves a problem many people have — a proxy panel hands you a subscription URL,
and turning that into a running, inspectable, per-domain-routed local proxy on
Linux takes an afternoon of undocumented trial and error.

The stack is not distributable in its current form. It has no installer, no
documentation, no tests, and no configuration layer: ports, file paths, and the
reachability probe URL are module-level constants in two 500–700 line scripts.

**Goal:** publish it as `subbox`, a public MIT-licensed project for Arch and
other Linux distributions, such that a new user fills in a subscription URL and
gets a working proxy.

## 2. Goals

- One command to install, one wizard to configure, working proxy at the end.
- Zero runtime dependencies beyond Python ≥ 3.11 stdlib and the `sing-box`
  binary itself.
- Parsers correct across the share-link dialects real panels emit — this is
  where third-party breakage will come from.
- The three failure modes that cost the author an evening in August 2026 are
  detected automatically and explained in plain language.
- Native Arch packaging; manual install everywhere else.

## 3. Non-goals

- Not a VPN client, not a TUN manager. `subbox` runs a local SOCKS/HTTP proxy
  on loopback. System-wide TUN routing is explicitly out of scope: it needs
  `CAP_NET_ADMIN`, which a user systemd unit cannot grant, and tools that do
  this well already exist.
- Not a DPI-bypass tool. Changing the exit IP and defeating L4 DPI are
  different problems; `zapret` and friends solve the latter. The README will
  say so and link out rather than bundle.
- Not a subscription panel, server-side installer, or node manager.
- No GUI.

## 4. Recorded decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | Universal core + optional Claude Code integration module |
| 2 | First-run UX | Installer wizard, plus unconfigured-state detection in the TUI |
| 3 | Packaging | `Makefile` (source of truth) + `install.sh` wrapper + `PKGBUILD` |
| 4 | PAC default list | Neutral AI-services minimum; author's fuller list as an example |
| 5 | Name | `subbox` — subscription + sing-box |
| 6 | License | MIT |
| 7 | Docs language | `README.md` English primary, `README.ru.md` full translation |
| 8 | Tests | Unit tests on parsers and config generation, plus CI |
| 9 | Config format | TOML, read via stdlib `tomllib`, written by a small flat-key emitter |
| 10 | Code layout | Python package under `src/subbox/`, replacing the two scripts |
| 11 | Maintainer's live stack | Untouched. `subbox` installs beside it, never over it |

## 5. Architecture

### 5.1 Repository layout

```
subbox/
├── README.md                     English, primary
├── README.ru.md                  Russian, full translation
├── LICENSE                       MIT
├── CHANGELOG.md
├── Makefile                      install / uninstall / check / lint, PREFIX + DESTDIR
├── install.sh                    dependency check → make install → subbox setup
├── pyproject.toml                metadata, entry points, requires-python >= 3.11
├── src/subbox/
│   ├── __init__.py               __version__
│   ├── paths.py                  XDG resolution; every file location lives here
│   ├── config.py                 defaults, tomllib load, TOML emit, validation
│   ├── links.py                  share link → sing-box outbound (pure)
│   ├── subscription.py           HTTP fetch + base64/plain decode
│   ├── generate.py               config assembly, sing-box check, atomic write, backups
│   ├── pac.py                    PAC rendering + the single-file PAC HTTP server
│   ├── clash.py                  Clash API client
│   ├── units.py                  systemctl --user helpers
│   ├── probe.py                  port checks, HTTP status probes, public IP
│   ├── doctor.py                 diagnostic checks
│   ├── wizard.py                 interactive first-run configuration
│   ├── tui.py                    curses application
│   └── cli.py                    argument parsing and dispatch
├── share/systemd/
│   ├── subbox.service            runs sing-box with the generated config
│   └── subbox-pac.service        runs the PAC server
├── share/pac/default-domains.toml
├── examples/
│   ├── config.toml               fully commented reference config
│   └── domains-ru.toml           broader domain set, for users who want it
├── integrations/claude-code/
│   ├── README.md
│   ├── claude                    PATH-shadowing wrapper
│   └── subbox-proxy-ensure.sh    SessionStart hook
├── packaging/
│   ├── PKGBUILD
│   └── .SRCINFO
├── tests/
│   ├── fixtures/                 synthetic subscriptions and links
│   ├── test_links.py
│   ├── test_generate.py
│   ├── test_config.py
│   ├── test_pac.py
│   └── test_doctor.py
├── docs/
│   ├── setup.md                  step by step, panel to working proxy
│   ├── troubleshooting.md        symptom → cause → fix
│   └── architecture.md           how the pieces fit
└── .github/workflows/ci.yml
```

### 5.2 Module boundaries

Dependencies point strictly downward; there are no cycles.

```
paths
  └─ config
       ├─ links, subscription, generate, pac, clash, units, probe
       │    └─ doctor
       │         └─ wizard, tui
       │              └─ cli
```

Each module answers "what does it do, how is it used, what does it depend on":

- **`paths`** — resolves `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`
  and the `SUBBOX_HOME` override into concrete paths. Depends on nothing but
  `os`. Every other module asks `paths` rather than calling `expanduser`.
- **`links`** — one function per scheme, `str -> dict`. No network, no disk, no
  config. This purity is what makes the parser tests meaningful; today the
  parsers are welded to fetching and writing inside one script.
- **`subscription`** — fetches a URL and returns a list of share-link strings,
  handling both base64 and plaintext bodies.
- **`generate`** — turns a node list into a sing-box config, validates it with
  `sing-box check` before it replaces anything, writes atomically, and rotates
  backups.
- **`pac`** — renders a PAC file from the configured domain list and serves
  exactly that one file over HTTP.
- **`clash`** — talks to sing-box's Clash API: list outbounds, read the current
  selection, switch nodes, trigger latency measurement.
- **`units`** — thin, testable wrappers over `systemctl --user`.
- **`probe`** — "is this port listening", "what status does this URL return",
  "what is my exit IP". Built on stdlib `urllib` and `socket`, so the tool has
  no `curl` dependency at runtime.
- **`doctor`** — composes `probe`, `units`, and a parsed config into a list of
  pass/fail checks with human-readable explanations.
- **`wizard`**, **`tui`**, **`cli`** — presentation only. No parsing, no config
  assembly logic of their own.

### 5.3 Data flow

```
panel subscription URL
        │
        ▼
 subscription.fetch ──► links.parse (per link) ──► [outbound dicts]
                                                          │
                                                          ▼
                                              generate.build_config
                                                          │
                                              sing-box check (gate)
                                                          │
                                                          ▼
                                    ~/.config/subbox/sing-box.json
                                                          │
                            systemctl --user restart subbox.service
                                                          │
                                                          ▼
                                    mixed inbound on 127.0.0.1:<listen_port>
                                                          │
                              ┌───────────────────────────┴──────────────┐
                              ▼                                          ▼
                   apps using HTTP(S)_PROXY                   browser using the PAC
```

## 6. Configuration

### 6.1 Schema

`~/.config/subbox/config.toml`, mode `0600`:

```toml
[subscription]
url = ""
# Skip TLS verification when fetching the subscription. Only for panels
# published on a bare IP with a self-signed certificate. The subscription
# body is a credential, so an unverified fetch is MITM-able.
insecure = false

[proxy]
listen_addr = "127.0.0.1"
listen_port = 1080
clash_port  = 9090

[pac]
enabled = true
port    = 7777
domains = ["anthropic.com", "claude.ai", "openai.com", "chatgpt.com"]

[probe]
# Endpoint used to answer "does traffic actually get out". Any URL works; what
# matters is knowing which status means healthy for that endpoint. The default
# is deliberately neutral — the Claude Code module offers a different one.
reach_url   = "https://www.gstatic.com/generate_204"
reach_ok    = [204]
latency_url = "https://www.gstatic.com/generate_204"
```

Read with stdlib `tomllib`. Written by a ~30-line emitter in `config.py`
covering exactly the types the schema uses: string, int, bool, list of string,
list of int. Comments are emitted from a table of per-key doc strings, so a
wizard-written config is as readable as a hand-written one.

`config.load()` fills missing keys from defaults rather than failing, so a
config written by an older version keeps working after an upgrade.

### 6.2 Why TOML and not env vars or JSON

Env vars fail the "fill it in and it runs" requirement — the user must first
learn the variable names. JSON cannot carry the inline comments that make a
generated config self-documenting. TOML reads with the stdlib and writes with a
small amount of code, which keeps the zero-dependency property.

### 6.3 Path map

| What | Where | Mode |
|---|---|---|
| User config | `$XDG_CONFIG_HOME/subbox/config.toml` | 0600 |
| Clash API secret | `$XDG_CONFIG_HOME/subbox/clash.secret` | 0600 |
| Generated sing-box config | `$XDG_CONFIG_HOME/subbox/sing-box.json` | 0600 |
| Config backups | `$XDG_CONFIG_HOME/subbox/sing-box.json.bak-<ts>` | 0600 |
| Rendered PAC | `$XDG_DATA_HOME/subbox/proxy.pac` | 0644 |
| sing-box cache db | `$XDG_CACHE_HOME/subbox/cache.db` | dir 0700 |
| User units (manual install) | `$XDG_CONFIG_HOME/systemd/user/` | 0644 |
| User units (package install) | `/usr/lib/systemd/user/` | 0644 |

The generated sing-box config deliberately does **not** live at
`~/.config/sing-box/config.json`. That path belongs to a manually configured
sing-box, and a user who has one must not lose it by installing `subbox`.

Setting `SUBBOX_HOME=<dir>` overrides all three XDG roots at once, which is how
a development instance runs beside a production one.

### 6.4 Secrets

- The subscription URL **is** a credential: anyone who reads it can use the
  account. `config.toml` is created `0600` and the wizard refuses to leave it
  more permissive.
- The **generated `sing-box.json` is equally sensitive** — it carries every
  node's uuid or password and the Clash API secret — so it and its backups are
  `0600` as well. It is created through `os.open` with that mode rather than
  written and then chmod-ed, so there is no window in which it is world
  readable.
- `clash.secret` stays in its own `0600` file rather than inside `config.toml`,
  so a user can attach their config to a bug report after removing one line
  instead of two. The Clash API can switch outbounds, so an unauthenticated
  listener would let any local process silently reroute traffic.
- `.gitignore` covers `config.toml`, `*.secret`, `sing-box.json*`, and
  `proxy.pac`. Test fixtures use obviously fake UUIDs and hostnames
  (`example.invalid`), never a redacted real subscription.

## 7. CLI surface

| Command | Behavior |
|---|---|
| `subbox` | Launch the TUI. Offers the wizard if unconfigured. |
| `subbox setup` | Interactive first-run wizard. |
| `subbox sync` | Re-fetch the subscription, regenerate, validate, restart. |
| `subbox pac` | Re-render the PAC file from the configured domain list. |
| `subbox status` | Non-interactive status. `--json` for scripts, `--quiet` for exit-code-only use by hooks. |
| `subbox doctor` | Run diagnostics, print findings and fixes. |
| `subbox serve-pac` | Serve the PAC file. This is what the PAC unit runs; not normally typed by a user. |

`sync`, `pac`, `status`, and `doctor` are all non-interactive and safe in
scripts and cron.

Exit codes are part of the contract, because the `SessionStart` hook and any
monitoring script depend on them: `0` when the proxy is up and reachable, `1`
when it is down or unreachable, `2` when `subbox` is not configured yet. Tests
cover all three.

`subbox sync` never leaves a broken proxy behind. The regenerated config is
validated with `sing-box check` before it replaces the live file, and on any
failure — unreachable subscription, unparseable links, rejected config — the
existing config and the running service are left untouched and the command
exits non-zero.

## 8. First-run flow

`install.sh`:

1. Detect the distribution's package manager: `pacman`, `apt`, `dnf`, `zypper`,
   `apk`, or `nix-env`. An unrecognized manager falls through to a generic
   message naming the two requirements.
2. Check for `sing-box` and Python ≥ 3.11. If missing, print the exact install
   command for that distribution and exit. **The installer never invokes `sudo`
   on the user's behalf** — a script that curls from the internet and
   escalates is exactly the pattern users should refuse.
3. `make install PREFIX="$HOME/.local"`.
4. Run `subbox setup`.

`subbox setup`:

1. Ask for the subscription URL, then immediately fetch it and print the nodes
   found. The user sees success or a precise error at step one, rather than
   after filling in five fields. On a TLS failure, explain the `insecure`
   option and what it costs, and ask rather than silently downgrading.
2. Ask for the listen port (default 1080), verifying it is free.
3. Ask whether to enable the PAC server; if yes, ask for its port and offer
   three domain sets: minimal AI services, the broader example list, or a
   hand-entered list.
4. Write `config.toml` at `0600`.
5. Generate the sing-box config and the PAC file.
6. Install and enable the user units, then start them.
7. Run `subbox doctor` and print the result table.

The TUI checks for a missing or empty configuration at startup and offers to run
the wizard rather than showing an empty broken dashboard.

## 9. `subbox doctor`

Each check reports pass, warn, or fail with a one-line explanation and a
concrete fix. The first three encode failure modes diagnosed the hard way:

| Check | Why it exists |
|---|---|
| `route.auto_detect_interface` is `false` | When true, sing-box binds its own dials to whatever TUN happens to be up, black-holing them. The symptom is `dial tcp <server>: i/o timeout` while a raw `nc` to the same port succeeds — which reads as a dead server, not a config bug. |
| `cache_file` directory exists | sing-box 1.13 refuses to start if the directory is missing, and the error does not name the directory. |
| `route.default_domain_resolver` is set | Required since 1.13. Without it, resolving node hostnames depends on the tunnel that is not up yet. |
| Reachability, direct vs proxied | Reports both statuses side by side. A status outside `reach_ok` through the proxy but not directly means the exit is blocked, not the tunnel. Also warns when `reach_url` points at a consumer web endpoint, which answers `403` to any client, proxied or not, and makes a healthy stack look broken. |
| Ports free / owned by us | Distinguishes "our service is down" from "something else holds the port". |
| Foreign TUN present | Warn only. A system-wide VPN changes what every other check means. |
| Unit state | `subbox.service` and `subbox-pac.service` loaded, enabled, active. |
| Config file mode | `config.toml` is `0600`. |

## 10. PAC serving

The current stack serves the PAC file with `python -m http.server`, which
exposes a directory listing and sends the wrong content type. `subbox
serve-pac` serves exactly one file at `/proxy.pac`, with content type
`application/x-ns-proxy-autoconfig`, bound to loopback, and returns `404` for
everything else.

The PAC file is rendered from `[pac].domains`, so the TUI's edit action edits a
domain list rather than raw JavaScript, and the proxy port in the generated PAC
always matches `[proxy].listen_port`.

Domain matching covers both the exact domain and its subdomains.

## 11. Claude Code integration

Optional, installed by `make install-claude`, documented separately in
`integrations/claude-code/README.md` so the core README stays about proxying.

- **`claude` wrapper** — shadows the real binary via `PATH`, exports
  `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`, then `exec`s the real
  binary so native self-updates keep working. It resolves the real binary by
  scanning `PATH` for the first `claude` that is not itself, compared by
  `readlink -f`, with a `CLAUDE_REAL_BIN` override. The current version
  hardcodes one user's home directory and cannot ship as is.
- **`subbox-proxy-ensure.sh`** — a `SessionStart` hook that starts the proxy if the
  port is dead and emits a `systemMessage` only when nothing usable is up.
  Calls `subbox status --quiet`.

The README explains the motivating case plainly: the Anthropic API answers
`403` to some source addresses, and a request that is geo-blocked at the edge
looks like an authentication failure rather than a network one.

Installing this module offers to set `[probe].reach_url` to
`https://api.anthropic.com/v1/models` with `reach_ok = [200, 401]`, the probe
that tells the two apart: `401` means the endpoint was reached, `403` means the
exit IP is blocked. The core default stays neutral.

## 12. Packaging

`Makefile` is the source of truth. `install.sh` and `PKGBUILD` both call it.

| Target | Effect |
|---|---|
| `install` | Install package, entry points, units, and share data under `PREFIX`, honoring `DESTDIR`. |
| `install-claude` | Additionally install the Claude Code wrapper and hook. |
| `uninstall` | Remove everything `install` created; never touch user config, generated files, or anything under `~/.claude`. |
| `uninstall-claude` | Remove the Claude Code wrapper and hook. Separate from `uninstall` because those files live among files subbox did not put there. |
| `check` | `pytest` |
| `lint` | `ruff` + `shellcheck` |

Unit files are installed with the correct root for the install mode:
`$XDG_CONFIG_HOME/systemd/user` for a `PREFIX=$HOME/.local` install,
`/usr/lib/systemd/user` for a packaged install.

`PKGBUILD` uses the standard Arch Python flow: `python -m build --wheel
--no-isolation`, then `python -m installer --destdir="$pkgdir"`. `depends`:
`python`, `sing-box`. There are no optional dependencies. Published to the AUR
as `subbox`.

Versioning is semantic. `__version__` in `src/subbox/__init__.py` is the single
source of truth; `pyproject.toml` and `PKGBUILD` read it rather than repeating
it. `CHANGELOG.md` follows Keep a Changelog, and a release is a git tag
`v<version>` plus a regenerated `.SRCINFO`.

## 13. Testing

`tests/test_links.py` is the highest-value file in the suite: table-driven
cases per scheme, covering TLS, Reality, WebSocket, gRPC, HTTP-upgrade
transports, Hysteria2 obfuscation, and both Shadowsocks userinfo encodings.
Third-party panels are where breakage will come from, and every new user brings
one.

`tests/test_generate.py` asserts the invariants `doctor` checks —
`auto_detect_interface` false, `default_domain_resolver` present, cache
directory created — plus tag deduplication and the direct route for the proxy
servers' own IPs. When a `sing-box` binary is present it additionally runs
`sing-box check` on the generated config; otherwise that test skips rather than
failing, so contributors without sing-box can still run the suite.

`tests/test_config.py` covers the defaults-to-TOML-to-`tomllib` round trip,
`0600` enforcement, and forward compatibility when keys are missing.

`tests/test_pac.py` is a golden-file test including port substitution.

`tests/test_doctor.py` feeds crafted configs and asserts each check fires.

CI on `ubuntu-latest`: a matrix of Python 3.11 and 3.13 running `pytest`,
`ruff`, and `shellcheck`, plus one job that installs `sing-box` so the
`sing-box check` test actually executes.

No test touches the developer's real config, real units, or real ports. Tests
set `SUBBOX_HOME` to a temporary directory.

## 14. Documentation

- **`README.md`** — what it is, what it is not, a 60-second install, a screenshot
  of the TUI, and links onward. Explicit about not being a VPN and not being a
  DPI-bypass tool.
- **`docs/setup.md`** — the step-by-step path the user asked for: where a
  subscription URL is found in common panels, what to paste, what each wizard
  question means, and the verification commands with their expected output.
- **`docs/troubleshooting.md`** — organized symptom → cause → fix, seeded with
  every failure mode in section 9.
- **`docs/architecture.md`** — module map and data flow, for contributors.
- **`README.ru.md`** — full translation. CI warns, without failing, when one
  README changes and the other does not, so drift gets caught without blocking
  an urgent fix.

## 15. Isolation from the maintainer's live stack

The author's machine runs the predecessor stack and depends on it for API
access. This is a design requirement, not a courtesy:

- `subbox` never writes `~/.config/sing-box/config.json`.
- Unit names are `subbox.service` and `subbox-pac.service`; the existing
  `sing-box.service` and `ai-pac.service` are never referenced, stopped, or
  disabled by any code path.
- Development and testing run under `SUBBOX_HOME` with ports 11080, 17777,
  and 19090.
- Migrating the author's machine is a separate task, done later, deliberately.

## 16. Acceptance criteria

1. On a clean Linux machine with no prior sing-box configuration, a user who
   follows `README.md` reaches a working proxy without reading source code.
2. `subbox doctor` reports all checks passing on that machine.
3. `curl -x http://127.0.0.1:1080 -o /dev/null -w '%{http_code}' <reach_url>`
   returns a status in `reach_ok`.
4. The exit IP through the proxy differs from the direct exit IP.
5. `pytest` passes with and without a `sing-box` binary present.
6. Installing and then uninstalling leaves no files behind except user
   configuration and generated output.
7. Nothing in the author's pre-existing stack changes state at any point.

Criterion 1 is verified on a fresh server the author will provide. A headless
VPS exercises install, wizard, units, sync, doctor, and the TUI over SSH; PAC
consumption by a browser is verified locally instead.

## 17. Out of scope for the first release

- TUN mode and system-wide routing.
- Multiple subscriptions or profile switching.
- Non-systemd init systems. The README will state the requirement plainly; a
  contributor wanting OpenRC or runit support can add it against a clean
  `units` module boundary.
- Windows and macOS.
