# Troubleshooting

Organised by what you see, because recognising the symptom is the hard part.
`subbox doctor` checks for most of these automatically.

## `dial tcp <server>: i/o timeout`, but the server is fine

You can reach the server port directly — `nc -vz <server> <port>` succeeds —
yet sing-box times out dialling it.

**Cause.** `route.auto_detect_interface` is true, so sing-box binds its own
outgoing connections to whatever tunnel interface happens to be up, typically
another VPN client's. Its dials then go into that tunnel and never come back.

**Fix.** `subbox sync` regenerates with the correct value. If another VPN is
running, note that it changes what every other check here means.

## sing-box exits immediately and says nothing useful

`systemctl --user status subbox` shows it starting and stopping, with no clear
error.

**Cause.** The `cache_file` directory does not exist. sing-box 1.13 refuses to
start in that case and the message does not name the directory.

**Fix.** `subbox doctor` names it. `mkdir -p ~/.cache/subbox`.

## Everything is up, but a site still fails

`subbox status` is happy, the port is listening, and a particular site or API
still refuses you.

**Cause.** The tunnel works; the exit address is what is being refused. This is
not a proxy failure.

**Fix.** Compare the two numbers in `subbox doctor`'s reachability line. A good
direct status and a bad proxied one means the exit is blocked. Switch nodes:
run `subbox`, press `p`, pick another.

## The reachability probe returns 403 no matter what

Both the direct and the proxied probe come back 403.

**Cause.** `probe.reach_url` points at a consumer web page. Pages behind bot
protection answer 403 to every client, proxied or not, so the probe cannot tell
a healthy tunnel from a blocked one.

**Fix.** Point `probe.reach_url` at an API endpoint. `subbox doctor` warns when
it recognises one of the common offenders.

## The dashboard says "clash api down"

**Cause.** The generated configuration predates the Clash API block, or sing-box
is not running.

**Fix.** `subbox sync`, then check `systemctl --user status subbox`.

## Both exit addresses are the same

`subbox doctor` reports the same address direct and through the proxy.

**Cause.** The proxy is accepting connections but not forwarding them — usually
every node is unreachable.

**Fix.** Press `d` in the dashboard to measure each node. If all of them time
out, the server or your route to it is the problem, not subbox.

## `subbox: command not found` after installing

**Cause.** `~/.local/bin` is not on your `PATH`.

**Fix.**

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Put it in the profile your terminal actually reads. If your terminal starts
fish or zsh, `~/.bashrc` is not that file.

## The launcher starts and says it cannot import subbox

You installed with a custom `PREFIX`.

**Cause.** That prefix is not on the Python interpreter's import path, so the
console script cannot find its own package. `make install` detects this and
refuses rather than leaving you a broken command.

**Fix.** Install with the default `PREFIX=$HOME/.local`, or export
`PYTHONPATH=<prefix>/lib/pythonX.Y/site-packages`.

## A development instance under `SUBBOX_HOME` is ignored by systemd

**Cause.** Unit files are static and point at the XDG paths. `SUBBOX_HOME`
relocates the instance's own files, not what systemd reads.

**Fix.** Run that instance in the foreground:

```bash
SUBBOX_HOME=/tmp/subbox-dev subbox sync
SUBBOX_HOME=/tmp/subbox-dev sing-box run -c /tmp/subbox-dev/config/sing-box.json
```

## Services do not come back after logout

**Cause.** systemd stops user services when your last session ends.

**Fix.**

```bash
loginctl enable-linger "$USER"
```

## Anything else

```bash
subbox doctor
systemctl --user status subbox --no-pager -n 50
```

If you open an issue, `config.toml` is safe to attach **after** you remove the
`url` line. The separate `clash.secret` file never needs to be shared.
