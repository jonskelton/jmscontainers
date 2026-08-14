# jmscontainers: throwaway Fedora dev container for claude-code / codex / opencode.
# Rebuild = update: `dnf upgrade` + `npm install -g` run at build time, so
# `jms build --base --pull --no-cache` picks up the latest Fedora packages and
# agent CLIs.

FROM registry.fedoraproject.org/fedora:latest

# --allowerasing: the fedora base image ships curl-minimal, which conflicts with curl.
# tzdata already arrives transitively; it is named anyway because `jms launch`
# passes the host's zone in as TZ, and a zone name with no /usr/share/zoneinfo
# entry behind it silently degrades to UTC -- the exact failure the inherited
# zone exists to prevent. Naming it makes a future slimming pass argue with a
# line rather than break dates quietly.
RUN dnf -y upgrade && \
    dnf -y install --allowerasing \
        neovim tmux zsh \
        git git-lfs gcc gcc-c++ make gdb strace ltrace patch diffutils \
        nodejs npm python3 python3-pip uv \
        sqlite moreutils \
        ripgrep fd-find fzf bat tree zoxide \
        curl wget jq yq bind-utils iproute iputils nmap-ncat openssh-clients rsync \
        htop procps-ng lsof psmisc file less man-db which util-linux findutils hostname \
        tar unzip zip xz zstd gh ShellCheck bubblewrap ca-certificates sudo \
        tzdata && \
    dnf -y install --skip-unavailable eza git-delta && \
    dnf clean all

RUN npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai pnpm @ast-grep/cli

# Non-root default user with passwordless sudo (throwaway sandbox — convenience wins).
# Pre-create the agent auth dirs so the runtime mounts land with sane ownership.
# UID/GID are pinned to 1000 and paired with the isolation constants in bin/jms.
# On macOS virtiofs squashes UIDs both ways (verified), while on Linux rootless Podman's
# --userns=keep-id:uid=1000,gid=1000 performs the equivalent alignment explicitly.
RUN groupadd -g 1000 isolation && \
    useradd -m -s /bin/bash -u 1000 -g 1000 isolation && \
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
# The date line states the day AND the zone abbreviation at every login, so a
# container whose zone did not arrive announces itself in the first line of the
# session rather than in an argument about a date three weeks later. JMS_BANNER
# keeps it to once per session: a zsh login shell reads both /etc/profile.d and
# /etc/zshrc, and unlike the exports around it, printing is not idempotent.
RUN printf '%s\n' \
        'export EDITOR=nvim' \
        'export CLAUDE_CONFIG_DIR="$HOME/.claude"' \
        'export CLAUDE_CODE_DISABLE_MOUSE=1' \
        'export HOSTNAME=container' \
        '[ -n "$PS1" ] && [ -z "$JMS_BANNER" ] && export JMS_BANNER=1 && date "+%a %Y-%m-%d %H:%M %Z"' \
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
