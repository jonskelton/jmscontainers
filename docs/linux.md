# Linux guide

jms selects local rootless Podman automatically on Linux. The qualified target
is Debian 13 on amd64 with Podman 5.4.2. Any local rootless Podman 5.4 or newer
is accepted; Podman majors newer than the qualified 5.x series produce a
warning. Other distributions, arm64, and SELinux-enforcing hosts are
**unqualified but allowed**.

## Install on Debian 13

Run these commands as a regular user, using `sudo` only for package
installation:

```sh
sudo apt install podman uidmap passt dbus-user-session fuse-overlayfs coreutils make
git clone https://github.com/jonskelton/jmscontainers.git
cd jmscontainers
make install
exec "$SHELL" -l
jms build --base
```

The full package list matters. `uidmap`, `passt`, and `dbus-user-session` are
only recommended dependencies of Podman and may be absent on a minimal system.
`make` is not part of a base Debian install. `coreutils` supplies the required
GNU host tools.

The login-shell restart matters on a fresh account: Debian adds
`~/.local/bin` to PATH at login only when the directory already exists, and
`make install` creates it.

## Rootless prerequisites

jms refuses uid 0, rootful Podman, and remote Podman services. Local path and
ownership semantics depend on running rootless as the invoking user.

Rootless Podman also needs at least 65,536 subordinate UIDs and GIDs. Debian's
`adduser` normally provisions these for newly created users in `/etc/subuid`
and `/etc/subgid`. Check an existing account with:

```sh
grep "^$(id -un):" /etc/subuid /etc/subgid
podman info
```

If the ranges are missing or too small, ask the system administrator to add
them before building an image. jms validates the maps at runtime and reports
the failed prerequisite.

## Security boundary

Linux containers use a rootless user namespace plus Podman's seccomp filter
and capability drops. This kernel boundary is meaningfully weaker than the
per-container VM used on macOS. Container root maps to an unprivileged host
identity, but a kernel or runtime escape can expose everything your host user
can access.

jms does not enforce a Podman sandbox profile. It pins the user-namespace
mapping and disables SELinux labeling, then accepts the rest of your Podman
configuration as trusted host input. If you customized `containers.conf`,
`mounts.conf`, OCI hooks, storage, registries, or policy configuration, those
settings still apply.

The qualified Debian target has no AppArmor or SELinux confinement. See
[SECURITY.md](../SECURITY.md) for the exact boundary and rationale.

## Known limitations

- **Local home filesystem required.** Rootless Podman storage under
  `~/.local/share/containers` is unsupported on NFS and other distributed
  home filesystems. jms does not attempt unreliable filesystem detection;
  Podman reports the failure during readiness, build, or launch.
- **Owner-based access only.** Project trees, extra mounts, and persistent
  state must be accessible through your UID and primary GID. Access granted
  only through supplementary groups, ACLs, or setgid directories does not
  survive the user-namespace mapping.
- **No nested bubblewrap sandbox.** Codex's full bubblewrap sandbox fails on
  rootless Podman's masked `/proc`. Run the agent without its inner sandbox;
  jms does not weaken container defaults to make nesting work.
- **The `jmscontainers-` image namespace is reserved.** jms cleanup treats
  local image names with that prefix (after stripping `localhost/`) as its
  own state. Do not tag unrelated images into it.
- **Concurrent image-store mutation is unsupported.** `jms clean` does not
  lock the entire Podman image store. A ref retagged between enumeration and
  removal can cause the wrong alias to be untagged.

## What jms refuses

jms refuses non-Linux/non-macOS platforms, uid 0 on Linux, Podman older than
5.4, rootful operation, remote services, inadequate subordinate ID maps, and
malformed or unreadable Podman readiness data. Distribution, architecture,
and SELinux mode are not detected; configurations outside the qualified
matrix run without a support guarantee.
