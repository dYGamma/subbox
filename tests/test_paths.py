import os
from pathlib import Path

from subbox import paths


def test_subbox_home_overrides_all_three_roots(isolated_home):
    assert paths.config_dir() == isolated_home / "config"
    assert paths.data_dir() == isolated_home / "data"
    assert paths.cache_dir() == isolated_home / "cache"


def test_xdg_used_when_subbox_home_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBBOX_HOME")
    assert paths.config_dir() == Path(os.environ["XDG_CONFIG_HOME"]) / "subbox"
    assert paths.data_dir() == Path(os.environ["XDG_DATA_HOME"]) / "subbox"
    assert paths.cache_dir() == Path(os.environ["XDG_CACHE_HOME"]) / "subbox"


def test_home_defaults_when_xdg_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBBOX_HOME")
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(var)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.config_dir() == tmp_path / ".config" / "subbox"
    assert paths.data_dir() == tmp_path / ".local" / "share" / "subbox"
    assert paths.cache_dir() == tmp_path / ".cache" / "subbox"


def test_generated_config_never_lands_in_sing_box_dir(monkeypatch, tmp_path):
    """Overwriting a hand-written sing-box config would destroy user work."""
    monkeypatch.delenv("SUBBOX_HOME")
    generated = paths.singbox_config()
    assert generated.name == "sing-box.json"
    assert "sing-box" not in generated.parent.name
    assert generated.parent == paths.config_dir()


def test_file_paths_sit_under_their_roots(isolated_home):
    assert paths.config_file() == paths.config_dir() / "config.toml"
    assert paths.clash_secret_file() == paths.config_dir() / "clash.secret"
    assert paths.pac_file() == paths.data_dir() / "proxy.pac"
    assert paths.cache_db() == paths.cache_dir() / "cache.db"


def test_ensure_dirs_creates_with_private_mode(isolated_home):
    paths.ensure_dirs()
    for d in (paths.config_dir(), paths.data_dir(), paths.cache_dir()):
        assert d.is_dir()
        assert oct(d.stat().st_mode & 0o777) == "0o700"


def test_tilde_abbreviates_the_home_directory(monkeypatch, tmp_path):
    """The dashboard header is one line wide; an absolute path overflows it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.tilde(tmp_path / ".config" / "subbox" / "config.toml") == (
        "~/.config/subbox/config.toml")


def test_tilde_leaves_paths_outside_home_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert paths.tilde(Path("/etc/subbox.toml")) == "/etc/subbox.toml"
