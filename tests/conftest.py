import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test runs against a throwaway SUBBOX_HOME.

    Without this the suite would read and write the developer's real
    configuration and generated files.
    """
    home = tmp_path / "subbox-home"
    monkeypatch.setenv("SUBBOX_HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return home
