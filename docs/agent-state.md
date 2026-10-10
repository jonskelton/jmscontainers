# Agent state and shell customization

## Persistent agent state

jms keeps each agent's credentials and configuration outside project
checkouts and mounts these host directories read-write only with your
consent. Custom project definitions require a credential grant; launches
without a project definition ask their own question (see
[Launches without a definition](#launches-without-a-definition)):

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

### Suspect a leak?

Deleting a state directory is not revocation. A token copied out of a
container keeps working until the provider revokes it. If a project you do
not trust ran with agent state mounted, revoke first, at the provider:

| Agent | Revoke at the provider | Local logout |
| --- | --- | --- |
| Claude Code | Subscription login: claude.ai, **Settings → Claude Code**, delete the token (trash icon) — [Anthropic help](https://support.claude.com/en/articles/10310342-how-do-i-log-out-of-all-active-sessions). API key: delete it in the [Claude Console](https://platform.claude.com). | `/logout` at the Claude Code prompt |
| Codex | API key: delete it at [platform.openai.com/api-keys](https://platform.openai.com/api-keys). ChatGPT sign-in: see [Codex authentication](https://learn.chatgpt.com/docs/auth). | `codex logout` |
| OpenCode | Revoke each provider key that `opencode auth list` shows, in that provider's console. | `opencode auth logout` |
| Pi | Revoke each provider key or subscription login you connected, at that provider. | `/logout` in Pi's interactive session |
| `gh` | [github.com/settings/applications](https://github.com/settings/applications), **GitHub CLI → Revoke access**. This revokes every `gh` token on all your devices. | `gh auth logout` (removes the local copy only; [it does not revoke](https://cli.github.com/manual/gh_auth_logout)) |

jms does not persist `gh` configuration, so a `gh auth login` lives only as
long as its container, but a token copied out during that session stays
valid until revoked.

Then delete the agent's state directory and log in again. A container that
could write this state could also have left settings, hooks, or extensions
in it, and deleting the directory removes those as well.

If the worry is a compromised agent package rather than a project, check
which versions your base image holds before rebuilding it. Each
`jms build --base` installs whatever npm resolves that day, and once the old
base is pruned its versions are gone:

```sh
jms launch --no-auth --no-network -w ~/some/project --bin npm -- ls -g --depth=0
```

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

### Launches without a definition

A launch that finds no `.jmscontainer/` uses the shared base and mounts no
agent state without consent:

- **First launch in a checkout, on a terminal:** jms asks the default-No
  credential question once and records the answer in the trust store. The
  answer is keyed on the checkout root (the nearest enclosing `.git`, `.hg`,
  `.jj` or `.svn`), or on the workdir outside a checkout, so launches from
  any subdirectory reuse it. A remembered "yes" mounts the state on later
  launches without asking; a remembered "no" leaves it out.
- **No terminal:** nothing is asked or recorded. No agent state is mounted,
  and one `note:` line on stderr says so.
- **`--auth`:** mounts the state for that launch only, on or off a terminal,
  and never changes a recorded answer. Unlike a definition's one-shot grant
  it needs no fingerprint pin: there is no project build/run code to pin.
- **A trusted definition that is gone:** if the workdir or an ancestor
  inside the checkout has a trust record for a definition that is no longer
  there, jms prints a warning and mounts nothing (unless `--auth` is given).
  It does not ask again, so deleting `.jmscontainer/` cannot turn a declined
  project into a credentialed one.

The remembered answer follows the checkout path, not the code, exactly like
a definition's grant. To change it, run `jms trust revoke PATH` and launch
again on a terminal; `jms inspect PATH` shows the answer as
`credential_grant`. These launches now read the trust store, so an
unreadable or newer-schema store stops them unless `--no-auth` is passed.

`--no-auth` controls these jms-managed mounts; it does not prevent writes
through approved project or extra mounts or neutralize trusted ambient
runtime configuration.

A project's `run.mount_auth = false` and its credential decision apply only
to launches that find its definition. Discovery stops at the nearest
checkout root, so a launch from a nested checkout inside the project (a
submodule or a separate clone in a subdirectory), or with an explicit
workdir above the project, finds no definition. It is a shared-base launch
with its own credential answer, keyed on the nested checkout (or the
explicit workdir's checkout), and asks separately even when the project
declined credentials. Answer no, or pass `--no-auth`, when the project's
sessions must not reach the shared state.

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
The read-only mount stops a compromised container from editing these shell
startup files. It does not cover the read-write agent state above, where a
container can leave settings or hooks that later agent sessions run.

**Never put secrets in this directory.** Every container sources these
files, including projects you have not granted credential access, so a
token exported from `bashrc` reaches all of them. jms has no supported way
to pass a secret into a container yet.

The base image wires up both shells. A standalone image still receives the
mount but must source the files itself. To use Zsh, run:

```sh
jms launch -b /bin/zsh
```

Or set `run.entry = ["/bin/zsh", "-l"]` in `jmscontainer.toml`.
