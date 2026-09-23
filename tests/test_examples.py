from pathlib import Path

from subbox import config

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_example_matches_the_defaults():
    """A stale example config is worse than none — people copy it."""
    example = ROOT / "examples/config.toml"
    assert example.read_text() == config.dumps(config.DEFAULTS)


def test_both_readmes_exist_and_are_not_stubs():
    for name in ("README.md", "README.ru.md"):
        text = (ROOT / name).read_text()
        assert len(text) > 2000, f"{name} looks like a stub"
        assert "subbox" in text


def test_readmes_share_the_same_commands():
    """The translation must not drift on anything executable."""
    import re

    def blocks(name):
        text = (ROOT / name).read_text()
        return [b.strip() for b in re.findall(r"```(?:bash|console|toml|json)\n(.*?)```",
                                              text, re.S)]

    assert blocks("README.md") == blocks("README.ru.md")
