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

Scope note (2026-07-29): the first push targets Debian 13 with Podman ≥ 5.4
only (MIR-015), so the 4.9.3 references and the "matrix-minimum" evidence
captured under them now serve as pre-qualification for the mid-term Ubuntu
target rather than first-push acceptance material.

### Issue summary

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| MIR-001 | Blocker | Runtime lifecycle | Resolved (design) |
| MIR-002 | Blocker | Runtime/platform selection | Resolved (design) |
| MIR-003 | Blocker | Consent and preflight ordering | Resolved (design) |
| MIR-004 | Blocker | Backend interface | Resolved (design) |
| MIR-005 | Blocker | Compatibility contract | Resolved (design) |
| MIR-006 | Blocker | Podman image schema | Resolved (design) |
| MIR-007 | Blocker | Podman container schema | Resolved (design) |
| MIR-008 | Blocker | Rootless readiness | Resolved (design) |
| MIR-009 | Blocker | Deterministic user namespaces | Resolved (design) |
| MIR-010 | Blocker | Isolation-user ABI | Resolved (design) |
| MIR-011 | Blocker | Base-image resolution | Resolved (design) |
| MIR-012 | Blocker | Security claims | Resolved (design) |
| MIR-013 | High | SELinux policy | Resolved (design) |
| MIR-014 | High | Version/support policy | Resolved (design) |
| MIR-015 | High | Linux prerequisites | Open (partially addressed) |
| MIR-016 | High | Host filesystem permissions | Resolved (design) |
| MIR-017 | High | Nested sandbox behavior | Resolved (design) |
| MIR-018 | High | Image identity and garbage collection | Resolved (design) |
| MIR-019 | High | Integration coverage | Resolved (design) |
| MIR-020 | High | CI definition | Resolved (design) |
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** §2's new "The backend protocol" subsection specifies the
  complete protocol. In summary: the protocol is exactly five class
  attributes plus fourteen methods split into two ownership classes —
  **pure serializers** (`version_argv`, `parse_version`, `local_name`,
  `mount_argument`, `build_argv`, `run_argv`, `stop_argv`, `remove_argv`,
  `remove_image_argv`) that return argv/strings, touch no process,
  filesystem, or environment, and are executed by their callers through
  `runtime_run()`; and **executing queries** (`ensure_started`,
  `image_exists`, `image_facts`, `ps`, plus the policy method
  `validate_version`) that own their invocation and normalization but must
  route every process through the module-level `runtime_run()` /
  `runtime_json()`. Inputs/outputs are typed and normalized: `ImageFact`
  is the MIR-006/018 `(id, refs, created, labels)` shape, `ps()` returns
  the MIR-007 `{"id", "labels"}` shape, and `run_argv(plan)` takes a new
  frozen `LaunchPlan` value whose field-by-field invariants (validation
  state, env/mount ordering, purity of serialization) are enumerated in
  §2. The error contract is single-channel: raise `JMSException` via
  `fail()` with terminal-safe messages — never returned errors, raw
  process objects, or printed diagnostics, with two enumerated output
  exceptions (`ensure_started` daemon-start progress, the
  `validate_version` untested-major warning). Stable monkeypatch seams
  are, in order, `JMS.runtime_run`, the unchanged public free functions,
  and the `_RUNTIME` cache (MIR-001); backends are prohibited from
  bypassing `runtime_run()`, and command functions are prohibited from
  branching on backend type, name, or platform. Conformance tests per
  **Done when** land with the implementation.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** jms consumes raw `podman images --format json` through a
  **strict fixture-backed normalizer**: the parser accepts exactly the shape
  proven by the checked-in 4.9.3/5.4.2 fixtures (uppercase `Id`,
  `Names` array-or-null, integer `Created`, top-level `Labels` map) and
  fails closed on anything else. Handling rules: records with null/empty
  `Names` (dangling) are skipped — dangling layers are never jms-owned; a
  malformed value in any ownership-relevant field (`Id`, `Names`,
  `Labels`) aborts the operation with an error rather than being silently
  skipped; `<none>` names are treated as absent; digests and `RepoTags`
  are ignored. No Go-template projection is used. Qualifying a new Podman
  version requires capturing a new fixture first, consistent with the
  MIR-014 forward-version policy. The fact shape itself is per image ID
  (MIR-018, §5). Acceptance tests per **Done when** land with the
  implementation.
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
  a single normalizer can serve 4.9–5.4 — the basis for the strict
  fixture-backed normalizer decision above.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** Two schemas, two owners, both strict and fail-closed.
  Inside jms, the backend `ps()` normalizer accepts exactly the shape
  proven by the checked-in 4.9.3/5.4.2 `ps` fixtures — full 64-character
  `Id`, top-level `Labels` map — and, per the shared error contract
  (§2/MIR-006), a malformed value in any ownership-relevant field aborts
  the whole operation rather than being skipped; the `Mounts` field is
  never consumed by jms at all. In the integration harness, the leak
  sweep is specified in §9's "Leak-sweep contract" as a testable spec: a
  two-step `podman ps --all --format json` → per-ID `podman inspect`
  walk (because `ps` JSON carries mount *targets* only — the load-bearing
  negative finding below), with a strict parse of both outputs, a single
  tolerated race ("no such container" between the two steps), and three
  mutually exclusive outcomes (clean / leak / sweep failure) where any
  inability to complete fails the run rather than reporting clean.
  Malformed-record fixtures and tests over them are acceptance work per
  **Done when**.
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
  sweep works across the whole version range. Malformed-record handling
  and the leak-sweep contract are now decided above and written into §9;
  the malformed fixtures and the tests over them are acceptance work per
  **Done when**.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** `ensure_started()` performs **full `podman info` validation
  and no create/run probe**. It parses `podman info --format json` and
  requires: `host.serviceIsRemote == false`, `host.security.rootless ==
  true`, non-empty `host.idMappings.uidmap`/`gidmap` including a
  subordinate-range entry beyond the invoking user's single mapping, and a
  present `store.graphDriverName`. Each failed check selects its own hint
  (remote connection configured; rootful invocation; missing/undersized
  `/etc/subuid`–`/etc/subgid` ranges; storage misconfiguration), and
  Podman's stderr is preserved verbatim — the single universal
  shadow-utils diagnosis is dropped. A cached minimal create/run probe is
  rejected for 1.1.0: it adds latency and an image dependency plus
  cache-invalidation rules, and the failure classes it would additionally
  catch (OCI runtime, network helper) surface with full stderr at the
  first real launch, after which the same evidence-keyed hint machinery
  applies. §4 is updated accordingly. Acceptance tests per **Done when**
  land with the implementation.
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
  `store.graphDriverName`), so one parser covers the version range. The
  readiness scope is now decided above; the failure-mode fixtures
  (rootful, remote, missing/undersized ID maps, storage failure, invalid
  JSON) are acceptance work per **Done when**.
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
  - Not yet covered (acceptance work): the same runs as real (non-nested)
    CI integration tests on the first-push substrate (Debian 13 / Podman
    ≥ 5.4; mechanism per MIR-020). The Ubuntu 24.04 runs are retained as
    mid-term pre-qualification (MIR-015).
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The runtime-user ABI is enforced by an **image label plus a
  preflight check on the Podman backend**. Every jms-driven build (base
  and project) stamps `jms.abi.isolation-uid=1000` alongside the existing
  labels, sourced from the single `ISOLATION_UID` constant in `bin/jms`
  (§3) — one source of truth feeding the Containerfile line, the
  `keep-id` mapping, and the label. Before any Podman launch, the backend
  reads the image's labels and fails closed — before mounting
  credentials, shell state, or the project — when the label is missing
  (stale pre-1.1.0 image → "rebuild with `jms build`" hint) or differs
  from the constant (a project Containerfile that recreates `isolation`
  at another UID → rejected with an error naming the label contract;
  deliberately divergent images are unsupported, not accommodated).
  Because OCI labels inherit through `FROM`, project images carry the
  base's stamp automatically. macOS launch behavior is unchanged in
  1.1.0: virtiofs squashing makes the mapping non-load-bearing there, and
  skipping the check preserves the compatibility contract for cached
  images. Acceptance tests per **Done when** land with the
  implementation.
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
  fast `image not known` exit-125 failure with the base absent (retained as
  mid-term pre-qualification per MIR-015). Remaining acceptance work per
  **Done when**: a network-isolation proof in CI on the first-push
  substrate (Debian 13 / Podman ≥ 5.4; mechanism per MIR-020) rather than
  a scratch run.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** SELinux support is desired but **out of scope for 1.1.0**.
  The population of Linux workstations running SELinux in enforcing mode is
  small, so qualifying enforcing-mode hosts — and Fedora as a host platform
  generally — is deferred to a follow-up release rather than blocking the
  first Linux push. Concretely:
  - The first push targets Debian 13, an AppArmor host (MIR-015). The
    Podman backend still passes `--security-opt label=disable`
    unconditionally (§7.2), which is a qualified no-op there.
  - SELinux-**enforcing** hosts are a **documented limitation**: README and
    SECURITY.md state that enforcing-mode hosts are unqualified and
    unsupported in 1.1.0. No preflight detection, warning, or refusal is
    added — the flag will typically work there, but behavior is not tested
    or promised.
  - The follow-up Fedora/SELinux release inherits this issue's original
    **Required resolution** as entry criteria: the recorded decision
    comparing `label=disable` with relabeling and non-mutating
    alternatives, and the SELinux-enforcing-host integration test.
- **Progress:** the non-SELinux half of the original **Done when** is
  observed locally:
  every qualification run on 2026-07-29 (Podman 5.4.2 rootless, Debian 13,
  an AppArmor host) passed `--security-opt label=disable` and the flag was
  accepted as a no-op. 2026-07-29 addendum: the flag is likewise accepted
  as a no-op on Podman 4.9.3 rootless under Ubuntu 24.04 (nested capture) —
  every run in the 4.9.3 qualification pass used it. With the version
  floor now at 5.4 (MIR-015), the 5.4.2 evidence covers the first-push
  minimum directly and the 4.9.3 evidence is retained as mid-term
  pre-qualification. The security decision record comparing alternatives
  and the SELinux-enforcing-host integration test (needs a Fedora or
  similar host; not reproducible on this machine) are deferred to the
  follow-up release per the decision above.
- **Affects:** §§7.2, 8, and 9
- **Finding:** The assertion that SELinux separation "adds little" is not
  established. `label=disable` avoids relabeling host trees but also removes a
  defense layer, and "no-op on non-SELinux hosts" is not a substitute for
  testing. The proposal does not evaluate alternatives or the interaction
  with an enforcing Fedora host.
- **Required resolution:** Record an explicit threat-model decision comparing
  `label=disable`, private/shared relabeling, and any non-mutating alternatives.
  State the residual risk and whether AppArmor behavior also needs control.
- **Done when (1.1.0):** A non-SELinux test proves `label=disable` remains
  accepted on the minimum Podman version, and README/SECURITY.md state the
  enforcing-host limitation in the terms of the decision above.
- **Done when (follow-up release):** An integration test on an
  SELinux-enforcing host proves project and agent-state mounts work, host
  labels are unchanged before/after, and the chosen option has the
  documented process label — alongside the recorded alternatives decision.

### MIR-014 — A minimum Podman version is not a support matrix

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The forward-version policy is **warn on untested major**:
  Podman ≥ 5.4 within major 5 is accepted silently; a future major
  (≥ 6.0.0) proceeds but prints a one-line warning that this Podman
  major has not been qualified with this jms release. There is no hard
  maximum and no Podman escape-hatch variable; `JMS_RUNTIME_ACCEPT`
  stays apple/container-only (§4). Version strings: accept a non-numeric
  suffix on the patch component (distro builds such as `5.4.2-dev`,
  `5.4.2+ds1`), truncated after the numeric prefix; a string not starting
  with numeric `major.minor.patch` is rejected as unparseable. Only the
  local client version is checked — remote services are rejected at
  readiness (MIR-002), so client and engine are the same binary on every
  supported configuration. The remaining matrix dimensions (kernel,
  cgroup manager, OCI runtime, storage driver, network backend) are
  recorded per release in the release checklist for the Debian 13 target
  (§10). Parser fixtures and the deliberate untested-major behavior per
  **Done when** land with the implementation.
- **Progress (2026-07-29):** the MIR-015 scope decision narrows the matrix
  materially: the first push is Debian 13 with its packaged rootless Podman
  5.4.x only, `version_min = (5, 4, 0)`; recent Fedora and Ubuntu are
  declared mid-term targets.
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

- **Status:** Open (partially addressed 2026-07-29)
- **Scope decision (2026-07-29):** the first push targets **Debian 13
  only** (rootless Podman 5.4.x, the packaged version). Recent Fedora and
  Ubuntu releases are declared **mid-term targets**: intended and named as
  such in the docs, but explicitly out of scope for the first push.
  Consequences:
  - The Podman version floor is raised to `version_min = (5, 4, 0)` (§§2,
    4); the 4.9.0 floor derived from Ubuntu 24.04 no longer applies to the
    first push.
  - The Podman 4.9.3 fixtures and qualification evidence recorded under
    MIR-006/007/008/009/011/013/017 are **retained as pre-qualification**
    for the mid-term Ubuntu target; they are no longer first-push
    acceptance material. When Ubuntu 24.04 is promoted, the floor decision
    is revisited (lower to 4.9, or require a newer Podman source there).
  - Fedora as a host is additionally gated on the SELinux follow-up
    (MIR-013).
  - The still-open substance of this issue — qualified package lists,
    installation documentation, and preflight diagnostics — need only
    cover Debian 13 for 1.1.0.
- **Affects:** §§1, 2, 4, and 10
- **Finding:** `podman` alone is not the complete host dependency. Depending on
  distribution and storage/network setup, rootless operation needs subordinate
  ID helpers/configuration, an OCI runtime, networking helpers, and possibly
  `fuse-overlayfs`; `/bin/realpath` additionally requires coreutils and is not
  guaranteed merely by merged-usr layout. The sample install hint is not a
  valid command as written for unprivileged users and cannot name equivalent
  package sets across distributions.
- **Required resolution:** List qualified host packages/configuration for
  Debian 13 (first push; mid-term targets get theirs at promotion time) and
  separate "CLI missing" from rootless setup, storage, filesystem, cgroup,
  and networking diagnostics. Decide support for NFS/distributed home
  directories and minimal installs.
- **Done when:** Installation documentation is tested from a clean Debian 13
  image/user and each preflight failure has an actionable, terminal-safe
  diagnostic.

### MIR-016 — Host group/ACL access and ownership parity are not covered

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The 1.1.0 host-permission contract is **owner-based only**:
  supported project trees, extra mounts, and shell/credential state are
  those readable/writable through the invoking user's own UID (any value,
  not just 1000) and primary GID, which `keep-id:uid=1000,gid=1000` maps
  faithfully for reads and writes. Access that exists only via
  supplementary groups, ACL grants, or setgid directories is a
  **documented limitation** in README and SECURITY.md — no preflight
  detection is added (owner/ACL heuristics false-positive too easily) and
  no `--group-add keep-groups` is passed (its portability across OCI
  runtimes is exactly the unqualified surface this issue flags).
  Supporting supplementary groups becomes entry criteria for a future
  release if the limitation proves painful in practice.
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
- **Done when (1.1.0):** Integration tests use a non-1000 host UID/GID and
  cover user-owned, read-only, and denied paths for normal and `--root`
  launches; README/SECURITY.md state the supplementary-group/ACL/setgid
  limitation in the terms of the decision above.
- **Done when (follow-up, if supplementary groups are promoted):**
  group-owned/setgid and ACL-granted paths are covered by integration
  tests under the then-qualified mechanism.

### MIR-017 — Nested sandbox behavior cannot remain speculative at release

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** 1.1.0 **documents the limitation only**. SECURITY.md and
  README state that bwrap-based inner sandboxes fail inside the container
  on the masked `/proc` (reproduced on 5.4.2 and 4.9.3, evidence below)
  and that agents should run without their inner sandbox — they are
  already inside jms's boundary. No unmask workaround is documented as a
  runnable command, and jms never passes `unmask` itself; qualifying a
  narrower `unmask=/proc/*` opt-in is deferred until a concrete need
  appears, precisely because documenting it would bless unmasking kernel
  interfaces inside the boundary. Testing the shipped Claude, Codex, and
  OpenCode launchers lands as integration assertions per **Done when**
  (recording agent and sandbox versions); if a launcher hard-requires
  bwrap, the recorded behavior becomes part of the documented limitation,
  not grounds for weakening container defaults (§12).
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
  kernel-adjacent — re-confirm on a real runner). Testing the shipped
  Claude/Codex/OpenCode launchers is acceptance work per **Done when**;
  the workaround-documentation question is settled by the decision above.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** Retention and GC are **per image ID, with tags as
  aliases**. `image_facts()` normalizes to `(id, refs, created, labels)` —
  one fact per image identity carrying all of its names — and `created`
  is normalized to a single internal type (Unix epoch seconds) on both
  backends: parsed from the ISO-8601 `creationDate` on apple/container,
  taken directly from integer `Created` on Podman. Retention counts
  distinct image IDs, so a multi-tagged image is one retained unit, and
  duplicate-removal scheduling is impossible by construction. Deletion is
  issued **per jms-owned ref** (untagging): the image itself disappears
  when its last name is removed, and an image that also bears a
  non-jms-owned tag loses only its jms tags — jms never deletes by bare
  ID, so it cannot destroy a user's unrelated alias of the same image.
  Ownership still requires label **and** tag prefix, now evaluated per
  ref within a fact. Dangling images are never jms-owned and are skipped
  (MIR-006). §§2 and 5 are updated accordingly. Verifying that
  apple/container's list output supports this identity model, plus
  deletion ordering and partial-failure behavior for base/child images,
  is part of the **Done when** conformance tests.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** §9 now carries a normative **requirements-to-tests table**
  mapping every claim in §§3–8 to a named unit, conformance, golden-argv,
  or integration test; rows the table cannot map to a test are limited to
  non-enforceable documentation wording, which is release-blocking doc
  review under MIR-012, never a blocker-level behavioral claim. The
  integration plan is extended to cover every gap in the finding:
  `--root` ownership and in-container UID, passwordless sudo under
  `keep-id`, credential/agent-state and read-only shell-state mounts,
  environment and entrypoint parity, `--hostname` behavior, exit-status
  and signal propagation through `execvp`, a deliberate failed-run
  cleanup check, ambient `PODMAN_USERNS`/`containers.conf` conflicts
  (MIR-009), and `label=disable` acceptance. The short-name check is the
  deterministic `--pull=never --network=none` form (MIR-011), not
  "offline-ish". The integration script is split into a fast tier A
  (base image only — preflight, launch-contract, and leak-sweep
  assertions) and an expensive tier B (example projects and agent-image
  coverage), and cleanup plus the leak sweep run from the EXIT trap so
  they execute even after partial failures, with sweep failure distinct
  from leak per the leak-sweep contract (MIR-007). The table is
  maintained with the code: a change to §§3–8 that adds or alters a
  claim must update the table row in the same change. Tests named in the
  table land with their phases per **Done when**.
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

- **Status:** Resolved (design) — 2026-07-29
- **Decision:** The `integration-linux` job runs on a **pinned
  `ubuntu-24.04` runner label** and executes the integration inside a
  **`debian:13` container using Debian's packaged rootless Podman 5.4**
  (nested, matching the nested-capture methodology already used for the
  4.9.3 qualification evidence). This pins the actual first-push userland
  and Podman build; the accepted caveat is that the kernel is the
  runner's Ubuntu kernel, so the non-nested confirmation on real
  Debian 13 remains a manual release-checklist step (§10) — the
  MIR-009/MIR-011 "CI on the first-push substrate" acceptance is
  satisfied by that checklist run plus this recurring nested job, not by
  CI alone. Workflow contract: `workflow_dispatch` plus a weekly
  `schedule` trigger; an explicit job timeout; least-privilege
  `permissions`; per-ref concurrency with cancellation; setup steps that
  *verify* (not assume) rootless prerequisites inside the Debian
  container; `podman info` and version output captured as a build
  artifact with no secrets; cleanup runs on cancellation where possible;
  and promotion to a required PR check only after a documented stability
  criterion (e.g. a recorded streak of consecutive green scheduled runs)
  is met. The workflow lands in phase 4 (§11); §9 is updated
  accordingly. Acceptance per **Done when**.
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
    install_hint = "install it with your distribution's package manager (e.g. apt install podman)"
    version_min = (5, 4, 0)        # Debian 13's packaged Podman; see §4 and MIR-015
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
not.

`runtime_json()` keeps owning UTF-8 decoding and JSON-syntax failures, so
both backends share one malformed-output error path; each backend's
normalizer then owns shape validation on the parsed object.

### The backend protocol (resolves MIR-004)

The protocol below is complete: a backend implements exactly the five class
attributes shown above (`name`, `exe`, `install_hint`, `version_min`,
`version_max`) plus the methods in the two tables below, and nothing else
about a backend is visible outside it.

#### Normalized types

All data crossing the protocol boundary is normalized. Command functions
never see raw runtime JSON, stderr bytes, or `subprocess` objects.

```python
Version = tuple[int, int, int]

ImageFact = tuple[               # one fact per image identity (MIR-018)
    str,                         # id: full, untruncated image identity
    tuple[str, ...],             # refs: every name exactly as the runtime
                                 #   stores it ("localhost/…" preserved);
                                 #   always non-empty — dangling images are
                                 #   skipped by rule (MIR-006)
    int,                         # created: Unix epoch seconds
    dict[str, str],              # labels
]

ContainerFact = {"id": str,      # full, untruncated, NUL-free
                 "labels": dict[str, str]}

Mount = tuple[bytes, str, bool]  # (host source, container target, readonly)

@dataclass(frozen=True)
class LaunchPlan:
    name: str                            # container name (given or generated)
    user: str                            # "isolation" | "root"
    root: bool                           # True iff --root; drives the Podman
                                         #   --userns variant (§7.1)
    tty: bool                            # append the runtime's --tty
    workdir: str                         # "/work" or "/work/<inner>"
    entrypoint: str                      # entry[0]
    image: str
    labels: tuple[tuple[str, str], ...]  # ordered; today exactly
                                         #   (("jms.project", pid),)
    env: tuple[tuple[str, str], ...]     # ordered, see invariants
    mounts: tuple[Mount, ...]            # ordered, see invariants
    command: tuple[str, ...]             # entry[1:] + extra argv
```

`LaunchPlan` invariants, established by the plan builder (`launch_plan()`,
which stays a runtime-agnostic free function and now returns a `LaunchPlan`)
and relied on by both serializers:

- Every `str` field is already NUL-free valid UTF-8: user-supplied values
  pass `runtime_argument()` at the CLI boundary, and `runtime_run()`
  re-checks the final argv as today.
- Mount **targets** are already validated (`valid_target`,
  reserved-target/overlap checks). Mount **sources** are absolute host
  paths still in bytes: grammar validation (`runtime_path()`: NUL, UTF-8,
  no `,`/`=`) happens at serialization time inside the backend's
  `mount_argument()`, with identical rules and error text on both backends.
- Ordering is fixed by the plan and preserved verbatim by `run_argv()`:
  `env` is `CLAUDE_CONFIG_DIR` first (auth only) then manifest env sorted
  by key; `mounts` is `/work`, manifest mounts in manifest order, the
  read-only shell-state mount, then agent-state mounts (auth only). The
  golden argv tests (§9) pin this per backend.
- Plan construction performs all filesystem side effects
  (`ensure_shell_state_directory`, `ensure_agent_state_directory`);
  `run_argv()` performs none.

#### Methods and execution ownership

**Class A — pure serializers and parsers.** No subprocess, no filesystem, no
environment reads; deterministic functions of their arguments plus class
attributes (the golden argv tests rely on this). The *caller* executes any
returned argv through `runtime_run()`:

| Method | Signature | Executed by |
| --- | --- | --- |
| `version_argv` | `() -> list[str]` | `runtime_ready()` |
| `parse_version` | `(first_line: str) -> Version \| None` | — (pure parse; `None` = unparseable, converted to a failure by `runtime_ready()`) |
| `local_name` | `(ref: str) -> str` | — |
| `mount_argument` | `(source: bytes \| str, target: str, readonly: bool = False) -> str` | — (called by `run_argv()`; grammar per §7.2) |
| `build_argv` | `(context: str, tag: str, labels: dict[str, str], *, no_cache: bool, pull: bool, project: bool) -> list[str]` | `run_build()` with `capture=False` (context already validated via `runtime_path()` by `run_build()`, as today) |
| `run_argv` | `(plan: LaunchPlan) -> list[str]` | `cmd_launch` via `runtime_run(argv, replace=True)` |
| `stop_argv` / `remove_argv` | `(container_id: str) -> list[str]` | `cmd_clean` (stop with `check=False`; forced remove authoritative, §5) |
| `remove_image_argv` | `(ref: str) -> list[str]` | `cmd_clean`, `gc_project_images` |

**Class B — executing queries and policy.** These own their invocation and
normalization because their success criteria are backend-specific, but every
process they start MUST cross the module-level `runtime_run()` /
`runtime_json()` — looked up as a module attribute at call time, never
`subprocess` directly and never a stored/bound reference — so the tests'
monkeypatch intercepts every execution on both backends:

| Method | Signature | Backend-specific part |
| --- | --- | --- |
| `validate_version` | `(parsed: Version, first_line: str) -> None` | policy: exact `min == max` pin (apple/container, honoring `JMS_RUNTIME_ACCEPT`) vs. min-only plus warn-on-untested-major (Podman, §4/MIR-014). Runs no process; grouped here because it reads the environment and may print one warning line to stderr |
| `ensure_started` | `() -> None` | apple/container: `system status`/`system start` dance; Podman: full `podman info --format json` validation, no create/run probe (§4, MIR-008) |
| `image_exists` | `(image: str) -> bool` | apple/container: exit 0 vs. the exact `Error: image not found: <ref>` stderr line; Podman: `image exists` exit 0/1, anything else a hard failure (§5) |
| `image_facts` | `() -> list[ImageFact]` | per-backend strict, fixture-backed, fail-closed normalizer (§5, MIR-006/018) |
| `ps` | `() -> list[ContainerFact]` | per-backend strict, fail-closed normalizer (§5, MIR-007); id/label validation (string, NUL-free, dict) shared |

#### Free-function surface and monkeypatch seams

The public surface stays the existing free functions, which delegate to
`runtime()` internally: `runtime_ready()` (runs `version_argv()` through
`runtime_run(check=False)`, decodes the first line — invalid UTF-8 or a
nonzero exit or a `None` parse fails closed with the output quoted — then
calls `validate_version()` and `ensure_started()`), `image_exists()`,
`image_facts()` (replacing `image_records()`/`image_record_facts()`),
`local_name()`, `run_build()`, `launch_plan()`, and `container_records()`
(delegating to `ps()`). The stable monkeypatching seams, in order of
authority:

1. `JMS.runtime_run` — the sole process boundary, exactly as today. Its
   only changes: the argv[0] assertion becomes `argv[0] == runtime().exe`,
   and the `FileNotFoundError` hint becomes `runtime().install_hint`.
2. The free functions above — existing tests that patch
   `JMS.image_exists`, `JMS.runtime_ready`, etc. keep working because
   command functions call them, never the backend directly.
3. `JMS._RUNTIME` — tests install a backend by assigning the cache
   (MIR-001), bypassing selection entirely.

#### Error contract

- The only failure channel is raising `JMSException` via `fail()`, with
  terminal-safe messages (`quote()`/`terminal_safe_text()`) — runtime
  output is untrusted bytes. Methods never return error strings, raw
  stderr, or `subprocess` results to commands; `parse_version`'s `None` is
  the single sentinel, and `runtime_ready()` converts it to a failure
  immediately.
- Executing queries preserve the runtime's stderr, quoted, in the raised
  message, and where a check has a known cause they append the
  evidence-keyed hint (§4, MIR-008) — never a universal diagnosis.
- Malformed values in ownership-relevant fields abort the whole operation;
  they are never silently skipped (MIR-006/007). Podman dangling images
  are skipped by rule, not by error.
- No backend method calls `sys.exit`, prompts, or prints, with exactly two
  exceptions: `ensure_started()` may print daemon-start progress on stdout
  (apple/container's "starting container runtime..."), and
  `validate_version()` may print its one-line untested-major warning on
  stderr.
- Exit codes are unchanged: runtime failures raise `JMSException` (exit 1);
  selection/usage failures raise `UsageError` (exit 2, §2).

#### Prohibitions

Each is enforced by a conformance test, not convention:

- No command function reads `runtime().name`, isinstance-checks a backend,
  or branches on `sys.platform` for runtime behavior. Anything
  backend-specific must be a protocol method.
- No backend method reaches `subprocess` (or `os.execvp`) except through
  the module-level `runtime_run()`.
- No backend method reads the trust store, prompts for consent, or mutates
  the filesystem — consent, state directories, and discovery are
  runtime-agnostic and stay outside the protocol.
- Class A methods perform no I/O of any kind.

#### Conformance suite

One parametrized test module (the MIR-004 **Done when**) runs both backends
through identical scenarios via the per-backend fakes (§9): version first
lines (valid, distro-suffixed, malformed, invalid UTF-8); image/`ps`/`info`
payloads (fixture-true, malformed records, wrong types, invalid UTF-8
bytes, non-array top level); `image_exists` tri-state (present, absent,
hard error with stderr preserved); mount serialization (plain, readonly,
and rejection of `,`, `=`, NUL, and non-UTF-8 in sources/targets); and
golden argv comparisons for build and every launch variant. A seam test
patches `runtime_run` and asserts no backend operation reaches
`subprocess` any other way.

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
   and this line — and note the pairing in a comment on both sides. The
   constant also feeds the `jms.abi.isolation-uid=1000` label stamped on
   every jms-driven build, which Podman launches validate before mounting
   anything (MIR-010); a stale or divergent image fails closed with a
   rebuild hint.

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
and the CLI surface jms uses (`run`, `build`, `image exists`,
`ps --format json`, `--userns=keep-id:uid=`) has been stable across
4.9 → 5.x. Policy:

- `version_min = (5, 4, 0)` — Debian 13's packaged Podman, the only
  first-push host target (MIR-015). Every feature jms uses predates 5.4 by
  years (`--userns=keep-id:uid=` needs ≥ 4.3, `image exists` is ancient),
  so the floor is set by the support scope, not by feature availability.
  When the mid-term Ubuntu 24.04 target is promoted, the floor is
  revisited: its packaged Podman is 4.9.x, already pre-qualified by the
  fixture evidence in §0.
- No hard maximum, but **warn on an untested major** (MIR-014): versions
  within major 5 are accepted silently; a future major (≥ 6.0.0) proceeds
  with a one-line "not qualified with this jms release" warning. Record
  the newest *tested* version in the release checklist.
  `JMS_RUNTIME_ACCEPT` remains meaningful only for the apple/container
  backend; document that.

### Startup / health probe

apple/container keeps the `system status` / `system start` dance. Podman is
daemonless, so `ensure_started()` instead runs one cheap probe that catches
the real-world rootless failure modes (missing `newuidmap`, unconfigured
`/etc/subuid`, broken storage config):

```sh
podman info --format json
```

The JSON is validated in full (MIR-008): `host.serviceIsRemote` must be
false (remote Podman is unsupported, §2/MIR-002); `host.security.rootless`
must be true; `host.idMappings.uidmap`/`gidmap` must be non-empty and
include a subordinate-range entry beyond the invoking user's single
mapping; and `store.graphDriverName` must be present, proving the storage
stack initializes. No create/run probe is performed — the residual failure
classes (OCI runtime, network helper) surface with full stderr at the
first real launch.

On failure, surface Podman's stderr verbatim plus a hint keyed to the
check that failed — remote connection configured, rootful invocation,
missing/undersized `/etc/subuid`–`/etc/subgid` ranges (the shadow-utils
hint below), or storage misconfiguration — never one universal diagnosis:

```
rootless podman is not usable: <stderr>
hint: rootless podman needs shadow-utils (newuidmap/newgidmap) and an
entry for your user in /etc/subuid and /etc/subgid; see podman(1).
```

This converts each common Linux support issue into a self-explanatory
error without misdiagnosing the others.

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
`image_facts()` returning already-normalized `(id, refs, created, labels)`
tuples — **one fact per image identity**, carrying all of its names
(MIR-018). Parsing is a strict fixture-backed normalizer (MIR-006): the
shape proven by the checked-in fixtures is accepted, anything else fails
closed, and malformed ownership-relevant fields abort rather than skip.

- apple/container: the current extraction, regrouped by image identity;
  `created` parsed from the ISO-8601 `creationDate` string.
- Podman: `refs` from `Names`; skip records with null/empty `Names`
  (dangling layers are never jms-owned); `created` from the integer
  `Created`.

`created` is one internal type — Unix epoch seconds — on both backends, so
sorting is uniform and never compares backend-local representations.

Retention in `gc_project_images` counts distinct image IDs (a multi-tagged
image is one retained unit); ownership still requires label **and** tag
prefix, evaluated per ref within a fact. Deletion untags per jms-owned ref
rather than deleting by bare ID: the image disappears when its last name
goes, and a non-jms alias of the same image survives. The
label-inheritance caveat (`bin/jms:869`) applies identically to Podman —
OCI labels inherit through `FROM` there too — so the dual check stays
load-bearing on both backends.

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

SELinux-**enforcing** hosts are out of scope for 1.1.0 (MIR-013): support
is desired and planned alongside Fedora host support, but deferred given
the small population of Linux workstations that run SELinux in enforcing
mode. jms does not detect or refuse enforcing hosts — the flag will
typically work there, but the configuration is unqualified, and README and
SECURITY.md record it as unsupported for now.

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
but that unmasks kernel interfaces inside the boundary, so jms never
passes it and must not weaken the container defaults globally. Per
MIR-017, 1.1.0 documents the limitation only — agents should run without
their inner sandbox, since they are already inside jms's boundary — and
no unmask workaround is documented as a runnable command; a narrower
`unmask=/proc/*` opt-in is deferred until a concrete need appears.
Codex's native Linux sandbox
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
  - SELinux-enforcing hosts are unqualified and unsupported in 1.1.0
    (MIR-013, §7.2); enforcing-mode support is planned alongside the
    Fedora host target.

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
  leaked-container sweep follows the "Leak-sweep contract" below — on
  Podman it lists IDs via `podman ps --all --format json` and reads mount
  sources via `podman inspect`, because on both 4.9.3 and 5.4.2 the `ps`
  JSON `Mounts` field is only a list of target paths with no sources
  (MIR-007), so `ps` alone cannot identify jms mounts.
- Add a `FROM jmscontainers-base:latest` resolution check (§3): build one
  example with `--pull=never --network=none` and assert success with the
  base present and a fast, non-interactive `image not known` failure
  (exit 125) with it absent — the deterministic form of the earlier
  "offline-ish" check, qualified locally per MIR-011.

The script is split into two tiers (MIR-019), so the launch-contract
assertions do not pay for the example-image builds:

- **Tier A — fast, base image only.** Runs the readiness preflight, builds
  the base, and asserts the launch contracts against `--bin` shell
  launches of the base image: `/work` ownership (default and `--root`),
  in-container UID per variant, passwordless sudo, hostname, environment
  and entrypoint parity, exit-status propagation, the read-only
  shell-state mount, the ambient-config conflict runs (MIR-009), the
  bwrap probes (MIR-017), and the deliberate-failure cleanup check.
- **Tier B — expensive, example images.** The existing per-example
  build/inspect/launch/clean cycle, the context-escape test, and the
  credential/agent-state mount assertions (which need `--auth` and real
  agent state directories).

Both tiers end in the leak sweep, and cleanup plus the sweep run from the
EXIT trap, so a failure in any step still sweeps and reports — a partial
failure can never skip leak detection (MIR-019); sweep failure stays
distinct from leak per the leak-sweep contract below.

The Linux-only tier-A launch-contract assertions, each keyed to a table
row below:

- **Ownership (default):** create a file in `/work` from inside the
  container (`--bin /bin/sh -- -c 'touch …'`) and verify host ownership
  equals the invoking user — the `keep-id` contract and the single most
  likely thing to break. Also assert `id -u` inside is 1000
  (`isolation`).
- **Ownership (`--root`):** the same write under `--root`, asserting
  `id -u` inside is 0 and host ownership is still the invoking user —
  the `--userns=host` contract, and the enforceable form of §8's
  "container root is an unprivileged mapped UID" claim.
- **Sudo:** `sudo -n true` succeeds as `isolation` under `keep-id`
  (§7.1's SECURITY.md claim).
- **Hostname:** `$HOSTNAME` inside the container is `container` (§7.3).
- **Env/entrypoint parity:** a manifest env var and `CLAUDE_CONFIG_DIR`
  (auth path, tier B) are visible inside with the documented ordering,
  and the entrypoint runs as `entry[0]` with `entry[1:]` + extra argv.
- **Exit propagation:** `--bin /bin/sh -- -c 'exit 7'` makes `jms launch`
  exit 7 (the `execvp` contract); a launch killed by SIGTERM leaves no
  container behind (verified by the sweep).
- **Read-only shell state:** writing to the shell-state target from
  inside the container fails.
- **Failed-run cleanup:** force one launch to fail mid-run (an
  entrypoint that exits nonzero after touching `/work`) and assert the
  trap-driven cleanup and sweep still run and report clean.
- **Security options:** every tier-A run passes
  `--security-opt label=disable` and succeeds — the 1.1.0 non-SELinux
  acceptance check from MIR-013.

### Leak-sweep contract (resolves MIR-007)

The final integration step asserts that no test container survived the run.
This subsection is the testable specification of that step; the parsing and
predicate logic lives in one `python3` snippet per backend so the same code
can be exercised as a unit test against the checked-in fixtures.

**Leak predicate.** Let `WORK` be the canonicalized (`realpath`) path of the
run's temporary workspace. jms canonicalizes every mount source through
`canon()` before launch, so the source recorded in engine metadata is
already canonical; the comparison is therefore an exact string test with no
compare-time normalization: a container **leaks** iff any of its mount
entries has a string source equal to `WORK` or beginning with `WORK + "/"`.
No globbing, no case folding, no symlink resolution at compare time.

**Enumeration on Podman — two steps, both parsed strictly.** The `ps` JSON
`Mounts` field carries target paths only (the MIR-007 negative finding,
proven on 4.9.3 and 5.4.2), so sources must come from `inspect`:

1. `podman ps --all --format json`. The output must be a JSON array (empty
   means no containers and the sweep passes). Every element must be a map
   whose `Id` is a 64-character lowercase-hex string
   (`tests/fixtures/podman-4.9.3-ps.json`,
   `tests/fixtures/podman-5.4.2-ps.json`). Anything else — non-array top
   level, non-map element, missing/truncated/non-string `Id` — aborts the
   sweep as a **sweep failure** (below). A malformed record is never
   skipped: a skipped record could hide a leak.
2. For each ID, `podman inspect --type container --format json <id>`,
   passing the ID exactly as returned. The output must be a
   single-element JSON array whose element is a map; its `Mounts` field
   must be an array (absent or non-array aborts); every mount entry must
   be a map whose `Source` and `Destination` are strings
   (`tests/fixtures/podman-4.9.3-inspect-mounts.json`). Non-conforming
   output aborts as a sweep failure. Entries are evaluated against the
   leak predicate regardless of their `Type` — a leak is a leak however
   it was mounted.

**The single tolerated race.** A container may exit and be removed between
steps 1 and 2 (jms launches pass `--rm`). If `inspect` fails and its stderr
identifies the container as unknown (Podman's "no such container" / "no
such object" diagnostics), that ID is treated as gone: a vanished container
holds no mounts and is not a leak. Any other `inspect` failure — nonzero
exit with different stderr, unparseable output — aborts as a sweep failure.
This is the only failure the sweep tolerates.

**Three mutually exclusive outcomes.**

| Outcome | Exit | Output contract |
| --- | --- | --- |
| Clean | 0 | nothing required |
| Leak found | nonzero | names every leaking container ID and each offending mount source |
| Sweep failure | nonzero | a diagnostic distinct from the leak message, quoting what failed to parse or execute |

A sweep that cannot complete must fail the integration run — fail closed —
and must never be conflated with "leak found", so a schema drift in a future
Podman shows up as its own signal rather than as a phantom leak.

**apple/container is unchanged.** `container list --all --format json`
already embeds `configuration.mounts[].source`, so macOS stays single-pass,
applying the same leak predicate and the same three-outcome contract to
that schema.

**Coverage note.** The 4.9.3 evidence shows auto-removed containers never
appear in `ps --all`, so the sweep observes exactly the leak classes
cleanup is responsible for: containers still running and containers that
failed before removal. This matches the apple/container sweep's semantics.

**Acceptance (the MIR-007 Done when).** The per-backend sweep snippet runs
as a unit test over the checked-in `ps` and `inspect` fixtures plus
malformed variants (non-array top level, truncated `Id`, missing `Mounts`,
non-string `Source`), asserting each of the three outcomes and the
tolerated-race path; the integration run then exercises the clean path for
real on both backends.

### Requirements-to-tests table (resolves MIR-019)

This table is normative: every behavioral claim in §§3–8 maps to at least
one named test, and a change to §§3–8 that adds or alters a claim must
update its row in the same change. Test names are the planned identities;
they land with their phases (§11) and existing names are reused where the
test already exists. Tiers: **unit** (fake-runtime/fixture tests in
`tests/test_jms.py`), **conformance** (the MIR-004 both-backend
parametrized suite), **golden** (golden argv unit tests), **int-A/int-B**
(integration tiers above), **macOS-int** (manual macOS integration run),
**doc** (release-blocking documentation review per MIR-012 — used only
for non-enforceable wording, never for a behavioral claim).

| ID | § | Claim | Tier | Test |
| --- | --- | --- | --- | --- |
| R3.1 | 3 | `isolation` UID/GID pinned to 1000; `ISOLATION_UID` constant and Containerfile line agree | unit | `test_isolation_uid_constant_matches_containerfile` (reads the Containerfile) |
| R3.2 | 3 | every jms-driven build stamps `jms.abi.isolation-uid` from the constant | golden | `test_build_argv_stamps_abi_label` (both backends) |
| R3.3 | 3 | Podman launch validates the ABI label before mounting; missing label → rebuild hint; divergent UID → rejected naming the contract | unit | `test_podman_launch_rejects_stale_or_divergent_abi_image` (MIR-010 matrix: missing label, divergent UID, cached project image) |
| R3.4 | 3 | rebuilt base image behaves unchanged on macOS | macOS-int | phase-3 rebuild-and-verify run of the full integration script |
| R3.5 | 3 | Podman `local_name()` strips `localhost/` so tag-prefix ownership checks work unmodified | conformance | `local_name` cases in the conformance suite |
| R3.6 | 3 | `image_exists` matches the `localhost/`-prefixed stored name | int-A | base built then `image_exists` true via a `jms build` no-op path; unit exit-code cases in R5.1 |
| R3.7 | 3 | `FROM jmscontainers-base:latest` resolves locally under `--pull=never`; base absent fails fast, non-interactive, exit 125 | int-A | FROM-resolution check (`--network=none`, base present/absent; MIR-011) |
| R4.1 | 4 | version first-line parsing: both formats, distro suffix truncation, malformed/non-numeric rejected, invalid UTF-8 fails closed | conformance | version-line fixtures (MIR-014) |
| R4.2 | 4 | apple/container exact `min == max` pin and `JMS_RUNTIME_ACCEPT` unchanged | unit | existing `test_version_gate`, `test_runtime_accept_pin_admits_one_exact_newer_version` |
| R4.3 | 4 | Podman floor (5, 4, 0); silent within major 5; one-line warning on major ≥ 6; `JMS_RUNTIME_ACCEPT` ignored on Podman | unit | `test_podman_version_floor_and_untested_major_warning` |
| R4.4 | 4 | `ensure_started()` validates `podman info` JSON: remote, rootful, missing/undersized ID maps, absent graph driver, invalid JSON each fail with their own hint and verbatim stderr; healthy engine passes | unit + int-A | `test_podman_readiness_matrix` over MIR-008 fixtures; tier-A preflight on the fresh CI user |
| R4.5 | 4 | `approve()` runs before `runtime_ready()` on both backends; grant-then-preflight-failure leaves a valid grant | unit | `test_consent_precedes_runtime_readiness` (MIR-003 matrix: accepted, declined, non-interactive failure, missing runtime, unusable rootless Podman) |
| R5.1 | 5 | `image_exists` tri-state: 0 true, 1 false, other exit hard failure with stderr | conformance | existing `test_image_exists_distinguishes_absence_from_failure`, parametrized |
| R5.2 | 5 | `image_facts()` strict fixture-backed normalizer; dangling skipped by rule; malformed ownership-relevant field aborts | unit | `test_podman_image_facts_normalizer` over 4.9.3/5.4.2 fixtures + malformed variants (MIR-006) |
| R5.3 | 5 | `created` is Unix epoch seconds on both backends; ordering never compares backend-local shapes | conformance | mixed-timestamp retention-ordering cases (MIR-018) |
| R5.4 | 5 | retention counts distinct image IDs; deletion untags per jms-owned ref; non-jms alias survives; label **and** tag-prefix ownership per ref | conformance | MIR-018 suite: multi-tag, duplicate ID, inherited labels, base-with-children, partial deletion failure |
| R5.5 | 5 | `ps()` strict normalizer: full 64-char `Id`, top-level `Labels`; malformed record aborts | unit | `test_podman_ps_normalizer` over `ps` fixtures + malformed variants (MIR-007) |
| R5.6 | 5 | stop may fail, forced delete authoritative, on both backends | unit | existing `test_stop_failure_does_not_abort_deletion` under both fakes |
| R6.1 | 6 | per-backend build argv: label flag spelling, `--pull=always` base-with-pull, `--pull=never` project builds | golden | `test_build_argv_golden` per backend |
| R6.2 | 6 | v2 context-escape failure still trips `CONTEXT_NOTE` under Podman | int-B | existing escape test, parametrized |
| R7.1 | 7.1 | explicit `--userns` on both variants: `keep-id:uid=1000,gid=1000` default, `host` under `--root` | golden | launch argv goldens (default, `--root`, manifest mounts, `--auth`) |
| R7.2 | 7.1 | default launch: `/work` writes host-owned by the invoking user; in-container UID 1000 | int-A | ownership (default) assertion |
| R7.3 | 7.1 | `--root`: in-container UID 0; `/work` writes still host-owned by the invoking user | int-A | ownership (`--root`) assertion |
| R7.4 | 7.1 | conflicting `PODMAN_USERNS` and `containers.conf` lose to the explicit flag for both variants | int-A | ambient-config conflict runs (MIR-009 **Done when**) |
| R7.5 | 7.1 | passwordless sudo works for `isolation` under `keep-id` | int-A | `sudo -n true` assertion |
| R7.6 | 7.2 | per-backend mount grammar (`type=bind` on Podman), readonly suffix; `,`/`=`/NUL/invalid-UTF-8 sources rejected with identical errors | conformance | existing `test_mount_argument_serialization`, parametrized + rejection cases |
| R7.7 | 7.2 | `--security-opt label=disable` always passed on Podman and accepted on the minimum version | golden + int-A | launch argv goldens; every tier-A run (MIR-013 1.1.0 **Done when**) |
| R7.8 | 7.3 | `--hostname container` passed; `$HOSTNAME` inside agrees | golden + int-A | launch argv goldens; hostname assertion |
| R7.9 | 7 | env ordering (`CLAUDE_CONFIG_DIR` first, manifest env sorted) and entrypoint/command shape preserved verbatim | golden + int-A/B | launch argv goldens; env/entrypoint parity assertions (auth path in tier B) |
| R7.10 | 7 | `launch` exits with the container's status via `execvp`; an interrupted launch leaves no container | int-A | exit-propagation (`exit 7`) and SIGTERM assertions |
| R7.11 | 7 | shell-state mount is read-only inside the container | int-A | read-only shell-state write-failure assertion |
| R7.12 | 7 | credential/agent-state mounts (`--auth`) are present, writable, and host-owned by the invoking user | int-B | auth-mount assertions |
| R7.13 | 7 | cleanup and leak sweep run after partial failures; sweep failure distinct from leak | unit + int-A | sweep-snippet unit tests over fixtures (MIR-007 **Done when**); deliberate failed-run cleanup check |
| R7.14 | 7.3 | nested bwrap: `--unshare-user` works, full sandbox fails on masked `/proc`; jms never passes `unmask` | int-A + golden | bwrap probes recording agent/sandbox versions (MIR-017); goldens prove no `unmask` in any argv |
| R8.1 | 8 | container "root" is an unprivileged mapped UID of the invoking user | int-A | covered by R7.3 (UID 0 inside, invoking-user ownership outside) |
| R8.2 | 8 | sudo-inside-container claim as stated in SECURITY.md | int-A | covered by R7.5 |
| R8.3 | 8 | read-only shell mount behaves as documented | int-A | covered by R7.11 |
| R8.4 | 8 | threat-model wording: kernel/OCI-runtime trust, escape consequences, weaker-than-VM statement, mounted-data exposure, SELinux/supplementary-group limitations | doc | release-blocking SECURITY.md/README review (MIR-012/013/016 **Done when**); non-enforceable by construction — no behavioral claim rides on it |

Every blocker-level claim (rows tracing to MIR-001–012) maps to a unit,
conformance, golden, or integration test; the only **doc** row is R8.4,
which contains no enforceable behavior. Selection, laziness, and remote
rejection (§2) are already covered by the MIR-001/002 acceptance tests
listed under those issues and the unit-test plan above.

### CI (`.github/workflows/test.yml`)

- Existing matrix (`make test` on Ubuntu 3.11/3.14 + macOS) unchanged; it
  now also exercises the Podman fake on the Ubuntu legs automatically.
- Add the `integration-linux` job per the MIR-020 decision: pinned
  `ubuntu-24.04` runner, integration executed inside a `debian:13`
  container with Debian's packaged rootless Podman 5.4 (nested — the
  first-push userland on the runner's kernel), triggered by
  `workflow_dispatch` plus a weekly `schedule`, with an explicit timeout,
  least-privilege permissions, per-ref concurrency cancellation, verified
  (not assumed) rootless prerequisites, and `podman info`/version output
  uploaded as an artifact. Keep it out of required PR checks until the
  documented stability criterion is met (MIR-020). The non-nested
  confirmation on real Debian 13 is a manual release-checklist step
  (§10). macOS integration remains manual (no nested virtualization on
  GH macOS runners).

---

## 10. Documentation and packaging checklist

- `README.md`: platform section becomes "Apple Silicon Mac (apple/container)
  **or** Debian 13 with rootless Podman ≥ 5.4", naming recent Fedora and
  Ubuntu as mid-term targets that are out of scope for 1.1.0 (MIR-015),
  SELinux-enforcing hosts as unqualified (MIR-013), and
  supplementary-group/ACL-only project access as unsupported (MIR-016);
  install instructions per platform; stack line gains a Linux variant
  (`Linux → rootless podman (user namespace) → Fedora → …`); isolation
  wording per §8.
- `docs/cli.md`: new "Runtimes" section (selection rules, per-backend
  qualification policy); `JMS_RUNTIME` added to environment variables;
  `JMS_RUNTIME_ACCEPT` marked apple/container-only; exit-code table
  unchanged.
- `SECURITY.md`: per-platform boundary statement (§8); `label=disable`
  rationale and the SELinux-enforcing-host limitation (§7.2, MIR-013);
  rootless-only statement; the owner-based host-permission contract
  (MIR-016); the nested-bwrap limitation with no unmask recommendation
  (§7.3, MIR-017).
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
   versions (at minimum: Debian 13's packaged 5.4.x, the only first-push
   host target per MIR-015).

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
- **Fedora and Ubuntu as host platforms (for 1.1.0).** Recent Fedora and
  Ubuntu releases are declared mid-term targets, out of scope for the
  first push (MIR-015): 1.1.0 qualifies Debian 13 only. The Ubuntu 24.04
  qualification evidence already captured is retained for the promotion.
- **SELinux-enforcing hosts (for 1.1.0).** Desired, deferred with the
  Fedora host target given the small enforcing-mode workstation population
  (MIR-013). A documented limitation — not detected or refused.
- **Cross-runtime image sharing.** Images are per-runtime-store; a user on
  both platforms builds the base twice. Fingerprint-derived tags make this
  transparent.
- **Weakening container defaults for nested bwrap** (§7.3).
