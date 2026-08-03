# jmscontainers

[![test](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml/badge.svg)](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/jonskelton/jmscontainers)](https://github.com/jonskelton/jmscontainers/releases)
[![license](https://img.shields.io/github/license/jonskelton/jmscontainers)](LICENSE)

Throwaway containers for running **claude-code**, **codex**, and **opencode**
in full-permission ("yolo") mode — without handing them your machine.

On an Apple Silicon Mac:

```sh
brew install container python   # Apple's container runtime + Python 3.11+
make install                    # puts `jms` on your PATH
jms build --base                # one-time shared image
cd ~/anywhere/myproject         # any checkout, wherever you keep it
jms launch                      # you're in — the project is mounted at /work
```

On Debian 13:

```sh
sudo apt install podman uidmap passt dbus-user-session fuse-overlayfs coreutils make
make install
exec "$SHELL" -l                # picks up ~/.local/bin, created by `make install`
jms build --base
cd ~/anywhere/myproject
jms launch
```

Two things to know before you type anything in there:

- **Containers are ephemeral** (`--rm`). Nothing survives exit except writes
  to `/work` and the persistent agent-state dirs. If it matters, it lives in
  `/work`.
- **A project's container definition never builds or runs until you approve it.**
  A cloned repo's `.jmscontainer/` is fingerprinted, and you approve that exact
  fingerprint before it builds — see [How trust works](#how-trust-works). The
  rest of the repo's code runs normally inside the container once you're in;
  the container boundary — a lightweight VM on macOS, a user namespace on
  Linux — not a review gate, is what contains it. The two boundaries are not
  equivalent; see [SECURITY.md](SECURITY.md).

Stack:

- macOS: `macOS → container (lightweight VM per container) → Fedora → bash → claude-code`
- Linux: `Linux → rootless podman (user namespace) → Fedora → bash → claude-code`

## Platform support

jms runs on an **Apple Silicon Mac** (macOS 15+, apple/container pinned to
the qualified release) **or** on **Debian 13 (amd64) with local rootless
Podman ≥ 5.4**, plus Python 3.11+ on both (macOS Command Line Tools'
`python3` is too old, hence the Homebrew one). On macOS the runtime wants
`container system start` once per boot, but jms starts it for you if it
isn't running.

The Linux install command above is load-bearing, not belt-and-braces: on
Debian 13, `uidmap`, `passt`, and `dbus-user-session` are only *Recommends*
of `podman`, so a Recommends-disabled minimal install silently lacks them.
Rootless Podman needs subordinate ID ranges (at least 65536 ids) in
`/etc/subuid` and `/etc/subgid`; Debian's `adduser` provisions them for new
users automatically. `make` is listed for the same reason — it is not part
of a base Debian 13 install, so `make install` would otherwise fail with
`command not found`. The `exec "$SHELL" -l` line matters too: Debian's
`~/.profile` adds `~/.local/bin` to `PATH` only if that directory already
exists at login, and `make install` is what creates it, so the shell that
ran the install cannot see `jms` without re-execing.

What jms **refuses** to run on is exactly: platforms other than Linux and
macOS, uid 0 on Linux (rootless Podman is the only qualified Linux mode),
and remote Podman services (detected via `podman info`, since a remote
engine breaks local path semantics). Everything else outside the qualified
matrix — other distributions, arm64, SELinux-enforcing hosts — is
**unqualified but allowed**: jms performs no distribution or architecture
detection and prints no warning. Recent Fedora and Ubuntu, arm64, and
SELinux-enforcing hosts are mid-term qualification targets.

Known Linux limitations, documented rather than detected:

- **NFS or distributed home directories are unsupported**: rootless Podman
  storage under `~/.local/share/containers` is known-broken on NFS. jms does
  not detect this (heuristics false-positive too easily); the failure
  surfaces at the first build or launch — or at `podman info` when storage
  initialization fails outright — with Podman's own stderr.
- **Project access must be owner-based**: supported project trees, extra
  mounts, and shell/credential state are those readable and writable through
  your own UID and primary GID. Access that exists only via supplementary
  groups, ACL grants, or setgid directories does not survive the user-ns
  mapping and is unsupported for now.
- **Image refs starting with `jmscontainers-` are reserved**: jms treats
  every local image name matching that prefix (after stripping `localhost/`)
  as its own user-visible state — manually tagging an image into that
  namespace hands the alias to jms cleanup. Concurrent mutation of the image
  store while `jms clean` runs is likewise unsupported: jms does not lock or
  re-check between enumerating and untagging, so a ref retagged mid-cleanup
  can be untagged from the wrong image.
- **Nested sandboxes**: bubblewrap's full sandbox (the Codex bwrap path)
  fails inside rootless Podman on the masked `/proc`; run agents without
  their inner sandbox — they are already inside jms's boundary. jms never
  weakens container defaults to work around this.

## Why jmscontainers?

A project may commit a `.jmscontainer/Containerfile`, much like a Dev
Container. Unlike a Dev Container, a cloned project never gets to execute its
definition until you approve it, and mounting agent credentials is a separate,
explicit approval. It's built for ephemeral agent sessions — in
`apple/container` VMs on macOS, in rootless Podman user namespaces on
Linux — not long-lived Docker-backed editor environments, and the image
format stays an ordinary Containerfile, no proprietary DSL.

## Everyday commands

```sh
jms launch                        # launch the current directory
jms launch ../sibling             # any relative path
jms launch /some/abs/path         # or an absolute one
jms launch -b yolo-claude         # straight into a full-permission agent
jms init                          # scaffold .jmscontainer/Containerfile here
jms trust                         # approve this project's definition
jms clean                         # clean up this project's containers
```

Paths work like they do in any other tool: relative to where you are, with no
operand meaning "here". jms has no opinion about where you keep your code. If
you do keep every checkout in one directory, point `JMS_PROJECT_ROOTS` at it
and a bare name works from anywhere:

```sh
export JMS_PROJECT_ROOTS=~/git    # then `jms launch myproject` finds ~/git/myproject
```

A name that exists in the current directory always wins over that search
path, so the shorthand never quietly mounts a directory other than the one
you named.

And for occasional maintenance:

```sh
jms build --base --pull --no-cache   # refresh the shared base image
jms trust list                       # show approvals (including vanished roots)
jms inspect                          # discovery, fingerprint, and trust state
jms clean --all                      # global cleanup of jms containers
```

The complete command and environment grammar is in the
[CLI reference](docs/cli.md).

## Inside the container

- User `isolation` (passwordless sudo); prompt reads `isolation@container`.
- Your project at `/work`; writes appear on the host with your ownership.
- `claude`, `codex`, `opencode` on PATH, plus full-permission launchers:
  - `yolo-claude` → `claude --dangerously-skip-permissions`
  - `yolo-codex` → `codex --dangerously-bypass-approvals-and-sandbox`
  - `yolo-opencode` → `opencode --auto` (opencode has no skip-permissions
    flag; `--auto` auto-approves prompts while explicit `deny` rules still
    apply)

  These are executables, so they also work as launch entrypoints:
  `jms launch -b yolo-claude` drops straight into the agent. Note
  the container exits with the agent — launch the default shell instead if
  you want somewhere to land afterwards.
- `bubblewrap` (`bwrap`) for the Codex Linux sandbox.
- `vi`/`vim` → Neovim; `tmux`, `zsh`, `rg`, `fzf`, `jq`, `gh`, etc. preinstalled.
- Your own `bashrc`/`zshrc` from the host — see
  [Shell customization](#shell-customization).

## Project definitions

A project opts in to its own image by committing a
`.jmscontainer/Containerfile`. Start one in a project root:

```sh
jms init
# edit .jmscontainer/Containerfile
jms launch
```

Most project images should layer on the base image:

```Dockerfile
FROM jmscontainers-base:latest
USER root
RUN dnf -y install your-tool && dnf clean all
USER isolation
```

`jms launch` discovers the nearest definition — searching upward from the
workdir and stopping at the root of the enclosing VCS checkout, so a
`.jmscontainer/` above your checkout is never picked up — prompts before
building or running it, and tags the image from the SHA-256 fingerprint of
`.jmscontainer/`'s exact contents. That directory is also the build context:
`COPY`/`ADD` sources must live inside it, so copy any needed repo files into
it or fetch them in a `RUN` step. jms keeps the newest two images per project
and removes older ones after each successful build.

An optional `.jmscontainer/jmscontainer.toml` configures runtime mounts,
environment, and entrypoint. It's runtime-only in meaning, but like every file
in `.jmscontainer/` it is part of the build context and the fingerprint; the
full versioned schema is in
[docs/jmscontainer.toml.md](docs/jmscontainer.toml.md). See
[examples](examples/) for Go and Rust toolchains, Odin/reverse-engineering,
data-science, and a minimal clean-slate image.

### Project image user ABI

Every project image launched in the default mode must provide:

- a user named `isolation` with UID 1000 and primary GID 1000;
- a passwd entry with home `/home/isolation` and shell `/bin/bash`;
- an existing, writable `/home/isolation` owned by `1000:1000`; and
- passwordless sudo (`sudo -n true` must succeed).

The group with GID 1000 should be named `isolation`; repository-owned images
use that name. Images should finish with `USER isolation` for a safe default
outside jms, although jms always selects the runtime user explicitly.

Images based on `jmscontainers-base:latest` inherit this contract. A
standalone Fedora image can create the account deterministically with:

```Dockerfile
RUN dnf -y install bash sudo && dnf clean all && \
    groupadd --gid 1000 isolation && \
    useradd --create-home --shell /bin/bash \
            --uid 1000 --gid 1000 isolation && \
    printf 'isolation ALL=(ALL) NOPASSWD: ALL\n' \
        > /etc/sudoers.d/isolation && \
    chmod 0440 /etc/sudoers.d/isolation
USER isolation
```

The numeric identity is required because rootless Podman maps the invoking
host user to container identity `1000:1000` and launches with numeric
`--user 1000:1000`. This keeps `/work` and persistent-state writes owned by
the host user without allowing image content to choose the runtime identity.
The build above intentionally fails if either ID is already occupied; choose
a compatible base instead of silently reusing or modifying an unrelated
account.

jms does not inspect or repair image account data before launch. A standalone
image that omits or mismatches this ABI is unsupported and may fail with a
runtime or in-container diagnostic. In particular, standalone definitions
created for 1.0 that relied on automatically allocated IDs must pin
`isolation` to `1000:1000` for cross-runtime use.

jms always replaces the image `ENTRYPOINT` and does not append `CMD`; use
`[run].entry` in the manifest or `jms launch --bin ...` to choose the command.
Never put credentials in a Containerfile, manifest, or build-context files —
those inputs can be fingerprinted, copied into build layers, and retained by
the runtime.

## How trust works

The contents of `.jmscontainer/` are untrusted input. The first project
build, launch, or `jms trust` shows a capability summary and asks two
separate questions — one for build/run, one for credentials (jms prints the
real canonicalized path where `${HOME}` stands in below):

```
Project container capabilities:
- build and run: arbitrary commands with unrestricted network and root via passwordless sudo
- project mount: "${HOME}/projects/myproject" -> "/work" read-write
- entry: "/bin/bash" "-l"
- agent state (credentials and configuration for claude, codex, opencode): read-write mount eligible with a separate grant
"${HOME}/projects/myproject" defines a custom container (trust fingerprint 3f9c2ab81d04).
Approving lets it run arbitrary commands at build and run time and mount the project read-write at /work.
Allow build & run? [y/N] y
Also mount persistent agent state -- credentials and configuration for claude, codex, and opencode -- with read-write access? [y/N]
```

Consent is bound to that fingerprint. Change anything in `.jmscontainer/` and
jms asks again. In CI, pin an audited fingerprint rather than bypassing trust:

```sh
JMS_TRUST_FINGERPRINT="$(jms inspect -w /absolute/project | sed -n 's/^trust_fingerprint: //p')" \
  jms build -w /absolute/project
```

Approvals are managed with `jms trust list`, `jms trust revoke
/path/to/project`, and `jms trust prune`. Read [SECURITY.md](SECURITY.md)
before granting credential access, especially for third-party projects.

## Agent state (credentials and configuration)

Each agent's persistent home-state — credentials *and* configuration — lives
under `~/.local/share/jmscontainers/agents/` on the host and is mounted
read-write into containers holding the credential grant:

| Host (`~/.local/share/jmscontainers/agents/`) | Container                 |
|-----------------------------------------------|---------------------------|
| `claude/`                                     | `~/.claude`               |
| `codex/`                                      | `~/.codex`                |
| `opencode/`                                   | `~/.local/share/opencode` |
| `opencode-config/`                            | `~/.config/opencode`      |

Log in once per tool inside any container; every later container is
pre-authenticated. With `--root` the same dirs mount under `/root`.

Because the mounts are shared, a file dropped into a leaf appears in
**every** container holding the grant: a
`~/.local/share/jmscontainers/agents/claude/settings.json` applies to all of
them, and likewise `claude/CLAUDE.md`, Codex's `codex/config.toml`, and
opencode's configuration under `opencode-config/`.

This tree holds live credentials. Never commit it, never let a dotfile-sync
tool copy it, and never bind-mount your real host `~/.claude` in its place —
a container agent writing hooks that your host session later executes is a
sandbox escape.

## Shell customization

Container-specific shell config lives in one host directory and follows you
into every container:

| Host (`~/.local/share/jmscontainers/shell/`) | Sourced by                 |
|----------------------------------------------|----------------------------|
| `bashrc`                                     | every interactive bash     |
| `zshrc`                                      | every interactive zsh      |

jms creates the directory on first launch and mounts it **read-only** at
`~/.config/jms-shell` in every container — base and project images alike,
under `/root` with `--root`. Anything else you keep there (an aliases file,
prompt config) can be sourced from your `bashrc`/`zshrc` via
`~/.config/jms-shell/...` paths. Edits on the host apply to the next
container; no rebuild. The sourcing hooks live in the base image's
`/etc/profile.d/jms.sh` and `/etc/zshrc`, so images that don't build
`FROM jmscontainers-base` still receive the mount but must wire up their
own sourcing.

Write container-specific files rather than symlinking your real host
`~/.bashrc`/`~/.zshrc` into the directory: macOS rc files are full of
host-only paths (Homebrew, macOS `$PATH` setup) that misbehave in Fedora.
The mount is read-only by design — these files execute at shell startup in
every container, so container-side writes would let one compromised agent
session persist into all future ones.

zsh ships in the base image. Drop into it with `jms launch -b /bin/zsh`, set
`run.entry = ["/bin/zsh", "-l"]` in a project manifest, or `exec zsh` from
your mounted `bashrc` if you want it everywhere.

## Updating container software

To pull the latest upstream base and rebuild the shared image from scratch:

```sh
jms build --base --pull --no-cache
```

A project image's tag derives from its definition fingerprint, so refreshing
the base does not rebuild existing project images by itself; run
`jms build --no-cache` (or `jms launch --no-cache`) in a project to rebuild it
onto the refreshed base. Already-running containers keep their original image,
so exit and launch a new container after an update.

## Development

```sh
make test              # unit tests plus shell lint, no runtime required
make integration       # real-runtime tiers: base contracts (a), examples (b)
```

`scripts/integration.sh` takes one positional tier argument — `a` (fast,
base image and launch contracts), `b` (expensive, example images; assumes
tier A's base already exists), or `all` (the default). The Linux launch
contracts and the egress-denied FROM-resolution check need `sudo` for a
harness-owned nftables rule; the qualified release run uses a fresh
non-1000 user over ssh (see the [release checklist](docs/release-checklist.md)).

(`make install` symlinks `~/.local/bin/jms` to this checkout's `bin/jms` and
installs Bash completion under `~/.local/share/bash-completion`. Most Linux
distributions put `~/.local/bin` on `PATH` by default; macOS does not — add
it in your shell profile if `jms` isn't found.)

Pull-request CI runs `make test` on Ubuntu (Python 3.11 and 3.14) and on
macOS; neither leg needs a container runtime (the Ubuntu legs exercise the
Podman fake, not a real engine). Real-runtime checks are
deliberately opt-in; releases follow the
[release checklist](docs/release-checklist.md) and are recorded in
[CHANGELOG.md](CHANGELOG.md). Contribution guidance is in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
