import json
import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "integrations/claude-code/claude"
HOOK = ROOT / "integrations/claude-code/subbox-proxy-ensure.sh"


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def fake_env(tmp_path):
    """A PATH holding the wrapper and, after it, a stub 'real' claude.

    Autostart is disabled and the port is a closed one, so no test can
    reach the developer's systemd or their running proxy.
    """
    wrapper_dir = tmp_path / "wrapper"
    real_dir = tmp_path / "real"
    wrapper_dir.mkdir()
    real_dir.mkdir()

    (wrapper_dir / "claude").write_text(WRAPPER.read_text())
    (wrapper_dir / "claude").chmod(0o755)

    real = real_dir / "claude"
    real.write_text(
        "#!/usr/bin/env bash\n"
        'echo "HTTPS_PROXY=${HTTPS_PROXY:-unset}"\n'
        'echo "ARGS=$*"\n'
    )
    real.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{wrapper_dir}:{real_dir}:/usr/bin:/bin"
    env["SUBBOX_NO_AUTOSTART"] = "1"
    env["SUBBOX_PROXY_PORT"] = str(_closed_port())
    return wrapper_dir, env


def _run(argv, env):
    return subprocess.run(argv, capture_output=True, text=True, env=env,
                          timeout=20, check=False)


def test_wrapper_and_hook_are_executable():
    for path in (WRAPPER, HOOK):
        assert path.stat().st_mode & stat.S_IXUSR


def test_no_home_directory_is_hardcoded():
    """The predecessor hardcoded one user's home and could not be shipped."""
    for path in (WRAPPER, HOOK):
        assert "/home/" not in path.read_text()


def test_wrapper_execs_the_next_claude_on_path(fake_env):
    wrapper_dir, env = fake_env
    result = _run([str(wrapper_dir / "claude"), "--flag", "value"], env)
    assert result.returncode == 0, result.stderr
    assert "ARGS=--flag value" in result.stdout


def test_wrapper_exports_a_proxy_when_one_is_listening(fake_env):
    wrapper_dir, env = fake_env
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    env["SUBBOX_PROXY_PORT"] = str(sock.getsockname()[1])
    try:
        result = _run([str(wrapper_dir / "claude")], env)
    finally:
        sock.close()
    assert f"HTTPS_PROXY=http://127.0.0.1:{env['SUBBOX_PROXY_PORT']}" in result.stdout


def test_wrapper_runs_direct_and_warns_when_no_proxy(fake_env):
    """Direct must mean direct, even when the outer shell exported a proxy."""
    wrapper_dir, env = fake_env
    env["HTTPS_PROXY"] = "http://127.0.0.1:9"
    env["https_proxy"] = "http://127.0.0.1:9"
    result = _run([str(wrapper_dir / "claude")], env)
    assert "HTTPS_PROXY=unset" in result.stdout
    assert "no local proxy" in result.stderr


def test_wrapper_reports_a_missing_real_binary_instead_of_looping(tmp_path):
    """Only the wrapper on PATH: it must not exec itself."""
    wrapper_dir = tmp_path / "only"
    wrapper_dir.mkdir()
    (wrapper_dir / "claude").write_text(WRAPPER.read_text())
    (wrapper_dir / "claude").chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{wrapper_dir}:/usr/bin:/bin"
    env["SUBBOX_NO_AUTOSTART"] = "1"
    env["SUBBOX_PROXY_PORT"] = str(_closed_port())
    result = _run([str(wrapper_dir / "claude")], env)
    assert result.returncode == 127
    assert "CLAUDE_REAL_BIN" in result.stderr


def test_claude_real_bin_overrides_path_resolution(fake_env, tmp_path):
    wrapper_dir, env = fake_env
    chosen = tmp_path / "elsewhere-claude"
    chosen.write_text("#!/usr/bin/env bash\necho CHOSEN\n")
    chosen.chmod(0o755)
    env["CLAUDE_REAL_BIN"] = str(chosen)
    result = _run([str(wrapper_dir / "claude")], env)
    assert "CHOSEN" in result.stdout


def test_hook_is_silent_when_the_proxy_is_up(fake_env):
    _, env = fake_env
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    env["SUBBOX_PROXY_PORT"] = str(sock.getsockname()[1])
    try:
        result = _run([str(HOOK)], env)
    finally:
        sock.close()
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_emits_valid_json_when_the_proxy_is_down(fake_env):
    _, env = fake_env
    result = _run([str(HOOK)], env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "systemMessage" in payload
    assert "subbox doctor" in payload["systemMessage"]
