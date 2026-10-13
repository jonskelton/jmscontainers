# Linux guide

jms selects local rootless Podman automatically on Linux. The qualified target
is Debian 13 on amd64 with Podman 5.4.2. Any local rootless Podman 5.4 or newer
is accepted; Podman majors newer than the qualified 5.x series produce a
warning. Other distributions, arm64, and SELinux-enforcing hosts are
**unqualified but allowed**.

**Docker is not supported**, rootful or rootless. jms runs only the `podman`
CLI, and file ownership on the project mount depends on Podman's explicit
user-namespace mapping (`--userns=keep-id`), which jms passes on every
launch. Podman installs alongside Docker; jms never talks to the Docker
daemon, and it refuses to mount the socket a `unix://` `DOCKER_HOST` names.

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
- **Files created as container root are not yours on the host.** The
  `isolation` user maps to your host UID, but container root (reached
  through `sudo` inside the container) maps to a subordinate UID. Anything it
  creates in the project shows up on the host owned by a number like
  `100000`, and a plain `rm -rf` can fail with `Permission denied`. Remove
  such files from inside Podman's user namespace instead:
  `podman unshare rm -rf <path>`.
- **The `jmscontainers-` image namespace is reserved.** jms cleanup treats
  local image names with that prefix (after stripping `localhost/`) as its
  own state. Do not tag unrelated images into it.
- **Concurrent image-store mutation is unsupported.** `jms clean` does not
  lock the entire Podman image store. A ref retagged between enumeration and
  removal can cause the wrong alias to be untagged.

## Disk usage

The shared base is roughly 3 GB, and each project image layers on top of
it. After each successful project build, jms keeps that project's two
newest images and deletes the rest. Two kinds of image escape that rule,
and jms never sees them again:

- **Old bases.** Rebuilding the base moves the `jmscontainers-base:latest`
  tag to the new image and leaves the old one untagged ("dangling"). jms
  works only with tagged images, and its own removals pass `--no-prune`, so
  it never deletes a dangling image.
- **Images of deleted projects.** Retention runs only when that project
  builds, and `jms clean` and `jms trust revoke --purge-images` need the
  project directory to exist.

Before deleting a checkout, run `jms clean --images` in it, or
`jms trust revoke --purge-images PATH` to drop its approval as well. For
what is already left over, use Podman's own commands. jms does not run
these for you:

```sh
podman system df                         # space used, and how much is reclaimable
podman images --filter dangling=true     # untagged images, including old bases
podman images --filter label=jms.project # project images built by jms
jms trust list                           # "missing" marks a deleted checkout
```

A project image is named `jmscontainers-<directory>-<id>:<tag>`, where
`<id>` is the first eight characters of the id `jms trust list` prints.
Remove a deleted project's images by name with `podman image rm`, then drop
its stale approval with `jms trust prune`. `podman image prune` removes
every dangling image on your account, not only the ones jms left, so read
the dangling list first.

## Resource limits

jms sets no CPU, memory, or process-count limit on a container, and
`jmscontainer.toml` has no key for one. An agent running `make -j` or a
runaway test competes with everything else on the host. Whatever your
Podman configuration sets as a default still applies, because jms accepts
`containers.conf` as trusted host input (see
[Security boundary](#security-boundary)); that file, or systemd resource
controls on your user session, is where to cap containers today.

## Proxies

jms has no proxy settings of its own, but it runs `podman` with your full
environment. Podman's default (`--http-proxy`, which jms never overrides)
copies `http_proxy`, `https_proxy`, `ftp_proxy`, `no_proxy`, and their
upper-case forms from that environment into both builds and launched
containers. Export them before `jms build` or `jms launch` and the base
build, its package downloads, and the agents all use them. Two consequences:

- **The agent can read them.** A proxy URL that embeds a username and
  password is visible inside every container.
- **Your Podman configuration applies.** A `http_proxy = false` setting in
  `containers.conf` stops the copying; registry mirrors in
  `registries.conf` apply to base and project image pulls.

## What jms refuses

jms refuses non-Linux/non-macOS platforms, uid 0 on Linux, Podman older than
5.4, rootful operation, remote services, inadequate subordinate ID maps, and
malformed or unreadable Podman readiness data. Distribution, architecture,
and SELinux mode are not detected; configurations outside the qualified
matrix run without a support guarantee.
