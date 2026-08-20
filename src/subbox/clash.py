"""Client for sing-box's Clash API — live node listing, switching, latency."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config, probe
from .generate import SELECTOR_TAG, URLTEST_TAG


class ClashError(Exception):
    """The API could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Node:
    tag: str
    type: str
    delay: int | None

    @property
    def delay_text(self) -> str:
        return f"{self.delay}ms" if self.delay else "-"


class Clash:
    def __init__(self, cfg: dict) -> None:
        self._port = cfg["proxy"]["clash_port"]
        self._latency_url = cfg["probe"]["latency_url"]
        self.base = f"http://127.0.0.1:{self._port}"

    def available(self) -> bool:
        return probe.port_listening(self._port)

    def _request(self, path: str, method: str = "GET",
                 body: dict | None = None, timeout: float = 10):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {config.clash_secret()}")
        if data:
            req.add_header("Content-Type", "application/json")
        # An ambient proxy must not be used to reach our own loopback API.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise ClashError(
                f"Clash API on port {self._port} is unreachable: {exc}") from exc
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ClashError("Clash API returned invalid JSON") from exc

    def proxies(self) -> dict:
        return self._request("/proxies").get("proxies", {})

    def nodes(self) -> list[Node]:
        """Real outbounds in selector order, without the urltest group."""
        proxies = self.proxies()
        order = [t for t in proxies.get(SELECTOR_TAG, {}).get("all", [])
                 if t != URLTEST_TAG]
        result = []
        for tag in order:
            entry = proxies.get(tag, {})
            history = entry.get("history") or [{}]
            result.append(Node(
                tag=tag,
                type=entry.get("type", "?"),
                delay=history[-1].get("delay") or None,
            ))
        return result

    def current(self) -> tuple[str, str]:
        """(what the selector points at, which node carries traffic)."""
        proxies = self.proxies()
        selector = (proxies.get(SELECTOR_TAG) or {}).get("now", "")
        node = selector
        if selector == URLTEST_TAG:
            node = (proxies.get(URLTEST_TAG) or {}).get("now") or "picking…"
        return selector or "?", node or "?"

    def select(self, name: str) -> None:
        self._request(f"/proxies/{urllib.parse.quote(SELECTOR_TAG)}",
                      method="PUT", body={"name": name})

    def measure(self, group: str | None = None,
                timeout_ms: int = 8000) -> dict[str, int]:
        query = urllib.parse.urlencode(
            {"url": self._latency_url, "timeout": timeout_ms})
        target = urllib.parse.quote(group or URLTEST_TAG)
        return self._request(f"/group/{target}/delay?{query}",
                             timeout=timeout_ms / 1000 + 10)
