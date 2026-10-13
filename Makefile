PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
COMPLETIONDIR ?= $(PREFIX)/share/bash-completion/completions
ZSH_COMPLETIONDIR ?= $(PREFIX)/share/zsh/site-functions

.PHONY: install uninstall test integration

install:
	mkdir -p "$(BINDIR)"
	ln -sfn "$(CURDIR)/bin/jms" "$(BINDIR)/jms"
	mkdir -p "$(COMPLETIONDIR)"
	ln -sfn "$(CURDIR)/completions/jms.bash" "$(COMPLETIONDIR)/jms"
	mkdir -p "$(ZSH_COMPLETIONDIR)"
	ln -sfn "$(CURDIR)/completions/_jms" "$(ZSH_COMPLETIONDIR)/_jms"
	@echo "installed jms -> $(CURDIR)/bin/jms"

uninstall:
	rm -f "$(BINDIR)/jms"
	rm -f "$(COMPLETIONDIR)/jms"
	rm -f "$(ZSH_COMPLETIONDIR)/_jms"
	@echo "removed $(BINDIR)/jms, $(COMPLETIONDIR)/jms and $(ZSH_COMPLETIONDIR)/_jms"
	@echo "trust store, agent state and images remain; see README.md#uninstalling"

test:
	python3 -X pycache_prefix=$$(mktemp -d) -m py_compile bin/jms
	python3 -B -m unittest discover -s tests
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/integration.sh scripts/qualify-macos.sh completions/jms.bash; \
	else \
		sh -n scripts/integration.sh; \
		sh -n scripts/qualify-macos.sh; \
		bash -n completions/jms.bash; \
	fi
	@if command -v zsh >/dev/null 2>&1; then zsh -n completions/_jms; fi

integration:
	./scripts/integration.sh
