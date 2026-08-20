import base64
import ssl

import pytest

from subbox import subscription

RAW = (
    "vless://00000000-0000-0000-0000-000000000000@a.example.invalid:443#A\n"
    "trojan://pw@b.example.invalid:443#B\n"
)


def test_decode_plaintext_body():
    assert subscription.decode(RAW) == [
        "vless://00000000-0000-0000-0000-000000000000@a.example.invalid:443#A",
        "trojan://pw@b.example.invalid:443#B",
    ]


def test_decode_base64_body():
    encoded = base64.b64encode(RAW.encode()).decode()
    assert subscription.decode(encoded) == subscription.decode(RAW)


def test_decode_base64_without_padding():
    encoded = base64.urlsafe_b64encode(RAW.encode()).decode().rstrip("=")
    assert subscription.decode(encoded) == subscription.decode(RAW)


def test_decode_skips_blank_and_non_link_lines():
    assert subscription.decode("\n# a comment\n\nvless://x@h.invalid:1#N\n") == [
        "vless://x@h.invalid:1#N"]


def test_decode_empty_body_yields_nothing():
    assert subscription.decode("   \n\n") == []


def test_fetch_passes_through_body(monkeypatch):
    monkeypatch.setattr(subscription, "_read", lambda url, timeout, ctx: RAW)
    assert subscription.fetch("https://panel.example.invalid/sub/x") == RAW


def test_fetch_verifies_tls_by_default(monkeypatch):
    captured = {}

    def fake_read(url, timeout, ctx):
        captured["verify_mode"] = ctx.verify_mode
        captured["check_hostname"] = ctx.check_hostname
        return RAW

    monkeypatch.setattr(subscription, "_read", fake_read)
    subscription.fetch("https://panel.example.invalid/sub/x")
    assert captured["verify_mode"] == ssl.CERT_REQUIRED
    assert captured["check_hostname"] is True


def test_fetch_insecure_is_opt_in(monkeypatch):
    captured = {}

    def fake_read(url, timeout, ctx):
        captured["verify_mode"] = ctx.verify_mode
        return RAW

    monkeypatch.setattr(subscription, "_read", fake_read)
    subscription.fetch("https://panel.example.invalid/sub/x", insecure=True)
    assert captured["verify_mode"] == ssl.CERT_NONE


def test_tls_failure_raises_a_typed_error_with_advice(monkeypatch):
    def boom(url, timeout, ctx):
        raise ssl.SSLCertVerificationError("self signed certificate")

    monkeypatch.setattr(subscription, "_read", boom)
    with pytest.raises(subscription.TlsError) as exc:
        subscription.fetch("https://panel.example.invalid/sub/x")
    assert "insecure" in str(exc.value)


def test_errors_never_echo_the_full_url(monkeypatch):
    """The subscription URL is a credential and must not leak into logs."""
    secret = "https://panel.example.invalid/sub/SUPERSECRETTOKEN"

    def boom(url, timeout, ctx):
        raise OSError("connection refused")

    monkeypatch.setattr(subscription, "_read", boom)
    with pytest.raises(subscription.SubscriptionError) as exc:
        subscription.fetch(secret)
    assert "SUPERSECRETTOKEN" not in str(exc.value)
    assert "panel.example.invalid" in str(exc.value)


def test_links_from_combines_fetch_and_decode(monkeypatch):
    monkeypatch.setattr(subscription, "_read", lambda url, timeout, ctx: RAW)
    assert len(subscription.links_from("https://panel.example.invalid/s")) == 2
