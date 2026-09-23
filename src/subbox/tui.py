"""Curses dashboard.

Rendering is a pure function over a snapshot so the layout can be tested
without a terminal; only the event loop below touches curses.
"""
from __future__ import annotations

import contextlib
import curses
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import clash, config, doctor, generate, pac, paths, probe, units, wizard

PASS, WARN, FAIL, PLAIN = "pass", "warn", "fail", "plain"


@dataclass
class Snapshot:
    configured: bool = False
    proxy_unit_state: str = "?"
    proxy_pid: str = "-"
    proxy_listening: bool = False
    pac_enabled: bool = True
    pac_state: str = "?"
    pac_listening: bool = False
    clash_up: bool = False
    selector: str = "?"
    node: str = "?"
    node_count: int = 0
    reach_direct: int | None = None
    reach_proxy: int | None = None
    reach_ok: tuple[int, ...] = (204,)
    ip_direct: str | None = None
    ip_proxy: str | None = None
    listen_port: int = 1080
    pac_port: int = 7777


def collect(cfg: dict, with_network: bool = False) -> Snapshot:
    snap = Snapshot(
        configured=config.is_configured(cfg),
        proxy_unit_state=units.state(units.PROXY_UNIT),
        proxy_pid=units.main_pid(units.PROXY_UNIT),
        proxy_listening=probe.port_listening(cfg["proxy"]["listen_port"]),
        pac_enabled=cfg["pac"]["enabled"],
        pac_state=units.state(units.PAC_UNIT),
        pac_listening=probe.port_listening(cfg["pac"]["port"]),
        reach_ok=tuple(cfg["probe"]["reach_ok"]),
        listen_port=cfg["proxy"]["listen_port"],
        pac_port=cfg["pac"]["port"],
    )
    api = clash.Clash(cfg)
    if api.available():
        try:
            snap.selector, snap.node = api.current()
            snap.node_count = len(api.nodes())
            snap.clash_up = True
        except clash.ClashError:
            snap.clash_up = False
    if with_network:
        proxy = probe.proxy_url(cfg)
        snap.reach_direct = probe.http_status(cfg["probe"]["reach_url"])
        snap.reach_proxy = probe.http_status(cfg["probe"]["reach_url"], proxy=proxy)
        snap.ip_direct = probe.public_ip()
        snap.ip_proxy = probe.public_ip(proxy=proxy)
    return snap


def _unit_row(label: str, state: str, pid: str) -> tuple[str, str, str]:
    status = PASS if state == "active" else FAIL
    return label, f"{state} (pid {pid})", status


def render(snap: Snapshot) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []

    rows.append(("subscription", "configured", PASS) if snap.configured else
                ("subscription", "not configured — run `subbox setup`", FAIL))
    rows.append(_unit_row("proxy service", snap.proxy_unit_state, snap.proxy_pid))
    rows.append(("proxy port", f"{snap.listen_port} listening", PASS)
                if snap.proxy_listening else
                ("proxy port", f"{snap.listen_port} dead", FAIL))

    if snap.pac_enabled:
        rows.append(("pac service", snap.pac_state,
                     PASS if snap.pac_state == "active" else FAIL))
        rows.append(("pac port", f"{snap.pac_port} listening", PASS)
                    if snap.pac_listening else
                    ("pac port", f"{snap.pac_port} dead", FAIL))
    else:
        rows.append(("pac service", "disabled", PLAIN))

    rows.append(("clash api", f"up, {snap.node_count} nodes", PASS)
                if snap.clash_up else ("clash api", "down", WARN))
    rows.append(("selected node", f"{snap.selector} → {snap.node}", PLAIN))

    if snap.reach_proxy is not None or snap.reach_direct is not None:
        direct = snap.reach_direct if snap.reach_direct is not None else "—"
        through = snap.reach_proxy if snap.reach_proxy is not None else "—"
        # Reaching the endpoint is not the same as being accepted by it: a
        # geo-blocked 403 arrives just fine and still means the exit is dead.
        status = PASS if snap.reach_proxy in snap.reach_ok else FAIL
        rows.append(("reachability",
                     f"direct {direct}, via proxy {through}", status))
    else:
        rows.append(("reachability", "not measured — press t", PLAIN))

    if snap.ip_proxy and snap.ip_direct:
        if snap.ip_proxy == snap.ip_direct:
            rows.append(("exit address",
                         f"{snap.ip_proxy} on both paths — traffic is not "
                         "tunnelled", FAIL))
        else:
            rows.append(("exit address",
                         f"direct {snap.ip_direct}, via proxy {snap.ip_proxy}",
                         PASS))
    else:
        rows.append(("exit address", "not measured — press i", PLAIN))
    return rows


@dataclass
class Action:
    key: str
    label: str
    handler_name: str
    needs_confirm: bool = False


ACTIONS: list[Action] = [
    Action("s", "Start proxy and PAC", "act_start"),
    Action("x", "Stop proxy and PAC", "act_stop", needs_confirm=True),
    Action("r", "Restart proxy", "act_restart"),
    Action("u", "Update nodes from subscription", "act_sync"),
    Action("p", "Pick node or auto", "act_pick"),
    Action("d", "Measure node latency", "act_delays"),
    Action("t", "Test reachability", "act_reach"),
    Action("i", "Show exit addresses", "act_ips"),
    Action("e", "Edit PAC domains", "act_edit_domains"),
    Action("c", "Edit config", "act_edit_config"),
    Action("l", "Tail proxy log", "act_log"),
    Action("w", "Run setup wizard", "act_wizard"),
    Action("D", "Run diagnostics", "act_doctor"),
    Action("F", "Refresh including network checks", "act_refresh_full"),
    Action("q", "Quit", "act_quit"),
]

_COLOR = {PASS: 1, WARN: 2, FAIL: 3, PLAIN: 0}


def _put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """addnstr that clips instead of raising on a small terminal."""
    height, width = win.getmaxyx()
    if y >= height or x >= width:
        return
    with contextlib.suppress(curses.error):
        win.addnstr(y, x, text, max(0, width - x - 1), attr)


class App:
    def __init__(self, stdscr, cfg: dict) -> None:
        self.stdscr = stdscr
        self.cfg = cfg
        self.snap = Snapshot()
        self.log: list[str] = []
        self.cursor = 0
        self.busy = ""
        self.running = True
        self.lock = threading.Lock()

    # --- helpers ---------------------------------------------------------
    def say(self, message: str) -> None:
        with self.lock:
            self.log.append(message)
            del self.log[:-200]

    def background(self, label: str, work: Callable[[], None]) -> None:
        def wrapper() -> None:
            try:
                work()
            except Exception as exc:  # a failed action must not kill the TUI
                self.say(f"{label} failed: {exc}")
            finally:
                self.busy = ""
        self.busy = label
        threading.Thread(target=wrapper, daemon=True).start()

    def refresh(self, with_network: bool = False) -> None:
        self.snap = collect(self.cfg, with_network=with_network)

    def _wanted_units(self) -> list[str]:
        return ([units.PROXY_UNIT, units.PAC_UNIT] if self.cfg["pac"]["enabled"]
                else [units.PROXY_UNIT])

    def _suspend(self, work: Callable[[], None]) -> None:
        """Drop out of curses, run something interactive, come back."""
        curses.def_prog_mode()
        curses.endwin()
        try:
            work()
        finally:
            curses.reset_prog_mode()
            self.stdscr.clear()
            self.stdscr.refresh()

    def editor(self, path: Path) -> None:
        chosen = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        self._suspend(lambda: subprocess.call([chosen, str(path)]))

    # --- actions ---------------------------------------------------------
    def act_start(self) -> None:
        for unit in self._wanted_units():
            code, out = units.start(unit)
            self.say(f"start {unit}: {'ok' if code == 0 else out.strip()}")
        self.refresh()

    def act_stop(self) -> None:
        for unit in self._wanted_units():
            code, out = units.stop(unit)
            self.say(f"stop {unit}: {'ok' if code == 0 else out.strip()}")
        self.refresh()

    def act_restart(self) -> None:
        code, out = units.restart(units.PROXY_UNIT)
        self.say(f"restart: {'ok' if code == 0 else out.strip()}")
        self.refresh()

    def act_sync(self) -> None:
        def work() -> None:
            nodes = generate.sync(self.cfg)
            self.say(f"synced {len(nodes)} nodes")
            for node in nodes:
                self.say(f"  {node['tag']} {node['server']}:{node['server_port']}")
            if self.cfg["pac"]["enabled"]:
                pac.write(self.cfg)
            units.restart(units.PROXY_UNIT)
            self.refresh()
        self.background("syncing", work)

    def act_pick(self) -> None:
        api = clash.Clash(self.cfg)
        if not api.available():
            self.say("clash api is down; press u to regenerate the config")
            return
        try:
            nodes = api.nodes()
        except clash.ClashError as exc:
            self.say(str(exc))
            return
        options = [(generate.URLTEST_TAG, "urltest", "pick the fastest")] + [
            (n.tag, n.type, n.delay_text) for n in nodes]
        index = self.menu("Select outbound",
                          [f"{t:<26} {ty:<12} {d}" for t, ty, d in options])
        if index is None:
            return
        try:
            api.select(options[index][0])
        except clash.ClashError as exc:
            self.say(str(exc))
            return
        self.say(f"selector → {options[index][0]}")
        self.refresh()

    def act_delays(self) -> None:
        def work() -> None:
            api = clash.Clash(self.cfg)
            api.measure()
            for node in api.nodes():
                self.say(f"  {node.tag:<26} {node.type:<12} {node.delay_text}")
            self.refresh()
        self.background("measuring", work)

    def act_reach(self) -> None:
        self.background("probing", lambda: self.refresh(with_network=True))

    act_ips = act_reach
    act_refresh_full = act_reach

    def act_edit_domains(self) -> None:
        self.editor(paths.config_file())
        self.cfg = config.load()
        if self.cfg["pac"]["enabled"]:
            pac.write(self.cfg)
            units.restart(units.PAC_UNIT)
            self.say("PAC regenerated")
        self.refresh()

    def act_edit_config(self) -> None:
        self.editor(paths.config_file())
        self.cfg = config.load()
        self.say("config reloaded")
        self.refresh()

    def act_log(self) -> None:
        _, out = units.systemctl("status", units.PROXY_UNIT, "--no-pager",
                                 "-n", "30")
        for line in out.splitlines():
            self.say(line)

    def act_wizard(self) -> None:
        self._suspend(lambda: wizard.run(cfg=self.cfg))
        self.cfg = config.load()
        self.refresh()

    def act_doctor(self) -> None:
        for check in doctor.run(self.cfg):
            self.say(f"[{check.status}] {check.name}: {check.detail}")
            if check.fix and check.status != doctor.PASS:
                self.say(f"    fix: {check.fix}")

    def act_quit(self) -> None:
        self.running = False

    # --- drawing ---------------------------------------------------------
    def invoke(self, action: Action) -> None:
        if action.needs_confirm and not self.confirm(action.label):
            return
        getattr(self, action.handler_name)()

    def confirm(self, what: str) -> bool:
        _put(self.stdscr, self.stdscr.getmaxyx()[0] - 1, 0,
             f"{what} — are you sure? [y/N] ".ljust(60), curses.A_REVERSE)
        self.stdscr.refresh()
        self.stdscr.nodelay(False)
        answer = self.stdscr.getch()
        return answer in (ord("y"), ord("Y"))

    def menu(self, title: str, items: list[str]) -> int | None:
        pos = 0
        while True:
            self.stdscr.erase()
            _put(self.stdscr, 0, 0, title, curses.A_BOLD)
            for index, item in enumerate(items):
                attr = curses.A_REVERSE if index == pos else 0
                _put(self.stdscr, index + 2, 2, item, attr)
            _put(self.stdscr, len(items) + 3, 0,
                 "↑/↓ move   enter select   esc cancel")
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                pos = max(0, pos - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                pos = min(len(items) - 1, pos + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                return pos
            elif key == 27:  # escape
                return None

    def draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()

        header = f" subbox — {paths.tilde(paths.config_file())} "
        if self.busy:
            header += f" [{self.busy}…] "
        _put(self.stdscr, 0, 0, header.ljust(max(0, width - 1)), curses.A_REVERSE)

        row = 2
        for label, value, status in render(self.snap):
            _put(self.stdscr, row, 2, f"{label:<16}")
            _put(self.stdscr, row, 20, value, curses.color_pair(_COLOR[status]))
            row += 1

        row += 1
        _put(self.stdscr, row, 0, " actions ".ljust(max(0, width - 1)),
             curses.A_REVERSE)
        row += 1
        action_top = row
        for index, action in enumerate(ACTIONS):
            attr = curses.A_REVERSE if index == self.cursor else 0
            _put(self.stdscr, action_top + index, 2,
                 f"[{action.key}] {action.label}", attr)

        log_top = action_top + len(ACTIONS) + 1
        if log_top < height - 1:
            _put(self.stdscr, log_top, 0, " log ".ljust(max(0, width - 1)),
                 curses.A_REVERSE)
            with self.lock:
                visible = self.log[-(height - log_top - 2):]
            for index, line in enumerate(visible):
                _put(self.stdscr, log_top + 1 + index, 1, line)
        self.stdscr.refresh()


def _main_loop(stdscr, cfg: dict) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)

    app = App(stdscr, cfg)
    app.refresh()
    while app.running:
        stdscr.timeout(700)
        app.draw()
        key = stdscr.getch()
        if key in (-1, curses.KEY_RESIZE):
            continue
        if key in (curses.KEY_UP, ord("k")):
            app.cursor = max(0, app.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app.cursor = min(len(ACTIONS) - 1, app.cursor + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            app.invoke(ACTIONS[app.cursor])
        elif 0 <= key < 256:
            match = next((a for a in ACTIONS if a.key == chr(key)), None)
            if match:
                app.invoke(match)


def run(cfg: dict) -> int:
    if not config.is_configured(cfg):
        print("subbox is not configured yet.")
        if input("Run setup now? [Y/n]: ").strip().lower() in ("", "y", "yes"):
            return wizard.run(cfg=cfg)
        return 2
    curses.wrapper(lambda stdscr: _main_loop(stdscr, cfg))
    return 0
