# Agent state and shell customization

## Persistent agent state

jms keeps each agent's credentials and configuration outside project
checkouts. Launches without a project definition use the shared base and
mount these host directories read-write by default, without a project
credential prompt. Custom project definitions require a credential grant
for these mounts:

| Host (`~/.local/share/jmscontainers/agents/`) | Container |
| --- | --- |
| `claude/` | `~/.claude` |
| `codex/` | `~/.codex` |
| `opencode/` | `~/.local/share/opencode` |
| `opencode-config/` | `~/.config/opencode` |
| `pi/` | `~/.pi/agent` |

Log in once inside a container; later containers that mount this state reuse
that login. Pi uses `/login` inside its interactive session; its state mount
also persists settings, sessions, and extensions. With `jms launch --root`, the same directories mount under `/root`.

The state is shared across custom-project and shared-base launches that
mount it. A global settings file or hook written by one container affects
later containers. It also contains live credentials:

- use dedicated, least-privileged agent accounts for third-party work;
- never commit or sync this directory;
- never replace it with a bind mount of your host's real agent directories;
- delete an agent's state directory and log in again if it is corrupted.

For custom definitions, project build/run approval and credential approval
are separate, and a new interactive credential question defaults to no.
Use `--no-auth` to suppress jms-managed agent-state mounts for that launch,
including shared-base launches. A manifest can set `run.mount_auth = false`
to suppress the default mount; an explicit `--auth` overrides that setting
when credential access has been granted. `--auth` alone does not authorize
access: without a current credential grant or an applicable exact-fingerprint
auth grant, the consent path still applies and unavailable prompting fails.
See the [CLI trust reference](cli.md#trust) for interactive and automation
behavior.

A credential grant is recorded for the project's path and the exact
contents of its `.jmscontainer/`, not for the code checked out there. Any
branch, fork, or pull request later checked out at that path with an
unchanged definition gets the same access without a new question. Launch
with `--no-auth` when an agent reviews code you did not write.

`--no-auth` controls these jms-managed mounts; it does not prevent writes
through approved project or extra mounts or neutralize trusted ambient
runtime configuration.

## Shell customization

Container-specific startup files live here:

| Host (`~/.local/share/jmscontainers/shell/`) | Sourced by |
| --- | --- |
| `bashrc` | every interactive Bash shell |
| `zshrc` | every interactive Zsh shell |

jms creates the directory on first launch and mounts it read-only at
`~/.config/jms-shell`. Edits on the host apply to the next container without
an image rebuild. Extra files in the directory can be sourced from `bashrc`
or `zshrc` through `~/.config/jms-shell/...`.

Keep these files container-specific. Host shell files often contain macOS,
Homebrew, or machine-specific paths that do not work in the Fedora container.
Do not symlink your host's real `~/.bashrc` or `~/.zshrc` into this directory.

**Never put secrets in this directory.** Every container sources these
files, including projects you have not granted credential access, so a
token exported from `bashrc` reaches all of them. jms has no supported way
to pass a secret into a container yet.
The read-only mount prevents a compromised container from changing startup
code used by all future sessions.

The base image wires up both shells. A standalone image still receives the
mount but must source the files itself. To use Zsh, run:

```sh
jms launch -b /bin/zsh
```

Or set `run.entry = ["/bin/zsh", "-l"]` in `jmscontainer.toml`.
