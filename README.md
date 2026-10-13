# jmscontainers

[![test](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml/badge.svg)](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/jonskelton/jmscontainers)](https://github.com/jonskelton/jmscontainers/releases)
[![license](https://img.shields.io/github/license/jonskelton/jmscontainers)](LICENSE)

Run **Claude Code**, **Codex**, **OpenCode**, and **[Pi](https://github.com/earendil-works/pi)** with full permissions
inside throwaway containers. The agent runs in the container, not directly
on your host, but your checkout is shared with it read-write. Its
top-level `.git` is read-only by default, so commit on the host or launch
with `--git-writable`.

`jms` mounts your checkout read-write at `/work`, starts a disposable Fedora
environment, and removes the container when you exit. (Launched from a
subdirectory of a checkout with no project definition, it mounts only that
subdirectory, with no read-only `.git`; launch from the checkout root to get
both.) It uses a lightweight VM
per container on macOS and rootless Podman on Linux. Projects can supply their
own Containerfile, but `jms` fingerprints it and asks before it can build, run,
or access persistent agent credentials. A checkout without one runs on the
shared base; the first launch there asks once whether to mount your agent
credentials (default no) and remembers the answer for that checkout.

## Install

Requirements: Python 3.11+, `make`, and the platform's container runtime:
apple/container on macOS, local rootless Podman on Linux. **Docker is not
supported** on either platform: jms has no Docker backend and no runtime
switch, because its boundary depends on a VM per container (macOS) or a
rootless user namespace that maps the container user to you (Linux).

The first `jms build --base` downloads Fedora and every agent CLI and
produces an image of roughly 3 GB; expect it to take several minutes.

### Apple Silicon macOS 15+

```sh
brew install container python
git clone https://github.com/jonskelton/jmscontainers.git
cd jmscontainers
make install
export PATH="$HOME/.local/bin:$PATH"
jms build --base
```

`jms` requires apple/container 1.2.2 or newer and starts its service when
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
Codex, OpenCode, Pi, Neovim, tmux, zsh, `rg`, `fzf`, `jq`, and `gh` are already
installed.

Start an agent directly in full-permission mode:

```sh
jms launch -b yolo-claude
jms launch -b yolo-codex
jms launch -b yolo-opencode
jms launch -b yolo-pi
```

The container exits with the agent. Use plain `jms launch` when you want a
shell to remain after the agent exits. The first launch in a checkout asks
whether to mount your agent credentials; answer `y` for an agent that should
stay logged in. Without a terminal, pass `--auth` to mount them. If you
answered no, `jms trust --auth` in the checkout changes the answer.

Your host's agent logins do not carry over: the container keeps its own
agent state, so log in once inside the container (for example, `yolo-claude`
opens Claude Code's login). Later launches that mount the credentials reuse
that login.

## Know these three things

1. **Only `/work` and persistent state survive.** Containers run with `--rm`.
   Keep important work in the mounted project.
2. **Project definitions require approval.** Any change under
   `.jmscontainer/` changes its SHA-256 fingerprint and triggers a new prompt.
   Build/run approval and credential access are separate grants. A
   credential grant follows the path, not the code: launch with `--no-auth`
   when an agent reviews a pull request or other code you did not write.
3. **Mounted data is not protected from the agent.** A container can change
   the project, including files your host tools later read or run (only the
   top-level `.git` is read-only), and can read or change any agent credentials and configuration
   mounted into it. That agent state is one pool shared by every launch
   that mounts it. macOS uses a VM boundary; Linux uses the weaker rootless
   user-namespace boundary. See
   [what a container can leave for the host](SECURITY.md#files-a-container-can-leave-for-the-host).

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
jms clean                        # remove this project's containers (asks first)
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
`~/.local/share/jmscontainers/agents/`. Nothing mounts it without your
consent: the first launch in a checkout without a project definition asks
once (default no) and remembers the answer for that checkout, and the first
approved custom project asks separately. Use `--no-auth` for a checkout you
do not trust. Use dedicated, least-privileged
agent accounts for untrusted work.

Container-only `bashrc` and `zshrc` files live under
`~/.local/share/jmscontainers/shell/` and are mounted read-only into every
container. See [Agent state and shell customization](docs/agent-state.md) for
the directory layout and safe setup.

## Update and remove

### Upgrading jms

`make install` links `jms` into your checkout, so the checkout *is* the
installation. Upgrade it in place, then rebuild the images:

```sh
cd ~/path/to/jmscontainers           # the checkout you installed from
git pull --ff-only
make install                         # re-links; picks up any new files
jms build --base --pull --no-cache   # rebuild the shared base from upstream
jms build                            # in each project (launch also does it)
```

- **Local edits ship.** The base builds from the checkout's `Containerfile`
  as it is on disk, and `jms` runs from the checkout's `bin/`. An
  uncommitted edit there becomes every project's base on this machine.
  Keep the checkout clean.
- **Running containers keep their image.** Exit and relaunch after an update.
- **The old base stays on disk.** jms no longer sees it; see disk usage on
  [Linux](docs/linux.md#disk-usage) or [macOS](docs/macos.md#disk-usage).

### Uninstalling

`make uninstall` removes only the `jms` command and its completion. Remove
the rest in this order, while `jms` still works:

| Left behind | Remove with |
| --- | --- |
| jms containers and images, including the base | `jms clean --all --images` |
| Images jms no longer sees (old bases, deleted projects) | your runtime's commands: see disk usage on [Linux](docs/linux.md#disk-usage) or [macOS](docs/macos.md#disk-usage) |
| Trust store: approvals and remembered credential answers | `rm -rf ~/.config/jmscontainers` |
| Agent logins and config, container shell files | `rm -rf ~/.local/share/jmscontainers` |
| The command and completion | `make uninstall`, then delete the checkout |

Deleting agent state removes the stored tokens but does not revoke them;
sign out or revoke them with each provider if they matter. `.jmscontainer/`
directories in your projects are yours and stay.

## More documentation

- [Documentation index](docs/README.md)
- [Security model](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

MIT—see [LICENSE](LICENSE).

jmscontainers is an independent project. It is not affiliated with or
endorsed by Anthropic, OpenAI, Apple, or the makers of OpenCode, Pi, Podman,
or Fedora. Product names are trademarks of their respective owners.
