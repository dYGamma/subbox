# Architecture

For contributors. If you only want to use subbox, `docs/setup.md` is the page
you want.

## Shape

A Python package with no runtime dependencies beyond the standard library,
layered so that pure logic has no I/O and can be tested directly.

```
paths
  └─ config
       ├─ links, subscription, generate, pac, clash, units, probe
       │    └─ doctor
       │         └─ wizard, tui
       │              └─ cli
```

Dependencies point strictly downward. There are no cycles.

| Module | Responsibility |
|---|---|
| `paths` | Every filesystem location. XDG resolution and the `SUBBOX_HOME` override |
| `config` | Defaults, `tomllib` load, TOML emitter, validation, the Clash secret |
| `links` | Share link → sing-box outbound. Pure: no network, no disk, no config |
| `subscription` | HTTP fetch and base64/plain decode |
| `generate` | Config assembly, `sing-box check`, atomic write, bounded backups |
| `pac` | PAC rendering and the single-file PAC server |
| `probe` | Port checks, HTTP status, exit address — on `urllib`, not `curl` |
| `units` | `systemctl --user` wrappers that return instead of raising |
| `clash` | Clash API client: list, select, measure |
| `doctor` | Diagnostic checks composed from the above |
| `wizard` | Interactive first run. `ask` and `out` are injected so it is testable |
| `tui` | curses dashboard. Rendering is a pure function over a snapshot |
| `cli` | Argument parsing, dispatch, exit codes |

## Data flow

```
panel subscription URL
        │
        ▼
 subscription.fetch ──► links.parse_link (per link) ──► [outbound dicts]
                                                              │
                                                              ▼
                                                    generate.build
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
                                          │                        │
                                          ▼                        ▼
                            apps using HTTP(S)_PROXY      browser using the PAC
```

## Why `links` is pure

It is the module most likely to break, because every new user arrives with a
different panel and panels disagree about how to encode the same node. Keeping
it free of I/O is what makes `tests/test_links.py` a table of real dialects
rather than a mock-heavy integration test. A malformed link returns `None`
rather than raising, so one bad node cannot abort a whole sync.

If you are adding support for a scheme or a transport, that file and its test
are the only two you should need to touch.

## Why rendering is separated from curses

`tui.render` turns a `Snapshot` into `(label, value, status)` triples. It is a
pure function, so what the dashboard claims can be asserted without a terminal.
The event loop below it only collects state and dispatches into modules that
are already covered by their own tests.

## Invariants worth knowing

Three settings in the generated configuration are easy to get wrong and hard to
diagnose. `generate` sets them, `doctor` checks them, and `tests/test_generate.py`
asserts them:

- `route.auto_detect_interface` must be `false`. True makes sing-box bind its
  own dials to whatever tunnel interface is up, which black-holes them.
- `route.default_domain_resolver` must be set, so resolving node hostnames does
  not depend on the tunnel that is not up yet.
- The `cache_file` directory must exist before start, because sing-box refuses
  to start without it and does not say which directory it means.

## Testing

Every test relocates its state with `SUBBOX_HOME`, set by an autouse fixture in
`tests/conftest.py`. No test starts a unit, binds a default port, or reaches a
real host. `tests/test_generate.py` additionally runs `sing-box check` on the
generated configuration when the binary is present, and skips that one
assertion when it is not.

To gate your own pushes on the suite:

```bash
make hooks
```

That points `core.hooksPath` at `.githooks/`, whose `pre-push` runs `make
check` and `make lint`. Undo with `git config --unset core.hooksPath`.
`make lint` needs `shellcheck`; if your distribution does not package it, point
at a static build with `make lint SHELLCHECK=/path/to/shellcheck`.

## Files this creates on a user's machine

| Path | Mode |
|---|---|
| `~/.config/subbox/config.toml` | 0600 — holds the subscription URL |
| `~/.config/subbox/sing-box.json` | 0600 — holds node passwords and the Clash secret |
| `~/.config/subbox/clash.secret` | 0600 |
| `~/.local/share/subbox/proxy.pac` | 0644 |
| `~/.cache/subbox/cache.db` | inside a 0700 directory |

Nothing is written to `~/.config/sing-box/`, which belongs to a hand-configured
sing-box that subbox must not disturb.
