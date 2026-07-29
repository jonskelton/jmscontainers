PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
COMPLETIONDIR ?= $(PREFIX)/share/bash-completion/completions

.PHONY: install uninstall test integration

install:
	mkdir -p "$(BINDIR)"
	ln -sfn "$(CURDIR)/bin/jms" "$(BINDIR)/jms"
	mkdir -p "$(COMPLETIONDIR)"
	ln -sfn "$(CURDIR)/completions/jms.bash" "$(COMPLETIONDIR)/jms"
	@echo "installed jms -> $(CURDIR)/bin/jms"

uninstall:
	rm -f "$(BINDIR)/jms"
	rm -f "$(COMPLETIONDIR)/jms"
	@echo "removed $(BINDIR)/jms and $(COMPLETIONDIR)/jms"

test:
	python3 -X pycache_prefix=$$(mktemp -d) -m py_compile bin/jms
	python3 -B -m unittest discover -s tests
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/integration.sh completions/jms.bash; \
	else \
		sh -n scripts/integration.sh; \
		bash -n completions/jms.bash; \
	fi

integration:
	./scripts/integration.sh
