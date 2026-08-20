import http.client
import threading
from http.server import HTTPServer

import pytest

from subbox import config, pac, paths


def test_render_embeds_the_configured_port():
    text = pac.render(["example.com"], "127.0.0.1", 11080)
    assert "PROXY 127.0.0.1:11080" in text
    assert "SOCKS5 127.0.0.1:11080" in text


def test_render_matches_domain_and_subdomains():
    text = pac.render(["example.com"], "127.0.0.1", 1080)
    assert '"example.com"' in text
    assert "dnsDomainIs" in text or "shExpMatch" in text


def test_render_is_valid_javascript_shape():
    text = pac.render(["a.invalid", "b.invalid"], "127.0.0.1", 1080)
    assert text.count("function FindProxyForURL") == 1
    assert text.rstrip().endswith("}")
    assert text.count("{") == text.count("}")


def test_render_escapes_quotes_in_a_domain():
    """A domain list is user input and must not be able to break out."""
    text = pac.render(['ev"il.invalid'], "127.0.0.1", 1080)
    assert 'ev"il' not in text.replace('\\"', "")


def test_render_with_no_domains_sends_everything_direct():
    text = pac.render([], "127.0.0.1", 1080)
    assert 'return "DIRECT"' in text


def test_write_places_the_file_in_the_data_dir():
    out = pac.write(config.DEFAULTS)
    assert out == paths.pac_file()
    assert "FindProxyForURL" in out.read_text()


@pytest.fixture
def server():
    cfg = config.load()
    cfg["pac"]["domains"] = ["example.com"]
    pac.write(cfg)
    httpd = HTTPServer(("127.0.0.1", 0), pac.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address
    httpd.shutdown()


def test_pac_is_served_with_the_content_type_browsers_expect(server):
    host, port = server
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/proxy.pac")
    resp = conn.getresponse()
    body = resp.read().decode()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == pac.PAC_CONTENT_TYPE
    assert "example.com" in body


def test_nothing_but_the_pac_file_is_served(server):
    """The predecessor served a directory listing. This one serves one file."""
    host, port = server
    for path in ("/", "/../config.toml", "/index.html"):
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", path)
        assert conn.getresponse().status == 404
