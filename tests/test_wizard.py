import stat

import pytest

from subbox import config, paths, wizard

NODE_LINK = ("vless://00000000-0000-0000-0000-000000000000@203.0.113.7:443"
             "?security=tls&sni=a.example.invalid#Main")
URL = "https://panel.example.invalid/sub/x"


class Script:
    """Feeds scripted answers and records what the wizard printed."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.lines: list[str] = []

    def ask(self, prompt):
        self.lines.append(prompt)
        if not self.answers:
            raise AssertionError(f"wizard asked more than scripted: {prompt!r}")
        return self.answers.pop(0)

    def out(self, line=""):
        self.lines.append(str(line))

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(wizard.subscription, "links_from",
                        lambda url, insecure=False: [NODE_LINK])
    monkeypatch.setattr(wizard.generate, "check", lambda path: (True, ""))
    monkeypatch.setattr(wizard.units, "available", lambda: True)
    monkeypatch.setattr(wizard.units, "is_installed", lambda unit: True)
    monkeypatch.setattr(wizard.units, "enable", lambda unit: (0, ""))
    monkeypatch.setattr(wizard.units, "restart", lambda unit: (0, ""))
    monkeypatch.setattr(wizard.probe, "port_listening", lambda port, **kw: False)
    monkeypatch.setattr(wizard.doctor, "run", lambda cfg: [])


def test_happy_path_writes_config_and_generates_everything(offline):
    script = Script([URL, "", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0

    cfg = config.load()
    assert cfg["subscription"]["url"] == URL
    assert cfg["proxy"]["listen_port"] == 1080
    assert paths.singbox_config().exists()
    assert paths.pac_file().exists()


def test_nodes_are_shown_before_any_further_question(offline):
    script = Script([URL, "", "", "", "1"])
    wizard.run(ask=script.ask, out=script.out)
    assert script.text.index("Main") < script.text.index("port")


def test_config_is_written_private(offline):
    script = Script([URL, "", "", "", "1"])
    wizard.run(ask=script.ask, out=script.out)
    assert oct(stat.S_IMODE(paths.config_file().stat().st_mode)) == "0o600"


def test_subscription_is_retried_rather_than_aborting(offline, monkeypatch):
    calls = {"n": 0}

    def flaky(url, insecure=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise wizard.subscription.SubscriptionError("cannot reach host")
        return [NODE_LINK]

    monkeypatch.setattr(wizard.subscription, "links_from", flaky)
    script = Script(["https://bad.example.invalid/s", URL, "", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    assert "cannot reach host" in script.text


def test_tls_failure_offers_insecure_and_records_the_choice(offline, monkeypatch):
    def flaky(url, insecure=False):
        if not insecure:
            raise wizard.subscription.TlsError("self signed certificate")
        return [NODE_LINK]

    monkeypatch.setattr(wizard.subscription, "links_from", flaky)
    script = Script([URL, "y", "", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    assert config.load()["subscription"]["insecure"] is True
    assert "intercept" in script.text.lower()


def test_declining_insecure_asks_for_another_url(offline, monkeypatch):
    """Refusing to downgrade must not silently proceed unverified."""
    def always_tls(url, insecure=False):
        if "good" not in url:
            raise wizard.subscription.TlsError("self signed certificate")
        return [NODE_LINK]

    monkeypatch.setattr(wizard.subscription, "links_from", always_tls)
    script = Script([URL, "n", "https://good.example.invalid/s", "", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    assert config.load()["subscription"]["insecure"] is False


def test_a_busy_port_is_rejected_and_asked_again(offline, monkeypatch):
    monkeypatch.setattr(wizard.probe, "port_listening",
                        lambda port, **kw: port == 1080)
    script = Script([URL, "1080", "1081", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    assert config.load()["proxy"]["listen_port"] == 1081
    assert "in use" in script.text


def test_declining_pac_skips_its_questions(offline):
    script = Script([URL, "", "n"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    cfg = config.load()
    assert cfg["pac"]["enabled"] is False
    assert not paths.pac_file().exists()


def test_domain_set_choice_two_uses_the_broader_list(offline):
    script = Script([URL, "", "", "", "2"])
    wizard.run(ask=script.ask, out=script.out)
    assert set(config.load()["pac"]["domains"]) == set(wizard.RU_DOMAINS)


def test_custom_domain_list_is_split_and_cleaned(offline):
    script = Script([URL, "", "", "", "3", " a.invalid, b.invalid ,, c.invalid "])
    wizard.run(ask=script.ask, out=script.out)
    assert config.load()["pac"]["domains"] == ["a.invalid", "b.invalid", "c.invalid"]


def test_wizard_never_echoes_the_full_url_back(offline):
    script = Script([URL, "", "", "", "1"])
    wizard.run(ask=script.ask, out=script.out)
    assert "/sub/x" not in script.text


def test_aborting_at_the_first_question_changes_nothing(offline):
    script = Script([""])
    assert wizard.run(ask=script.ask, out=script.out) == 2
    assert not paths.config_file().exists()


def test_a_busy_default_port_is_replaced_by_a_free_suggestion(offline, monkeypatch):
    """Re-offering a port just refused means Enter cannot make progress."""
    monkeypatch.setattr(wizard.probe, "port_listening",
                        lambda port, **kw: port in (1080, 7777))
    script = Script([URL, "", "", "", "1"])
    assert wizard.run(ask=script.ask, out=script.out) == 0
    cfg = config.load()
    assert cfg["proxy"]["listen_port"] == 1081
    assert cfg["pac"]["port"] == 7778
    assert "Local proxy port [1081]" in script.text


def test_end_of_input_ends_the_wizard_cleanly(offline):
    """A piped stdin that runs out must not produce a traceback."""
    def ask(prompt):
        raise EOFError

    lines = []
    assert wizard.run(ask=ask, out=lines.append) == 2
    assert any("did not finish" in line for line in lines)


def test_interrupt_ends_the_wizard_cleanly(offline):
    def ask(prompt):
        raise KeyboardInterrupt

    lines = []
    assert wizard.run(ask=ask, out=lines.append) == 2
    assert any("did not finish" in line for line in lines)


def test_subscription_is_read_through_the_secret_reader(offline):
    """It is a credential; echoing it leaves it in scrollback and screenshots."""
    seen = {"secret": [], "plain": []}

    def ask(prompt):
        seen["plain"].append(prompt)
        return ""

    def ask_secret(prompt):
        seen["secret"].append(prompt)
        return URL

    lines = []
    assert wizard.run(ask=ask, out=lines.append, ask_secret=ask_secret) == 0
    assert any("Subscription URL" in p for p in seen["secret"])
    assert not any("Subscription URL" in p for p in seen["plain"])


def test_every_question_says_what_it_is_for(offline):
    """A bare 'Local proxy port [1080]:' does not tell anyone what to type."""
    script = Script([URL, "", "", "", "1"])
    wizard.run(ask=script.ask, out=script.out)
    text = script.text
    assert "Press Enter at any question to accept the value in brackets" in text
    assert "applications will connect to" in text
    assert "only the domains you choose" in text
    assert "browser fetches the PAC file" in text


def test_the_secret_reader_falls_back_when_there_is_no_terminal(monkeypatch):
    """Piped input must still work; getpass would fail on a closed stdin."""
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: False)
    read = wizard._secret_reader(lambda prompt: "typed")
    assert read("Subscription URL: ") == "typed"
