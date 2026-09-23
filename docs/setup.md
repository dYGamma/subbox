# Setup, step by step

Written for someone who has never configured sing-box by hand.

## 1. Find your subscription URL

Every panel calls it something slightly different. You are looking for a single
`https://` link that ends in a long random string — not a QR code, and not the
per-node "share link".

| Panel | Where it is |
|---|---|
| 3x-ui | Inbounds → your client row → the **Subscription URL** button |
| Marzban | The user's page → **Subscription link**, the copy icon next to it |
| Hiddify | User area → **Copy subscription link** |
| Anything else | Look for a link labelled "subscription", "sub", or "подписка" |

That link is a credential: anyone who has it can use your account. `subbox`
stores it in a file only you can read, and never prints it in full.

If your panel gives you a per-application link ("for Clash", "for v2rayN", and
so on), pick the generic one. `subbox` reads the standard base64 list of share
links that nearly every panel serves.

## 2. Run the wizard

```bash
subbox setup
```

**Subscription URL from your panel.** Paste the link. `subbox` fetches it
immediately and prints the nodes it found, so you find out right away whether
the link works rather than after filling in the rest of the form.

If the fetch fails, the wizard says why and asks again; it does not abort.

If your panel uses a self-signed certificate, you will be told so and asked
whether to fetch without verifying. Saying yes means anyone on the network path
can read your subscription. Say no unless you know that is your situation.

**Local proxy port.** The port applications will point at. The default is 1080,
or the next free port if 1080 is taken. Anything already in use is refused.

**Serve a PAC file.** Say yes if you want a browser to send only some domains
through the proxy. Say no if you will set proxy environment variables by hand.

**Which domains.** Either the small default list of AI services, a broader list
that also covers social networks, or your own comma-separated list. You can
change this later in `config.toml` and run `subbox pac`.

## 3. Verify

```bash
subbox doctor
```

Everything should report `ok`. If something does not, the line says what the
symptom looks like and what to do about it.

Then check it by hand. Through the proxy:

```bash
curl -x http://127.0.0.1:1080 -o /dev/null -w '%{http_code}\n' https://www.gstatic.com/generate_204
```

Expect `204`.

And confirm your traffic actually comes out somewhere else:

```bash
curl -x http://127.0.0.1:1080 https://api.ipify.org
curl https://api.ipify.org
```

Expect two different addresses. If they match, the proxy is answering but not
forwarding.

## 4. Point things at it

For a shell, and anything that reads the usual variables:

```bash
export HTTPS_PROXY=http://127.0.0.1:1080
export HTTP_PROXY=http://127.0.0.1:1080
export ALL_PROXY=socks5h://127.0.0.1:1080
export NO_PROXY=localhost,127.0.0.1,::1
```

For a browser, set **Automatic proxy configuration URL** to
`http://127.0.0.1:7777/proxy.pac`. In Firefox that is Settings → Network
Settings → Automatic proxy configuration URL. Chrome uses the system proxy
settings; on GNOME that is Settings → Network → Network Proxy → Automatic.

## 5. Later

When your panel changes nodes:

```bash
subbox sync
```

Or press `u` in the dashboard. The new configuration is validated by `sing-box`
before it replaces the working one, so a bad subscription cannot leave you
without a proxy.

To survive logout, if your machine does not already do this:

```bash
loginctl enable-linger "$USER"
```

Without it, systemd stops your user services when your last session ends.
