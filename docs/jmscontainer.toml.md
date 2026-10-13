# `jmscontainer.toml` reference (schema 1)

`jmscontainer.toml` is optional and lives beside the project Containerfile at
`.jmscontainer/jmscontainer.toml`. It configures runtime behavior only; it
cannot select an image, inject build arguments, define services, or otherwise
orchestrate containers. Like everything under `.jmscontainer/`, it is part of
the build context and the trust fingerprint; it must never contain secrets.

```toml
schema = 1
name = "example"

[env]
HELLO = "world"

[[mounts]]
source = "~/.cache/example"
target = "/home/isolation/.cache/example"
readonly = true

[run]
entry = ["/bin/bash", "-l"]
mount_auth = true
preserve_host_path = false
git_writable = false
```

## Schema

Unknown keys at every level are errors. Values are exact TOML types: no
coercion is performed, and floats and datetimes are accepted nowhere.

| Key | Type | Default | Rules |
| --- | --- | --- | --- |
| `schema` | integer | `1` | Must be `1`; a newer integer version fails closed and asks for a newer `jms`. |
| `name` | string | project-directory slug | Cosmetic slug for generated container names. Must match `^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$`. It does not affect the project ID, but it is manifest content: changing it changes the trust fingerprint, and the image tag ends in that fingerprint. |
| `env` | table | empty | Environment names match `^[A-Za-z_][A-Za-z0-9_]*$`; values are strings without NUL or newline. `TZ` is special only in that `launch` supplies a default from the host: see [Time zone](#time-zone). |
| `mounts` | array of tables | empty | Each item has `source`, `target`, and optional `readonly` and `allow_socket` only. |
| `mounts[].source` | string | — | Required, nonempty host path. `~`, `$VAR`, and `${VAR}` expand once from the host environment; unset or empty expansions fail. Relative paths resolve from the project root (not `.jmscontainer/` or the invoking working directory). The result must already exist: jms canonicalizes it (resolving symlinks) while parsing, so a missing source is a manifest error. |
| `mounts[].target` | string | — | Required container path. Absolute paths use the allowlist in [Mount targets](#mount-targets); relative paths resolve from the container project path and may leave that allowlist, subject to the system-state and reserved-path checks below. Targets may not overlap each other or any reserved path. |
| `mounts[].readonly` | boolean | `true` | Set `false` only when the container must write the host path. A writable host toolchain cache (such as `~/.cargo/registry`, `~/go/pkg/mod` or `~/.cache/pip`) is code host builds of every project will later run, so give a container its own cache directory instead. Read-only does not restrict a socket, FIFO or device node: the container can still connect to or write it, which is why such sources need `allow_socket`. |
| `mounts[].allow_socket` | boolean | `false` | Permit a source that is a socket, FIFO, or character/block device; without it such a source is refused. The consent summary then names the grant (`SOCKET (allow_socket = true)`) instead of `read-only`. An exact socket path is also exempt from the socket-directory refusal; a directory never is. See [Host sockets](#host-sockets). |
| `run` | table | defaults below | Only `entry`, `mount_auth`, `preserve_host_path`, and `git_writable`. |
| `run.entry` | array of strings | `["/bin/bash", "-l"]` | Nonempty; first element nonempty; no element contains NUL. |
| `run.mount_auth` | boolean | `true` | The key name is historical: it gates the agent-state mount (credentials and configuration). If false, mounting requires the user to type `--auth`; it does not change the approval record or prompts. |
| `run.preserve_host_path` | boolean | `false` | Mount the project at its own host path instead of `/work`, so a path-keyed tool resolves the same key inside and outside. See [Project mount path](#project-mount-path). |
| `run.git_writable` | boolean | `false` | Mount the project's top-level `.git` read-write instead of read-only. Hooks and config there run on your host, so approval names it. See [Read-only .git](#read-only-git). |

Any byte change under `.jmscontainer/` — including this manifest — changes the
trust fingerprint and requires fresh consent.

`source` values are host-controlled capability requests. They are canonicalized
before approval; mount sources that touch jms credential, configuration, or tool
directories are rejected. For the complete security and trust behavior, see
[SECURITY.md](../SECURITY.md).

### Credential-path mounts

A mount whose canonical source overlaps a host credential store is kept
only when the launch holds the project's credential grant: the recorded
answer to the credential question was yes, or a matching
`JMS_TRUST_FINGERPRINT` pin is combined with `--auth`. Otherwise jms drops
it and prints one `note: not mounting host credential path ...` line per
dropped mount; the launch still proceeds. That covers a declined grant,
`--no-auth`, a bare `--trust`, and a pin without `--auth`. The gate reads
the grant itself, not `run.mount_auth`: a manifest with
`mount_auth = false` still keeps its credential mounts when the grant is
recorded. The consent summary marks these mounts, and the credential
question names them.

"Overlaps" means the source is one of these paths, inside one, or a
directory that contains one, after resolving symlinks. Paths are relative
to `$HOME`:

`.ssh`, `.gnupg`, `.config/gh`, `.aws`, `.azure`, `.config/gcloud`,
`.kube`, `.docker`, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`,
`.cargo/credentials.toml`, `.vault-token`, `.terraform.d`,
`.m2/settings.xml`, `.gradle/gradle.properties`, `.1password`,
`Library/Keychains` (macOS), and the host agents' own `.claude`, `.codex`,
`.local/share/opencode`, `.config/opencode` and `.pi/agent`.

When set, `$GNUPGHOME`, `$DOCKER_CONFIG`, each absolute entry of
`$KUBECONFIG`, and `$AWS_SHARED_CREDENTIALS_FILE` are added to the list.

Because a containing directory matches, mounting all of `~/.cargo` or
`~/.m2` also goes through the credential question; mount the cache
subdirectory you need (`~/.cargo/registry`) to avoid that. The list is
best-effort, not exhaustive: a credential store it does not name is
mounted under build/run approval like any other source.

On the Linux backend, access to a mount source is owner-based: a source is
supported only if it is reachable through the invoking user's own UID and
primary GID. Access that exists only via a supplementary group, an ACL grant,
or a setgid directory does not survive the rootless user-namespace mapping,
so such a mount may resolve and pass approval on the host and still be
unreadable or unwritable inside the container. jms performs no preflight
detection of this; the failure surfaces in the container. The same rule
applies to the project tree itself.

## Host sockets

A socket inside a mount still accepts connections whatever the mount flags,
and a host socket is often a host command channel: the user systemd
manager, D-Bus, a tmux server, a container engine. jms therefore refuses a
mount whose canonical source:

- is a socket, FIFO, or character/block device, unless the mount sets
  `allow_socket = true`;
- contains or sits inside a known socket directory: `$XDG_RUNTIME_DIR`
  (when set), `/run/user/<uid>`, `/run`, `/var/run`, `/tmp/tmux-<uid>`, or
  `/tmp/.X11-unix`. That refuses `/tmp` itself, but other `/tmp`
  subtrees stay mountable;
- is, or contains, the socket named by `$SSH_AUTH_SOCK` or by a `unix://`
  `$DOCKER_HOST`. Only that path and its ancestors are refused, so
  `SSH_AUTH_SOCK=~/.agent.sock` does not make the rest of `~` unmountable.

A mount with `allow_socket = true` whose source is exactly a socket skips
the two directory rules; a directory never does, because it would carry
every socket created in it later.

A socket inside a credential path (`~/.ssh/agent.sock`,
`~/.1password/agent.sock`, a gpg-agent socket under `~/.gnupg`) is also a
credential mount: it is kept only with the credential grant and is otherwise
dropped with a `note:`, see [Credential-path mounts](#credential-path-mounts).

The list is **best-effort**, not a guarantee. Agent sockets elsewhere that
no environment variable names (under `$HOME`, say) are not detected, so
review every extra mount at consent as a grant of whatever it contains.

To forward the host ssh-agent, mount the exact socket and point the
container at it with `[env]`:

```toml
[env]
SSH_AUTH_SOCK = "/opt/ssh-agent.sock"

[[mounts]]
source = "$SSH_AUTH_SOCK"
target = "/opt/ssh-agent.sock"
allow_socket = true
```

The container can then ask the agent to sign with any loaded key for as
long as it runs, though it cannot copy the keys. The source expands from
the host environment, so a launch without an agent fails with an unset
variable. This does not work on macOS: apple/container (checked on 1.5.0)
bind-mounts directories, not single files, so there the launch fails
after the build with `path '...' is not a directory`. That applies to any
`[[mounts]]` source that is a file there, not just a socket.

## Time zone

`jms launch` passes the host's IANA zone into every container as `TZ`, so
dates written inside a container are your local calendar dates rather than
the image default of UTC (see [the CLI reference](cli.md#launch)). Setting
`TZ` in `[env]` replaces that inherited value:

```toml
[env]
TZ = "America/Los_Angeles"
```

Pin it when the project's dates are decisions rather than telemetry — a
record whose dates must read the same whether the session ran on a laptop,
a colleague's machine, or a UTC CI runner. Use an IANA zone name, never a
fixed offset: `Etc/GMT+7` and a hardcoded `-0700` are correct for part of
the year and silently wrong for the rest, which is harder to notice than
being wrong all the time. The pinned value is manifest content, so it is
covered by the trust fingerprint and changing it requires fresh consent.

## Project mount path

By default the checkout mounts at `/work`, and every project therefore has
the same path inside its container. Tools that key per-project state on the
working directory see that as one shared project: Claude Code stores state
under `~/.claude/projects/<cwd with slashes as dashes>`, which is `-work` for
every jms project at once, while the same checkout on the host has a key of
its own. State cannot be shared in either direction, and unrelated projects
share a key inside.

`run.preserve_host_path = true` mounts the checkout at its own absolute host
path instead, so the two keys agree:

```toml
[run]
preserve_host_path = true
```

The manifest chooses only *whether* to preserve the path, never what the path
is — the value is the checkout location you already picked — so the key grants
a project no target it did not already have. jms still refuses the mount when
the resulting path would damage the container:

- a path that is, contains, or sits inside `/`, `/bin`, `/boot`, `/dev`,
  `/etc`, `/lib`, `/lib64`, `/proc`, `/root`, `/run`, `/sbin`, `/sys`,
  `/usr`, or `/var` — a checkout under `/etc` would shadow the image's own
  system state, and one under `/proc` would reach into kernel state;
- a path that overlaps a reserved target (below), including `/home` itself,
  which would swallow the agent-state mounts;
- any manifest `[[mounts]]` target that overlaps the preserved path.
  `/work` is a reserved target, so the default mount is already protected
  from this; a preserved path is checked separately at launch.

Because `--root` moves the effective home to `/root`, a checkout under `/root`
is refused rather than landing somewhere the manifest did not name.

The key is manifest content: turning it on changes the trust fingerprint and
requires fresh consent, and the consent summary names the path that will be
mounted.

## Read-only .git

Every launch mounts the project's top-level `.git` read-only inside the
read-write project mount, at `/work/.git` (or `<host path>/.git` with
`run.preserve_host_path`). Host git runs what lives there: hooks, and config
such as `core.fsmonitor` and `core.hooksPath`. A container that could write
`.git` would get code run on your host the next time you type `git status`.

The bind applies only when `.git` at the project mount root is a real
directory:

- a `.git` **file** (a linked worktree or a submodule) points at a git
  directory outside the mount, which the container cannot reach; nothing is
  bound;
- a `.git` **symlink** is not bound;
- **no `.git`** at the mount root — a launch with no definition from a
  checkout's subdirectory mounts only that subdirectory — means nothing is
  bound. Note that the container can then create a `.git` there, and host git
  run in that directory would use it.

Inside the container `git status`, `log`, and `diff` work, but `git add` and
`git commit` fail with `Unable to create '.git/index.lock': Read-only file
system`. Commit on the host, or relax the default:

```toml
[run]
git_writable = true
```

or, for one launch, `jms launch --git-writable`. Launches with no definition
have only the flag. Without the key, a definition's own read-write
`[[mounts]]` entry whose source is `.git`, a path inside it, or a directory
containing it (such as `.`) is refused, since it would hand the same
directory back writable under another target; a read-only one is fine. The key is manifest content written by the repository
author, so it is covered by the trust fingerprint, and the approval prompt
says "container can write .git (hooks and config there run on your host)".
Approve it only for a repository whose author you trust with your host.

## Mount targets

A relative `target` is resolved lexically from the container project path (`/work`
by default, or the host project path with `run.preserve_host_path = true`).
Trailing slashes and `.`/`..` components are normalized before validation. Relative
targets may land outside the absolute-target allowlist, but cannot overlap the
project, other mounts, reserved agent-state paths, or container system paths such
as `/etc`, `/usr`, `/proc`, and `/root`. Sources still undergo the existing
symlink resolution, existence, and protected-host-directory checks.

For sibling checkouts, this preserves `../sibling/` inside the container:

```toml
[[mounts]]
source = "../sibling/"
target = "../sibling/"
readonly = true

[run]
preserve_host_path = true
```

With the default project path `/work`, the same relative target becomes
`/sibling`. Resolution is always from the project root, even when launching
from a nested working directory. Container target resolution does not follow
host symlinks.

An absolute `target` must be normalized: no trailing slash, no
empty or `.`/`..` component, and no `,`, `=`, or control character (NUL,
newline and the rest of U+0000–U+001F, or DEL). The runtime's mount grammar
cannot carry these: a newline could end the mount record before `readonly`.
Host paths that reach a mount (the project root, extra mount sources) are
refused for the same characters. An absolute target must sit under one of four
prefixes:

- `/home/isolation/` — the home fixed by the
  [project-image user ABI](project-images.md#project-image-user-abi)
- `/opt/`
- `/mnt/`
- `/srv/`

and it may not be, contain, or sit inside a reserved target:

- `/work` — the project mount (still reserved when
  [`run.preserve_host_path`](#project-mount-path) moves the project elsewhere)
- `/home/isolation/.claude`, `/home/isolation/.codex`,
  `/home/isolation/.local/share/opencode`, `/home/isolation/.config/opencode`,
  `/home/isolation/.pi/agent`
  — the agent-state mounts
- `/home/isolation/.config/jms-shell` — the read-only shell-config mount

`jms launch --root` re-checks every target against the effective home
`/root`, so a manifest that mounts under `/home/isolation/...` is refused
under `--root` rather than landing somewhere the manifest did not name. Use
`/opt`, `/mnt`, or `/srv` for a mount that must work as either user.
