from subbox import config, tui


def snap(**over):
    base = dict(
        configured=True, proxy_unit_state="active", proxy_pid="123",
        proxy_listening=True, pac_enabled=True, pac_state="active",
        pac_listening=True, clash_up=True, selector="auto", node="Main",
        node_count=3, reach_direct=204, reach_proxy=204,
        ip_direct="198.51.100.4", ip_proxy="203.0.113.7",
        listen_port=1080, pac_port=7777,
    )
    base.update(over)
    return tui.Snapshot(**base)


def rows(s):
    return {label: (value, status) for label, value, status in tui.render(s)}


def test_healthy_snapshot_renders_all_pass():
    assert all(status in ("pass", "plain")
               for _, _, status in tui.render(snap()))


def test_dead_port_is_flagged():
    value, status = rows(snap(proxy_listening=False))["proxy port"]
    assert status == "fail"


def test_identical_exit_ips_are_flagged():
    value, status = rows(snap(ip_proxy="198.51.100.4"))["exit address"]
    assert status == "fail"
    assert "not tunnelled" in value


def test_unreachable_shows_the_probe_pair():
    value, _ = rows(snap(reach_direct=204, reach_proxy=403))["reachability"]
    assert "204" in value and "403" in value


def test_a_status_outside_reach_ok_is_not_called_healthy():
    """A geo-blocked 403 arriving through the tunnel is not a pass."""
    _, status = rows(snap(reach_proxy=403))["reachability"]
    assert status == "fail"


def test_unconfigured_snapshot_says_so_rather_than_showing_blanks():
    value, status = rows(snap(configured=False))["subscription"]
    assert status == "fail"
    assert "setup" in value


def test_every_action_key_is_unique():
    keys = [a.key for a in tui.ACTIONS]
    assert len(keys) == len(set(keys))


def test_quit_and_the_core_actions_are_present():
    keys = {a.key for a in tui.ACTIONS}
    assert {"q", "u", "r", "p", "d", "t"} <= keys


def test_every_action_maps_to_a_real_handler():
    for action in tui.ACTIONS:
        assert hasattr(tui.App, action.handler_name), action.handler_name


def test_destructive_actions_require_confirmation():
    stop = next(a for a in tui.ACTIONS if a.key == "x")
    assert stop.needs_confirm is True


def test_render_never_shows_the_subscription_url():
    cfg = config.load()
    cfg["subscription"]["url"] = "https://panel.example.invalid/sub/SECRET"
    text = " ".join(f"{a} {b}" for a, b, _ in tui.render(snap()))
    assert "SECRET" not in text


def test_collect_maps_every_field_from_its_source(monkeypatch):
    cfg = config.load()
    cfg["subscription"]["url"] = "https://panel.example.invalid/sub/x"
    monkeypatch.setattr(tui.units, "state", lambda unit: "active")
    monkeypatch.setattr(tui.units, "main_pid", lambda unit: "77")
    monkeypatch.setattr(tui.probe, "port_listening", lambda port, **kw: True)

    class FakeClash:
        def __init__(self, cfg):
            pass

        def available(self):
            return True

        def current(self):
            return "auto", "Main"

        def nodes(self):
            return [object(), object()]

    monkeypatch.setattr(tui.clash, "Clash", FakeClash)
    s = tui.collect(cfg)
    assert s.configured is True
    assert s.proxy_unit_state == "active"
    assert s.proxy_pid == "77"
    assert s.proxy_listening is True
    assert s.clash_up is True
    assert (s.selector, s.node) == ("auto", "Main")
    assert s.node_count == 2
    assert s.reach_proxy is None  # network checks are opt-in
