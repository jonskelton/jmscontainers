# Proposal: Declare the standalone image user ABI

Status: Accepted and implemented in 1.1.0 (2026-08-03). The ABI is normative
in the [project image guide](project-images.md#project-image-user-abi); this document is the
design record behind it.
Target: 1.1.0 multi-runtime release
Related issue: RC-001 in `docs/release-critical-issues.md` (closed)

## Summary

Make `isolation` at UID/GID `1000:1000` an explicit ABI requirement for every
jms project image, including images that do not inherit
`jmscontainers-base:latest`.

The ABI will require:

- a user named `isolation` with UID 1000 and primary GID 1000;
- a passwd entry whose home is `/home/isolation` and shell is `/bin/bash`;
- an existing, writable `/home/isolation` directory owned by `1000:1000`; and
- passwordless sudo for `isolation`.

The standalone example will pin this identity rather than relying on the base
distribution's account-allocation defaults. Unit tests will keep the runtime
constants and repository-owned image definitions in agreement. The real
Podman integration tier will launch the standalone image and verify the
complete ABI.

This proposal does not add image inspection or support arbitrary
container-side UID/GID values.

## Problem statement

The multi-runtime implementation contains a numeric user contract that is
only partially declared.

The Podman serializer in `bin/jms:489-506` launches the normal mode with:

```text
--user 1000:1000
--userns=keep-id:uid=1000,gid=1000
```

Both values are derived from `ISOLATION_UID = 1000` in `bin/jms:36-40`.
Podman's `keep-id` options are consequential: Podman 5.4.2 documents
`uid=UID` and `gid=GID` as overriding the container-side UID and GID to which
the current host user is mapped. Its mapping table gives
`keep-id:uid=200,gid=210` as mapping the host caller to container identity
`200:210`.

Reference:
[Podman 5.4.2, `--userns=mode`](https://docs.podman.io/en/v5.4.2/markdown/podman-run.1.html#usernsmode).

The repository base image satisfies the numeric contract. `Containerfile:26-31`
pins `isolation` to UID/GID `1000:1000`, and the unit test at
`tests/test_jms.py:1998-2006` checks that the base Containerfile agrees with
`ISOLATION_UID`.

Standalone images are not held to the same contract:

- `README.md:197-199` says only that the runtime user needs a home directory
  and `/bin/bash`. It does not state the user's name, numeric UID/GID, fixed
  home path, or sudo requirement in the project-image contract.
- `examples/README.md:24-25` says the standalone example creates the required
  `isolation` user, but does not describe its numeric identity.
- `examples/clean-slate/.jmscontainer/Containerfile:5-8` invokes `useradd`
  without `--uid` or `--gid`, leaving the identity to the selected base
  image's account database and allocation policy.
- `scripts/integration.sh:292-298` proves that the clean-store standalone
  image can fetch and build, but does not launch it and verify its user ABI.
  The earlier example loop launches only `/bin/true`, which cannot distinguish
  a correct account from a numeric process with no matching passwd entry.

An image conforming to the currently documented contract may therefore assign
`isolation` an identity other than `1000:1000`. On macOS,
`ContainerBackend.run_argv()` passes `--user isolation` and selects that
account by name. On Linux, `PodmanBackend.run_argv()` passes
`--user 1000:1000`, regardless of the image's account database. The two
backends can consequently run the same image as different identities.

On Linux, the mismatch can cause:

- UID 1000 to have no passwd entry or to resolve to a different account;
- `$HOME` and login-shell behavior to disagree with `/home/isolation`;
- the fixed agent and shell-state mount targets under `/home/isolation` to
  disagree with the actual runtime account;
- the sudoers rule for `isolation` not to apply to the numeric process; and
- files prepared for `isolation` during the build to be inaccessible to the
  runtime process.

This violates the intended shared project-image contract and makes a mutable
base image's current account-allocation behavior part of release correctness.

## Goals

1. State one project-image user contract that is valid on both supported
   backends.
2. Preserve Podman's explicit `keep-id` mapping so `/work` and persistent
   state writes retain host ownership.
3. Preserve numeric `--user` selection on Podman so project image content
   cannot select the runtime UID.
4. Make every repository-owned image example conform deterministically.
5. Detect drift in unit tests and exercise the complete contract on a real
   rootless Podman host.
6. Give authors of standalone images a copyable, distribution-appropriate
   construction pattern.

## Non-goals

- Discovering an arbitrary `isolation` UID/GID from an image.
- Inspecting or exporting an image filesystem.
- Adding a runtime ABI-attestation subsystem.
- Rewriting passwd, group, home ownership, or sudoers state at launch.
- Supporting supplementary-group-based host access.
- Changing `--root`, which continues to use `--user 0:0` and
  `--userns=host` under rootless Podman.

## Proposed ABI

A project image that is launched in the default mode MUST satisfy all of the
following:

| Property | Required value |
| --- | --- |
| Account name | `isolation` |
| UID | `1000` |
| Primary GID | `1000` |
| Home in passwd | `/home/isolation` |
| Login shell in passwd | `/bin/bash` |
| Home directory | Exists, is a directory, and is writable by `1000:1000` |
| Privilege escalation | `sudo -n true` succeeds as `isolation` |

The group owning GID 1000 SHOULD be named `isolation`. Repository-owned images
MUST use that name.

The image's final `USER` instruction SHOULD be `USER isolation` so the image
also has a safe default outside jms. jms does not rely on the image default:
both runtimes pass an explicit user during launch.

The fixed paths in `docs/jmscontainer.toml.md:58-69` remain valid under this
ABI. In particular, agent state and shell configuration continue to mount
under `/home/isolation`.

## Implementation

### 1. Make UID and GID explicit runtime constants

Replace the use of one UID constant for both fields with an explicit pair in
`bin/jms`:

```python
ISOLATION_UID = 1000
ISOLATION_GID = 1000
```

`PodmanBackend.run_argv()` will format both `--user` and `--userns` from these
constants:

```text
--user 1000:1000
--userns=keep-id:uid=1000,gid=1000
```

This is primarily a clarity and drift-prevention change; it does not alter
launch behavior.

### 2. Pin the standalone image

Change `examples/clean-slate/.jmscontainer/Containerfile` to allocate the
group and user explicitly:

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

The build SHOULD fail if UID or GID 1000 is already occupied. Silently
reusing or modifying an unrelated account would hide a nonconforming base
image and could assign incorrect ownership or sudo policy.

### 3. Publish the contract

Update `README.md` under "Project definitions" so the existing general
sentence at lines 197-199 is replaced by the complete ABI. Include the pinned
`groupadd`/`useradd` fragment for standalone image authors and explain that
the numeric identity is required by rootless Podman's explicit mapping.

Update `examples/README.md` to state that `clean-slate` demonstrates the
standalone `1000:1000` ABI.

Update `docs/jmscontainer.toml.md` where `/home/isolation` is described so it
links the fixed mount path to the project-image ABI rather than describing it
only as the default user's home.

Update `CHANGELOG.md` to describe the full project-image ABI and the
standalone example pin. The existing entry at lines 34-36 currently mentions
only the base-image pin.

Update `docs/multi-runtime-implementation.md` in these areas:

- Section 3 must state that the pin applies to all conforming project images,
  not only the repository base image.
- Section 7.1 must classify a mismatched passwd entry as a nonconforming image,
  not an accepted way for an image to misdirect its own environment.
- Section 7.4 may continue to reject runtime image attestation, but must
  explain that numeric `--user` enforces the runtime identity while the
  documented ABI makes the corresponding name, home, shell, ownership, and
  sudo state an image-author responsibility.
- The requirements table must cover both repository-owned Containerfiles and
  the real standalone launch assertions.

`SECURITY.md` does not need to treat UID 1000 as a new host privilege. Under
`keep-id`, it is the container-side identity mapped to the invoking host user.
Its existing statement that container root is a mapped subordinate UID
remains unchanged.

### 4. Add unit coverage

Replace or extend `IsolationUidPinTests` so it checks:

1. `ISOLATION_UID == 1000`;
2. `ISOLATION_GID == 1000`;
3. the base `Containerfile` explicitly creates `isolation` with both values;
4. the standalone example explicitly creates `isolation` with both values;
5. the Podman launch golden continues to contain
   `--user 1000:1000`; and
6. the Podman launch golden continues to contain
   `--userns=keep-id:uid=1000,gid=1000`.

The existing launch golden already covers the last two values. The image ABI
test should own the relationship between the constants and both
Containerfiles.

### 5. Add real-runtime conformance

After the clean-store standalone build in `scripts/integration.sh`, launch the
image through jms and assert, inside the container:

```sh
test "$(id -u)" = 1000
test "$(id -g)" = 1000
test "$(id -un)" = isolation
test "$(id -u isolation)" = 1000
test "$(id -g isolation)" = 1000
test "$(getent passwd isolation | cut -d: -f6)" = /home/isolation
test "$(getent passwd isolation | cut -d: -f7)" = /bin/bash
test -d /home/isolation
test -w /home/isolation
test "$(stat -c %u:%g /home/isolation)" = 1000:1000
sudo -n true
```

The integration should also create a file in `/work` and retain the existing
host-ownership assertion. This verifies that the image account ABI and the
`keep-id` host mapping work together, rather than testing either half alone.

The release gate remains the qualified environment described in
`docs/release-checklist.md:24-30`: Debian 13 amd64, local rootless Podman, and
a fresh invoking user whose host UID and primary GID are both non-1000. A
host user at `1000:1000` is not sufficient evidence because it can conceal a
broken namespace mapping.

The macOS real-runtime tier SHOULD continue to launch `clean-slate`. Once the
example is pinned, `--user isolation` must resolve to the same `1000:1000`
account required on Linux.

## Error handling

jms will not add a preflight that diagnoses nonconforming third-party images.
The ABI is an image-author contract, comparable to the existing requirements
for `/bin/bash`, `/home/isolation`, and passwordless sudo.

An image with a conflicting UID/GID allocation should fail while its
Containerfile creates `isolation`. An image that omits the required account
may build but is unsupported and can fail at launch with the runtime or
in-container command's diagnostic.

Documentation should make this distinction explicit so the absence of a jms
preflight is not mistaken for arbitrary-UID support.

## Compatibility and release impact

The change does not alter the Linux argv: Linux already runs the default mode
as numeric `1000:1000`. It makes that behavior a documented producer
requirement and corrects the repository-owned standalone example.

The 1.0 README did not constrain the numeric identity of `isolation`, and the
macOS backend selects it by name. A pre-existing standalone image with a
different UID/GID can therefore work on 1.0/macOS while being nonconforming
under the proposed cross-runtime ABI.

Before release, maintainers must explicitly reconcile this tightening with
`docs/release-checklist.md:3-5`, which says breaking changes require a major
version. The available release decisions are:

1. Treat the previously unspecified numeric identity as an undocumented
   implementation assumption, retain 1.1.0, and publish a prominent migration
   note for standalone images; or
2. Treat arbitrary numeric identities as part of the 1.0 standalone contract
   and use a major version for the fixed cross-runtime ABI.

This proposal recommends the fixed ABI regardless of version number. It does
not recommend claiming that arbitrary-UID standalone images are portable to
Linux.

## Alternatives considered

### Resolve an arbitrary image account and map the host user to it

jms could discover the UID/GID of `isolation`, then construct numeric
`--user` and `keep-id` arguments per image.

This preserves the broadest interpretation of the 1.0 contract, but it
requires a trustworthy image ABI inspection mechanism. The implementation
record at `docs/multi-runtime-implementation.md:1884-1909` documents the
rejected design: create/copy/remove probes, strict passwd/group parsing,
probe lifecycle cleanup, volume suppression, and a significantly larger
integration matrix. Running `id` or `getent` inside the image is not an
independent attestation because it executes image-controlled content.

This complexity is disproportionate to selecting a conventional fixed
development-container identity and would reverse the current numeric-user
design.

### Pass `--user isolation` on Podman

This makes the process UID image-controlled and does not solve the mapping:
`keep-id:uid=1000,gid=1000` would still map the host caller to 1000, while an
`isolation` account at another ID would lose owner access to `/work` and
persistent mounts.

It also contradicts the explicit decision in
`docs/multi-runtime-implementation.md:1808-1822` to keep Podman's runtime UID
independent of image content.

### Use plain `--userns=keep-id`

Without `uid=` and `gid=`, Podman maps the invoking host UID/GID to the same
numeric values inside the container. That would require every image to create
an account matching every possible host user and would make the image
environment host-dependent. It is incompatible with the fixed
`/home/isolation` state paths and with qualification under a fresh non-1000
host user.

### Rewrite the account at container startup

An entrypoint could create or modify `isolation` dynamically. jms deliberately
overrides image entrypoints, the process begins without the required account
state, and mutation would complicate read-only image layers, file ownership,
sudo policy, and both backend implementations. It would also execute
privileged setup code on every launch.

## Acceptance criteria

RC-001 can be closed when all of the following are true:

- The README declares the complete `isolation` `1000:1000` ABI.
- The base and standalone Containerfiles pin the same UID and GID.
- Examples and configuration documentation agree on `/home/isolation`.
- The changelog and implementation record describe the same contract.
- Unit tests tie both Containerfiles to the runtime UID/GID constants.
- Golden tests retain the numeric Podman user and explicit keep-id mapping.
- The standalone image passes the identity, home, shell, sudo, and `/work`
  ownership assertions on the qualified fresh non-1000 Debian host.
- The standalone image still launches successfully in the qualified macOS
  integration run.
- The release notes record the compatibility/versioning decision.
