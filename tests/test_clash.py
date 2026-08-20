import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from subbox import clash, config, generate

PROXIES = {
    "proxies": {
        "proxy": {"type": "Selector", "now": "auto",
                  "all": ["auto", "Main", "Backup"]},
        "auto": {"type": "URLTest", "now": "Main", "all": ["Main", "Backup"]},
        "Main": {"type": "Vless", "history": [{"delay": 42}]},
        "Backup": {"type": "Hysteria2", "history": []},
    }
}


class _Api(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str]] = []

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode() if length else ""

    def _respond(self, payload):
        blob = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):  # noqa: N802
        self.seen.append(("GET", self.path, self.headers.get("Authorization", "")))
        if self.path == "/proxies":
            self._respond(PROXIES)
        elif self.path.startswith("/group/"):
            self._respond({"Main": 42, "Backup": 130})
        else:
            self.send_error(404)

    def do_PUT(self):  # noqa: N802
        self.seen.append(("PUT", self.path, self._body()))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def api():
    _Api.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cfg = config.load()
    cfg["proxy"]["clash_port"] = httpd.server_address[1]
    yield cfg
    httpd.shutdown()


def test_available_follows_the_port(api):
    assert clash.Clash(api).available() is True
    api["proxy"]["clash_port"] = 1
    assert clash.Clash(api).available() is False


def test_requests_carry_the_bearer_token(api):
    clash.Clash(api).proxies()
    method, path, auth = _Api.seen[0]
    assert path == "/proxies"
    assert auth.startswith("Bearer ")
    assert auth.split(" ", 1)[1] == config.clash_secret()


def test_nodes_follow_selector_order_and_exclude_the_urltest_group(api):
    nodes = clash.Clash(api).nodes()
    assert [n.tag for n in nodes] == ["Main", "Backup"]
    assert nodes[0].type == "Vless"
    assert nodes[0].delay == 42
    assert nodes[1].delay is None


def test_delay_text_renders_missing_measurements_as_a_dash(api):
    nodes = clash.Clash(api).nodes()
    assert nodes[0].delay_text == "42ms"
    assert nodes[1].delay_text == "-"


def test_current_resolves_auto_to_the_node_actually_in_use(api):
    selector, node = clash.Clash(api).current()
    assert selector == generate.URLTEST_TAG
    assert node == "Main"


def test_select_puts_the_name_on_the_selector(api):
    clash.Clash(api).select("Backup")
    method, path, body = _Api.seen[-1]
    assert method == "PUT"
    assert path == f"/proxies/{generate.SELECTOR_TAG}"
    assert json.loads(body) == {"name": "Backup"}


def test_measure_returns_per_node_delays(api):
    assert clash.Clash(api).measure() == {"Main": 42, "Backup": 130}


def test_measure_uses_the_configured_latency_url(api):
    api["probe"]["latency_url"] = "https://probe.example.invalid/204"
    clash.Clash(api).measure()
    _, path, _ = _Api.seen[-1]
    assert "probe.example.invalid" in path


def test_a_dead_api_raises_clash_error_not_a_socket_error():
    cfg = config.load()
    cfg["proxy"]["clash_port"] = 1
    with pytest.raises(clash.ClashError):
        clash.Clash(cfg).proxies()
