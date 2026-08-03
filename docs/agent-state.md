# Agent state and shell customization

## Persistent agent state

jms keeps each agent's credentials and configuration outside project
checkouts. With the credential grant, these host directories are mounted
read-write:

| Host (`~/.local/share/jmscontainers/agents/`) | Container |
| --- | --- |
| `claude/` | `~/.claude` |
| `codex/` | `~/.codex` |
| `opencode/` | `~/.local/share/opencode` |
| `opencode-config/` | `~/.config/opencode` |

Log in once inside a container; later containers with the grant reuse that
login. With `jms launch --root`, the same directories mount under `/root`.

The state is shared across every approved project. A global settings file or
hook written by one container affects later containers. It also contains live
credentials:

- use dedicated, least-privileged agent accounts for third-party work;
- never commit or sync this directory;
- never replace it with a bind mount of your host's real agent directories;
- delete an agent's state directory and log in again if it is corrupted.

Project build/run approval and credential approval are separate. Use
`--no-auth` to launch without agent state. A manifest can set
`run.mount_auth = false` to suppress the default mount; `--auth` explicitly
requests it. See the [CLI trust reference](cli.md#trust) for interactive and
automation behavior.

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
The read-only mount prevents a compromised container from changing startup
code used by all future sessions.

The base image wires up both shells. A standalone image still receives the
mount but must source the files itself. To use Zsh, run:

```sh
jms launch -b /bin/zsh
```

Or set `run.entry = ["/bin/zsh", "-l"]` in `jmscontainer.toml`.
