# Security policy

## Trust model

`.jmscontainer/` is project-controlled input — the one untrusted input in the
threat model. jmscontainers fingerprints its exact contents and requires an
explicit build/run grant before the project can be built or launched; the
fingerprint is re-checked immediately before the build and a changed
fingerprint requires fresh consent. Credential mounting is a second, distinct
grant and defaults to no. In non-interactive automation, use an audited exact
fingerprint; do not use a boolean bypass.

Everything else running as the invoking user on the host — the filesystem
outside project definitions, the container runtime and its output, and other
jms processes — is trusted. An attacker who can tamper with those already has
the user's account; jms does not defend the user's machine against itself.

Granting both grants hands the project's image — and every transitive
dependency it pulls in — read/write access to your agents' persistent state:
their credentials and their configuration. The `isolation` user is not a security boundary
(passwordless sudo is by design);
the container boundary limits blast radius to the *host*, not to anything
mounted into the container. Credential mounts stay read-write because the
agent CLIs refresh tokens in place (`--mount …,readonly` exists but would
break auth persistence); recovery from corruption is "delete the dir and log
in again." Prefer dedicated, least-privileged agent accounts for third-party
work; per-project auth profiles are future work. Never claim the container
boundary meaningfully limits exfiltration of mounted credentials.

## The container boundary, per platform

The boundary that contains an approved project is different on the two
supported platforms, and the difference matters:

- **macOS (apple/container):** each container runs in its own lightweight
  virtual machine. The boundary is hardware-virtualized.
- **Linux (rootless Podman):** the boundary is a user namespace plus
  Podman's seccomp filter and capability drops *as configured on the host* —
  kernel isolation, not hardware-virtualized isolation. This is a
  meaningfully weaker boundary than the macOS VM against kernel exploits.
  SELinux label separation contributes nothing here: jms always passes
  `--security-opt label=disable`, because relabeling (`:z`) would `chcon`
  your real project tree and the shared agent-state directories on the host
  — mutating host state and fighting other tools — while the sandbox's real
  boundary is the user namespace. On non-SELinux hosts (the qualified
  Debian 13 target runs AppArmor) the flag is a no-op.

The precise Linux claims:

- **Ambient Podman configuration is trusted host input.** `containers.conf`
  and its drop-ins, `mounts.conf`, `storage.conf`,
  `policy.json`/`registries.conf`, configuration-selecting environment
  variables, and OCI hooks belong to the invoking user and sit in the same
  trust class as the `podman` binary and the kernel, for `build` and `run`
  alike. jms neither validates nor neutralizes them; host configuration
  that mounts additional data into containers is your own configuration,
  outside jms's claims. jms's argv pins only what it itself relies on: the
  explicit `--userns` mapping and `label=disable`.
- **Trusted: the host kernel and the OCI runtime.** The boundary holds only
  as long as they do; a kernel or runtime exploit can cross the namespace
  boundary and potentially elevate beyond the invoking user. No claim of
  the form "an escape can never yield host root" is made.
- **What the boundary aims to contain:** absent such an exploit, container
  processes — including container "root", which is an unprivileged mapped
  UID of the invoking user — hold at most the invoking user's authority on
  the host. `sudo` inside the container works under the isolation user
  because container root is a mapped subordinate UID, not host root.
- **What an escape yields:** everything the invoking user's account can do —
  their files, credentials, processes, and network access. For a
  single-user development machine that is most of what matters; "not host
  root" is a limited consolation and is not presented as more.
- **What no boundary mitigates:** anything deliberately mounted in. Project
  files and mounted credentials are exposed to the agent by design; the
  credential-exfiltration warning above applies regardless of boundary
  type.
- SELinux-**enforcing** hosts are unqualified and unsupported in 1.1.0;
  enforcing-mode support is planned alongside the Fedora host target.
- The host-permission contract is owner-based only: project trees, extra
  mounts, and shell/credential state must be reachable through the invoking
  user's own UID and primary GID. Supplementary-group, ACL-only, and setgid
  access is a documented limitation, with no preflight detection.
- Nested sandboxes: bubblewrap's full sandbox fails inside rootless Podman
  on the masked `/proc`. jms never passes `--security-opt unmask` and does
  not weaken container defaults to accommodate an inner sandbox; agents run
  without one, inside jms's boundary.

Unchanged on both platforms: the protected-source rules, the read-only
shell-mount rationale, the trust-store location, and the credential-mount
warning, none of which depend on the boundary type.

Do not put secrets in Containerfiles, manifests, or files under
`.jmscontainer/`: the whole directory is the build context, so build inputs
and image layers are not a secret channel. Network access is available to
approved builds and containers.

The trust store lives at `~/.config/jmscontainers/store.json`; agent state —
credentials and configuration — lives under
`~/.local/share/jmscontainers/agents/`, outside any git checkout. Neither
location, the jms checkout, nor the agent-state directories can ever be
mounted into a container — not by a project manifest, not as a project
root, and not as the workdir of a base-image `jms launch` (explicit or
defaulted from the current directory). The one jms-controlled exception is
`~/.local/share/jmscontainers/shell/`, which jms itself mounts **read-only**
at `~/.config/jms-shell` so user shell config reaches every container.
Read-only is load-bearing there: those files execute at shell startup in
every container, so a writable mount would let one compromised container
persist into all future ones. Projects still cannot mount that source or
claim its target. Those sources are rejected before
the consent prompt and before any container starts, so neither an approved
definition nor a container-side agent can grant itself further trust by
editing the trust store or the jms code the host will run next. To hack on
jms itself inside a container, work from a scratch clone of the checkout
rather than the live one.

## Reporting a vulnerability

The supported version is the latest release; older releases receive no
fixes.

Please do not file public issues for suspected vulnerabilities. Contact the
maintainer privately through the repository's security advisory/reporting
channel, including a minimal reproduction, affected revision, impact, and any
suggested mitigation. We will acknowledge the report, investigate it, and
coordinate disclosure after a fix or mitigation is available.
