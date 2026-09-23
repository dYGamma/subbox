PREFIX  ?= $(HOME)/.local
DESTDIR ?=
PYTHON  ?= python3
SHELLCHECK ?= shellcheck

# A packaged install owns /usr/lib/systemd/user; a home install must use the
# only per-user directory systemd actually reads.
ifeq ($(PREFIX),/usr)
UNITDIR ?= /usr/lib/systemd/user
else ifeq ($(PREFIX),/usr/local)
UNITDIR ?= /usr/local/lib/systemd/user
else
UNITDIR ?= $(or $(XDG_CONFIG_HOME),$(HOME)/.config)/systemd/user
endif

LIBDIR     ?= $(PREFIX)/lib/subbox
SHAREDIR   ?= $(PREFIX)/share/subbox
CLAUDE_BIN ?= $(HOME)/.local/share/subbox-claude/bin
HOOK_DIR   ?= $(HOME)/.claude/hooks

.PHONY: all install install-python install-data install-claude uninstall uninstall-claude check lint dev smoke hooks

all:
	@echo "targets: install install-claude uninstall check lint dev"

install: install-python install-data smoke
	@echo
	@echo "Installed. Next: subbox setup"

# No pip, no wheel, no build backend. subbox is pure Python with no
# dependencies, so installing it is copying files and writing a launcher that
# knows where they went. That sidesteps PEP 668, distributions that ship pip
# as a separate package, and the --prefix import-path trap in one move.
install-python:
	install -d "$(DESTDIR)$(LIBDIR)/subbox"
	install -m644 src/subbox/*.py "$(DESTDIR)$(LIBDIR)/subbox/"
	install -d "$(DESTDIR)$(PREFIX)/bin"
	@py="$$(command -v $(PYTHON))"; \
	test -n "$$py" || { echo "$(PYTHON) not found"; exit 1; }; \
	{ \
	  echo "#!$$py"; \
	  echo "import sys"; \
	  echo "if sys.version_info < (3, 11):"; \
	  echo "    sys.exit('subbox needs Python 3.11 or newer; this is %d.%d'"; \
	  echo "             % sys.version_info[:2])"; \
	  echo 'sys.path.insert(0, "$(LIBDIR)")'; \
	  echo "from subbox.cli import main"; \
	  echo "sys.exit(main())"; \
	} > "$(DESTDIR)$(PREFIX)/bin/subbox"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/subbox"

install-data:
	install -d "$(DESTDIR)$(UNITDIR)"
	@# The units must name a directory that actually holds the binaries: a
	@# systemd user unit gets a fixed PATH that excludes ~/.local/bin.
	sed 's|@BINDIR@|$(PREFIX)/bin|g' share/systemd/subbox.service \
		> "$(DESTDIR)$(UNITDIR)/subbox.service"
	sed 's|@BINDIR@|$(PREFIX)/bin|g' share/systemd/subbox-pac.service \
		> "$(DESTDIR)$(UNITDIR)/subbox-pac.service"
	chmod 644 "$(DESTDIR)$(UNITDIR)/subbox.service" "$(DESTDIR)$(UNITDIR)/subbox-pac.service"
	install -Dm644 share/pac/default-domains.toml "$(DESTDIR)$(SHAREDIR)/default-domains.toml"
	install -Dm644 examples/config.toml "$(DESTDIR)$(SHAREDIR)/config.toml.example"
	install -Dm644 examples/domains-ru.toml "$(DESTDIR)$(SHAREDIR)/domains-ru.toml"
	install -Dm644 README.md "$(DESTDIR)$(PREFIX)/share/doc/subbox/README.md"
	install -Dm644 LICENSE "$(DESTDIR)$(PREFIX)/share/licenses/subbox/LICENSE"
	@if [ -z "$(DESTDIR)" ] && command -v systemctl >/dev/null 2>&1; then \
		systemctl --user daemon-reload || true; \
	fi

# A launcher that cannot import its own package is the most common way a
# --prefix install goes wrong, and without this it fails at first use with a
# traceback instead of here with an explanation.
smoke:
	@if [ -n "$(DESTDIR)" ]; then exit 0; fi; \
	if "$(PREFIX)/bin/subbox" --version >/dev/null 2>&1; then exit 0; fi; \
	echo "subbox landed in $(PREFIX) but its launcher cannot import the package:"; \
	echo "that prefix is not on this interpreter's import path."; \
	echo "Use the default PREFIX=\$$HOME/.local, or export PYTHONPATH to"; \
	echo "$(PREFIX)/lib/pythonX.Y/site-packages before running subbox."; \
	exit 1

install-claude:
	install -Dm755 integrations/claude-code/claude "$(CLAUDE_BIN)/claude"
	install -Dm755 integrations/claude-code/subbox-proxy-ensure.sh "$(HOOK_DIR)/subbox-proxy-ensure.sh"
	@echo
	@echo "Add this to your shell profile, ahead of the real claude on PATH:"
	@echo "    export PATH=\"$(CLAUDE_BIN):\$$PATH\""
	@echo "Then register the hook as described in integrations/claude-code/README.md"

# pip cannot uninstall a --prefix install, and on an externally managed
# interpreter it refuses outright, so the files are removed directly. The
# PREFIX guard is here because the next line is an rm -rf.
uninstall:
	@test -n "$(PREFIX)" || { echo "PREFIX is empty; refusing to remove anything"; exit 1; }
	@# Stop first: deleting a unit file leaves the service running with no way
	@# to manage it.
	@if command -v systemctl >/dev/null 2>&1 && [ -z "$(DESTDIR)" ]; then \
		systemctl --user disable --now subbox.service subbox-pac.service \
			>/dev/null 2>&1 || true; \
	fi
	rm -f "$(PREFIX)/bin/subbox"
	rm -rf "$(LIBDIR)"
	@# releases before 0.1.1 installed through pip; sweep that layout too
	@for d in "$(PREFIX)"/lib/python*/site-packages/subbox \
	          "$(PREFIX)"/lib/python*/site-packages/subbox-*.dist-info; do \
		if [ -e "$$d" ]; then rm -rf "$$d" && echo "removed $$d"; fi; \
	done
	rm -f "$(UNITDIR)/subbox.service" "$(UNITDIR)/subbox-pac.service"
	rm -rf "$(SHAREDIR)" "$(PREFIX)/share/doc/subbox" "$(PREFIX)/share/licenses/subbox"
	@if command -v systemctl >/dev/null 2>&1 && [ -z "$(DESTDIR)" ]; then \
		systemctl --user daemon-reload >/dev/null 2>&1 || true; \
	fi
	@echo "A development install made with 'make dev' is removed by: pip uninstall subbox"
	@echo "Configuration and generated files were left alone."
	@echo "The Claude Code integration, if installed, is removed by: make uninstall-claude"
	@echo "Remove them yourself if you want: $(or $(XDG_CONFIG_HOME),$(HOME)/.config)/subbox"

# Separate from `uninstall` on purpose: these live under the user's own
# ~/.claude, alongside files subbox did not put there.
uninstall-claude:
	rm -f "$(CLAUDE_BIN)/claude" "$(HOOK_DIR)/subbox-proxy-ensure.sh"
	@echo "Remove the PATH line for $(CLAUDE_BIN) from your shell profile,"
	@echo "and the hook entry from ~/.claude/settings.json."

# Gate pushes on the suite. Worth having even once CI works: a failure here
# costs seconds instead of a round trip through a runner.
hooks:
	git config core.hooksPath .githooks
	@echo "pre-push hook active; disable with: git config --unset core.hooksPath"

check:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests
	@if command -v $(SHELLCHECK) >/dev/null 2>&1; then \
		$(SHELLCHECK) install.sh integrations/claude-code/subbox-proxy-ensure.sh && \
		$(SHELLCHECK) -s bash integrations/claude-code/claude; \
	else \
		echo "shellcheck not found, so shell linting was skipped."; \
		echo "Point at a binary with: make lint SHELLCHECK=/path/to/shellcheck"; \
		echo "Static builds: https://github.com/koalaman/shellcheck/releases"; \
	fi

dev:
	$(PYTHON) -m pip install -e .
