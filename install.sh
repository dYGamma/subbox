#!/usr/bin/env bash
# subbox installer.
#
# Deliberately does not run sudo. A script fetched from the internet that
# escalates privileges is a pattern you should refuse, including this one:
# when a system package is missing, the exact command is printed for you to
# run and inspect yourself.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"

say()  { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

install_hint() {
    local package="$1"
    if   command -v pacman  >/dev/null 2>&1; then say "    sudo pacman -S $package"
    elif command -v apt-get >/dev/null 2>&1; then say "    sudo apt install $package"
    elif command -v dnf     >/dev/null 2>&1; then say "    sudo dnf install $package"
    elif command -v zypper  >/dev/null 2>&1; then say "    sudo zypper install $package"
    elif command -v apk     >/dev/null 2>&1; then say "    sudo apk add $package"
    elif command -v nix-env >/dev/null 2>&1; then say "    nix-env -iA nixpkgs.$package"
    else say "    install '$package' with your distribution's package manager"
    fi
}

python_ok() {
    command -v python3 >/dev/null 2>&1 &&
        python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
}

missing=0

if ! python_ok; then
    say "Python 3.11 or newer is required (subbox reads TOML with tomllib)."
    install_hint python
    missing=1
fi

if ! command -v sing-box >/dev/null 2>&1; then
    say "The sing-box binary is required."
    install_hint sing-box
    say "    or see https://sing-box.sagernet.org/installation/"
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
