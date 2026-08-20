"""Answering 'is it up' and 'where does traffic come out'.

Built on urllib rather than shelling out to curl, so the tool has no
runtime dependency beyond the standard library.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

IPIFY_URL = "https://api.ipify.org"


def proxy_url(cfg: dict) -> str:
    return f"http://{cfg['proxy']['listen_addr']}:{cfg['proxy']['listen_port']}"


def port_listening(port: int, host: str = "127.0.0.1",
                   timeout: float = 0.3) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
    return True


def _opener(proxy: str | None) -> urllib.request.OpenerDirector:
    # ProxyHandler with an explicit mapping — an empty dict disables proxying
    # entirely, so an ambient HTTPS_PROXY cannot skew a direct probe.
    handlers = {"http": proxy, "https": proxy} if proxy else {}
    return urllib.request.build_opener(urllib.request.ProxyHandler(handlers))


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "subbox"})


def http_status(url: str, proxy: str | None = None,
                timeout: int = 8) -> int | None:
    """Return the status code, or None when the request could not complete.

    An HTTP error status is an answer, not a failure: 403 versus 401 is
    exactly the distinction that tells a blocked exit from a reachable one.
    """
    try:
        with _opener(proxy).open(_request(url), timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def public_ip(proxy: str | None = None, timeout: int = 6) -> str | None:
    try:
        with _opener(proxy).open(_request(IPIFY_URL), timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace").strip() or None
    except (urllib.error.URLError, OSError):
        return None
