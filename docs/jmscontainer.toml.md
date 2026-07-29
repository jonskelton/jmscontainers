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
```

## Schema

Unknown keys at every level are errors. Values are exact TOML types: no
coercion is performed, and floats and datetimes are accepted nowhere.

| Key | Type | Default | Rules |
| --- | --- | --- | --- |
| `schema` | integer | `1` | Must be `1`; a newer integer version fails closed and asks for a newer `jms`. |
| `name` | string | project-directory slug | Cosmetic slug for generated container names. Must match `^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$`. It does not affect the project ID, but it is manifest content: changing it changes the trust fingerprint, and the image tag ends in that fingerprint. |
| `env` | table | empty | Environment names match `^[A-Za-z_][A-Za-z0-9_]*$`; values are strings without NUL or newline. |
| `mounts` | array of tables | empty | Each item has `source`, `target`, and optional `readonly` only. |
| `mounts[].source` | string | — | Required, nonempty host path. `~`, `$VAR`, and `${VAR}` expand once from the host environment; unset or empty expansions fail. The result must be absolute and must already exist: jms canonicalizes it (resolving symlinks) while parsing, so a missing source is a manifest error. |
| `mounts[].target` | string | — | Required, absolute container path under the allowlist in [Mount targets](#mount-targets). Targets may not overlap each other or any reserved path. |
| `mounts[].readonly` | boolean | `true` | Set `false` only when the container must write the host path. |
| `run` | table | defaults below | Only `entry` and `mount_auth`. |
| `run.entry` | array of strings | `["/bin/bash", "-l"]` | Nonempty; first element nonempty; no element contains NUL. |
| `run.mount_auth` | boolean | `true` | The key name is historical: it gates the agent-state mount (credentials and configuration). If false, mounting requires the user to type `--auth`; it does not change the approval record or prompts. |

Any byte change under `.jmscontainer/` — including this manifest — changes the
trust fingerprint and requires fresh consent.

`source` values are host-controlled capability requests. They are canonicalized
before approval; mount sources that touch jms credential, configuration, or tool
directories are rejected. For the complete security and trust behavior, see
[SECURITY.md](../SECURITY.md).

## Mount targets

A `target` is an absolute, normalized container path: no trailing slash, no
empty or `.`/`..` component, and no `,`, `=`, or NUL (the runtime's mount
grammar cannot carry the first two). It must sit under one of four prefixes:

- `/home/isolation/` — the default runtime user's home
- `/opt/`
- `/mnt/`
- `/srv/`

and it may not be, contain, or sit inside a reserved target:

- `/work` — the project mount
- `/home/isolation/.claude`, `/home/isolation/.codex`,
  `/home/isolation/.local/share/opencode`, `/home/isolation/.config/opencode`
  — the agent-state mounts
- `/home/isolation/.config/jms-shell` — the read-only shell-config mount

`jms launch --root` re-checks every target against the effective home
`/root`, so a manifest that mounts under `/home/isolation/...` is refused
under `--root` rather than landing somewhere the manifest did not name. Use
`/opt`, `/mnt`, or `/srv` for a mount that must work as either user.
