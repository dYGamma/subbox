# Claude Code integration

Optional. It makes the `claude` CLI go through the proxy subbox manages, and
warns you at the start of a session when no proxy is up. Nothing in the core
depends on it, and nothing here is needed to use subbox for anything else.

The reason it exists: the Anthropic API answers `403` to some source addresses.
A request refused at the edge looks like an authentication problem rather than
a network one, which is a confusing half hour the first time it happens.

## Install

```bash
make install-claude
```

That puts two files in place:

| File | Where | What it does |
|---|---|---|
| `claude` | `~/.local/share/subbox-claude/bin/claude` | A wrapper that exports the proxy variables and then execs the real binary |
| `subbox-proxy-ensure.sh` | `~/.claude/hooks/subbox-proxy-ensure.sh` | A `SessionStart` hook that starts the proxy if it is down |

Then put the wrapper ahead of the real binary on your `PATH`:

```bash
export PATH="$HOME/.local/share/subbox-claude/bin:$PATH"
```

Put that in the profile your terminal actually reads. If your terminal starts
fish or zsh, `~/.bashrc` is not it.

Check the order with `which -a claude`: the wrapper must come first, the real
binary second. The wrapper finds the real one by walking `PATH` and skipping
itself, so it never recurses.

## Register the hook

In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/subbox-proxy-ensure.sh" }
        ]
      }
    ]
  }
}
```

The hook prints nothing while the proxy is up, so it costs no context in the
normal case. It speaks only when there is nothing listening.

## Recommended probe setting

The core ships a vendor-neutral reachability probe. For this use, point it at
the API instead, in `~/.config/subbox/config.toml`:

```toml
[probe]
reach_url = "https://api.anthropic.com/v1/models"
reach_ok = [200, 401]
```

`401` means the endpoint was reached and simply had no credentials — which is
exactly what an unauthenticated probe should get. `403` means the exit address
was refused. Telling those two apart is the whole point, and a consumer web
page cannot do it: pages behind bot protection answer `403` to every client,
proxied or not, which makes a perfectly healthy tunnel look broken.

## Environment overrides

| Variable | Effect |
|---|---|
| `SUBBOX_PROXY_PORT` | Port to use and to wait for. Default `1080` |
| `CLAUDE_REAL_BIN` | Full path to the real binary, skipping `PATH` resolution |
| `SUBBOX_NO_AUTOSTART` | Never try to start `subbox.service`; just report |

## Behaviour when there is no proxy

The wrapper clears every proxy variable, including ones inherited from the
surrounding shell, and says so on stderr before running. "Running direct" then
means it: an inherited, stale proxy will not silently be used instead.

## Remove

```bash
make uninstall-claude
```

Then drop the `PATH` line from your profile and the hook entry from
`settings.json`. `make uninstall` deliberately leaves these alone, because
`~/.claude` holds files subbox did not put there.
