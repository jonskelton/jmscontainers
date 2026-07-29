# jmscontainers: throwaway Fedora dev container for claude-code / codex / opencode.
# Rebuild = update: `dnf upgrade` + `npm install -g` run at build time, so
# `jms build --base --pull --no-cache` picks up the latest Fedora packages and
# agent CLIs.

FROM registry.fedoraproject.org/fedora:latest

# --allowerasing: the fedora base image ships curl-minimal, which conflicts with curl.
RUN dnf -y upgrade && \
    dnf -y install --allowerasing \
        neovim tmux zsh \
        git git-lfs gcc gcc-c++ make gdb strace ltrace patch diffutils \
        nodejs npm python3 python3-pip uv \
        sqlite moreutils \
        ripgrep fd-find fzf bat tree zoxide \
        curl wget jq yq bind-utils iproute iputils nmap-ncat openssh-clients rsync \
        htop procps-ng lsof psmisc file less man-db which util-linux findutils hostname \
        tar unzip zip xz zstd gh ShellCheck bubblewrap ca-certificates sudo && \
    dnf -y install --skip-unavailable eza git-delta && \
    dnf clean all

RUN npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai pnpm @ast-grep/cli

# Non-root default user with passwordless sudo (throwaway VM — convenience wins).
# Pre-create the agent auth dirs so the runtime mounts land with sane ownership.
# virtiofs squashes UIDs both ways (verified), so no host-UID alignment is needed.
RUN useradd -m -s /bin/bash isolation && \
    echo 'isolation ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/isolation && \
    chmod 440 /etc/sudoers.d/isolation && \
    mkdir -p /home/isolation/.claude /home/isolation/.codex \
             /home/isolation/.local/share/opencode \
             /home/isolation/.config/opencode \
             /home/isolation/.config/jms-shell && \
    chown -R isolation:isolation /home/isolation && \
    mkdir -p /root/.claude /root/.codex /root/.local/share/opencode \
             /root/.config/opencode /root/.config/jms-shell /work && \
    chown isolation:isolation /work && \
    ln -sf /usr/bin/nvim /usr/local/bin/vi && \
    ln -sf /usr/bin/nvim /usr/local/bin/vim

# Full-permission agent launchers. Real executables, not aliases: they must
# also work as `jms launch --bin` entrypoints, which bypass /etc/profile.d,
# so each wrapper sets the env a login shell would have provided.
# opencode has no skip-permissions flag; `--auto` is its sanctioned
# auto-approve mode (explicit "deny" rules still apply).
RUN printf '%s\n' \
        '#!/bin/sh' \
        'export EDITOR="${EDITOR:-nvim}"' \
        'export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"' \
        'export CLAUDE_CODE_DISABLE_MOUSE="${CLAUDE_CODE_DISABLE_MOUSE:-1}"' \
        'exec claude --dangerously-skip-permissions "$@"' \
        > /usr/local/bin/yolo-claude && \
    printf '%s\n' \
        '#!/bin/sh' \
        'export EDITOR="${EDITOR:-nvim}"' \
        'exec codex --dangerously-bypass-approvals-and-sandbox "$@"' \
        > /usr/local/bin/yolo-codex && \
    printf '%s\n' \
        '#!/bin/sh' \
        'export EDITOR="${EDITOR:-nvim}"' \
        'exec opencode --auto "$@"' \
        > /usr/local/bin/yolo-opencode && \
    chmod 755 /usr/local/bin/yolo-claude /usr/local/bin/yolo-codex /usr/local/bin/yolo-opencode

# QoL profile: `container run` has no hostname flag, so fake it in the prompt.
# zsh login shells also source /etc/profile.d/*.sh (via /etc/zprofile ->
# /etc/profile), so bash-specific lines are guarded by BASH_VERSION.
# ~/.config/jms-shell is the user's host-side shell config
# (~/.local/share/jmscontainers/shell), mounted read-only by jms.
RUN printf '%s\n' \
        'export EDITOR=nvim' \
        'export CLAUDE_CONFIG_DIR="$HOME/.claude"' \
        'export CLAUDE_CODE_DISABLE_MOUSE=1' \
        'export HOSTNAME=container' \
        '[ -n "$PS1" ] && [ -n "$BASH_VERSION" ] && PS1="[\u@container \W]\\$ "' \
        '[ -n "$PS1" ] && [ -n "$BASH_VERSION" ] && [ -r "$HOME/.config/jms-shell/bashrc" ] && . "$HOME/.config/jms-shell/bashrc"' \
        'true' \
        > /etc/profile.d/jms.sh

# Interactive zsh: non-login shells never read profile.d, so pull in jms.sh
# here (idempotent for login shells), replace the bash-escape prompt, and
# source the user's mounted zshrc.
RUN printf '%s\n' \
        '. /etc/profile.d/jms.sh' \
        'PS1="[%n@container %1~]%# "' \
        '[ -r "$HOME/.config/jms-shell/zshrc" ] && . "$HOME/.config/jms-shell/zshrc"' \
        'true' \
        >> /etc/zshrc

WORKDIR /work
USER isolation
