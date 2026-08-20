"""Thin wrappers over `systemctl --user`.

Every function returns rather than raises, because a missing systemd or a
hung unit is a state the dashboard should display, not a crash.
"""
from __future__ import annotations

import shutil
import subprocess

PROXY_UNIT = "subbox.service"
PAC_UNIT = "subbox-pac.service"
ALL_UNITS = (PROXY_UNIT, PAC_UNIT)


def available() -> bool:
    return shutil.which("systemctl") is not None


def systemctl(*args: str, timeout: int = 10) -> tuple[int, str]:
    if not available():
        return 127, "systemctl not found; subbox needs systemd user units"
    cmd = ["systemctl", "--user", *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"`{' '.join(cmd)}` timed out after {timeout}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def is_active(unit: str) -> bool:
    return systemctl("is-active", unit, timeout=3)[0] == 0


def state(unit: str) -> str:
    return systemctl("is-active", unit, timeout=3)[1].strip() or "unknown"


def main_pid(unit: str) -> str:
    _, out = systemctl("show", unit, "--property=MainPID", "--value", timeout=3)
    pid = out.strip()
    return pid if pid and pid != "0" else "-"


def is_installed(unit: str) -> bool:
    code, out = systemctl("list-unit-files", unit, timeout=3)
    return code == 0 and unit in out


def start(unit: str) -> tuple[int, str]:
    return systemctl("start", unit)


def stop(unit: str) -> tuple[int, str]:
    return systemctl("stop", unit)


def restart(unit: str) -> tuple[int, str]:
    return systemctl("restart", unit, timeout=20)


def enable(unit: str) -> tuple[int, str]:
    return systemctl("enable", unit)


def disable(unit: str) -> tuple[int, str]:
    return systemctl("disable", unit)


def daemon_reload() -> tuple[int, str]:
    return systemctl("daemon-reload")
