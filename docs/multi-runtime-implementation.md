# Implementation guide: supporting Podman on Linux alongside apple/container

Status: proposal (not yet implemented)
Target: jms 1.1.0

This guide describes how to make `jms` run seamlessly on Linux with rootless
Podman while keeping the existing `apple/container` backend on macOS
byte-for-byte compatible. It is written against `bin/jms` at version 1.0.0.

The guiding constraint: **the trust model, fingerprinting, consent flow,
manifest schema, and project discovery do not change at all.** Only the layer
that talks to the container runtime becomes pluggable. A user on either
platform types the same commands, reads the same consent prompts, and gets the
same `/work` + agent-state contract inside the same Fedora image.

### Compatibility contract (resolves MIR-005)

"Compatible" means exactly the following enumerated invariants, each of which
must be pinned by a regression test or golden before release; anything not
listed here may change:

**Invariant on both platforms:**

- Trust-store location, record format, and semantics.
- Project trust fingerprints (the `GOLDEN_TREE_TF`-style goldens must not
  change).
- Consent prompt text, ordering, and accepted responses.
- Manifest schema and validation errors.
- Project discovery and workdir resolution rules.
- Documented exit codes.
- The CLI surface, except for the additive `JMS_RUNTIME` variable.

**Invariant on macOS specifically:**

- The exact `container` argv for build, launch (all variants), list, and
  cleanup operations, pinned by golden argv tests.
- Diagnostics for existing failure modes (missing CLI, version mismatch,
  image not found).

**Intentionally changed, and listed in the changelog and release notes:**

- The base `Containerfile`: `isolation` UID/GID pinned to 1000 and the
  virtiofs comment updated (§3). A rebuilt base image therefore differs in
  content from a 1.0.0 build; behavior is verified unchanged on macOS
  (§11 phase 3).
- New diagnostics for runtime selection failures (invalid `JMS_RUNTIME`,
  unsupported platform, uid-0 on Linux).

**Explicitly not invariant:** startup timing, internal code structure, and
wording of newly introduced (Linux-only) diagnostics.

## 0. Pre-implementation review gate

Review date: 2026-07-29

This section is normative for implementation planning. The design below is
not implementation-ready while any **blocker** remains open. Issue IDs are
stable so they can be copied into commits, pull requests, or an external issue
tracker. When an issue is resolved, replace `Open` with `Resolved` and add a
short decision plus links to the implementing tests/commit; do not delete the
issue or renumber later issues.

The review checked this proposal against the current `bin/jms`, unit tests,
integration script, workflow, README, and security documentation. It also
checked the proposed Podman contracts against the Podman 4.9.3 and current
manuals. In particular, these upstream references are load-bearing:

- [Podman 4.9.3 `run`](https://docs.podman.io/en/v4.9.3/markdown/podman-run.1.html)
- [Podman 4.9.3 `ps`](https://docs.podman.io/en/v4.9.3/markdown/podman-ps.1.html)
- [Podman 4.9.3 `info`](https://docs.podman.io/en/v4.9.3/markdown/podman-info.1.html)
- [current `podman images`](https://docs.podman.io/en/stable/markdown/podman-images.1.html)
- [GitHub-hosted Ubuntu 24.04 image inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)

### Issue summary

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| MIR-001 | Blocker | Runtime lifecycle | Resolved (design) |
| MIR-002 | Blocker | Runtime/platform selection | Resolved (design) |
| MIR-003 | Blocker | Consent and preflight ordering | Resolved (design) |
| MIR-004 | Blocker | Backend interface | Open |
| MIR-005 | Blocker | Compatibility contract | Resolved (design) |
| MIR-006 | Blocker | Podman image schema | Open (partially addressed) |
| MIR-007 | Blocker | Podman container schema | Open (partially addressed) |
| MIR-008 | Blocker | Rootless readiness | Open (partially addressed) |
| MIR-009 | Blocker | Deterministic user namespaces | Resolved (design) |
| MIR-010 | Blocker | Isolation-user ABI | Open |
| MIR-011 | Blocker | Base-image resolution | Resolved (design) |
| MIR-012 | Blocker | Security claims | Resolved (design) |
| MIR-013 | High | SELinux policy | Open (partially addressed) |
| MIR-014 | High | Version/support policy | Open |
| MIR-015 | High | Linux prerequisites | Open |
| MIR-016 | High | Host filesystem permissions | Open |
| MIR-017 | High | Nested sandbox behavior | Open (partially addressed) |
| MIR-018 | High | Image identity and garbage collection | Open |
| MIR-019 | High | Integration coverage | Open |
| MIR-020 | High | CI definition | Open |
| MIR-021 | High | Rollout and documentation atomicity | Resolved (design) |

"Resolved (design)" means the design ambiguity is settled in this document
with a recorded decision; the issue's **Done when** criteria remain the
acceptance tests the implementation must land before release.

### MIR-001 — Runtime selection must not break runtime-free commands

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** Runtime selection is lazy: a `runtime()` accessor selects and
  caches the backend on first use, and only runtime-touching seams call it
  (§2). Pure commands (`--version`, `inspect`, `init`, store-only `trust`
  forms) never select a runtime, so they work with no runtime installed, on
  unsupported platforms, and under uid 0. Tests install a backend by setting
  the cached value directly; imports never consult `JMS_RUNTIME` or the
  platform. Phase 1 no longer fails Linux at startup (§11). Acceptance tests
  per **Done when** land with the implementation.
- **Affects:** §§2, 9, and 11
- **Finding:** Selecting and validating a module-level `RUNTIME` at import or
  process startup can make `jms --version`, `inspect`, `init`, and the
  store-only `trust` forms fail on unsupported platforms, under uid 0, or
  without a runtime installed. It also conflicts with the current Linux unit
  jobs, which import `bin/jms` before any fake runtime is installed. Phase 1's
  proposed "Linux fails with coming soon" behavior would therefore break the
  existing Ubuntu test matrix.
- **Required resolution:** Define lazy selection/validation semantics. Pure
  commands must remain runtime-free, and tests must be able to install a
  backend without depending on import-time platform or environment state.
- **Done when:** Unit tests prove `--version`, `inspect`, `init`, `trust list`,
  `trust revoke` without `--purge-images`, and `trust prune` work with no
  runtime executable, on an unsupported platform, and in a mocked uid-0
  process. Ubuntu and macOS imports must not need `JMS_RUNTIME`.

### MIR-002 — The platform/override matrix and remote Podman are undefined

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The support matrix in §2 is now explicit: macOS/apple-container
  and Linux/local-rootless-Podman are the only supported combinations; forced
  cross-platform combinations (`JMS_RUNTIME=podman` on macOS,
  `JMS_RUNTIME=container` on Linux) are rejected with exit 2 before any trust
  prompt. Remote Podman is rejected: `ensure_started()` parses
  `podman info --format json` and fails when `host.serviceIsRemote` is true,
  so `CONTAINER_HOST`/`CONTAINER_CONNECTION`/containers.conf connections are
  detected at the engine rather than guessed from the environment (§§2, 4, 12).
  Acceptance tests per **Done when** land with the implementation.
- **Affects:** §§2, 4, 10, and 12
- **Finding:** The sample selector permits `JMS_RUNTIME=podman` on macOS and
  `JMS_RUNTIME=container` on Linux even though the stated support model is
  macOS/apple-container and local Linux/rootless-Podman. Podman also switches
  to a remote service when `CONTAINER_HOST`, `CONTAINER_CONNECTION`, or
  containers configuration selects one. A local `geteuid()` check says
  nothing about that service's operating system or rootless status.
- **Required resolution:** Publish an explicit platform/backend matrix and
  either reject remote Podman and unsupported forced combinations or expand
  the design, threat model, version checks, path semantics, and tests to
  support them. Document precedence and treatment of all Podman connection
  environment/configuration, not only `JMS_RUNTIME`.
- **Done when:** Selection tests cover every platform/backend combination and
  a Podman-info fixture with `serviceIsRemote=true`. Unsupported combinations
  fail before trust prompts and with a documented exit code.

### MIR-003 — The proposed preflight timing contradicts the current consent flow

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The current ordering is kept unchanged on both backends:
  `approve()` runs before `runtime_ready()` (as `cmd_build` and `cmd_launch`
  do today). This preserves the existing property that an unapproved
  definition never contacts the runtime, and macOS behavior does not change.
  Consequence, accepted deliberately: a durable trust grant may be recorded
  before a Linux preflight failure. That is safe because a grant records
  consent to a project definition, not runtime state — the command then fails
  without building or running anything, and the grant remains valid for a
  retry after the host is fixed. §4's "before any build or consent prompt"
  claim is corrected to "after consent, before any build". Call-order tests
  per **Done when** land with the implementation.
- **Affects:** §§1, 4, and 11
- **Finding:** Section 4 says readiness failures are reported "before any build
  or consent prompt", but current project `build` and `launch` call `approve()`
  before `runtime_ready()`. Moving the probe earlier changes observable
  consent flow and the existing property that an unapproved definition does
  not contact the runtime. Leaving the order unchanged means a durable grant
  may be recorded before Linux prerequisites fail.
- **Required resolution:** Choose and document one ordering, including why it
  is safe, whether durable trust may be written before runtime preflight, and
  whether macOS behavior changes. Do not claim both an unchanged consent flow
  and pre-consent Podman probing.
- **Done when:** Call-order tests cover approval accepted, approval declined,
  non-interactive trust failure, missing runtime, and unusable rootless
  Podman. User-facing documentation matches the tested order.

### MIR-004 — The backend contract is incomplete and too implicit

- **Status:** Open
- **Affects:** §§2, 5, 6, and 7
- **Finding:** The method table omits the later backend-specific
  `mount_argument()`, does not define the type or invariants of the `plan`
  passed to `run_argv(plan)`, and leaves execution ownership unclear for
  `ensure_started()` and `image_exists()`. It also does not define whether
  backends return raw processes, normalized data, or already-rendered
  failures. This invites backend conditionals to leak back into command
  functions and makes terminal-safe diagnostics inconsistent.
- **Required resolution:** Specify the complete backend protocol, typed
  normalized inputs/outputs, command execution ownership, validation
  boundaries, and error contract. State which free functions remain stable
  monkeypatching seams and prohibit backend methods from bypassing
  `runtime_run()`.
- **Done when:** A protocol/interface test exercises both backends through the
  same conformance suite, including malformed UTF-8, malformed JSON, nonzero
  exits, and mount serialization. No command function branches on backend
  type or name.

### MIR-005 — “Byte-for-byte compatible” is undefined and currently impossible

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The "byte-for-byte" phrase is removed and replaced by the
  enumerated "Compatibility contract" section in the introduction, which
  classifies each surface (trust fingerprints, consent flow, macOS argv,
  diagnostics, exit codes, Containerfile, base-image contents) as invariant
  or intentionally changed. Regression tests/goldens per **Done when** land
  with the implementation.
- **Affects:** introduction and §§3, 7, 9, and 11
- **Finding:** Pinning UID/GID and changing Containerfile comments necessarily
  changes the macOS base image, while backend extraction can change argv,
  diagnostics, and startup timing. That conflicts with the opening
  "byte-for-byte compatible" claim. The document alternately appears to mean
  unchanged trust fingerprints, unchanged apple/container argv, and unchanged
  user-visible behavior; those are different contracts.
- **Required resolution:** Replace the phrase with an enumerated compatibility
  contract. At minimum decide whether exact argv order, diagnostics, exit
  codes, consent/store writes, project trust fingerprints, generated
  Containerfiles, and base-image contents are each invariant or intentionally
  changed.
- **Done when:** Each claimed invariant has a regression test or golden. Every
  intentional macOS change is listed in the changelog and release notes.

### MIR-006 — The proposed Podman image JSON schema is contradicted upstream

- **Status:** Open (partially addressed 2026-07-29)
- **Progress (local qualification, Podman 5.4.2 rootless, Debian 13):**
  a real `podman images --format json` fixture is checked in as
  `tests/fixtures/podman-5.4.2-images.json`. On 5.4.2 the raw shape matches the
  proposal's original assumption — uppercase `Id`, `Names` (array), integer
  `Created`, top-level `Labels` map — plus an RFC3339 `CreatedAt` string,
  `Digest`, and `RepoTags` that can be `null`. This confirms the manual's
  lowercase example does not describe 5.4.2's raw output, i.e. the shape
  variance concern is real, not hypothetical.
- **Progress (matrix-minimum qualification, 2026-07-29, Podman 4.9.3
  rootless, Ubuntu 24.04 — nested capture, see `tests/fixtures/README.md`):**
  `tests/fixtures/podman-4.9.3-images.json` shows the identical raw shape —
  uppercase `Id`, `Names` array, integer `Created`, top-level `Labels` —
  and adds dangling-image coverage: dangling records carry JSON null for
  both `Names` and `RepoTags`. Both ends of the version range now agree, so
  a single normalizer can serve 4.9–5.4. Still open: the contract decision
  (jms-owned projection vs. fixture-versioned normalizer) and the strict
  handling rules for `<none>`/null names, digests, and malformed records.
- **Affects:** §§5 and 9
- **Finding:** The proposal assumes `Id`, `Names`, integer `Created`, and
  `Labels`. The current Podman manual's `podman images --format json` example
  uses lowercase `id`, `names`, and an RFC3339 `created` string. Raw JSON shape
  and field casing have varied across Podman releases, and the proposal
  supplies no captured 4.9.x or 5.x fixtures. Implementing the shown
  normalizer would silently skip all images on at least one documented shape,
  disabling GC and `clean --images`.
- **Required resolution:** Choose a stable query contract: preferably an
  explicit Go template/JSON projection owned by jms, or a versioned
  normalizer backed by real outputs. Define exact handling for missing labels,
  `<none>`, null/empty names, digests, multiple tags, malformed records, and
  creation times.
- **Done when:** Checked-in fixtures from every minimum release target and at
  least one current 5.x release pass strict normalization tests. Tests prove
  project GC and both clean scopes select the intended refs and fail closed on
  malformed ownership-relevant fields.

### MIR-007 — Podman `ps` and integration mount schemas are unqualified

- **Status:** Open (partially addressed 2026-07-29)
- **Progress (local qualification, Podman 5.4.2 rootless, Debian 13):**
  a real `podman ps --all --format json` fixture with running, stopped, and
  labelled containers is checked in as
  `tests/fixtures/podman-5.4.2-ps.json`. On
  5.4.2: `Id` is the full 64-character ID, `Labels` is a top-level map, and
  image labels are inherited onto container `Labels` (the jms label check
  must therefore key on the jms-owned label exactly, as it already does).
  **Load-bearing negative finding:** the `Mounts` field is only a flat list
  of *target* paths (e.g. `["/work"]`) — it carries no source information,
  so the proposed integration leak sweep cannot identify jms mounts from
  `ps` JSON at all and must use `podman inspect` (or a Go-template
  projection of `.Mounts`) instead; §9 is updated accordingly.
- **Progress (matrix-minimum qualification, 2026-07-29, Podman 4.9.3
  rootless, Ubuntu 24.04 — nested capture, see `tests/fixtures/README.md`):**
  `tests/fixtures/podman-4.9.3-ps.json` matches the 5.4.2 shape — full
  64-char `Id`, top-level `Labels` with image-label inheritance — and the
  no-sources `Mounts` finding holds on 4.9.3 too (`["/work"]`).
  Auto-removed coverage is captured: a `--rm` container does not appear in
  `ps --all`. `tests/fixtures/podman-4.9.3-inspect-mounts.json` confirms
  `podman inspect` exposes `Source`/`Destination`, so the inspect-based
  sweep works across the whole version range. Still open:
  malformed-record handling and writing the inspect-based leak-sweep
  contract into §9 as a testable spec.
- **Affects:** §§5 and 9
- **Finding:** The design assumes raw `podman ps --format json` records contain
  `Id`, top-level `Labels`, and an integration-usable `Mounts` field with a
  particular shape. The 4.9.3 manual documents Go-template fields but does not
  establish the raw JSON casing or nested mount representation used here.
  Truncated versus full IDs is also unspecified.
- **Required resolution:** Project only the fields jms needs into a stable
  format or capture and support exact per-version schemas. The leak sweep must
  use a documented representation, and cleanup must validate IDs and label
  values before acting.
- **Done when:** Real 4.9.x and 5.x fixtures cover running, stopped,
  auto-removed, malformed, labelled, and unlabelled containers plus bind
  mounts. Cleanup and leak-sweep tests operate on those fixtures.

### MIR-008 — `podman info` is not a sufficient rootless health probe

- **Status:** Open (partially addressed 2026-07-29)
- **Progress (local qualification, Podman 5.4.2 rootless, Debian 13):**
  a healthy-engine `podman info --format json` fixture is checked in as
  `tests/fixtures/podman-5.4.2-info.json` (sanitized: username and hostname
  replaced). All fields the expanded probe would need
  exist with the expected casing on 5.4.2: `host.serviceIsRemote` (bool),
  `host.security.rootless` (bool), `host.idMappings.uidmap`/`gidmap`
  (present, showing the invoking-user + subordinate-range entries),
  `host.ociRuntime.name`, `host.networkBackend`, and
  `store.graphDriverName`. So the probe *can* validate rootless state,
  remoteness, and ID mappings from one invocation, not just storage.
- **Progress (matrix-minimum qualification, 2026-07-29, Podman 4.9.3
  rootless, Ubuntu 24.04 — nested capture, see `tests/fixtures/README.md`):**
  `tests/fixtures/podman-4.9.3-info.json` shows every probe-relevant field
  present with identical casing on 4.9.3 (`host.serviceIsRemote`,
  `host.security.rootless`, `host.idMappings.uidmap`/`gidmap`,
  `host.ociRuntime.name`, `host.networkBackend`,
  `store.graphDriverName`), so one parser covers the version range. Still
  open: the readiness scope decision (which of these fields are checked,
  and whether a cached create/run probe is included), failure-mode fixtures
  (rootful, remote, missing/undersized ID maps, storage/OCI/network
  failures, invalid JSON), and evidence-driven hints instead of the single
  shadow-utils diagnosis.
- **Affects:** §§2, 4, and 9
- **Finding:** Printing only `Store.GraphDriverName` proves that Podman can
  inspect storage; it does not prove the selected engine is local, Linux,
  rootless, has usable subordinate ID mappings, can create
  `keep-id:uid=1000,gid=1000`, has a working OCI runtime/network helper, or can
  bind-mount the project. The targeted hint also assumes every failure is
  caused by `shadow-utils`/subuid configuration, which can misdiagnose NFS
  homes, storage drivers, cgroups, networking, or remote services.
- **Required resolution:** Parse `podman info --format json` and validate the
  fields required by the support policy, including rootless and remote state.
  Decide whether readiness includes a cached minimal create/run probe using
  the exact user namespace and security flags. Preserve the actual stderr and
  emit hints selected by evidence rather than one universal diagnosis.
- **Done when:** Tests cover rootful, remote, missing/undersized ID maps,
  storage failure, OCI-runtime failure, network-helper failure, invalid JSON,
  and a healthy engine. A real fresh-user integration run validates the
  preflight.

### MIR-009 — Omitting `--userns` under `--root` is not deterministic

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** §7.1 passes an explicit `--userns` for **both** launch
  variants (`keep-id:uid=1000,gid=1000` normally, `host` under `--root` —
  the explicit spelling of the rootless `$UID → 0` mapping), so neither
  `PODMAN_USERNS` nor `containers.conf` can silently change the mapping.
  Both halves of that claim and the `--root` contract are now empirically
  qualified on Podman 5.4.2 (evidence below); the §7.1 fallbacks
  (`keep-id:uid=0,gid=0`, explicit `--uidmap`) remain documented but are
  not needed. Repetition of the same checks on the matrix minimum
  (Ubuntu 24.04's Podman 4.9.x) folds into the **Done when** acceptance
  tests, alongside the standing requirement that any other load-bearing
  ambient Podman default discovered during implementation be either
  overridden explicitly or detected and rejected.
- **Qualification evidence (2026-07-29, Podman 5.4.2 rootless, Debian 13,
  overlay driver, fedora:latest plus a derived image with `isolation`
  pinned to UID/GID 1000 per §3):**
  - `--userns=host` → container `uid=0 gid=0`; `keep-id:uid=1000,gid=1000`
    → container `uid=1000 gid=1000`.
  - Bind-mounted `/work` writes under both variants owned on the host by
    the invoking user, including the exact `--root` shape
    (`--userns=host`, container root) and the exact default shape
    (`--userns=keep-id:uid=1000,gid=1000 --user isolation`).
  - `--user isolation` resolves to `uid=1000(isolation)` under both
    `keep-id:uid=1000,gid=1000` and `host` modes against the pinned §3
    user. (Under `host` mode the isolation user maps to a subordinate UID
    and cannot write `/work` — irrelevant to jms, which uses `host` only
    for `--root`, i.e. container root; recorded to prevent a future
    "run isolation under host mode" variant.)
  - Conflicting `PODMAN_USERNS` loses to the explicit flag in both
    directions (`PODMAN_USERNS=keep-id` + `--userns=host` → uid 0;
    `PODMAN_USERNS=host` + `--userns=keep-id:uid=1000,gid=1000` → uid
    1000), satisfying the env-var half of **Done when**.
  - Conflicting `containers.conf` (`[containers] userns` via
    `CONTAINERS_CONF_OVERRIDE`) also loses to the explicit flag in both
    directions, with a no-flag control run confirming the conf setting
    does take effect when nothing is passed — satisfying the
    `containers.conf` half of **Done when** on 5.4.2.
  - 2026-07-29 addendum: the full matrix above (both `--userns` variants,
    `/work` ownership, `--user isolation` resolution, `PODMAN_USERNS` and
    `containers.conf` conflicts in both directions plus the no-flag
    control) passed identically on Podman 4.9.3 rootless under Ubuntu
    24.04 — as a nested container capture, not bare metal (see
    `tests/fixtures/podman-4.9.3-qualification-results.txt`).
  - Not yet covered (acceptance work): the same runs on a real (non-nested)
    Ubuntu 24.04 host as CI integration tests.
- **Affects:** §7.1
- **Finding:** Podman documents that the default user namespace can be changed
  by `PODMAN_USERNS` or `containers.conf`; only in the absence of those
  settings does rootless Podman map the invoking user to container root.
  Therefore "pass no `--userns` flag" does not guarantee the proposed
  `--root` contract. Other ambient Podman defaults may similarly change
  behavior the design assumes.
- **Required resolution:** Pass an explicit user-namespace mode for both
  launch variants (subject to empirical qualification per §7.1), and
  inventory every
  ambient Podman setting that can alter security-, mount-, pull-, or user-
  relevant behavior. Either override each load-bearing default or document it
  as unsupported and detect it.
- **Done when:** Integration tests set conflicting `PODMAN_USERNS` and
  temporary `containers.conf` values yet still observe the documented UID/GID
  mapping for normal and `--root` launches.

### MIR-010 — UID/GID 1000 must be an enforced image ABI, not a comment

- **Status:** Open
- **Affects:** §§3 and 7.1
- **Finding:** A constant in `bin/jms` and a literal in the Containerfile are
  two sources of truth, not one. More importantly, project Containerfiles are
  allowed to modify or recreate `isolation`; `--user isolation` may then
  resolve to a UID other than the `keep-id` mapping's 1000. Existing cached
  base/project images are not automatically rebuilt merely because jms or the
  checkout Containerfile changed.
- **Required resolution:** Define the runtime-user ABI for base and project
  images, how jms enforces or validates it, and how the UID/GID value is kept
  synchronized. Add an image ABI/version label or another migration mechanism
  so stale/incompatible images cannot be launched. Decide behavior for custom
  images that deliberately alter `isolation`.
- **Done when:** Tests cover a stale pre-change base image, a cached project
  image, a project that changes the UID/GID, a missing `isolation` user, and a
  synchronized UID/GID source. Launch fails before mounting credentials when
  the ABI is incompatible.

### MIR-011 — Local short-name resolution is a release blocker, not a caveat

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** Project Containerfiles keep `FROM jmscontainers-base:latest`,
  and the Podman backend makes resolution deterministic by **always passing
  `--pull=never` on project builds** (§6): Buildah resolves the `FROM` short
  name against local storage first, and `--pull=never` guarantees that no
  registry is consulted or prompted regardless of `registries.conf`. The
  missing-base error path is defined: the build fails fast and
  non-interactively with Buildah's `image not known` error (exit 125), which
  jms wraps in its existing build-failure reporting plus a "run `jms build`
  for the base image first" hint. Base builds keep `--pull=always` only when
  the caller requests pull (§6), unchanged.
- **Qualification evidence (2026-07-29, Podman 5.4.2 rootless, Debian 13):**
  with a locally built `localhost/jmscontainers-base:latest` present, a
  project build `FROM jmscontainers-base:latest` with `--pull=never
  --network=none` succeeds offline; with the base absent it fails fast,
  non-interactively, with `image not known` (exit 125). Both results hold
  identically under three `registries.conf` variants injected via
  `CONTAINERS_REGISTRIES_CONF`: no unqualified-search registries (this
  host's default), permissive short-name mode with search registries, and
  enforcing short-name mode with search registries. 2026-07-29 addendum:
  the identical six-cell matrix (three `registries.conf` variants × base
  present/absent, `--pull=never --network=none`, non-interactive) passed
  on Podman 4.9.3 rootless under Ubuntu 24.04 (nested capture; see
  `tests/fixtures/podman-4.9.3-qualification-results.txt`), including the
  fast `image not known` exit-125 failure with the base absent. Remaining
  acceptance work per **Done when**: a network-isolation proof in CI on a
  real Ubuntu 24.04 runner rather than a scratch run.
- **Affects:** §§3, 6, 9, and 10
- **Finding:** The entire project build path depends on
  `FROM jmscontainers-base:latest` resolving to
  `localhost/jmscontainers-base:latest` without registry prompting or network
  access. Behavior can vary with `registries.conf`, short-name aliases,
  enforcement mode, Buildah/Podman versions, and whether the local image is
  present. The proposed "offline-ish" test does not prove no registry access.
- **Required resolution:** Either remove the short-name dependency with a
  canonical local reference/mapping that preserves existing project files, or
  explicitly qualify the relevant configurations. Define the missing-base
  error path and ensure no prompt can hang non-interactive builds.
- **Done when:** Tests run with strict and permissive short-name configs,
  `--pull=never`, and network disabled; they cover local base present and
  absent. Packet/network isolation or an equivalent deterministic mechanism
  proves the success case did not contact a registry.

### MIR-012 — The Linux security statement overpromises

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** §8 is rewritten as an explicit Linux threat model that
  enumerates the boundary components, the trusted computing base (kernel and
  OCI runtime), what an escape yields, the disabled SELinux separation, and
  the mounted-data exposure that no boundary mitigates. The categorical
  "never host root" claim is removed. The SECURITY.md review and claim tests
  per **Done when** land with the docs/enablement phase (§11).
- **Affects:** §§7.2 and 8
- **Finding:** "A container escape yields the invoking user's account, never
  host root" is too absolute. A kernel exploit may cross user-namespace
  boundaries or elevate further, and an escape to the host user already gains
  all resources available to that account. The phrase also obscures the
  deliberate disabling of SELinux label separation. Rootless Podman is a
  materially different and weaker boundary than the macOS VM, but the exact
  guarantees and non-guarantees are not stated precisely enough.
- **Required resolution:** Have the Linux threat model explicitly enumerate
  protected assets, attacker capabilities, mounted-data exposure, host-user
  consequences, kernel/OCI-runtime trust, and the effects of rootless mode,
  seccomp, capabilities, AppArmor/SELinux, and `--root`. Remove categorical
  claims that the design cannot guarantee.
- **Done when:** `SECURITY.md` wording is reviewed as a release-blocking
  artifact and tests verify every enforceable claim. README language links to
  the detailed model and does not summarize Linux as VM-equivalent.

### MIR-013 — Disabling SELinux needs a documented security decision and test

- **Status:** Open (partially addressed 2026-07-29)
- **Progress:** the non-SELinux half of **Done when** is observed locally:
  every qualification run on 2026-07-29 (Podman 5.4.2 rootless, Debian 13,
  an AppArmor host) passed `--security-opt label=disable` and the flag was
  accepted as a no-op. 2026-07-29 addendum: the flag is likewise accepted
  as a no-op on Podman 4.9.3 rootless under Ubuntu 24.04 (nested capture) —
  every run in the 4.9.3 qualification pass used it, satisfying the
  minimum-version half of **Done when** pending re-confirmation on a real
  runner. Still open: the security decision record comparing alternatives
  and the SELinux-enforcing-host integration test (needs a Fedora or
  similar host; not reproducible on this machine).
- **Affects:** §§7.2, 8, and 9
- **Finding:** The assertion that SELinux separation "adds little" is not
  established. `label=disable` avoids relabeling host trees but also removes a
  defense layer, and "no-op on non-SELinux hosts" is not a substitute for
  testing. The proposal does not evaluate alternatives or the interaction
  with an enforcing Fedora host.
- **Required resolution:** Record an explicit threat-model decision comparing
  `label=disable`, private/shared relabeling, and any non-mutating alternatives.
  State the residual risk and whether AppArmor behavior also needs control.
- **Done when:** An integration test on an SELinux-enforcing host proves
  project and agent-state mounts work, host labels are unchanged before/after,
  and the chosen option has the documented process label. A non-SELinux test
  proves the flag remains accepted on the minimum Podman version.

### MIR-014 — A minimum Podman version is not a support matrix

- **Status:** Open
- **Affects:** §§4, 9, 10, and 11
- **Finding:** "Podman >= 4.9 on Linux" leaves distro, architecture, kernel,
  cgroup version/manager, OCI runtime, storage driver, network backend, and
  security-module combinations unbounded. A no-maximum policy also
  automatically treats future major versions as qualified, contrary to the
  current runtime-qualification rationale. Distro-suffixed version parsing
  and client-versus-service version handling are underspecified.
- **Required resolution:** Define a finite release qualification matrix and a
  forward-version policy (for example, a tested major range plus an explicit
  escape hatch). Specify accepted version strings and whether local engine,
  client, and remote service versions are checked.
- **Done when:** Parser fixtures cover supported distro suffixes and malformed
  versions; CI/integration records all matrix dimensions and tested versions;
  an untested future major has deliberate, documented behavior.

### MIR-015 — Linux host prerequisites and diagnostics are incomplete

- **Status:** Open
- **Affects:** §§1, 2, 4, and 10
- **Finding:** `podman` alone is not the complete host dependency. Depending on
  distribution and storage/network setup, rootless operation needs subordinate
  ID helpers/configuration, an OCI runtime, networking helpers, and possibly
  `fuse-overlayfs`; `/bin/realpath` additionally requires coreutils and is not
  guaranteed merely by merged-usr layout. The sample install hint is not a
  valid command as written for unprivileged users and cannot name equivalent
  package sets across distributions.
- **Required resolution:** List qualified host packages/configuration per
  supported distribution and separate "CLI missing" from rootless setup,
  storage, filesystem, cgroup, and networking diagnostics. Decide support for
  NFS/distributed home directories and minimal distributions.
- **Done when:** Installation documentation is tested from clean supported
  distro images/users and each preflight failure has an actionable,
  terminal-safe diagnostic.

### MIR-016 — Host group/ACL access and ownership parity are not covered

- **Status:** Open
- **Affects:** §§7.1 and 9
- **Finding:** Mapping only the invoking UID/GID does not establish behavior
  for project files accessible through supplementary groups, ACLs, setgid
  directories, unusual primary GIDs, or non-1000 host IDs. Podman has
  runtime-specific supplementary-group behavior, and options such as
  `keep-groups` are not universally portable across OCI runtimes. A single
  `touch` ownership check covers only the simplest case.
- **Required resolution:** Define the supported host permission contract and
  decide whether supplementary groups/ACL-only projects are supported,
  detected, or documented as limitations. Include both reads and writes for
  `/work`, extra mounts, shell state, and credential state.
- **Done when:** Integration tests use a non-1000 host UID/GID and cover
  user-owned, group-owned/setgid, ACL-granted, read-only, and denied paths for
  normal and `--root` launches.

### MIR-017 — Nested sandbox behavior cannot remain speculative at release

- **Status:** Open (partially addressed 2026-07-29)
- **Progress (local reproduction, Podman 5.4.2 rootless, Debian 13,
  bubblewrap 0.11.0 in the Fedora 44 image, jms-shaped launch flags
  `--userns=keep-id:uid=1000,gid=1000 --user isolation --security-opt
  label=disable`):** the failure is now concrete, and it is **not** what
  §7.3 speculated. bwrap successfully creates its nested user namespace
  (`bwrap --unshare-user --ro-bind / / id` works under default container
  security settings); a full sandbox (`--unshare-all … --proc /proc`)
  fails at `bwrap: Can't mount proc on /newroot/proc: Operation not
  permitted`, caused by Podman's masked `/proc` paths, not by seccomp or
  userns creation. Adding `--security-opt unmask=ALL` to the *container*
  launch makes the same bwrap invocation succeed; a control run without it
  reproduces the failure. §7.3 is updated with this reproduction.
  2026-07-29 addendum: the same three-way reproduction (unshare-user works;
  full sandbox fails on masked `/proc`; `unmask=ALL` makes it succeed)
  holds on Podman 4.9.3 rootless under Ubuntu 24.04 (nested capture, so
  kernel-adjacent — re-confirm on a real runner). Still
  open: testing the actual shipped Claude/Codex/OpenCode launchers, whether
  a narrower unmask (e.g. `unmask=/proc/*`) suffices, and the decision on
  whether any workaround is documented given its security consequence
  (unmasking kernel interfaces inside the boundary).
- **Affects:** §§7.3, 8, 9, and 10
- **Finding:** The proposal says bwrap "may fail", says the Codex native Linux
  sandbox is unaffected, and suggests disabling an inner sandbox without a
  reproduction or versioned agent behavior. Those claims can change as the
  globally installed agent CLIs change and may lead users to weaken a control
  unnecessarily. The exact manifest/command workaround is not given.
- **Required resolution:** Test the shipped Claude, Codex, and OpenCode
  launchers plus direct sandboxed modes under the minimum/current Podman
  matrix. Document exact observed failures and narrowly scoped workarounds;
  otherwise remove the workaround recommendation.
- **Done when:** Integration output records agent and sandbox versions,
  expected behavior is asserted, and every documented workaround is an exact
  command with an explicit security consequence.

### MIR-018 — Image identity, multi-tag behavior, and GC semantics are unclear

- **Status:** Open
- **Affects:** §5
- **Finding:** Expanding one Podman image into one fact per name makes retention
  count tags rather than image identities and can schedule multiple removals
  for the same image. Creation-key types/shapes may differ within one backend,
  and lexicographic ordering is only safe for normalized timestamps. The text
  asserts equivalence with today's semantics without proving
  apple/container's list identity/tag behavior.
- **Required resolution:** Define whether retention is per image ID or per tag,
  how aliases/digests/dangling images are handled, and how deletion order and
  failures work when base/child or multiple tags share an image. Normalize
  creation times to one internal type rather than relying on backend-local
  comparability.
- **Done when:** Cross-backend conformance tests cover multi-tag images,
  duplicate IDs, equal/missing timestamps, inherited labels, dangling images,
  base images with children, and partial deletion failures.

### MIR-019 — The integration plan misses several load-bearing contracts

- **Status:** Open
- **Affects:** §9
- **Finding:** The proposed additions do not test `--root` ownership,
  passwordless sudo under `keep-id`, credential/shell-state mounts, environment
  and entrypoint parity, explicit hostname behavior, signal/exit propagation,
  failed-run cleanup, ambient Podman configuration, or security-option
  behavior. The short-name test is described as "offline-ish", which is not a
  deterministic assertion.
- **Required resolution:** Turn each backend-specific security or compatibility
  claim into an integration assertion, split fast preflight from expensive
  agent-image coverage where useful, and make cleanup/leak detection run even
  after partial failures.
- **Done when:** A requirements-to-tests table maps every claim in §§3-8 to a
  unit or integration test, with no untested blocker-level claim.

### MIR-020 — The CI job is not sufficiently defined or reproducible

- **Status:** Open
- **Affects:** §9
- **Finding:** "Opt-in or nightly" is not a workflow definition.
  `ubuntu-latest` moves over time, preinstalled Podman and subordinate-ID
  configuration are runner-image implementation details, and the full Fedora
  plus npm build is network-heavy. The proposal lacks event triggers,
  timeouts, concurrency, cache policy, setup verification, failure artifacts,
  and a promotion criterion for becoming required.
- **Required resolution:** Choose a pinned runner label, trigger(s), timeout,
  permissions, concurrency policy, package/setup strategy, diagnostics upload,
  network/cache policy, and measurable stability threshold. Verify rather than
  assume rootless prerequisites.
- **Done when:** The checked-in workflow can be manually dispatched and
  scheduled, records `podman info`/versions without secrets, cleans up on
  cancellation where possible, and has a documented criterion for required-PR
  promotion.

### MIR-021 — Security docs and backend enablement must ship atomically

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The Podman backend is unreachable behind an explicit
  development gate (`JMS_PODMAN_PREVIEW=1`) from the moment its code exists;
  without the gate, Linux fails at first runtime use with a "not yet
  supported" error while every runtime-free command keeps working. The gate
  is removed in the final phase in the *same change* that lands SECURITY.md,
  README, CLI docs, installation docs, and the changelog. The phase plan
  (§11) is rewritten so each phase preserves existing supported behavior and
  a green matrix; the phase-1 conflict with Linux unit imports is removed via
  lazy selection (MIR-001).
- **Affects:** §§8, 10, and 11
- **Finding:** Phase 2 can make the Podman backend selectable while Phase 5
  delays the weaker-boundary disclosure and Linux operating instructions.
  "Still no doc promises" does not prevent users from selecting an exposed
  backend. The phase plan also claims each phase lands independently green
  while Phase 1 knowingly conflicts with current Linux imports/tests.
- **Required resolution:** Keep Podman unreachable behind an explicit
  development-only gate until integration, security text, CLI docs,
  installation docs, and changelog are complete, or land those artifacts in
  the same change that enables selection. Rewrite phases so every merged phase
  preserves existing supported behavior and CI.
- **Done when:** No released or normally selectable code path exposes Podman
  without the finalized threat model and operating documentation, and every
  phase has explicit entry/exit criteria with a green existing matrix.

---

## 1. Where the runtime is coupled today

All runtime access already flows through one seam, `runtime_run()`
(`bin/jms:79`), which asserts `argv[0] == "container"`. The call sites that
encode apple/container specifics:

| Call site | apple/container behavior encoded |
| --- | --- |
| `runtime_run` (`bin/jms:96`) | `brew install container` install hint |
| `runtime_ready` (`bin/jms:731`) | `container --version` line format; `RUNTIME_MIN`/`RUNTIME_MAX` exact qualification; `container system status` / `system start` daemon lifecycle |
| `image_exists` (`bin/jms:762`) | matches the literal stderr string `Error: image not found: <ref>` |
| `image_records` / `image_record_facts` (`bin/jms:775`) | `container image list --format json` schema: `configuration.name`, `configuration.creationDate` (ISO-8601 string), labels nested under `variants[0].config.config.Labels` |
| `local_name` (`bin/jms:796`) | strips only the `docker.io/library/` prefix |
| `run_build` (`bin/jms:801`) | `container build` with `-l key=value` labels and boolean `--pull` |
| `mount_argument` (`bin/jms:964`) | bare `source=…,target=…[,readonly]` grammar (no `type=` key) |
| `launch_plan` (`bin/jms:985`) | `container run` argv; no user-namespace flags (virtiofs squashes UIDs, per the Containerfile comment); no hostname flag; no SELinux concerns |
| `container_records` (`bin/jms:1209`) | `container list --all --format json` schema: `id`, `configuration.labels` |
| `cmd_clean` (`bin/jms:1274`) | `container stop` / `container delete --force` / `container image delete` |

Everything else — trust store, fingerprinting, discovery, manifest parsing,
path validation, consent — is runtime-agnostic already and must not move.

Two platform notes that need no code change:

- `canon()` execs `/bin/realpath` (`bin/jms:114`); this exists on any
  merged-usr Linux distro (all current Debian/Ubuntu/Fedora/Arch releases).
- The path rules in `runtime_path()` (no NUL, valid UTF-8, no `,` or `=`)
  are stricter than Podman requires but remain correct for Podman's `--mount`
  grammar, which is also comma/equals-delimited. Keep them identical on both
  backends so error behavior does not fork.

---

## 2. Architecture: one `Runtime` object, selected lazily, once per process

Introduce a small backend class per runtime, selected **lazily on first use**
and cached for the rest of the process (MIR-001). Keep the existing free
functions as the public surface; they delegate to the selected backend for
anything backend-specific. This keeps the diff reviewable and the tests'
monkeypatching seam (`JMS.runtime_run`) intact.

Nothing runs at import time or in `main()` startup: only the runtime-touching
seams (`runtime_run`, `runtime_ready`, `image_exists`, `image_facts`,
build/launch/clean argv assembly) call the accessor. `--version`, `inspect`,
`init`, `trust list`, `trust revoke` without `--purge-images`, and
`trust prune` therefore never select a runtime and keep working with no
runtime installed, on unsupported platforms, and under uid 0.

```python
_RUNTIME: Backend | None = None

def runtime() -> Backend:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = select_runtime()
    return _RUNTIME
```

Tests install a backend by assigning the cache directly (or via a small
install helper), with no dependence on `JMS_RUNTIME`, `sys.platform`, or
euid at import.

```python
class ContainerBackend:            # apple/container (macOS)
    name = "container"
    exe = "container"
    install_hint = "install it with: brew install container"
    version_min = (1, 1, 0)
    version_max = (1, 1, 0)        # exact qualification, as today

class PodmanBackend:               # podman (Linux, rootless)
    name = "podman"
    exe = "podman"
    install_hint = "install it with your distribution's package manager (e.g. dnf/apt install podman)"
    version_min = (4, 9, 0)
    version_max = None             # min-only; see §4
```

### Selection and the support matrix

The supported combinations are exactly two (MIR-002). Everything else is
rejected with exit 2 at selection time — which, per MIR-001, happens only
when a command actually needs the runtime, so the rejection can never block
a pure command:

| Platform | Backend | Status |
| --- | --- | --- |
| macOS | apple/container | supported (default) |
| Linux | Podman, **local** and **rootless** | supported (default) |
| macOS | `JMS_RUNTIME=podman` | rejected, exit 2 |
| Linux | `JMS_RUNTIME=container` | rejected, exit 2 |
| Linux, euid 0 | any | rejected, exit 2 |
| any | `JMS_RUNTIME=docker` or other value | rejected, exit 2 |
| other platforms | any | rejected, exit 2 |

```python
def select_runtime() -> Backend:
    forced = os.environ.get("JMS_RUNTIME")
    if forced is not None and forced not in ("container", "podman"):
        fail("JMS_RUNTIME must be 'container' or 'podman': " + quote(forced), 2)
    if sys.platform == "darwin":
        if forced == "podman":
            fail("JMS_RUNTIME=podman is not supported on macOS", 2)
        return ContainerBackend()
    if sys.platform.startswith("linux"):
        if forced == "container":
            fail("JMS_RUNTIME=container is not supported on Linux", 2)
        if os.geteuid() == 0:
            fail("jms on Linux supports rootless podman only; "
                 "run as a regular user", 2)
        return PodmanBackend()
    fail("unsupported platform for jms: " + sys.platform, 2)
```

`JMS_RUNTIME` exists so tests/CI can force a backend deterministically and so
the error for an unsupported request is explicit rather than accidental.
Docker support is explicitly out of scope (see §12).

The uid-0 refusal lives inside selection because rootless Podman is the only
qualified Linux mode: running the whole tool as uid 0 silently removes the
user-namespace boundary that stands in for the macOS VM.

**Remote Podman is unsupported and detected, not guessed.** Podman silently
switches to a remote service when `CONTAINER_HOST`, `CONTAINER_CONNECTION`,
or containers.conf selects one, and a local `geteuid()` check says nothing
about that service. jms does not parse the connection environment itself;
instead `ensure_started()` (§4) reads `podman info --format json` and fails
when `host.serviceIsRemote` is true, which catches every configuration
mechanism at the engine. The support matrix, threat model, and path
semantics in this document assume a local engine only.

### The seam

`runtime_run()` changes only its assertion and hint:

```python
if not argv or argv[0] != RUNTIME.exe:
    raise AssertionError("runtime argv must begin with " + RUNTIME.exe)
...
except FileNotFoundError:
    fail(RUNTIME.exe + " CLI not found; " + RUNTIME.install_hint)
```

Every current `["container", ...]` literal becomes `[RUNTIME.exe, ...]` where
the subcommand grammar is shared, or a call to a backend method where it is
not. The methods that must exist on the backend, and nothing more:

| Backend method | Returns |
| --- | --- |
| `version_argv()` / `parse_version(first_line)` | argv; `(major, minor, patch)` or `None` |
| `ensure_started()` | raises on an unusable runtime (see §4) |
| `image_exists(image)` | bool (see §5) |
| `image_facts()` | normalized `[(ref, created_key, labels)]` (see §5) |
| `local_name(ref)` | ref with registry/localhost prefix stripped |
| `build_argv(context, tag, labels, no_cache, pull)` | argv (see §6) |
| `run_argv(plan)` | argv (see §7) |
| `ps()` | normalized `[{"id", "labels"}]` |
| `stop_argv(id)` / `remove_argv(id)` / `remove_image_argv(ref)` | argv |

---

## 3. Base image: one Containerfile, two runtimes

The existing Fedora `Containerfile` builds unchanged under Podman/Buildah.
Two small hardening edits make it deterministic across backends:

1. **Pin the `isolation` UID/GID.** Rootless Podman's `--userns=keep-id`
   mapping (§7) must name the container-side UID, so it cannot be left to
   `useradd`'s "first free UID" default (which *is* 1000 on a fresh Fedora
   image, but implicitly):

   ```dockerfile
   RUN groupadd -g 1000 isolation && \
       useradd -m -s /bin/bash -u 1000 -g 1000 isolation && ...
   ```

   Keep `1000` in one place — a `ISOLATION_UID = 1000` constant in `bin/jms`
   and this line — and note the pairing in a comment on both sides.

2. **Update the virtiofs comment** (`Containerfile` line 26) to describe both
   backends: virtiofs squashes UIDs on macOS; on Linux, `keep-id` performs
   the equivalent alignment explicitly.

No other change: `FROM registry.fedoraproject.org/fedora:latest` is fully
qualified (no short-name ambiguity), and every package including `bubblewrap`
exists in Fedora regardless of what runs the build.

### Base image naming under Podman

`podman build --tag jmscontainers-base:latest` stores the image as
`localhost/jmscontainers-base:latest`. Project Containerfiles keep
`FROM jmscontainers-base:latest` — Buildah resolves `FROM` short names
against local storage first, so this finds the locally built base without
touching a registry, and project builds pass `--pull=never` to make that
deterministic under every `registries.conf` (MIR-011, qualified locally on
5.4.2). The Linux integration run (§9) re-verifies it on the matrix minimum;
it is the one short-name resolution the design depends on.

Consequences handled by the backend:

- `local_name()` for Podman strips `localhost/` (and `docker.io/library/`
  for safety) so the `jmscontainers-…` tag-prefix ownership checks in
  `gc_project_images` and `cmd_clean` keep working unmodified.
- `image_exists("jmscontainers-base:latest")` must match the
  `localhost/`-prefixed stored name; `podman image exists` does this
  natively (§5).

---

## 4. Runtime readiness (`runtime_ready`)

### Version parsing

- apple/container: `container CLI version X.Y.Z …` (unchanged).
- Podman: `podman --version` → `podman version X.Y.Z` (possibly with a
  distro suffix such as `5.4.2-dev` — accept and truncate a non-numeric
  suffix on the patch component).

### Qualification policy — deliberately different per backend

Keep the exact `RUNTIME_MIN == RUNTIME_MAX` pin for apple/container: it is a
single-channel Homebrew install and the pin has already proven its worth.

For Podman, an exact pin is wrong: versions are chosen by the distribution,
span 4.9 → 5.x across supported distros, and the CLI surface jms uses
(`run`, `build`, `image exists`, `ps --format json`, `--userns=keep-id:uid=`)
has been stable across that whole range. Policy:

- `version_min = (4, 9, 0)` — the oldest version in a supported distro
  (Ubuntu 24.04 LTS); `--userns=keep-id:uid=` needs ≥ 4.3, `image exists`
  is ancient, so 4.9 has margin.
- No maximum. Record the newest *tested* version in the release checklist
  instead. `JMS_RUNTIME_ACCEPT` remains meaningful only for the
  apple/container backend; document that.

### Startup / health probe

apple/container keeps the `system status` / `system start` dance. Podman is
daemonless, so `ensure_started()` instead runs one cheap probe that catches
the real-world rootless failure modes (missing `newuidmap`, unconfigured
`/etc/subuid`, broken storage config):

```sh
podman info --format json
```

The JSON is parsed for two things: `host.serviceIsRemote` must be false
(remote Podman is unsupported, §2/MIR-002) and `store.graphDriverName` must
be present, proving the storage stack initializes. (Whether readiness must
validate more than this — ID mappings, OCI runtime, network helper — is
MIR-008, still open.)

On failure, surface Podman's stderr plus a targeted hint:

```
rootless podman is not usable: <stderr>
hint: rootless podman needs shadow-utils (newuidmap/newgidmap) and an
entry for your user in /etc/subuid and /etc/subgid; see podman(1).
```

This converts the single most common Linux support issue into a
self-explanatory error.

**Ordering (MIR-003):** the current consent-first order is unchanged on both
backends: project `build` and `launch` call `approve()` before
`runtime_ready()`, exactly as today, so an unapproved definition never
contacts the runtime. Readiness failures are therefore reported *after
consent and before any build*. A durable trust grant recorded immediately
before a preflight failure is accepted: it records consent to the project
definition, nothing has been built or run, and the grant remains valid for a
retry once the host is fixed.

---

## 5. Image existence, listing, and facts

### `image_exists`

Drop stderr-string matching entirely on the Podman backend — Podman has a
purpose-built command with a clean exit-code contract:

```sh
podman image exists <ref>    # 0 = exists, 1 = not found, 125 = error
```

Treat 0 as True, 1 as False, anything else as a hard failure with stderr.
This also transparently handles the `localhost/` prefix for local tags.

### `image_records` → normalized facts

`podman images --format json` returns a flat schema, roughly:

```json
[{"Id": "…", "Names": ["localhost/jmscontainers-base:latest"],
  "Created": 1753752000, "Labels": {"jms.project": "…"}}]
```

Replace the current `image_record_facts()` with a backend method
`image_facts()` returning the already-normalized
`(ref, created_key, labels)` tuples the callers sort and filter on:

- apple/container: exactly the current extraction; `created_key` is the
  ISO-8601 `creationDate` string (sorts correctly lexicographically).
- Podman: one tuple **per name** in `Names` (a multi-tagged image is
  multiple refs to the callers, same as today's semantics); skip records with
  empty/None `Names` (dangling layers are never jms-owned); `created_key` is
  the integer `Created`.

`created_key` types must never be compared across backends — they aren't:
each invocation runs one backend. Keep the sort call sites unchanged.

`gc_project_images` and `cmd_clean --images` then work verbatim, because
their ownership logic (label **and** tag prefix) operates on normalized
facts. The label-inheritance caveat (`bin/jms:869`) applies identically to
Podman — OCI labels inherit through `FROM` there too — so the dual check
stays load-bearing on both backends.

### `container_records` → `ps()`

Podman: `podman ps --all --format json` → flat records with `Id` and a
top-level `Labels` map. Normalize to the existing
`[{"id": …, "labels": {…}}]` shape; validation rules (string id, no NUL,
dict labels) carry over unchanged.

### Cleanup verbs

| Operation | apple/container | podman |
| --- | --- | --- |
| stop | `container stop ID` | `podman stop ID` |
| remove container | `container delete --force ID` | `podman rm --force ID` |
| remove image | `container image delete REF` | `podman image rm REF` |

Same "stop may fail, forced delete is authoritative" pattern on both.

---

## 6. Build (`run_build`)

| Aspect | apple/container | podman |
| --- | --- | --- |
| tag/file/context | `--tag`, `--file`, positional context | identical |
| labels | `-l key=value` | `--label key=value` |
| no cache | `--no-cache` | identical |
| pull (base only) | `--pull` | `--pull=always` |
| project builds | (no pull flag) | `--pull=never` (MIR-011: pins `FROM jmscontainers-base:latest` to local storage; never contacts or prompts for a registry) |

`build_argv()` on the backend assembles this; the surrounding logic —
context = `.jmscontainer/`, the pre-build fingerprint re-check in
`build_project`, `CONTEXT_NOTE` on failure — is untouched. The v2 context
rule ("COPY/ADD sources must live inside `.jmscontainer/`") is enforced by
both builders since the context directory is identical; the integration
escape test (§9) verifies the Podman error path still trips `CONTEXT_NOTE`.

---

## 7. Launch (`launch_plan`) — the one genuinely different area

The good news: `--rm --interactive --tty --name --user --workdir
--entrypoint --label --env --mount` all exist in Podman with compatible
meanings, including string `--entrypoint`. Three real differences:

### 7.1 UID mapping (replaces virtiofs squashing)

On macOS, virtiofs squashes UIDs bidirectionally, so `/work` writes appear
with host ownership for free. Rootless Podman needs the mapping stated:

Both launch variants pass an **explicit** `--userns` flag (MIR-009): Podman's
default user namespace can be changed by `PODMAN_USERNS` or
`containers.conf`, so relying on the default would let ambient host
configuration silently alter the security-relevant mapping.

- **Default (isolation user):** `--userns=keep-id:uid=1000,gid=1000` — the
  invoking host user maps to container UID/GID 1000 (`isolation`, pinned in
  §3). Writes to `/work` and the agent-state mounts land on the host owned
  by the invoking user; container-side files owned by `isolation` are
  exactly the host user.
- **`--root`:** `--userns=host` — under rootless Podman, `host` mode runs
  the container in the rootless user namespace, mapping the invoking user
  to container root (`$UID → 0` per the 4.9.3 mapping table), which is
  precisely what `--root` means here; host ownership of writes is again
  the invoking user. This is the explicit spelling of the ambient default
  the earlier draft relied on implicitly, has been stable since rootless
  Podman existed, and needs no version qualification. It is safe *only*
  because rootful Podman is rejected at selection (§2) — under rootful,
  `host` would mean no user namespace at all. Qualified on Podman 5.4.2
  (MIR-009 evidence): `/work` writes are owned by the invoking user and
  the `isolation` UID 1000 resolves via the subordinate range. Fallback
  candidates, retained in case the 4.9.x acceptance runs disagree:
  `keep-id:uid=0,gid=0` (needs 4.9.x qualification of `uid=0`), then an
  explicit `--uidmap`/`--gidmap` triple — never an omitted flag.
  Note that rootless `--uidmap` values are relative to the *intermediate*
  rootless namespace (0 = the invoking user, not host uid 0), so that
  fallback needs its own golden-argv pin if it ever becomes real.

Note `sudo` inside the container (the `isolation` user's passwordless sudo)
still works under `keep-id`: container root is a mapped subordinate UID, not
host root. State that explicitly in SECURITY.md (§8).

### 7.2 Mount grammar and SELinux

Backend-specific `mount_argument()`:

- apple/container: `source=S,target=T[,readonly]` (unchanged).
- Podman: `type=bind,source=S,target=T[,readonly]`.

Do **not** use `:z`/`relabel=shared` volume relabeling: it would `chcon` the
user's real project tree and the shared agent-state directories on the host —
mutating host state and fighting other tools. Instead, always pass

```
--security-opt label=disable
```

on the Podman backend. Rationale, which belongs in SECURITY.md verbatim: the
container is a full-permission agent sandbox whose boundary is the user
namespace; SELinux container separation adds little here, and relabeling
host project files is an unacceptable side effect. On non-SELinux hosts the
flag is a no-op.

The existing `,`/`=` path rejections in `runtime_path()` keep the Podman
mount string unambiguous too. NUL/UTF-8 rules are shared.

### 7.3 Hostname

apple/container has no hostname flag, hence the `HOSTNAME=container` fakery
in `/etc/profile.d/jms.sh`. Podman has one — pass `--hostname container` for
parity so the prompt and `$HOSTNAME` agree by construction. The profile
fallback stays (harmless, still needed on macOS).

### Resulting Podman argv shape

```text
podman run --rm --interactive [--tty]
  --name jms-<slug>-<hex> --user isolation --workdir /work
  --entrypoint /bin/bash --label jms.project=<pid>
  --hostname container --security-opt label=disable
  --userns=keep-id:uid=1000,gid=1000            # --userns=host under --root
  [--env CLAUDE_CONFIG_DIR=…]
  --mount type=bind,source=<root>,target=/work
  [--env K=V]… [--mount type=bind,…[,readonly]]…
  --mount type=bind,source=<shell>,target=…/.config/jms-shell,readonly
  [agent-state mounts]…
  <image> -l [extra args…]
```

Everything upstream of argv assembly in `launch_plan` — target validation
against the effective home, reserved-target checks, mount ordering, the
`mount_auth` logic — is untouched. `runtime_run(argv, replace=True)`'s
`execvp` works identically; `launch` still exits with the container's status.

### Known caveat: nested sandboxes

`bubblewrap` (the Codex bwrap path) fails inside rootless Podman, and the
mechanism is now reproduced (MIR-017, Podman 5.4.2 / bubblewrap 0.11.0):
creating the nested user namespace *works* under the default seccomp and
capability set, but mounting a fresh `/proc` inside it fails with
`Can't mount proc on /newroot/proc: Operation not permitted`, because
Podman masks `/proc` paths in the container. Launching the container with
`--security-opt unmask=ALL` makes the same bwrap invocation succeed —
but that unmasks kernel interfaces inside the boundary, so jms does **not**
pass it by default and must not weaken the container defaults globally.
Document the limitation; a project that truly needs bwrap can either run
the agent without its inner sandbox (it is already inside jms's boundary)
or accept the unmask trade-off explicitly. Codex's native Linux sandbox
(Landlock/seccomp) is expected to be unaffected — still to be verified
against the shipped agent CLIs (MIR-017).

---

## 8. Security model documentation (required, not optional)

The README's promise — "without handing them your Mac", "the VM boundary …
is what contains it" — is a VM claim that must not silently stretch to
cover Linux. Update SECURITY.md and the README with an explicit per-platform
statement:

- **macOS / apple/container:** boundary is a lightweight VM per container
  (unchanged text).
- **Linux / rootless Podman:** boundary is a user namespace plus Podman's
  default seccomp filter and capability drops — kernel isolation, not
  hardware-virtualized isolation. SELinux label separation for mounts is
  deliberately disabled (§7.2), so it contributes nothing here. The precise
  claims, stated in SECURITY.md in these terms (MIR-012):
  - **Trusted:** the host kernel and the OCI runtime. The boundary holds
    only as long as they do; a kernel or runtime exploit can cross the
    namespace boundary and potentially elevate beyond the invoking user.
    No claim of the form "an escape can never yield host root" is made.
  - **What the boundary aims to contain:** absent such an exploit, container
    processes — including container "root", which is an unprivileged mapped
    UID of the invoking user — hold at most the invoking user's authority on
    the host.
  - **What an escape yields:** everything the invoking user's account can
    do — their files, credentials, processes, and network access. For a
    single-user development machine that is most of what matters; "not host
    root" is a limited consolation and is not presented as more.
  - **What no boundary mitigates:** anything deliberately mounted in.
    Project files and mounted credentials are exposed to the agent by
    design; the existing credential-exfiltration warning applies regardless
    of boundary type.
  - This is a meaningfully weaker boundary than the macOS VM against kernel
    exploits, and the docs must say so in those words.

Unchanged on both platforms, and worth restating: the credential-mount
warning ("never claim the VM meaningfully limits exfiltration of mounted
credentials") already doesn't depend on the boundary type; the protected-
source rules, read-only shell mount rationale, and trust store location are
identical.

---

## 9. Testing and CI

### Unit tests (`tests/test_jms.py`)

The `FakeRuntime` class is keyed on `argv` prefixes like
`["container", "--version"]`. Plan:

1. **Refactor first, behavior-neutral:** land the backend extraction with
   apple/container as the only backend and the entire existing suite green,
   including the golden fingerprints (`GOLDEN_TREE_TF` etc. — nothing in the
   trust path may move, and the goldens prove it).
2. **Parametrize the fake:** give `FakeRuntime` a backend name and canned
   outputs per backend (`podman --version` line, `podman images` flat JSON,
   `podman ps` flat JSON, `image exists` exit codes). Run the
   runtime-touching test classes under both fakes via a shared mixin;
   trust/discovery/manifest tests stay single-run (they never hit the seam).
3. **Golden argv tests per backend:** assert the exact `run` argv for the
   canonical launches (default, `--root`, manifest mounts, `--auth`) on both
   backends — this pins `keep-id`, `label=disable`, mount grammar, and flag
   ordering, the places a regression would be silent and security-relevant.
4. **Selection tests:** `JMS_RUNTIME` override, platform default, invalid
   value (exit 2), the rejected forced combinations (podman-on-macOS,
   container-on-Linux), root-on-Linux refusal, and a Podman-info fixture
   with `serviceIsRemote=true` failing readiness.
5. **Laziness tests (MIR-001):** `--version`, `inspect`, `init`,
   `trust list`, `trust revoke` without `--purge-images`, and `trust prune`
   succeed with no runtime executable, on a mocked unsupported platform, and
   in a mocked uid-0 process; imports never read `JMS_RUNTIME`.

`make test` still requires no runtime on either OS.

### Integration (`scripts/integration.sh`)

Parametrize on the selected runtime instead of hard-requiring `container`:

- Resolve the runtime the same way jms does (`JMS_RUNTIME`, then platform).
- The two direct `container …` invocations become runtime-conditional: the
  bwrap smoke test uses `podman run` on Linux, and the final
  leaked-container sweep lists IDs via `podman ps -a --format json` and
  reads mount sources via `podman inspect` — on 5.4.2 the `ps` JSON
  `Mounts` field is only a list of target paths with no sources (MIR-007),
  so `ps` alone cannot identify jms mounts.
- Add one Linux-only assertion after the first project launch: create a file
  in `/work` from inside the container (`--bin /bin/sh -- -c 'touch …'`) and
  verify host ownership equals the invoking user — this is the `keep-id`
  contract and the single most likely thing to break.
- Add a `FROM jmscontainers-base:latest` resolution check (§3): build one
  example with `--pull=never --network=none` and assert success with the
  base present and a fast, non-interactive `image not known` failure
  (exit 125) with it absent — the deterministic form of the earlier
  "offline-ish" check, qualified locally per MIR-011.

### CI (`.github/workflows/test.yml`)

- Existing matrix (`make test` on Ubuntu 3.11/3.14 + macOS) unchanged; it
  now also exercises the Podman fake on the Ubuntu legs automatically.
- Add an **opt-in or nightly** job `integration-linux` on `ubuntu-latest`
  running `scripts/integration.sh` with rootless Podman — GitHub's Ubuntu
  runners ship Podman preinstalled and subuid-configured, so this is the
  first time real-runtime coverage can run in CI at all. Keep it out of
  required PR checks initially (network + registry flakiness), promote once
  it proves stable. macOS integration remains manual (no nested
  virtualization on GH macOS runners).

---

## 10. Documentation and packaging checklist

- `README.md`: platform section becomes "Apple Silicon Mac (apple/container)
  **or** Linux with rootless Podman ≥ 4.9"; install instructions per
  platform; stack line gains a Linux variant
  (`Linux → rootless podman (user namespace) → Fedora → …`); isolation
  wording per §8.
- `docs/cli.md`: new "Runtimes" section (selection rules, per-backend
  qualification policy); `JMS_RUNTIME` added to environment variables;
  `JMS_RUNTIME_ACCEPT` marked apple/container-only; exit-code table
  unchanged.
- `SECURITY.md`: per-platform boundary statement (§8); `label=disable`
  rationale (§7.2); rootless-only statement.
- `docs/release-checklist.md`: add "tested Podman version" recording and a
  Linux integration run.
- `completions/jms.bash`: no runtime references — unchanged.
- `Makefile`: unchanged (`make install` already works on Linux;
  `~/.local/bin` is on PATH by default on most distros — soften the
  macOS-specific PATH note in the README).
- `CHANGELOG.md`: 1.1.0 entry; minor version bump since the CLI surface
  grows (`JMS_RUNTIME`) but nothing breaks.

---

## 11. Phased implementation plan

Each phase lands independently green: every merged phase preserves all
currently supported behavior and the existing CI matrix (MIR-021). Until the
final phase, the Podman backend is unreachable except behind the explicit
development gate `JMS_PODMAN_PREVIEW=1`; without it, Linux fails at first
*runtime use* (never at import or in pure commands, per MIR-001) with a
clear "Linux support is not yet released" error.

1. **Extract the backend seam.** Pure refactor: `Backend` class, lazy
   `runtime()` selection (apple/container only; Linux runtime use fails with
   the not-yet-released error), all `["container", …]` literals routed
   through it. Imports stay side-effect-free, so the existing Ubuntu unit
   jobs stay green unchanged. Full suite green, golden argvs identical. No
   user-visible change on macOS.
2. **Podman backend + unit coverage, gated.** Implement §§4–7 argv assembly
   and normalizers behind `JMS_PODMAN_PREVIEW=1`; parametrized fakes; golden
   argv tests; selection and laziness tests. No doc promises; the gate is
   documented only as unsupported/dev-only.
3. **Base image determinism.** Pin `isolation` to UID/GID 1000; update the
   Containerfile comments. Rebuild-and-verify on macOS to confirm no
   behavior change there.
4. **Linux integration.** Parametrize `scripts/integration.sh` (CI sets the
   gate); add the ownership and FROM-resolution assertions; add the opt-in
   CI job. Fix whatever reality disagrees with (most likely candidates:
   short-name FROM resolution details, `podman images` field names across
   4.9/5.x, seccomp interactions with the agent CLIs).
5. **Enablement + docs, atomically.** One change removes the
   `JMS_PODMAN_PREVIEW` gate *and* lands §§8 and 10 in full: SECURITY.md,
   README, CLI docs, installation docs, changelog. No released state exposes
   Podman without the finalized threat model and operating documentation.
6. **Release 1.1.0** per the release checklist, recording the tested Podman
   versions (at minimum: Ubuntu 24.04's 4.9.x and current Fedora's 5.x).

## 12. Explicit non-goals

- **Docker support.** Docker's rootless mode, JSON schemas, and label
  semantics differ again; nothing here precludes a later `DockerBackend`,
  but qualifying it is separate work. `JMS_RUNTIME` rejects `docker` today
  with a clear error rather than half-working.
- **Root Podman.** Refused at selection (§2); it would silently change the
  security story.
- **Remote Podman.** Refused at readiness via `host.serviceIsRemote` (§§2,
  4); a remote service invalidates the local-path mount semantics and the
  rootless threat model, and nothing in this design qualifies it.
- **Cross-runtime image sharing.** Images are per-runtime-store; a user on
  both platforms builds the base twice. Fingerprint-derived tags make this
  transparent.
- **Weakening container defaults for nested bwrap** (§7.3).
