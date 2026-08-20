import stat
import tomllib

import pytest

from subbox import config, paths


def test_defaults_are_complete_and_neutral():
    d = config.DEFAULTS
    assert d["subscription"]["url"] == ""
    assert d["subscription"]["insecure"] is False
    assert d["proxy"]["listen_addr"] == "127.0.0.1"
    assert d["proxy"]["listen_port"] == 1080
    assert d["proxy"]["clash_port"] == 9090
    assert d["pac"]["enabled"] is True
    assert d["pac"]["port"] == 7777
    # The core ships a vendor-neutral probe; the Claude module changes it.
    assert d["probe"]["reach_url"] == "https://www.gstatic.com/generate_204"
    assert d["probe"]["reach_ok"] == [204]


def test_round_trip_through_real_toml_parser():
    cfg = config.DEFAULTS
    reparsed = tomllib.loads(config.dumps(cfg))
    assert reparsed == cfg


def test_dumps_emits_comments():
    text = config.dumps(config.DEFAULTS)
    assert "# " in text
    assert "MITM" in text  # the insecure flag must carry its warning


def test_save_creates_file_private():
    config.save(config.DEFAULTS)
    mode = stat.S_IMODE(paths.config_file().stat().st_mode)
    assert oct(mode) == "0o600"


def test_save_tightens_a_world_readable_file():
    """A subscription URL is a credential; a 0644 config is a leak."""
    paths.ensure_dirs()
    paths.config_file().write_text("")
    paths.config_file().chmod(0o644)
    config.save(config.DEFAULTS)
    assert oct(stat.S_IMODE(paths.config_file().stat().st_mode)) == "0o600"


def test_load_fills_missing_keys_from_defaults():
    """A config written by an older version must keep working."""
    paths.ensure_dirs()
    paths.config_file().write_text('[proxy]\nlisten_port = 1234\n')
    cfg = config.load()
    assert cfg["proxy"]["listen_port"] == 1234
    assert cfg["proxy"]["clash_port"] == config.DEFAULTS["proxy"]["clash_port"]
    assert cfg["pac"]["enabled"] is True


def test_load_returns_defaults_when_absent():
    assert config.load() == config.DEFAULTS


def test_is_configured_tracks_subscription_url():
    assert config.is_configured(config.load()) is False
    cfg = config.load()
    cfg["subscription"]["url"] = "https://panel.example.invalid/sub/abc"
    assert config.is_configured(cfg) is True


@pytest.mark.parametrize(
    "mutate, expected_fragment",
    [
        (lambda c: c["proxy"].__setitem__("listen_port", 0), "listen_port"),
        (lambda c: c["proxy"].__setitem__("listen_port", 70000), "listen_port"),
        (lambda c: c["pac"].__setitem__("port", -1), "port"),
        (lambda c: c["proxy"].__setitem__("clash_port", 1080), "must differ"),
        (lambda c: c["subscription"].__setitem__("url", "ftp://x.invalid"), "http"),
        (lambda c: c["probe"].__setitem__("reach_ok", []), "reach_ok"),
    ],
)
def test_validate_rejects_bad_values(mutate, expected_fragment):
    cfg = config.load()
    cfg["proxy"]["listen_port"] = 1080
    cfg["proxy"]["clash_port"] = 9090
    mutate(cfg)
    errors = config.validate(cfg)
    assert any(expected_fragment in e for e in errors), errors


def test_validate_accepts_defaults():
    assert config.validate(config.DEFAULTS) == []


def test_clash_secret_is_stable_and_private():
    first = config.clash_secret()
    assert first == config.clash_secret()
    assert len(first) >= 24
    mode = stat.S_IMODE(paths.clash_secret_file().stat().st_mode)
    assert oct(mode) == "0o600"


def test_clash_secret_not_stored_in_config():
    """Kept separate so a user can share config.toml after removing one line."""
    config.clash_secret()
    config.save(config.load())
    assert "secret" not in paths.config_file().read_text()
