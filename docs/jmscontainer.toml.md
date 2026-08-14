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
```

## Schema

Unknown keys at every level are errors. Values are exact TOML types: no
coercion is performed, and floats and datetimes are accepted nowhere.

| Key | Type | Default | Rules |
| --- | --- | --- | --- |
| `schema` | integer | `1` | Must be `1`; a newer integer version fails closed and asks for a newer `jms`. |
| `name` | string | project-directory slug | Cosmetic slug for generated container names. Must match `^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$`. It does not affect the project ID, but it is manifest content: changing it changes the trust fingerprint, and the image tag ends in that fingerprint. |
| `env` | table | empty | Environment names match `^[A-Za-z_][A-Za-z0-9_]*$`; values are strings without NUL or newline. `TZ` is special only in that `launch` supplies a default from the host: see [Time zone](#time-zone). |
| `mounts` | array of tables | empty | Each item has `source`, `target`, and optional `readonly` only. |
| `mounts[].source` | string | — | Required, nonempty host path. `~`, `$VAR`, and `${VAR}` expand once from the host environment; unset or empty expansions fail. The result must be absolute and must already exist: jms canonicalizes it (resolving symlinks) while parsing, so a missing source is a manifest error. |
| `mounts[].target` | string | — | Required, absolute container path under the allowlist in [Mount targets](#mount-targets). Targets may not overlap each other or any reserved path. |
| `mounts[].readonly` | boolean | `true` | Set `false` only when the container must write the host path. |
| `run` | table | defaults below | Only `entry`, `mount_auth`, and `preserve_host_path`. |
| `run.entry` | array of strings | `["/bin/bash", "-l"]` | Nonempty; first element nonempty; no element contains NUL. |
| `run.mount_auth` | boolean | `true` | The key name is historical: it gates the agent-state mount (credentials and configuration). If false, mounting requires the user to type `--auth`; it does not change the approval record or prompts. |
| `run.preserve_host_path` | boolean | `false` | Mount the project at its own host path instead of `/work`, so a path-keyed tool resolves the same key inside and outside. See [Project mount path](#project-mount-path). |

Any byte change under `.jmscontainer/` — including this manifest — changes the
trust fingerprint and requires fresh consent.

`source` values are host-controlled capability requests. They are canonicalized
before approval; mount sources that touch jms credential, configuration, or tool
directories are rejected. For the complete security and trust behavior, see
[SECURITY.md](../SECURITY.md).

On the Linux backend, access to a mount source is owner-based: a source is
supported only if it is reachable through the invoking user's own UID and
primary GID. Access that exists only via a supplementary group, an ACL grant,
or a setgid directory does not survive the rootless user-namespace mapping,
so such a mount may resolve and pass approval on the host and still be
unreadable or unwritable inside the container. jms performs no preflight
detection of this; the failure surfaces in the container. The same rule
applies to the project tree itself.

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

## Mount targets

A `target` is an absolute, normalized container path: no trailing slash, no
empty or `.`/`..` component, and no `,`, `=`, or NUL (the runtime's mount
grammar cannot carry the first two). It must sit under one of four prefixes:

- `/home/isolation/` — the home fixed by the
  [project-image user ABI](project-images.md#project-image-user-abi)
- `/opt/`
- `/mnt/`
- `/srv/`

and it may not be, contain, or sit inside a reserved target:

- `/work` — the project mount (still reserved when
  [`run.preserve_host_path`](#project-mount-path) moves the project elsewhere)
- `/home/isolation/.claude`, `/home/isolation/.codex`,
  `/home/isolation/.local/share/opencode`, `/home/isolation/.config/opencode`
  — the agent-state mounts
- `/home/isolation/.config/jms-shell` — the read-only shell-config mount

`jms launch --root` re-checks every target against the effective home
`/root`, so a manifest that mounts under `/home/isolation/...` is refused
under `--root` rather than landing somewhere the manifest did not name. Use
`/opt`, `/mnt`, or `/srv` for a mount that must work as either user.
