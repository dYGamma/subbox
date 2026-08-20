"""Fetching a subscription and decoding it into share links."""
from __future__ import annotations

import base64
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse


class SubscriptionError(Exception):
    """Anything that stops a subscription from being retrieved."""


class TlsError(SubscriptionError):
    """Certificate verification failed."""


def _safe(url: str) -> str:
    """A URL rendering safe to put in an error message.

    The path carries the account token, so it never appears in full.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/…"


def _read(url: str, timeout: int, ctx: ssl.SSLContext) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "sing-box"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch(url: str, timeout: int = 25, insecure: bool = False) -> str:
    ctx = ssl.create_default_context()
    if insecure:
        # Opt-in only: the subscription body is a credential, so an
        # unverified fetch hands it to anyone on the path.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        return _read(url, timeout, ctx)
    except ssl.SSLError as exc:
        raise TlsError(
            f"TLS verification failed for {_safe(url)}: {exc}. "
            f"If this panel really uses a self-signed certificate, set "
            f"subscription.insecure = true — the subscription is then "
            f"exposed to interception."
        ) from exc
    except urllib.error.HTTPError as exc:
        raise SubscriptionError(
            f"{_safe(url)} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SubscriptionError(f"cannot reach {_safe(url)}: {exc}") from exc


def _b64_loose(data: str) -> str:
    data = "".join(data.split()).replace("-", "+").replace("_", "/")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data).decode("utf-8", "replace")


def decode(body: str) -> list[str]:
    """Return share links, whether the body was base64 or plain text."""
    body = body.strip()
    if not body:
        return []
    if "://" not in body:
        try:
            body = _b64_loose(body)
        except Exception as exc:
            raise SubscriptionError(
                "subscription body is neither share links nor valid base64"
            ) from exc
    return [ln.strip() for ln in body.splitlines()
            if ln.strip() and "://" in ln.strip()]


def links_from(url: str, insecure: bool = False) -> list[str]:
    return decode(fetch(url, insecure=insecure))
