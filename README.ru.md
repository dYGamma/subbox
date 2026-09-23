# subbox

Превращает подписку прокси-панели в работающий локальный прокси, с терминальным
дашбордом, чтобы следить за ним и переключать ноды.

Панель выдаёт вам ссылку на подписку. `subbox` её забирает, превращает ноды в
проверенный конфиг [sing-box](https://sing-box.sagernet.org/), запускает его
пользовательским systemd-юнитом и отдаёт смешанный HTTP/SOCKS5 прокси на
`127.0.0.1:1080`. По желанию он же раздаёт PAC-файл, чтобы браузер отправлял в
прокси только выбранные вами домены, а всё остальное шло напрямую.

## Чем это не является

- **Не VPN и не TUN.** `subbox` слушает петлю. Он не перехватывает трафик всей
  системы, потому что для этого нужен `CAP_NET_ADMIN`, а пользовательскому
  юниту его выдать нельзя. Инструменты, которые делают это хорошо, уже есть.
- **Не обход DPI.** Сменить адрес, с которого выходит трафик, и обмануть
  инспекцию трафика на лету — разные задачи. Вторую решает
  [zapret](https://github.com/bol-van/zapret).
- **Не панель.** Он подписку потребляет, а не выдаёт.

## Требования

- Linux с systemd
- Python 3.11 или новее
- Бинарь `sing-box`

## Установка

На Arch:

```bash
yay -S subbox
subbox setup
```

Везде остальном:

```bash
git clone https://github.com/dYGamma/subbox
cd subbox
./install.sh
```

Установщик проверяет требования, печатает точную команду вашего пакетного
менеджера, если чего-то не хватает, и затем запускает визард. `sudo` он за вас
не вызывает никогда.

## Первый запуск

```console
$ subbox setup
subbox setup
Paste the subscription URL your panel gave you. It is a credential, so it is stored in a file only you can read.
Subscription URL from your panel: https://panel.example.com/sub/9f3c…
  found 3 node(s):
    Amsterdam 443                vless        198.51.100.10:443
    Amsterdam WS                 vless        198.51.100.10:8443
    Amsterdam Hy2                hysteria2    198.51.100.10:36712
Local proxy port [1080]:
Serve a PAC file so a browser routes only chosen domains? [Y/n]:
PAC server port [7777]:
Which domains should go through the proxy?
  1) AI assistants only (default)
  2) broader list (36 domains, includes social networks)
  3) enter your own
Choice [1]:
```

Подписка забирается на первом же вопросе, так что свои ноды вы видите до того,
как отвечать на всё остальное. Дальше визард пишет конфигурацию, поднимает
сервисы и печатает сводку диагностики.

## Команды

| Команда | Что делает |
|---|---|
| `subbox` | Открыть дашборд |
| `subbox setup` | Интерактивная настройка |
| `subbox sync` | Перечитать подписку, перегенерировать конфиг, перезапустить |
| `subbox pac` | Перегенерировать PAC-файл |
| `subbox status` | Состояние; `--json` для скриптов, `--quiet` только код возврата |
| `subbox doctor` | Найти проблемы и сказать, как их чинить |

`status` возвращает `0`, когда прокси поднят, `1`, когда лежит, и `2`, когда
subbox ещё не настроен. На это можно опираться в скриптах.

## Дашборд

`subbox` без аргументов открывает дашборд: какая нода несёт трафик, подняты ли
сервисы, какой у вас адрес на выходе. Клавиши: `u` пересинхронизировать
подписку, `p` выбрать ноду, `d` замерить задержки, `t` проверить достижимость,
`D` прогнать диагностику, `q` выход.

## Конфигурация

`~/.config/subbox/config.toml`, создаётся с правами `0600`, потому что ссылка на
подписку сама по себе является учётными данными.

```toml
[subscription]
url = "https://panel.example.com/sub/9f3c"
insecure = false

[proxy]
listen_addr = "127.0.0.1"
listen_port = 1080
clash_port = 9090

[pac]
enabled = true
port = 7777
domains = ["anthropic.com", "claude.ai", "openai.com", "chatgpt.com"]

[probe]
reach_url = "https://www.gstatic.com/generate_204"
reach_ok = [204]
latency_url = "https://www.gstatic.com/generate_204"
```

Полный прокомментированный образец лежит в `examples/config.toml`.

Сгенерированный конфиг sing-box кладётся в `~/.config/subbox/sing-box.json` и
никогда не поверх вашего собственного `~/.config/sing-box/config.json`. Он
перегенерируется из подписки, поэтому правьте `config.toml` и запускайте
`subbox sync`, а не редактируйте его напрямую.

## Как пользоваться прокси

Для оболочки:

```bash
export HTTPS_PROXY=http://127.0.0.1:1080
export ALL_PROXY=socks5h://127.0.0.1:1080
```

Для браузера укажите URL автоматической настройки прокси:

```console
http://127.0.0.1:7777/proxy.pac
```

Через прокси пойдут только домены из `pac.domains`, остальное — напрямую.

## Когда что-то не так

```bash
subbox doctor
```

Каждая проверка называет симптом, а не только неверную настройку, потому что
трудно именно опознать симптом:

```console
[ok  ] Subscription configured: a subscription URL is set
[ok  ] Credential file permissions: 3 file(s) are 0600
[ok  ] route.auto_detect_interface: correctly false
[ok  ] route.default_domain_resolver: set
[ok  ] Cache directory: /home/you/.cache/subbox
[FAIL] Reachability: direct 204, via proxy 403 — the tunnel carries traffic but the exit address is rejected by this endpoint
         fix: switch to another node with `subbox` and press p
```

Подробнее по каждому отказу — в `docs/troubleshooting.md`.

## Документация

- [`docs/setup.md`](docs/setup.md) — по шагам, от панели до работающего прокси
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — симптом, причина, лечение
- [`docs/architecture.md`](docs/architecture.md) — как устроено, для контрибьюторов
- [`integrations/claude-code/`](integrations/claude-code/) — необязательная обвязка для Claude Code

[English version](README.md).

## Лицензия

MIT.
