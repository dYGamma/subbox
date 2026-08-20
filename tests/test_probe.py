import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from subbox import config, probe


@pytest.fixture
def closed_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def open_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    yield sock.getsockname()[1]
    sock.close()


def test_port_listening_true_for_a_bound_port(open_port):
    assert probe.port_listening(open_port) is True


def test_port_listening_false_for_a_free_port(closed_port):
    assert probe.port_listening(closed_port) is False


class _Echo(BaseHTTPRequestHandler):
    status = 204

    def do_GET(self):  # noqa: N802
        self.send_response(self.status)
        body = b"203.0.113.9"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def http_server():
    httpd = HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}/"
    httpd.shutdown()


def test_http_status_returns_the_code(http_server):
    assert probe.http_status(http_server) == 204


def test_http_status_reports_error_codes_rather_than_raising(http_server, monkeypatch):
    monkeypatch.setattr(_Echo, "status", 403)
    assert probe.http_status(http_server) == 403


def test_http_status_returns_none_when_unreachable(closed_port):
    assert probe.http_status(f"http://127.0.0.1:{closed_port}/") is None


def test_http_status_does_not_inherit_ambient_proxy_env(monkeypatch, http_server):
    """A stale HTTPS_PROXY in the environment would silently skew every probe."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert probe.http_status(http_server) == 204


def test_public_ip_reads_the_body(monkeypatch, http_server):
    # 200, not the handler's default 204: a 204 carries no body by
    # definition, so http.client would hand back an empty string.
    monkeypatch.setattr(_Echo, "status", 200)
    monkeypatch.setattr(probe, "IPIFY_URL", http_server)
    assert probe.public_ip() == "203.0.113.9"


def test_public_ip_returns_none_when_unreachable(monkeypatch, closed_port):
    monkeypatch.setattr(probe, "IPIFY_URL", f"http://127.0.0.1:{closed_port}/")
    assert probe.public_ip() is None


def test_proxy_url_built_from_config():
    cfg = config.load()
    cfg["proxy"]["listen_addr"] = "127.0.0.1"
    cfg["proxy"]["listen_port"] = 1080
    assert probe.proxy_url(cfg) == "http://127.0.0.1:1080"
