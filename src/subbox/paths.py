"""Every filesystem location subbox uses.

Centralised so that no other module calls expanduser, and so that setting
SUBBOX_HOME relocates an entire instance — which is how a development copy
runs beside a production one without touching it.
"""
from __future__ import annotations

import os
from pathlib import Path

APP = "subbox"


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _root(kind: str, xdg_var: str, fallback: Path) -> Path:
    override = os.environ.get("SUBBOX_HOME")
    if override:
        return Path(override) / kind
    base = os.environ.get(xdg_var)
    return (Path(base) if base else fallback) / APP


def config_dir() -> Path:
    return _root("config", "XDG_CONFIG_HOME", _home() / ".config")


def data_dir() -> Path:
    return _root("data", "XDG_DATA_HOME", _home() / ".local" / "share")


def cache_dir() -> Path:
    return _root("cache", "XDG_CACHE_HOME", _home() / ".cache")


def config_file() -> Path:
    return config_dir() / "config.toml"


def clash_secret_file() -> Path:
    return config_dir() / "clash.secret"


def singbox_config() -> Path:
    return config_dir() / "sing-box.json"


def pac_file() -> Path:
    return data_dir() / "proxy.pac"


def cache_db() -> Path:
    return cache_dir() / "cache.db"


def user_unit_dir() -> Path:
    """Where systemd looks for user units.

    Not relocatable by SUBBOX_HOME — systemd reads this path and no other.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else _home() / ".config") / "systemd" / "user"


def tilde(path: Path) -> str:
    """Render a path with the home directory abbreviated, as a shell prompt does.

    The dashboard header is one line wide; an absolute path pushes the rest
    of it off the screen.
    """
    home = _home()
    try:
        return str(Path("~") / path.relative_to(home))
    except ValueError:
        return str(path)


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        d.chmod(0o700)
