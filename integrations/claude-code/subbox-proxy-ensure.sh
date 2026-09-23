#!/usr/bin/env bash
# SessionStart hook: make sure the proxy is up before the session starts.
#
# Quiet when healthy, so it costs nothing in the common case. A geo-blocked
# request returns 403, which reads as an authentication failure rather than
# a network one — hence saying so explicitly when the tunnel is down.
#
# Named subbox-proxy-ensure.sh rather than proxy-ensure.sh so it cannot
# collide with a hook you already have.
set -u

PORT="${SUBBOX_PROXY_PORT:-1080}"

listening() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- && return 0
    return 1
}

listening "$PORT" && exit 0

if [ -z "${SUBBOX_NO_AUTOSTART:-}" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user start subbox.service >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6 7 8; do
        listening "$PORT" && exit 0
        sleep 0.25
    done
fi

printf '%s\n' '{"systemMessage":"subbox: no proxy on port '"$PORT"'. Requests will use your direct address, which some APIs answer with 403 — that reads as an auth error but is not. Run `subbox doctor`."}'
exit 0
