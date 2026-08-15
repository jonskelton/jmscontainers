# jmscontainers

[![test](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml/badge.svg)](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/jonskelton/jmscontainers)](https://github.com/jonskelton/jmscontainers/releases)
[![license](https://img.shields.io/github/license/jonskelton/jmscontainers)](LICENSE)

Run **Claude Code**, **Codex**, and **OpenCode** with permission checks disabled
inside throwaway containers—not on your host.

`jms` mounts your checkout read-write at `/work`, starts a disposable Fedora
environment, and removes the container when you exit. It uses a lightweight VM
per container on macOS and rootless Podman on Linux. Projects can supply their
own Containerfile, but `jms` fingerprints it and asks before it can build, run,
or access persistent agent credentials.

## Install

Requirements: Python 3.11+, `make`, and one supported container runtime.

### Apple Silicon macOS 15+

```sh
brew install container python
git clone https://github.com/jonskelton/jmscontainers.git
cd jmscontainers
make install
export PATH="$HOME/.local/bin:$PATH"
jms build --base
```

`jms` is qualified against apple/container 1.2.2 and starts its service when
needed. See the [macOS guide](docs/macos.md) for PATH setup, version handling,
and platform notes.

### Debian 13 (amd64)

```sh
sudo apt install podman uidmap passt dbus-user-session fuse-overlayfs coreutils make
git clone https://github.com/jonskelton/jmscontainers.git
cd jmscontainers
make install
exec "$SHELL" -l
jms build --base
```

The qualified target is Debian 13 on amd64 with local rootless Podman 5.4.2;
local rootless Podman 5.4+ is accepted. New users created with `adduser`
normally receive the required subordinate ID ranges in `/etc/subuid` and
`/etc/subgid`. Other distributions, arm64, and SELinux-enforcing hosts are
**unqualified but allowed**. See the [Linux guide](docs/linux.md) for the
support boundary, prerequisite checks, and known limitations.

## Use

From any checkout:

```sh
cd ~/path/to/project
jms launch
```

You land in a shell as `isolation` with passwordless sudo. The project is at
`/work`; writes there appear on the host with your ownership. (A project that
needs its container path to match its host path — so a path-keyed tool agrees
on both sides — can set `run.preserve_host_path`; see
[the manifest reference](docs/jmscontainer.toml.md#project-mount-path).)
Claude Code,
Codex, OpenCode, Neovim, tmux, zsh, `rg`, `fzf`, `jq`, and `gh` are already
installed.

Start an agent directly in full-permission mode:

```sh
jms launch -b yolo-claude
jms launch -b yolo-codex
jms launch -b yolo-opencode
```

The container exits with the agent. Use plain `jms launch` when you want a
shell to remain after the agent exits.

## Know these three things

1. **Only `/work` and persistent state survive.** Containers run with `--rm`.
   Keep important work in the mounted project.
2. **Project definitions require approval.** Any change under
   `.jmscontainer/` changes its SHA-256 fingerprint and triggers a new prompt.
   Build/run approval and credential access are separate grants.
3. **Mounted data is not protected from the agent.** A container can change
   the project and, if approved, read or change agent credentials. macOS uses
   a VM boundary; Linux uses the weaker rootless user-namespace boundary.

Read [SECURITY.md](SECURITY.md) before granting credential access to a
third-party project.

## Everyday commands

```sh
jms launch                       # launch the current checkout
jms launch ../sibling            # launch another path
jms launch -b yolo-codex         # start an agent directly
jms inspect                      # show discovery, fingerprint, and trust
jms init                         # create .jmscontainer/Containerfile
jms trust                        # review and approve a project definition
jms clean                        # remove this project's containers
jms clean --all                  # remove all jms containers
```

Set a search path if you want to launch checkouts by name from anywhere:

```sh
export JMS_PROJECT_ROOTS=~/git
jms launch myproject
```

See the [CLI reference](docs/cli.md) for every command, flag, environment
variable, and exit code.

## Customize a project

Create a project definition:

```sh
cd ~/path/to/project
jms init
```

Then edit `.jmscontainer/Containerfile`. Most projects only need to layer
tools onto the shared base:

```Dockerfile
FROM jmscontainers-base:latest
USER root
RUN dnf -y install your-tool && dnf clean all
USER isolation
```

The `.jmscontainer/` directory is the build context, so `COPY` and `ADD`
cannot read files outside it. Never put secrets there. Add
`.jmscontainer/jmscontainer.toml` when you need extra mounts, environment
variables, or a different entrypoint.

A container runs in your host's time zone, so dates written inside it are
your local calendar dates. Pin one with `[env] TZ` when a project's dates
must not vary with the machine the session runs on — see
[Time zone](docs/jmscontainer.toml.md#time-zone).

- [Project image guide](docs/project-images.md): discovery, build context,
  standalone images, and the required `isolation` user ABI
- [`jmscontainer.toml` reference](docs/jmscontainer.toml.md): complete schema
- [Examples](examples/): Go, Rust, Odin, data science, and a clean-slate image

## Credentials and shell setup

Agent credentials and configuration persist under
`~/.local/share/jmscontainers/agents/`. The first approved custom project asks
separately whether it may mount that state. Use dedicated, least-privileged
agent accounts for untrusted work.

Container-only `bashrc` and `zshrc` files live under
`~/.local/share/jmscontainers/shell/` and are mounted read-only into every
container. See [Agent state and shell customization](docs/agent-state.md) for
the directory layout and safe setup.

## Update and remove

```sh
jms build --base --pull --no-cache   # rebuild the shared base from upstream
jms build --no-cache                 # rebuild this project's image
make uninstall                       # remove the jms command and completion
```

Already-running containers keep their original image; exit and relaunch after
an update.

## More documentation

- [Documentation index](docs/README.md)
- [Security model](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

MIT—see [LICENSE](LICENSE).
