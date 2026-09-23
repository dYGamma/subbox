#!/usr/bin/env bash
# subbox installer.
#
# Deliberately does not run sudo. A script fetched from the internet that
# escalates privileges is a pattern you should refuse, including this one:
# when a system package is missing, the exact command is printed for you to
# run and inspect yourself.
#
#   ./install.sh                    check requirements, install, run setup
#   ./install.sh --fetch-sing-box   also download the official sing-box
#                                   binary into the prefix, without root
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
FETCH_SING_BOX=0

say()  { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --fetch-sing-box) FETCH_SING_BOX=1 ;;
        -h|--help)        usage ;;
        *)                fail "unknown option: $1 (try --help)" ;;
    esac
    shift
done

# A binary fetched into the prefix must be visible to the checks below.
export PATH="$PREFIX/bin:$PATH"

# ---------------------------------------------------------------------------
# package manager
# ---------------------------------------------------------------------------

detect_pm() {
    local pm
    for pm in pacman apt-get dnf zypper apk nix-env; do
        if command -v "$pm" >/dev/null 2>&1; then
            printf '%s\n' "$pm"
            return
        fi
    done
    printf 'unknown\n'
}

PM="$(detect_pm)"

# The same software is named differently in different repositories, and
# guessing wrong sends people to a package that does not exist.
pkg_name() {
    case "$1" in
        python) [ "$PM" = pacman ] && printf 'python\n' || printf 'python3\n' ;;
        *)      printf '%s\n' "$1" ;;
    esac
}

install_hint() {
    local package
    package="$(pkg_name "$1")"
    case "$PM" in
        pacman)  say "    sudo pacman -S $package" ;;
        apt-get) say "    sudo apt install $package" ;;
        dnf)     say "    sudo dnf install $package" ;;
        zypper)  say "    sudo zypper install $package" ;;
        apk)     say "    sudo apk add $package" ;;
        nix-env) say "    nix-env -iA nixpkgs.$package" ;;
        *)       say "    install '$package' with your distribution's package manager" ;;
    esac
}

# ---------------------------------------------------------------------------
# sing-box
# ---------------------------------------------------------------------------

sing_box_hint() {
    case "$PM" in
        pacman)
            say "    sudo pacman -S sing-box"
            ;;
        apk)
            say "    sudo apk add sing-box"
            ;;
        nix-env)
            say "    nix-env -iA nixpkgs.sing-box"
            ;;
        apt-get|dnf|zypper)
            say "    Your distribution does not package sing-box. Use the official"
            say "    repository or .deb/.rpm from:"
            say "        https://sing-box.sagernet.org/installation/"
            ;;
        *)
            say "    https://sing-box.sagernet.org/installation/"
            ;;
    esac
    say ""
    say "    Or let this installer put the official static binary in $PREFIX/bin,"
    say "    no root required:"
    say "        ./install.sh --fetch-sing-box"
}

sing_box_arch() {
    case "$(uname -m)" in
        x86_64|amd64)  printf 'amd64\n' ;;
        aarch64|arm64) printf 'arm64\n' ;;
        armv7l|armv7)  printf 'armv7\n' ;;
        *)             printf '\n' ;;
    esac
}

fetch_sing_box() {
    local arch version base url tmp
    command -v curl >/dev/null 2>&1 || fail "curl is needed to download sing-box"
    command -v tar  >/dev/null 2>&1 || fail "tar is needed to download sing-box"

    arch="$(sing_box_arch)"
    [ -n "$arch" ] || fail "no official sing-box build for $(uname -m); see https://sing-box.sagernet.org/installation/"

    say "Looking up the latest sing-box release..."
    version="$(curl -fsSL --max-time 60 https://api.github.com/repos/SagerNet/sing-box/releases/latest \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p' | head -n1)"
    [ -n "$version" ] || fail "could not determine the latest sing-box version"

    base="sing-box-${version}-linux-${arch}"
    url="https://github.com/SagerNet/sing-box/releases/download/v${version}/${base}.tar.gz"

    tmp="$(mktemp -d)"
    # shellcheck disable=SC2064  # expand tmp now, not when the trap fires
    trap "rm -rf '$tmp'" EXIT

    say "Downloading $base from github.com/SagerNet/sing-box"
    curl -fsSL --max-time 300 "$url" -o "$tmp/sing-box.tar.gz" \
        || fail "download failed: $url"
    tar -xzf "$tmp/sing-box.tar.gz" -C "$tmp" "${base}/sing-box" \
        || fail "unexpected archive layout in $base.tar.gz"
    install -Dm755 "$tmp/${base}/sing-box" "$PREFIX/bin/sing-box"
    say "Installed $("$PREFIX/bin/sing-box" version | head -n1) into $PREFIX/bin"
}

# ---------------------------------------------------------------------------
# requirements
# ---------------------------------------------------------------------------

python_ok() {
    command -v python3 >/dev/null 2>&1 &&
        python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
}

if [ "$FETCH_SING_BOX" -eq 1 ] && ! command -v sing-box >/dev/null 2>&1; then
    fetch_sing_box
fi

missing=0

if ! python_ok; then
    if command -v python3 >/dev/null 2>&1; then
        say "Python 3.11 or newer is required; this system has $(python3 -V 2>&1 | cut -d' ' -f2)."
    else
        say "Python 3.11 or newer is required (subbox reads TOML with tomllib)."
    fi
    install_hint python
    missing=1
fi

if ! command -v sing-box >/dev/null 2>&1; then
    say "The sing-box binary is required."
    sing_box_hint
    missing=1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    say "systemd is required: subbox manages sing-box through user units."
    missing=1
fi

if ! command -v make >/dev/null 2>&1; then
    say "make is required to run the installer."
    install_hint make
    missing=1
fi

[ "$missing" -eq 0 ] || fail "install the requirements above, then run this again"

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

say "Installing subbox into $PREFIX"
make install PREFIX="$PREFIX"

if ! command -v subbox >/dev/null 2>&1; then
    say
    say "$PREFIX/bin is not on your PATH. Add it:"
    say "    export PATH=\"$PREFIX/bin:\$PATH\""
    say "Then run: subbox setup"
    exit 0
fi

say
subbox setup
