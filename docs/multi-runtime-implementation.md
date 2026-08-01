# Implementation guide: supporting Podman on Linux alongside apple/container

Status: proposal (not yet implemented)
Target: jms 1.1.0

**Standing direction:** jms has no install base. Backwards-compatibility
machinery is to be avoided in this work — design for the right behavior,
not for preserving 1.0.0's — and the project stays a svelte automation
layer for isolating AI agents via containers.

This guide describes how to make `jms` run on Linux with rootless Podman
alongside the existing `apple/container` backend on macOS. It is written
against `bin/jms` at version 1.0.0.

The guiding constraint: **the trust model, fingerprinting, consent flow,
manifest schema, and project discovery are shared and do not fork per
backend.** Only the layer that talks to the container runtime becomes
pluggable. A user on either platform types the same commands, reads the same
consent prompts, and gets the same `/work` + agent-state contract inside the
same Fedora image.

> **Provenance.** This is the slimmed edition of the proposal. jms has no
> installed user base, so the earlier revision's compatibility contract,
> preview gate, and 1.0.0-behavior-preservation machinery have been removed,
> and the resolved review-gate issue log (MIR-001…MIR-032) has been folded
> into the body. The full issue log, decision history, and qualification
> narratives live in git history (the pre-slim revision of this file).
> MIR-033…MIR-051 are tracked in the pre-implementation register below.
>
> **Second slim, 2026-07-30.** A proportionality review removed three
> subsystems whose cost outweighed the risk they mitigated: the image ABI
> attestation probe (superseded by a numeric `--user`, which removes the
> attested surface entirely — MIR-034/036/037), the nested
> `integration-linux` CI job (the release-blocking manual Debian 13
> walkthrough in §10 is the Linux confirmation — MIR-033), and the
> tri-state removal classification (Podman's `--ignore` flags make
> absence a success at the engine — MIR-035). The Podman 4.9.3
> pre-qualification fixtures and the untested-major version warning were
> dropped, and MIR-038's identity merging was scoped to the one backend
> whose output shape needs it. The register retains every ID and finding
> with updated statuses; the deleted designs survive in git history.
>
> **Issue-resolution pass, 2026-07-30.** The twelve implementation-readiness
> findings (MIR-040…MIR-051) are resolved in place, following the standing
> direction toward proportionate machinery: ambient host configuration is
> trusted input (MIR-040), the local nested harness is dropped as a gate
> (MIR-049), apple/container removal absence is classified by existence
> recheck instead of diagnostic matching (MIR-043), and `LaunchPlan` keeps a
> single user-mode authority (MIR-046). Each resolution is recorded in the
> register entry and the affected normative sections.
>
> **External validation pass, 2026-07-30.** An outside review of the
> resolved document surfaced five further findings: the apple/container
> removal recheck could raise inside a never-raises path, null-label
> normalization was undecided, §11 phase 1 built normalizers before
> phase 2 captured their fixtures, the missing-base behavior overclaimed
> failure speed and hint precision, and the real-host integration
> harness left tooling choices open. They are registered and resolved as
> MIR-052…MIR-056.

## Scope for 1.1.0

- **macOS:** Apple Silicon, apple/container CLI pinned exactly to 1.2.0
  (the only version Homebrew ships; identity fixture captured on it).
- **Linux:** local rootless Podman ≥ 5.4; the qualified configuration is
  Debian 13 on amd64 (Debian's packaged Podman). The Debian/amd64 boundary
  is a **qualification statement, not an enforced gate** (MIR-039): jms
  detects neither distribution nor architecture, and other local rootless
  Linux hosts select the Podman backend and run **unqualified but
  allowed**, with no warning — consistent with the SELinux and NFS
  non-detection stances (§§7.2, 10). What is **refused** is exactly:
  non-Linux/non-macOS platforms, uid 0 on Linux, and remote Podman
  (§§2, 4). Recent Fedora and Ubuntu, arm64, and SELinux-enforcing hosts
  are named mid-term qualification targets, out of scope for the first
  push (§12).
- The Podman 4.9.3 fixtures and qualification runs previously checked in
  under `tests/fixtures/` are deleted: pre-paying for a possible
  Ubuntu 24.04 promotion serves no current user. Fixtures for that
  target are recaptured if and when it is actually qualified.

## Shared invariants

These surfaces are one implementation used by both backends, pinned by the
existing tests and goldens — not per-backend behavior to keep in sync:

- Trust-store location, record format, and semantics.
- Project trust fingerprints (the `GOLDEN_TREE_TF`-style goldens).
- Consent prompt text, ordering, and accepted responses.
- Manifest schema and validation errors.
- Project discovery and workdir resolution rules.
- Documented exit codes: runtime failures exit 1, selection/usage failures
  exit 2.

Golden argv tests pin each backend's build and launch argv as designed
here; they are regression pins for the new behavior and are re-baselined
freely when the design changes deliberately.

---

## 0. Pre-implementation issue register

Review date: 2026-07-29

This register contains findings not tracked by the folded MIR-001…MIR-032
review. Resolve these issues in the design before implementing the affected
area; do not let an implementation choice silently settle them. When an
issue is resolved, retain the ID and finding, change its status, record the
decision in the affected normative sections, and add or update the named
acceptance tests.

The 2026-07-30 proportionality review (see Provenance) superseded four
resolutions (MIR-033, MIR-034, MIR-036, MIR-037) and re-resolved two in
simpler forms (MIR-035, MIR-038). Superseded entries keep their findings
as recorded constraints on any future feature that reopens the area.

An implementation-readiness review on 2026-07-30 added MIR-040…MIR-051.
All twelve were resolved later the same day (see Provenance); each entry
records its decision, and the affected normative sections carry the
resolved text.

An external validation review on 2026-07-30 (see Provenance) added
MIR-052…MIR-056; all five are resolved in place under the same
convention.

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| MIR-033 | High | Nested CI execution contract | Superseded (§§9, 10) |
| MIR-034 | Blocker | Cached-image ABI attestation | Superseded (§§7.1, 7.4) |
| MIR-035 | Blocker | Cleanup result protocol | Resolved (§§2, 5) |
| MIR-036 | Blocker | ABI-probe volume side effects | Superseded (§7.4) |
| MIR-037 | High | Shell ABI observation | Superseded (§7.4) |
| MIR-038 | High | Duplicate image identities | Resolved (§5) |
| MIR-039 | High | Linux support-scope enforcement | Resolved (Scope, §§2, 9, 10, 12) |
| MIR-040 | Blocker | Ambient Podman configuration and implicit exposure | Resolved (§8, §10) |
| MIR-041 | Blocker | Project-build pull and missing-base contract | Resolved (§§3, 6) |
| MIR-042 | High | Image removal can prune unselected parents | Resolved (§5) |
| MIR-043 | High | apple/container absence classification | Resolved (§§2, 5) |
| MIR-044 | High | Qualification fixtures do not cover the promised schemas | Resolved (§§5, 11) |
| MIR-045 | High | Normalized-fact validation is incomplete | Resolved (§5) |
| MIR-046 | High | `LaunchPlan` has contradictory user-mode authorities | Resolved (§2, §7.1) |
| MIR-047 | High | Image-ref ownership and concurrent retagging | Resolved (§§3, 5) |
| MIR-048 | High | GC and purge failure-policy boundary | Resolved (§5) |
| MIR-049 | High | The retained local nested harness is undefined and non-gating | Resolved (§§9, 11, 12) |
| MIR-050 | Medium | Readiness overclaims storage validation | Resolved (§§4, 10) |
| MIR-051 | Medium | Lazy runtime accessor is inconsistently specified | Resolved (§2) |
| MIR-052 | High | apple/container removal recheck envelope | Resolved (§§2, 5) |
| MIR-053 | High | Null-label normalization | Resolved (§5) |
| MIR-054 | Medium | Fixture-before-normalizer phase ordering | Resolved (§11) |
| MIR-055 | Medium | Missing-base failure and hint claims | Resolved (§§3, 6, 9) |
| MIR-056 | Medium | Real-host integration harness contract | Resolved (§9) |

### MIR-033 — The nested CI job lacks an executable outer-harness contract

- **Status:** Superseded 2026-07-30 (originally resolved 2026-07-29)
- **Affects:** §9's CI section, §11 implementation phase 2
- **Finding:** The `integration-linux` job was decided in outline only.
  The repository's nested qualification requires an outer `--privileged`
  container, `/dev/fuse`, subordinate-ID setup, a fresh non-root user,
  and cgroup/event-log overrides; a GitHub Actions job-level container
  cannot express that by implication, and a host `docker run`/Podman
  harness has different mounts, signal handling, cancellation, and
  cleanup — none of which were written down.
- **Resolution:** Superseded: the nested `integration-linux` job is
  removed from 1.1.0 rather than specified. The 2026-07-29 resolution
  wrote the full executable contract (privileged rootful-Docker outer
  container, `scripts/ci-debian-nested.sh`, subordinate-ID plumbing,
  divergence records, a 4-green-run promotion protocol) — a second,
  lower-fidelity copy of qualification the release checklist performs by
  hand anyway; the finding itself documents why a nested run cannot
  match a real workstation. With no userbase and no PR contributors
  needing CI-time Linux signal, Linux qualification for 1.1.0 is the
  local nested harness during development plus the release-blocking
  manual clean-host walkthrough on real Debian 13 (§10). A CI job can
  return, with this finding as its requirements list, when contributors
  exist; the pre-slim contract survives in git history.
  **Amended 2026-07-30 (MIR-049):** the "local nested harness" half of
  this resolution is dropped too — Linux qualification is real-host
  only: the integration tiers on a real Debian 13 amd64 host plus the
  §10 walkthrough.
- **Done when:** No `integration-linux` job, `ci-debian-nested.sh`, or
  nested harness exists; §9's CI section and §11 phase 2 reference only
  the real-host integration run and the §10 walkthrough; the release
  checklist names them as the Linux confirmation.

### MIR-034 — Cached images bypass the isolation-user ABI attestation

- **Status:** Superseded 2026-07-30 (originally resolved 2026-07-29)
- **Affects:** §§2, 3, 6, 7.4, 9, 11, R3.3, and the launch-time
  re-verification non-goal in §12
- **Finding:** The current text runs `verify_image_abi()` only after a build
  that jms actually performs. Both `build_project()` and `ensure_base()`
  have an image-exists fast path, so a cached image is returned without any
  attestation. More seriously, a newly built divergent image keeps the
  predictable target tag when its post-build probe fails; a retry can take
  the cache fast path and report success or launch the image. The claim that
  every image jms launches “has been attested once” is therefore not
  established by the specified call sites. This is a regression from the
  pre-slim MIR-022 decision, which checked the resolved image on every
  Podman launch before `launch_plan()`.
- **Resolution:** Superseded along with the attestation itself. The
  Podman backend now passes `--user` numerically (§7.1) —
  `--user 1000:1000` by default, `--user 0:0` under `--root` — so the
  image's `/etc/passwd` can no longer influence which UID the container
  process runs as. The coherence the attestation defended holds by
  construction for cached, freshly built, and out-of-band-mutated images
  alike, and there is no attestation left to bypass. `verify_image_abi`
  does not exist on any backend. Decision record in §7.4.
- **Done when:** No `verify_image_abi` exists; launch argv goldens
  (R7.1) pin the numeric `--user` on both variants.

### MIR-035 — Cleanup cannot classify removal results through the protocol

- **Status:** Resolved 2026-07-30 (simplifies the 2026-07-29 tri-state)
- **Affects:** §2's backend protocol and error contract, §5, §9, R5.7, and
  implementation phase 1
- **Finding:** Section 5 requires cleanup and GC to attempt every removal,
  treat backend-specific “resource vanished” diagnostics as success, retain
  quoted stderr for hard failures, and aggregate rather than raise
  immediately. The protocol exposes only pure `stop_argv`, `remove_argv`,
  and `remove_image_argv` serializers. At the same time, its error contract
  says commands never receive raw `subprocess` results or raw stderr. A
  command therefore cannot implement the required tri-state
  success/absent/hard-failure behavior without either parsing
  backend-specific stderr itself, branching on the backend, or violating the
  protocol's result boundary.
- **Resolution:** The pure serializers are replaced by three Class B
  executing operations — `stop_container()`, `remove_container()`,
  `remove_image()` — that own their invocation through the module-level
  `runtime_run()` and return a normalized `RemovalResult`, but the
  originally proposed tri-state collapses to `removed` | `failed`. The
  Podman backend makes absence a success at the engine — `podman stop
  --ignore`, `podman rm --ignore --force`, `podman image rm --ignore`,
  all documented on 5.4 and qualified as part of acceptance — so no
  not-found stderr patterns exist to maintain. The apple/container
  backend maps its one exact not-found diagnostic to `removed`
  internally, the same stderr matching `image_exists` already performs
  today. The error contract keeps one deliberate exception for this
  non-raising result channel. Recorded in §§2, 5; tests in R5.9.
  **Amended 2026-07-30 (MIR-043):** apple/container absence is
  classified by post-failure existence recheck, not diagnostic
  matching — the borrowed inspect-image string proved unproven for the
  removal verbs.
- **Done when:** Cross-backend conformance tests
  (`RemovalClassificationTests`, R5.9) feed success, absence, and
  hard failure into container and image removals; absence classifies as
  `removed` on both backends. Command tests prove attempt-all ordering
  and aggregated terminal-safe diagnostics without backend branches or
  direct inspection of a `CompletedProcess`.

### MIR-036 — The ABI probe can create persistent image-declared volumes

- **Status:** Superseded 2026-07-30 (originally resolved 2026-07-29)
- **Affects:** §§2, 7.4, 9, R3.2, R3.3, R3.8, and the probe argv golden
- **Finding:** `podman create` defaults `--image-volume` to `bind`; for every
  built-in `VOLUME` in an untrusted project image, Podman creates an
  anonymous named volume. The specified `podman rm --force` does not request
  volume removal. Thus the statement that the never-started probe has no
  side effects is false, and repeated builds can leak host storage even when
  the probe container itself is removed. Podman 5.4 documents both the
  default and `--image-volume=ignore`:
  <https://docs.podman.io/en/v5.4.2/markdown/podman-create.1.html#image-volume-bind-tmpfs-ignore>.
- **Resolution:** Superseded: the ABI probe no longer exists (§7.4,
  MIR-034), so no jms code path runs `podman create` outside a launch,
  and launches run with `--rm`, which removes the container and its
  anonymous volumes on exit. The finding is retained as a standing
  constraint: any future feature that creates a container it does not
  `--rm` must pass `--image-volume=ignore` and remove with `--volumes`.
- **Done when:** Nothing to implement; the constraint travels with the
  finding.

### MIR-037 — The shell probe is both “strictly parsed” and discarded

- **Status:** Superseded 2026-07-30 (originally resolved 2026-07-29)
- **Affects:** §§3, 7.4, 9, and R3.3
- **Finding:** Section 7.4 says every `podman cp` stream must contain exactly
  one regular file of bounded size, then says the `/bin/bash` stream is
  discarded unread and only its exit status matters. Those contracts are
  mutually exclusive. Podman permits the copied source to be either a file
  or a directory and streams either as tar, so exit 0 alone does not prove
  that `/bin/bash` is a usable shell. It also leaves executable mode and
  final-component symlink handling undefined.
- **Resolution:** Superseded: the shell probe no longer exists (§7.4,
  MIR-034). With `--user` passed numerically (§7.1) the shell
  observation defended nothing security-relevant, and an image without a
  usable `/bin/bash` now fails at launch with the runtime's own error —
  an acceptable diagnostic for a project definition the user has already
  trusted. The tar-stream contract analysis in the finding is retained
  for any future feature that parses `podman cp` output.
- **Done when:** Nothing to implement.

### MIR-038 — “One fact per image identity” lacks a duplicate-record rule

- **Status:** Resolved 2026-07-30 (narrows the 2026-07-29 merge rule)
- **Affects:** §2 normalized types, §5, §9, R5.2–R5.4
- **Finding:** `ImageFact` promises exactly one fact per image ID and
  retention relies on that uniqueness. The apple/container text says to
  group one-ref records by ID, while the Podman text describes one output
  record at a time. Neither defines what happens when duplicate records for
  one ID disagree on `created` or `labels`, repeat refs, mix dangling and
  named records, or arrive in a different order. The normalized
  `dict[str, str]` label type is also not backed by key/value validation.
  An implementation can therefore duplicate retention units or
  arbitrarily choose ownership data while still appearing to follow the
  per-backend paragraphs.
- **Resolution:** Validation is shared; merging is scoped to the one
  backend whose format needs it. Both normalizers validate IDs as
  64-character lowercase hex and refs/label keys/values as NUL-free
  valid UTF-8 (keys non-empty), aborting the operation on violation, and
  drop dangling records so a fact's `refs` is always non-empty.
  apple/container — the only format that legitimately yields several
  records per image ID (one ref per record) — merges: refs unioned,
  deduplicated, and sorted lexicographically so output is independent of
  record order, and any disagreement between records for one ID on
  `created` or a label value aborts as malformed engine output. Podman
  emits one record per identity, so a duplicate `Id` in its output
  aborts as malformed rather than being merged. Facts are emitted sorted
  by `id`. Recorded in §5; tests in R5.10.
  **Amended 2026-07-30 (fixture capture):** the "one record per
  identity" premise is false on real 5.4.2 — a multi-tagged image is
  emitted as one byte-identical record per tag, each carrying the full
  `Names` array (pinned by the recaptured
  `tests/fixtures/podman-5.4.2-images.json`). The Podman rule is
  therefore: exactly-identical duplicate records for one `Id` collapse
  to one fact; records for one `Id` that disagree in any normalized
  field abort as malformed engine output.
- **Done when:** `test_image_fact_accumulator` (R5.10) covers the
  apple/container cases — reordered duplicates, repeated refs,
  conflicting timestamps, conflicting labels, mixed dangling/named
  records; every accepted permutation yields the same single
  `ImageFact`, every ambiguous ownership case aborts — plus the Podman
  duplicate-`Id` abort, with shared-validation rejection cases under
  both backends.

### MIR-039 — The declared Debian/amd64 support scope is not enforced or qualified

- **Status:** Resolved 2026-07-29
- **Affects:** Scope, §2 selection, §§4, 8–10, §12, and the selection tests
- **Finding:** The support scope says Linux means Debian 13 on amd64 only,
  while `select_runtime()` accepts every `sys.platform.startswith("linux")`
  host and readiness checks neither distribution nor architecture.
  Fedora, Ubuntu, arm64, and SELinux-enforcing systems therefore select the
  production backend with no warning even though later sections call them
  out of scope or unsupported. The document does explicitly choose
  non-detection for SELinux, but it never says whether the Debian and amd64
  boundaries are enforceable gates or qualification statements only.
- **Resolution:** Debian 13/amd64 is a **qualification matrix, not an
  enforced gate**. jms performs no distribution or architecture detection
  anywhere — consistent with the existing SELinux and NFS non-detection
  stances — and other local rootless Linux configurations select the
  Podman backend and run unqualified, with no warning (a warning would
  require exactly the detection being declined). What *is* refused stays
  refused: non-Linux/non-macOS platforms, uid 0 on Linux, and remote
  Podman. Scope, §2 selection, and §§10, 12 now use the shared “refused”
  versus “unqualified but allowed” vocabulary. Recorded in Scope, §§2, 9,
  10, 12; test named in §9's selection tests.
- **Done when:** Selection/readiness tests
  (`test_linux_scope_is_qualification_not_gate`) cover Debian amd64,
  another distro, arm64, and the already-decided SELinux non-gate. README,
  SECURITY.md, CLI docs, release checklist, and §12 use the same “refused”
  versus “unqualified but allowed” vocabulary.

### MIR-040 — Ambient Podman configuration can change the isolation and mount contract

- **Status:** Resolved 2026-07-30
- **Affects:** §§2, 4, 7.1–7.2, 8–10, R7.4, R7.7, R8.1–R8.4
- **Finding:** The proposal treats explicit `--userns` and
  `--security-opt label=disable` as sufficient to establish the Linux
  boundary, but Podman also consumes system/user `containers.conf`,
  `containers.conf.d`, `mounts.conf`, and configuration-selecting
  environment variables. Those inputs can automatically mount host
  directories (commonly secrets), inject host environment, select an
  unconfined seccomp profile or different capability/device defaults, and
  install OCI hooks. Podman's own manual says `mounts.conf` entries are
  automatically mounted by `podman run`:
  <https://docs.podman.io/en/v5.4.2/markdown/podman.1.html#configuration-files>.
  The design overrides the ambient user-namespace default only. It neither
  neutralizes nor validates the other inputs, yet §8 promises Podman's
  default seccomp/capability boundary and says deliberately mounted data is
  the exposure surface. `LaunchPlan.mounts` and the argv goldens cannot
  observe implicit mounts or environment added after serialization.
- **Resolution:** The third model: the effective Podman configuration is
  **trusted host input**, for `run` and `build` alike. jms's boundary
  defends against the agent inside the container, not against the
  invoking user's own host configuration; `containers.conf` and its
  drop-ins, `mounts.conf`, `storage.conf`, `policy.json`/`registries.conf`,
  configuration-selecting environment variables, and OCI hooks belong to
  the invoking user and sit in the same trust class as the `podman`
  binary and the kernel. jms neither neutralizes nor validates them —
  consistent with the SELinux and NFS non-detection stances. The two
  explicit overrides stay (`--userns`, `--security-opt label=disable`)
  because they pin the mapping and labeling contract jms itself relies
  on; they are qualified argv, not an audit of the rest. Remote detection
  (`host.serviceIsRemote`) also stays — a remote service breaks path
  semantics, not just configuration trust. §8's boundary claims are
  narrowed to Podman's seccomp/capability boundary *as configured on the
  host*, and `LaunchPlan.mounts` and the argv goldens are documented as
  pinning jms-requested mounts only. Recorded in §8; doc wording in §10.
- **Done when:** SECURITY.md and README name the ambient-configuration
  trust assumption in §8's terms; no neutralization or validation code
  exists; the R8.4 documentation review covers the statement. The
  originally proposed acceptance matrix is not built — under the trusted
  model there is no enforced policy to prove.

### MIR-041 — `--pull=missing` is not qualified and the missing-base behavior does not exist

- **Status:** Resolved 2026-07-30
- **Affects:** §§3, 6, 9, 11, R3.7, `scripts/qualify-podman.sh`
- **Finding:** The normative design says every Podman project build uses
  `--pull=missing`, that a present short-name base never contacts a
  registry, and that an absent base fails quickly and non-interactively
  with an existing jms-specific hint. The checked-in qualification script
  proves a different command: all three registries.conf cases use
  `--pull=never`. Current `run_build()` has only the generic context-rule
  note and no missing-base classifier or hint. With `--pull=missing`, an
  absent `jmscontainers-base:latest` is eligible for short-name expansion,
  registry access, and (depending on registries.conf and TTY state) a
  prompt. The claimed clean-store external-base example is also
  `FROM fedora:latest`, not a fully qualified reference as §3 calls it.
  Thus neither side of R3.7 is established by the recorded evidence.
- **Resolution:** Project builds keep `--pull=missing`; the design gains
  a non-interactivity rule and an evidence-keyed hint, and the false
  qualification claim is removed. (a) Every build runs with stdin
  redirected from `/dev/null`, so no engine prompt — short-name or
  otherwise — can hang a build; beyond that, short-name resolution
  follows the host's `registries.conf`, which is trusted host input
  (MIR-040). (b) jms never parses Containerfile syntax to find the base.
  The missing-base classifier is post-hoc: when a project build fails,
  jms calls `image_exists("jmscontainers-base:latest")`; only when the
  base is observed absent is the existing "run `jms build` for the base
  image first" hint appended after `CONTEXT_NOTE`. The hint is advisory
  and keyed to observed evidence (the failed build plus the observed
  absence). (c) External bases are unrestricted: docs recommend fully
  qualified `FROM` references and `examples/clean-slate` moves to one
  (`registry.fedoraproject.org/fedora:latest`), but nothing is enforced.
  (d) The "qualified across three registries.conf variants" statement is
  removed; qualification with the production argv happens in §9's
  FROM-resolution check, and `scripts/qualify-podman.sh`'s `--pull=never`
  runs do not count (the script is deleted — MIR-049). Recorded in
  §§3, 6.
  **Amended 2026-07-30 (MIR-055):** the "fails fast" claim is dropped —
  `--pull=missing` attempts a pull for an absent base per the host's
  `registries.conf`, so only non-interactivity is guaranteed — and the
  hint's wording is conditional ("if this project builds from it…"),
  since jms cannot identify shared-base projects without the
  Containerfile parsing this resolution declines.
- **Done when:** The integration FROM-resolution check executes the exact
  production argv with `--pull=missing`: base present under network
  denial succeeds with no registry contact; base absent fails
  non-interactively with the conditional missing-base hint; a
  clean-store standalone project fetches its fully qualified external
  base. The example and README follow the fully-qualified
  recommendation, and builds provably run with stdin from `/dev/null`.

### MIR-042 — Podman image removal can delete unselected dangling parents

- **Status:** Resolved 2026-07-30
- **Affects:** §§2, 5, 9, R5.4, R5.7, R5.9
- **Finding:** The document says cleanup “untags per jms-owned ref” and
  never deletes anything else by identity. The specified
  `podman image rm --ignore REF` does more: Podman removes dangling parent
  images by default. Its 5.4.2 manual explicitly provides `--no-prune` to
  suppress that behavior:
  <https://docs.podman.io/en/v5.4.2/markdown/podman-rmi.1.html#no-prune>.
  Extra parent removal is outside the enumerated schedule, is not reported
  through one `RemovalResult` per selected ref, and may delete an
  unlabelled image that jms never classified as owned.
- **Resolution:** `--no-prune`. Podman's `remove_image` argv becomes
  `podman image rm --ignore --no-prune REF`; the ownership model is not
  expanded — dangling parents are outside it (skipped at enumeration by
  rule, §5) and are never removed as a side effect of an untag.
  apple/container's delete-by-ref cascade behavior is undocumented; the
  R5.4 survivor-set acceptance run on macOS determines it, and a
  discovered cascade is a qualification failure to resolve before
  release, not a silently accepted behavior. Recorded in §5.
- **Done when:** Real-runtime tests build a graph containing selected and
  unselected parents plus jms and non-jms aliases, remove one scheduled
  ref, and assert the exact survivor set on Podman and apple/container.
  Golden removal argv pins `--no-prune`; R5.4/R5.9 pin the behavior.

### MIR-043 — apple/container does not have one proven absence diagnostic for all removals

- **Status:** Resolved 2026-07-30
- **Affects:** MIR-035, §§2, 5, 9, R5.7, R5.9
- **Finding:** MIR-035 says apple/container maps “its one exact not-found
  diagnostic (the same match `image_exists` already performs today)” to
  `removed` for `stop_container`, `remove_container`, and `remove_image`.
  The existing match is specifically `Error: image not found: <ref>` from
  image inspection. The proposal supplies no evidence that stop/delete of
  a container, or image deletion rather than inspection, uses that text,
  exit code, or output stream. It also leaves a failed
  `RemovalResult.detail` undefined when stderr is empty but stdout contains
  the diagnostic, despite requiring `detail` to be non-empty for every
  failure.
- **Resolution:** The borrowed inspect-image diagnostic is dropped;
  apple/container removal operations classify absence by **post-failure
  existence recheck**, not output matching. On a nonzero exit,
  `remove_image` re-checks `image_exists(ref)` and `remove_container`
  re-checks `ps()` for the ID; if the resource is absent, the outcome is
  `removed` — the goal state holds, however the CLI spelled its
  complaint. A `failed` `stop_container` is superseded by a subsequent
  successful `remove_container` for the same ID and dropped from the
  aggregate (the forced delete is authoritative, §5). A genuine
  failure's `detail` quotes stderr, falling back to stdout, falling back
  to the fixed text `no diagnostic output (exit N)` — non-empty in every
  failure, terminal-safe throughout (invalid UTF-8 is handled by the
  existing quoting). Podman is unchanged (`--ignore` at the engine). No
  stability assumption about apple/container's error text remains
  anywhere. Recorded in §§2, 5; MIR-035's mechanism is amended
  accordingly.
  **Amended 2026-07-30 (MIR-052):** `stop_container` rechecks `ps()`
  too, so absence classifies as `removed` on all three operations; and
  the recheck runs inside the operation's non-raising envelope — a
  recheck that itself fails leaves the outcome `failed` with the
  original diagnostic plus an appended recheck-failure note, so no
  exception escapes into `execute_removal_schedule()`.
- **Done when:** R5.9 covers, per operation and backend: success,
  vanished-before, failed-then-recheck-absent, failed-with-resource-
  present (stays `failed`), stdout-only, and empty-output cases; the
  stop-superseded-by-remove rule has a named case; a manual macOS race
  test proves idempotent cleanup.

### MIR-044 — The checked-in fixtures do not cover the schemas the normalizers promise

- **Status:** Resolved 2026-07-30
- **Affects:** §§5, 9, tests/fixtures, R5.2, R5.5, R5.8, R7.13
- **Finding:** `podman-5.4.2-images.json` contains one named Fedora record;
  it contains no null/empty `Names`, `<none>` spelling, dangling image,
  jms ownership labels, or multi-name identity. Nevertheless §5 calls
  those accepted/skipped fixture-backed variants. The Podman `ps` fixture
  predates `jms.container=launch`, so it cannot prove the new provenance
  predicate, and the inspect-mount fixture required by the leak-sweep
  contract is not checked in. The qualification script attempts to create
  richer image output, but the committed fixture and its README do not
  contain that result. Strict parsing against a narrow happy-path capture
  risks rejecting normal engine output or testing invented variants.
- **Resolution:** Fixture capture becomes a specified phase-1/2
  deliverable with a provenance contract, and §5 stops implying the
  current captures already contain the variants. Every fixture file gets
  a one-command reproducible capture recipe recorded in
  `tests/fixtures/README`, executed on the qualified engine versions,
  preserving whole records for: Podman images — named, multi-named,
  unlabeled, jms-labelled, dangling, and `<none>`-named; Podman `ps` —
  inherited image labels, the `jms.container=launch` override, marker
  absence, running and exited states; the Podman `inspect` mounts
  fixture the leak sweep requires; and the apple/container 1.2.0
  equivalents. Synthetic malformed cases live in test code, never in
  fixture files. A normalizer lands only after its fixtures do — this is
  the ordering rule in §11 phase 2 (resequenced by MIR-054 so no
  normalizer work precedes capture). Recorded in §§5, 11.
  **Amended 2026-07-30 (fixture capture):** the `<none>`-named variant is
  dropped from the capture list — real 5.4.2 JSON spells danglings as
  `"Names": null` and never emits a `<none>` name (recorded in
  `tests/fixtures/README`), so `<none>` filtering stays a synthetic case
  in test code, consistent with the done-when list below.
- **Done when:** Fixture provenance is reproducible from one documented
  command; Podman images cover named, multi-named, unlabeled, and dangling
  records; Podman and apple/container container fixtures cover inherited
  image labels, the launch override, marker absence, running/exited
  states, and mount metadata; the Podman inspect fixture exists. Each
  accepted normalizer branch is reached by a captured record.

### MIR-045 — The normalized fact types are stricter than their specified validators

- **Status:** Resolved 2026-07-30
- **Affects:** §§2, 5, 9, MIR-038, R5.2–R5.5, R5.10
- **Finding:** `ContainerFact` promises `dict[str, str]`, but `ps()`
  validates only that `labels` is a dict; non-string, empty, NUL-bearing,
  or otherwise invalid keys/values cross the backend boundary and feed the
  destructive ownership predicate. Its ID is documented as full and
  untruncated, while shared validation checks only string/NUL and the
  Podman paragraph separately claims 64 lowercase hex. `ImageFact.created`
  has no complete validity contract: negative/boolean/out-of-range Podman
  integers and timezone-less, non-finite, or out-of-range apple/container
  dates are not addressed. Finally, apple/container duplicate merging says
  conflicting values fail but does not say whether `{}` and
  `{"jms.project": "x"}` conflict or are unioned; arbitrary union would
  synthesize ownership data absent from one record.
- **Resolution:** The validators are specified completely so the types
  and prose agree; details in §5. ID forms: Podman image and container
  IDs are 64-character lowercase hex; apple/container image IDs are
  64-character lowercase hex (asserted equal to the descriptor digest);
  apple/container container IDs are non-empty NUL-free valid-UTF-8
  strings (that engine's ID is a name — no truncated hex form exists).
  Labels, both fact types, both backends: keys non-empty NUL-free
  valid-UTF-8 `str`, values NUL-free valid-UTF-8 `str`; any non-string
  key or value aborts. `created`: an `int` that is not a `bool`
  (Python's `bool` subclasses `int` and is rejected explicitly) in
  `[0, 253402300799]` (year 9999); out-of-range aborts. apple/container
  `creationDate` must be strict ISO-8601 with an explicit UTC offset;
  naive, unparseable, or out-of-range dates abort, and the parsed value
  converts into the same epoch range. Duplicate apple/container records
  for one ID must carry **exactly equal** label maps — a key present in
  one record and absent in another is a conflict and aborts; no union,
  ownership data is never synthesized. Recorded in §5.
- **Done when:** The normalized type definitions and parser prose agree.
  Cross-backend malformed matrices cover every field and boundary,
  including missing-vs-present duplicate labels and time limits, and no
  command can receive a value outside the annotated normalized type.

### MIR-046 — `LaunchPlan.user` and `LaunchPlan.root` can disagree

- **Status:** Resolved 2026-07-30
- **Affects:** §2 protocol, §7.1, §9, R7.1–R7.5
- **Finding:** `LaunchPlan` stores both `user` (`"isolation" | "root"`)
  and `root: bool`. The apple/container serializer consumes `user`, while
  Podman derives security-sensitive `--user` and `--userns` values from
  `root`. No invariant requires the two fields to agree, and Class A
  serializers are public pure functions that tests will construct
  directly. One logical plan can therefore serialize as root on one
  backend and isolation on the other, violating the shared-plan premise.
- **Resolution:** `LaunchPlan.root` is deleted. `user: "isolation" |
  "root"` is the single user-mode authority, validated at construction
  (any other value is rejected before argv creation, in `__post_init__`).
  The apple/container serializer passes it verbatim as `--user`; the
  Podman serializer derives both security spellings from it —
  `"isolation"` → `--user 1000:1000` + `--userns=keep-id:uid=1000,gid=1000`,
  `"root"` → `--user 0:0` + `--userns=host` (§7.1). Contradictory state
  is unrepresentable. Recorded in §2 (type definition), §7.1.
- **Done when:** Contradictory state is unrepresentable or rejected before
  argv creation; direct serializer tests cover both modes and attempted
  invalid construction; the launch goldens derive from the same plans for
  both backends.

### MIR-047 — Ref-prefix matching is not provenance and ref deletion has a retag race

- **Status:** Resolved 2026-07-30
- **Affects:** §§3, 5, 9, R3.5, R5.4, R5.7
- **Finding:** The document promises that a non-jms alias of a jms-labelled
  image survives. That is only true when the alias does not normalize to a
  jms prefix. A user-created alias such as
  `docker.io/library/jmscontainers-<slug>-<pid-prefix>:manual` is normalized by
  `local_name()` and selected even though jms did not create it; stripping
  `docker.io/library/` broadens that destructive namespace beyond Podman's
  `localhost/` build result. Conversely, the proposed label is image-wide
  and cannot prove which actor created an individual alias. There is also
  a race between enumerating `(id, ref)` and deleting `ref`: another
  process can move that mutable ref to a different image, after which jms
  removes an image name it never evaluated. The vanished-resource rule
  does not cover ref rebinding.
- **Resolution:** Three decisions. **Reserved grammar:** a ref is
  jms-reserved iff its `local_name()` normalization begins with a jms tag
  prefix (`jmscontainers-…`). All matching aliases are reserved
  user-visible state — jms tracks no per-ref provenance, and a user who
  manually tags into the reserved namespace has handed that alias to
  jms; the README documents the reserved namespace (§10).
  **Narrowed normalization:** Podman's `local_name()` strips exactly
  `localhost/` — the only qualification its production builds emit — and
  nothing else; the speculative `docker.io/library/` strip is removed,
  so a registry-qualified manual alias falls outside the reserved
  namespace and survives. apple/container's existing strip is unchanged
  (it matches that engine's own qualification of stored names).
  **Concurrency:** same-store concurrent mutation during cleanup is an
  explicit documented limitation — jms neither locks nor rechecks
  identity between enumerating `(id, ref)` and untagging `ref`; the
  residual retag race is accepted and named in the README. §5's survival
  claim is narrowed to: an alias **outside the reserved namespace**
  survives. Recorded in §§3, 5.
- **Done when:** Tests cover matching and nonmatching manual aliases
  under each backend's stripped qualification, multiple aliases on one
  ID, and (as a documented-limitation test, not a safety claim) a ref
  rebound between enumeration and removal. README documents the reserved
  namespace and concurrency limitation; §5's survival claim is the
  narrowed form.

### MIR-048 — Background GC and explicit purge need different failure contracts

- **Status:** Resolved 2026-07-30
- **Affects:** §§2, 5, 9, 11, R5.4, R5.7
- **Finding:** Section 5 requires project GC to warn and never fail the
  successful build/launch, while `clean` and `revoke --purge-images` must
  aggregate failures and exit 1. Today both retention and revoke purge call
  `gc_project_images()` with only a `keep` value. The proposal changes
  removal results but does not specify a return type or policy parameter
  that lets the caller enforce the two outcomes. It discusses per-untag
  failures only; an `image_facts()` execution/schema failure occurs before
  a schedule exists and would still raise through background GC, contrary
  to “never fails the surrounding build/launch.” A readiness failure after
  revocation is specified, but enumeration and partial-purge failures are
  not connected to the final aggregate.
- **Resolution:** Selection and execution split, policy assigned per
  call site. `image_removal_schedule(...)` enumerates and selects
  (readiness, `image_facts()`, ownership/retention) and raises on any
  failure; `execute_removal_schedule(schedule)` performs the removals,
  never raises, and returns the ordered `(ref, RemovalResult)` list.
  Policy: **background GC** (post-build/launch retention) wraps both
  steps — any raise, including an enumeration failure, becomes one
  stderr warning and the already-successful build/launch result stands;
  **`clean` / `clean --all` / `revoke --purge-images`** let schedule
  failures raise (exit 1) and aggregate execution failures into the
  exit-1 report. Revocation commits before the purge begins, so every
  purge-path failure — readiness, enumeration, or removal — keeps the
  "trust was revoked, but image purge failed" split. Per-item success
  lines print as they happen and remain valid when a later removal
  fails; no overall summary claims success while the aggregate holds
  failures. Recorded in §5; tests extend R5.7.
- **Done when:** Tests inject readiness, enumeration/normalization, and
  every removal-position failure into every caller. Background GC always
  returns the already-successful build/launch result with warnings;
  explicit cleanup/purge attempts every schedulable operation, reports one
  aggregate, and exits 1; revocation remains durable in every purge
  failure case.

### MIR-049 — Removing nested CI did not specify the retained local nested harness

- **Status:** Resolved 2026-07-30
- **Affects:** MIR-033, §§9–11, R3.7, R4.4, R7.2–R7.14
- **Finding:** MIR-033 was superseded by deleting the CI job, but §§9–11
  still make a “local nested harness” a phase-2 integration dependency.
  No outer image, invocation, privilege/device mounts, subordinate-ID
  plumbing, cancellation behavior, or artifact location is specified.
  The existing `scripts/qualify-podman.sh` is not the two-tier integration
  harness described in §9, tests `--pull=never` rather than the production
  pull policy, and ends with `exit 0` even when its `FAILCOUNT` is nonzero.
  It therefore cannot gate implementation or release as written. This is
  the executable-contract portion of MIR-033 resurfacing under a different
  name.
- **Resolution:** The local nested harness is removed as a specified
  artifact and as a gate — the resurfaced half of MIR-033 resolves the
  same way as the first: Linux qualification for 1.1.0 is real-host
  only. The gates are (a) both integration tiers (§9) run green on a
  real Debian 13 amd64 host with a fresh non-root, non-1000 user, and
  (b) the §10 clean-host install walkthrough. Whatever environment a
  developer uses day-to-day is their business and gates nothing.
  `scripts/qualify-podman.sh` is deleted: its registries.conf coverage
  is superseded by the production-argv FROM-resolution check
  (MIR-041, §9), and its `exit 0`-despite-failures behavior made it
  unusable as a gate anyway. §§9–11 no longer mention a nested harness.
  Recorded in §§9, 11, 12.
- **Done when:** No nested harness and no `scripts/qualify-podman.sh`
  exist in the tree; §11 phase 2 and the release checklist name the
  real-host integration run and the walkthrough as the only Linux gates.

### MIR-050 — `graphDriverName` does not prove the storage stack is usable

- **Status:** Resolved 2026-07-30
- **Affects:** §§4, 9, 10, R4.4
- **Finding:** Readiness treats a present `store.graphDriverName` as proof
  that storage initialized, and §10 says unsupported NFS/distributed-home
  failures surface through that check. `podman info` returning a driver
  name proves that metadata was read, not that image extraction, layer
  creation, bind mounting, or the configured graph root works. Podman's
  rootless documentation explicitly calls NFS and other distributed
  filesystems unsupported:
  <https://docs.podman.io/en/v5.4.2/markdown/podman.1.html#note-unsupported-file-systems-in-rootless-mode>.
  The proposal separately rejects a create/run probe, so the stronger
  readiness and diagnostic claims have no specified evidence.
- **Resolution:** Narrowed, no functional check added (§4's create/run
  probe rejection stands). Readiness claims only that `podman info` and
  its required metadata are readable — a present `store.graphDriverName`
  proves Podman initialized and reported its storage configuration,
  nothing more. Storage-operation failures (image extraction, layer
  creation, bind mounting, an NFS-broken graph root) surface at the
  first build or launch with Podman's own stderr, where the
  evidence-keyed hint machinery applies — or at `podman info` itself
  when storage initialization fails outright. §10's NFS wording changes
  to match: documented, not detected, surfacing at build/launch rather
  than "via the storage check". Recorded in §§4, 10; R4.4 reworded.
- **Done when:** §4, the README limitation, and R4.4 state the same
  enforceable property; tests distinguish missing/malformed driver metadata
  from a later storage-operation failure; every hint is keyed to evidence
  actually observed.

### MIR-051 — The lazy runtime accessor and the `RUNTIME` pseudo-global are inconsistent

- **Status:** Resolved 2026-07-30
- **Affects:** §2, §9 selection/laziness tests, implementation phase 1
- **Finding:** The only defined cache/accessor pair is `_RUNTIME` and
  `runtime()`, but the seam pseudo-code reads `RUNTIME.exe` and
  `RUNTIME.install_hint`, and the migration rule says literals become
  `[RUNTIME.exe, ...]`. No `RUNTIME` binding or lifetime is defined.
  Introducing one at import/startup would violate the central lazy-selection
  guarantee; leaving it undefined makes the snippets unusable; repeatedly
  resolving it inside serializers obscures which backend owns a call.
  This is especially consequential in `runtime_run()`, which is both the
  first selection trigger and the backend methods' process seam.
- **Resolution:** One spelling, one ownership rule; there is no
  `RUNTIME` global. The only cache/accessor pair is `_RUNTIME` /
  `runtime()`. Public free functions that touch the runtime acquire
  `backend = runtime()` once at their boundary and use that object for
  every backend decision in the operation, so one operation observes one
  backend instance. `runtime_run()` calls `runtime()` only for its
  argv[0] assertion and the `FileNotFoundError` install hint — selection
  is side-effect-free (§2), so a first selection happening there is
  harmless and still lazy. The migration rule reads: inside a free
  function holding `backend`, literals become `[backend.exe, ...]`. The
  §2 seam snippets are rewritten in this spelling. Tests install and
  reset the backend by assigning `JMS._RUNTIME`; the laziness tests
  count accessor calls as well as subprocess calls; no module-level
  expression selects a backend, and pure commands never call the
  accessor. Recorded in §2.
- **Done when:** Every pseudo-code identifier is defined; no module-level
  expression constructs/selects a backend; one operation observes one
  backend instance; pure commands never call the accessor; and the
  selection/laziness tests instrument accessor-call count as well as
  subprocess count.

### MIR-052 — apple/container removal rechecks can raise inside the never-raises path

- **Status:** Resolved 2026-07-30
- **Affects:** MIR-035/043, §§2, 5, R5.9
- **Finding:** The removal operations promise a non-raising
  `RemovalResult` channel and `execute_removal_schedule()` "never
  raises", but MIR-043's absence classification calls `image_exists()`
  and `ps()` — both of which raise on hard errors or malformed engine
  output — from inside that channel. A failed removal whose recheck also
  failed would therefore raise through the non-raising path, and the
  design defined no terminal-safe `RemovalResult` for that case.
  Separately, "absence counts as removed on both backends" was
  established by recheck only for `remove_container` and `remove_image`;
  `stop_container` of an absent container on apple/container had no
  recheck and would classify `failed`, contradicting the general claim.
- **Resolution:** Two rules, recorded in §2. (a) All three
  apple/container removal operations recheck on a nonzero exit:
  `stop_container` and `remove_container` re-check `ps()` for the ID,
  `remove_image` re-checks `image_exists(ref)`; absence classifies as
  `removed` uniformly. The failed-stop-superseded-by-remove rule
  (MIR-043) is unchanged and now covers only genuine stop failures.
  (b) The recheck runs inside the operation's non-raising envelope: any
  recheck failure — its process fails, `image_exists` classifies a hard
  error, or the `ps()` normalizer aborts — is caught inside the removal
  operation; the outcome stays `failed` with the original diagnostic in
  `detail` and a terminal-safe `; recheck failed: <quoted>` note
  appended. No exception escapes a removal operation, so
  `execute_removal_schedule()` keeps its never-raises contract.
- **Done when:** R5.9 adds, per apple/container operation: an absent-stop
  case classifying `removed` via the `ps()` recheck, and injected
  recheck failures (nonzero recheck process, malformed `ps()` output)
  that leave `failed` with the original diagnostic plus the appended
  note, with no exception reaching the caller.

### MIR-053 — Null and missing label maps have no decided normalization

- **Status:** Resolved 2026-07-30
- **Affects:** §5, MIR-044/045, R5.2, R5.5
- **Finding:** The normalizers are strict and fail-closed, and MIR-044's
  required fixture variants include unlabeled records, but the schemas
  define `Labels` only as a map: whether Podman's `"Labels": null` — its
  normal spelling for an unlabeled image — or an absent key normalizes
  to `{}` or aborts was undecided. An abort would break enumeration on
  essentially every real store (unlabeled images are ordinary), and the
  answer feeds the destructive ownership predicate. The checked-in image
  fixture contains a single labelled record, so nothing pinned the
  decision either way.
- **Resolution:** Both backends, both fact types: an absent or JSON-null
  label map normalizes to `{}` — an unlabeled image or container is
  normal engine output, never an error — and any other non-map value
  aborts as malformed. The MIR-045 key/value grammar applies to entries
  of present maps. The unlabeled and dangling fixture records MIR-044
  requires pin the null spelling at capture time. Recorded in §5.
- **Done when:** Normalizer tests cover null, absent, and non-map
  `Labels` for images and containers on both backends; the captured
  fixtures contain at least one null-label record.

### MIR-054 — Phase 1 implements normalizers before phase 2 captures their fixtures

- **Status:** Resolved 2026-07-30
- **Affects:** §11, MIR-044
- **Finding:** §11 phase 1 said to implement the Podman backend "argv
  assembly and normalizers", while the fixture set the normalizers must
  be built against was a phase-2 deliverable — directly contradicting
  MIR-044's ordering rule that a normalizer lands only after its
  fixtures. Following the plan in order would build the parsers against
  the known-insufficient checked-in captures.
- **Resolution:** §11 is resequenced. Phase 1 is the behavior-neutral
  seam, selection/readiness policy, argv assembly, and goldens only
  (plus fixture-independent conformance cases such as version-line
  parsing and mount grammar). Phase 2 begins by capturing and approving
  the complete fixture set per the MIR-044 provenance contract on the
  qualified engines, then implements the normalizers, removal
  classification, parametrized fakes, and the fixture-dependent
  conformance suite, then proceeds to integration. Recorded in §11.
- **Done when:** §11's phases match MIR-044's ordering rule; no
  normalizer or fixture-dependent test work is listed before fixture
  capture.

### MIR-055 — The missing-base behavior overclaims failure speed and hint precision

- **Status:** Resolved 2026-07-30
- **Affects:** §§3, 6, 9, MIR-041, R3.7
- **Finding:** The design asserted an absent base "fails fast", but
  `--pull=missing` explicitly attempts a pull when the image is absent
  (podman-build(1) pull policy), so the failure may include short-name
  registry contact and network waits; stdin from `/dev/null` guarantees
  only non-interactivity. And because jms never parses the
  Containerfile, the "run `jms build` for the base image first" hint is
  appended to *any* failed project build whenever the shared base
  happens to be absent — including standalone external-base projects
  failing for unrelated reasons — where an unconditional imperative is
  simply wrong advice.
- **Resolution:** The speed claim is dropped everywhere (§§3, 6, 9,
  R3.7, and MIR-041's gate): the guarantee is a non-interactive failure,
  with no latency claim. The hint's wording becomes conditional —
  "note: the shared base image jmscontainers-base:latest is not present;
  if this project builds from it, run `jms build` in the base directory
  first" — advisory, keyed to the observed absence, and explicitly
  conditional because jms cannot identify shared-base projects without
  Containerfile parsing, which stays declined (MIR-041). Recorded in
  §§3, 6, 9.
- **Done when:** No "fails fast" claim remains; R3.7 asserts
  non-interactivity and the conditional hint; the hint wording is pinned
  by a unit test.

### MIR-056 — The real-host integration contract left tooling choices open

- **Status:** Resolved 2026-07-30
- **Affects:** §9 (integration tiers, leak sweep), R7.13, release
  checklist (§10)
- **Finding:** §9 named two tiers, "network isolation", a fresh non-1000
  user, and a tolerated inspect race without specifying: how a tier is
  selected; what concretely denies the network (an `unshare --net`
  wrapper cannot work — unprivileged network namespaces need a new user
  namespace, which either maps the invoker to euid 0, tripping jms's
  uid-0 refusal, or single-maps the invoking UID, destroying the
  subordinate-ID ranges rootless Podman needs); what the test user
  requires beyond a non-1000 UID; and which `inspect` diagnostics
  identify the vanished-container race — the latter via stderr matching,
  the very technique MIR-043 removed elsewhere.
- **Resolution:** Recorded in §9. **Tier selection:** one positional
  argument — `scripts/integration.sh a|b|all`, default `all`; tier B
  assumes tier A's base image already exists. **Network denial:** a
  harness-owned nftables rule dropping all non-loopback output traffic
  whose socket UID is the test user's, installed via sudo immediately
  before the FROM-resolution check and removed in the EXIT trap; a
  failure to install or remove it is a harness failure, distinct from a
  test failure. Namespace wrappers are rejected for the reasons in the
  finding. **Test-user preconditions:** created with `adduser` (which
  provisions the 65536-ID subordinate ranges readiness requires),
  non-1000 UID and non-1000 primary GID, fresh home on a local
  filesystem with no prior container state, tiers run from a real login
  session (ssh) so `pam_systemd` provides the `XDG_RUNTIME_DIR` and
  user D-Bus session rootless Podman's networking needs. **Inspect
  race:** stderr matching is dropped for the MIR-043 rule shape — on an
  `inspect` failure the sweep runs `podman container exists <id>`:
  exit 1 classifies the ID as gone (not a leak); exit 0 or any other
  exit aborts as a sweep failure.
- **Done when:** §9 contains each decision; the sweep unit tests cover
  all three `container exists` recheck outcomes; the release
  checklist's Linux integration run follows the specified user and
  denial setup.

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
| `launch_plan` (`bin/jms:985`) | `container run` argv; no user-namespace flags (virtiofs squashes UIDs); no hostname flag; no SELinux concerns |
| `container_records` (`bin/jms:1209`) | `container list --all --format json` schema: `id`, `configuration.labels` |
| `cmd_clean` (`bin/jms:1274`) | `container stop` / `container delete --force` / `container image delete` |

Everything else — trust store, fingerprinting, discovery, manifest parsing,
path validation, consent — is runtime-agnostic already and must not move.

Two platform notes:

- `canon()` execs `/bin/realpath` (`bin/jms:114`). The actionable
  missing-binary diagnostic lives in `canon()` itself: `subprocess.run`
  raises `FileNotFoundError` when the binary is absent, and `canon()`
  converts it to a terminal-safe "cannot canonicalize paths: /bin/realpath
  not found" failure with the coreutils hint (Debian 13:
  `sudo apt install coreutils`). The check is shared code, so macOS gets
  the same diagnostic; it sits below the runtime seam, so pure commands
  never select a backend because of it.
- The path rules in `runtime_path()` (no NUL, valid UTF-8, no `,` or `=`)
  are stricter than Podman requires but remain correct for Podman's
  `--mount` grammar, which is also comma/equals-delimited. Keep them
  identical on both backends so error behavior does not fork.

---

## 2. Architecture: one `Runtime` object, selected lazily, once per process

Introduce a small backend class per runtime, selected **lazily on first
use** and cached for the rest of the process. Keep the existing free
functions as the public surface; they delegate to the selected backend for
anything backend-specific. This keeps the diff reviewable and the tests'
monkeypatching seam (`JMS.runtime_run`) intact.

Nothing runs at import time or in `main()` startup: only the
runtime-touching seams (`runtime_run`, `runtime_ready`, `image_exists`,
`image_facts`, build/launch/clean argv assembly) call the accessor.
`--version`, `inspect`, `init`, `trust list`, `trust revoke` without
`--purge-images`, and `trust prune` therefore never select a runtime and
keep working with no runtime installed, on unsupported platforms, and under
uid 0.

```python
_RUNTIME: Backend | None = None

def runtime() -> Backend:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = select_runtime()
    return _RUNTIME
```

Tests install a backend by assigning the cache directly (or via a small
install helper), with no dependence on `sys.platform` or euid at import.

```python
class ContainerBackend:            # apple/container (macOS)
    name = "container"
    exe = "container"
    install_hint = "install it with: brew install container"
    version_min = (1, 2, 0)        # exact pin, as today
    version_max = (1, 2, 0)

class PodmanBackend:               # podman (Linux, rootless)
    name = "podman"
    exe = "podman"
    install_hint = ("install the qualified package set: sudo apt install "
                    "podman uidmap passt dbus-user-session fuse-overlayfs "
                    "coreutils")     # verbatim the README command (§10)
    version_min = (5, 4, 0)        # Debian 13's packaged Podman; see §4
    version_max = None             # min-only; see §4
```

### Selection

The backend is determined entirely by the platform; there is no runtime
override variable. (`JMS_RUNTIME_ACCEPT`, the apple/container version
escape hatch, is unrelated and unchanged.)

```python
def select_runtime() -> Backend:
    if sys.platform == "darwin":
        return ContainerBackend()
    if sys.platform.startswith("linux"):
        if os.geteuid() == 0:
            fail("jms on Linux supports rootless podman only; "
                 "run as a regular user", 2)
        return PodmanBackend()
    fail("unsupported platform for jms: " + sys.platform, 2)
```

Selection is **side-effect-free** — it reads only the platform and the
euid, starts no process, prompts nothing, and writes nothing — and every
runtime-touching command calls `runtime()` as its first action, before
`resolve_operand()` or `approve()`. Every selection failure (unsupported
platform, Linux euid 0) therefore exits 2 before any consent prompt or
trust-store write. `trust revoke --purge-images` likewise selects before
mutating the store, so a selection failure leaves the store untouched.

The uid-0 refusal lives inside selection because rootless Podman is the
only qualified Linux mode: running the whole tool as uid 0 silently removes
the user-namespace boundary that stands in for the macOS VM.

Selection deliberately accepts every Linux (MIR-039): the Debian 13/amd64
scope is a qualification matrix, not a gate, and no distribution or
architecture detection exists anywhere in jms. A Fedora, Ubuntu, or arm64
host running local rootless Podman is unqualified but allowed, silently —
the selection tests (§9) pin this.

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
if not argv or argv[0] != runtime().exe:
    raise AssertionError("runtime argv must begin with " + runtime().exe)
...
except FileNotFoundError:
    fail(runtime().exe + " CLI not found; " + runtime().install_hint)
```

There is no `RUNTIME` global (MIR-051): public free functions that touch
the runtime acquire `backend = runtime()` once at their boundary and use
that object for every backend decision in the operation, so one operation
observes one backend instance; only `runtime_run()`'s assertion and hint
call the accessor directly. Every current `["container", ...]` literal
becomes `[backend.exe, ...]` where the subcommand grammar is shared, or a
call to a backend method where it is not.

`runtime_json()` keeps owning UTF-8 decoding and JSON-syntax failures, so
both backends share one malformed-output error path; each backend's
normalizer then owns shape validation on the parsed object.

### The backend protocol

The protocol is complete: a backend implements exactly the five class
attributes shown above (`name`, `exe`, `install_hint`, `version_min`,
`version_max`) plus the methods in the two tables below, and nothing else
about a backend is visible outside it.

#### Normalized types

All data crossing the protocol boundary is normalized. Command functions
never see raw runtime JSON, stderr bytes, or `subprocess` objects.

```python
Version = tuple[int, int, int]

ImageFact = tuple[               # one fact per image identity (§5)
    str,                         # id: full, untruncated image identity
    tuple[str, ...],             # refs: every name exactly as the runtime
                                 #   stores it ("localhost/…" preserved);
                                 #   always non-empty — dangling images are
                                 #   skipped by rule (§5)
    int,                         # created: Unix epoch seconds
    dict[str, str],              # labels
]

ContainerFact = {"id": str,      # full, untruncated, NUL-free
                 "labels": dict[str, str]}

Mount = tuple[bytes, str, bool]  # (host source, container target, readonly)

@dataclass(frozen=True)
class RemovalResult:             # normalized removal outcome (§5, MIR-035)
    outcome: str                 # "removed" | "failed"; absence counts
                                 #   as removed on both backends
    detail: str = ""             # terminal-safe quoted diagnostic;
                                 #   non-empty iff outcome == "failed"

@dataclass(frozen=True)
class LaunchPlan:
    name: str                            # container name (given or generated)
    user: str                            # "isolation" | "root" — the single
                                         #   user-mode authority (MIR-046),
                                         #   validated at construction; any
                                         #   other value is rejected before
                                         #   argv creation. apple/container
                                         #   passes it verbatim; Podman
                                         #   derives its numeric --user and
                                         #   its --userns variant from it
                                         #   (§7.1)
    tty: bool                            # append the runtime's --tty
    workdir: str                         # "/work" or "/work/<inner>"
    entrypoint: str                      # entry[0]
    image: str
    labels: tuple[tuple[str, str], ...]  # ordered; exactly
                                         #   (("jms.project", pid),
                                         #    ("jms.container", "launch"))
                                         #   (§5 provenance)
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

**Class A — pure serializers and parsers.** No subprocess, no filesystem,
no environment reads; deterministic functions of their arguments plus class
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

**Class B — executing queries and policy.** These own their invocation and
normalization because their success criteria are backend-specific, but
every process they start MUST cross the module-level `runtime_run()` /
`runtime_json()` — looked up as a module attribute at call time, never
`subprocess` directly and never a stored/bound reference — so the tests'
monkeypatch intercepts every execution on both backends:

| Method | Signature | Backend-specific part |
| --- | --- | --- |
| `validate_version` | `(parsed: Version, first_line: str) -> None` | policy: exact `min == max` pin (apple/container, honoring `JMS_RUNTIME_ACCEPT`) vs. min-only (Podman, §4). Runs no process; grouped here because it reads the environment |
| `ensure_started` | `() -> None` | apple/container: `system status`/`system start` dance; Podman: full `podman info --format json` validation, no create/run probe (§4) |
| `image_exists` | `(image: str) -> bool` | apple/container: exit 0 vs. the exact `Error: image not found: <ref>` stderr line; Podman: `image exists` exit 0/1, anything else a hard failure (§5) |
| `image_facts` | `() -> list[ImageFact]` | per-backend strict, fixture-backed, fail-closed normalizer (§5) |
| `ps` | `() -> list[ContainerFact]` | per-backend strict, fail-closed normalizer (§5); id/label validation (string, NUL-free, dict) shared |
| `stop_container` / `remove_container` | `(container_id: str) -> RemovalResult` | executes the backend's stop / forced-remove argv via `runtime_run(check=False)` with output captured and classifies the outcome; Podman passes `--ignore` so absence succeeds at the engine; apple/container rechecks existence after a failure, on stop too (§5, MIR-035/043/052) |
| `remove_image` | `(ref: str) -> RemovalResult` | executes the backend's image untag/remove argv the same way (Podman: `image rm --ignore --no-prune` — MIR-042) and classifies the outcome (§5, MIR-035/043) |

Removal classification (MIR-035, amended by MIR-043/052), identical rule
shape on both backends: exit 0 is `removed`; anything else is `failed`,
with the diagnostic quoted terminal-safe into `detail` (stderr, falling
back to stdout, falling back to the fixed text `no diagnostic output
(exit N)` — non-empty for every failure). Absence is folded into
`removed` inside the backend rather than classified: Podman's removal
argv passes `--ignore`, so a vanished resource exits 0 at the engine;
apple/container performs a post-failure existence recheck on all three
operations — on a nonzero exit, `remove_image` re-checks
`image_exists(ref)` while `stop_container` and `remove_container`
re-check `ps()` for the ID — and an absent resource classifies as
`removed` with no dependence on the CLI's error text. The recheck runs
inside the operation's non-raising envelope (MIR-052): if the recheck
itself fails — its process fails, `image_exists` classifies a hard
error, or the `ps()` normalizer aborts — the exception is caught inside
the removal operation, the outcome stays `failed` with the original
diagnostic in `detail`, and a terminal-safe `; recheck failed: <quoted>`
note is appended. No exception ever escapes a removal operation, so
`execute_removal_schedule()` (§5) keeps its never-raises contract.
Cleanup aggregates `failed` results and reports (§5). Command code
consumes only `RemovalResult` values: no backend branches, no
`CompletedProcess`, no raw stderr.

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
3. `JMS._RUNTIME` — tests install a backend by assigning the cache,
   bypassing selection entirely.

#### Error contract

- The only failure channel is raising `JMSException` via `fail()`, with
  terminal-safe messages (`quote()`/`terminal_safe_text()`) — runtime
  output is untrusted bytes. Methods never return error strings, raw
  stderr, or `subprocess` results to commands; `parse_version`'s `None` is
  the single sentinel, and `runtime_ready()` converts it to a failure
  immediately. One deliberate exception (MIR-035): the removal operations
  (`stop_container`, `remove_container`, `remove_image`) return a
  normalized `RemovalResult` instead of raising, so cleanup can attempt
  every removal and aggregate; their `detail` field is already
  terminal-safe and never raw stderr bytes. Recheck failures are caught
  inside the operations (MIR-052), so this channel truly never raises.
- Executing queries preserve the runtime's stderr, quoted, in the raised
  message, and where a check has a known cause they append the
  evidence-keyed hint (§4) — never a universal diagnosis.
- Malformed values in ownership-relevant fields abort the whole operation;
  they are never silently skipped (§5). Podman dangling images are skipped
  by rule, not by error.
- No backend method calls `sys.exit`, prompts, or prints, with exactly
  two exceptions: `ensure_started()` may print daemon-start progress on
  stdout (apple/container's "starting container runtime..."), and
  apple/container's `validate_version()` prints its existing
  `JMS_RUNTIME_ACCEPT` warning to stderr (§4, R4.2 — unchanged 1.0.0
  behavior).
- Exit codes are unchanged: runtime failures raise `JMSException` (exit 1);
  selection/usage failures raise `UsageError` (exit 2).

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

One parametrized test module runs both backends through identical scenarios
via the per-backend fakes (§9): version first lines (valid,
distro-suffixed, malformed, invalid UTF-8); image/`ps`/`info` payloads
(fixture-true, malformed records, wrong types, invalid UTF-8 bytes,
non-array top level); `image_exists` tri-state (present, absent, hard error
with stderr preserved); mount serialization (plain, readonly, and rejection
of `,`, `=`, NUL, and non-UTF-8 in sources/targets); removal
classification (`stop_container`/`remove_container`/`remove_image` fed
success, absence, and hard failure — MIR-035, R5.9); and golden argv
comparisons for build and every launch variant. A seam test patches
`runtime_run` and asserts no backend operation reaches `subprocess` any
other way.

---

## 3. Project-image user ABI: one identity, two runtimes

Every conforming project image, whether it inherits the repository base or is
standalone, provides an `isolation` account at UID/GID `1000:1000`, with
`/home/isolation` and `/bin/bash` in passwd, an existing writable home owned
by `1000:1000`, and passwordless sudo. Repository-owned images name the group
`isolation` and end with `USER isolation`. This is an image-author contract;
jms does not inspect or repair it at runtime.

The existing Fedora base `Containerfile` builds unchanged under
Podman/Buildah. Its identity, and the standalone clean-slate example's
identity, must be deterministic across backends:

1. **Pin the `isolation` UID/GID in every project image.** Rootless Podman's
   `--userns=keep-id` mapping (§7) must name the container-side UID, so it
   cannot be left to `useradd`'s "first free UID" default:

   ```dockerfile
   RUN groupadd -g 1000 isolation && \
       useradd -m -s /bin/bash -u 1000 -g 1000 isolation && ...
   ```

   Keep the runtime values explicit as `ISOLATION_UID = 1000` and
   `ISOLATION_GID = 1000` in `bin/jms`, and test those constants against
   both repository-owned Containerfiles. The constants feed the `keep-id`
   mapping and numeric `--user` value (§7.1); because the user is passed
   numerically, image content cannot influence which UID/GID the process
   runs as, and no image attestation exists (§7.4).

2. **Update the virtiofs comment** (`Containerfile` line 26) to describe
   both backends: virtiofs squashes UIDs on macOS; on Linux, `keep-id`
   performs the equivalent alignment explicitly.

No other change: `FROM registry.fedoraproject.org/fedora:latest` is fully
qualified (no short-name ambiguity), and every package including
`bubblewrap` exists in Fedora regardless of what runs the build.

### Base image naming under Podman

`podman build --tag jmscontainers-base:latest` stores the image as
`localhost/jmscontainers-base:latest`. Project Containerfiles keep
`FROM jmscontainers-base:latest` — Buildah resolves `FROM` short names
against local storage first, so this finds the locally built base without
touching a registry, and project builds pass an explicit `--pull=missing`,
which uses the local base whenever present and never re-pulls it while
letting standalone projects fetch external bases on a clean store
(`examples/clean-slate` moves to the fully qualified
`FROM registry.fedoraproject.org/fedora:latest`, the documented
recommendation for external bases — nothing is enforced, and short-name
resolution beyond jms's own argv follows the host's `registries.conf`,
trusted host input per MIR-040/§8).

Non-interactivity and the missing-base diagnostic (MIR-041, amended by
MIR-055): every build runs with stdin redirected from `/dev/null`, so no
engine prompt can hang a build. Non-interactivity is the whole
guarantee — failure speed is not part of it: under `--pull=missing`, an
absent `jmscontainers-base:latest` is eligible for short-name pull
attempts per the host's `registries.conf` before the build fails, so no
"fails fast" claim is made. jms never parses Containerfile syntax to
find the base, so it cannot know whether a failed project actually
builds from the shared base; instead, when a project build fails, it
checks `image_exists("jmscontainers-base:latest")` and, only when the
base is observed absent, appends a conditionally worded hint after
`CONTEXT_NOTE`:

```
note: the shared base image jmscontainers-base:latest is not present;
if this project builds from it, run `jms build` in the base directory
first
```

The wording is conditional because the evidence is partial (MIR-055): a
standalone external-base project that failed for unrelated reasons can
also trigger it, and must not be told the base build *is* its fix. This
contract is qualified by §9's FROM-resolution check running the exact
production argv (`--pull=missing`); no substitute pull policy counts as
qualification.

Consequences handled by the backend:

- `local_name()` for Podman strips exactly `localhost/` — the only
  qualification its production builds emit — and nothing else (MIR-047:
  a broader strip would pull registry-qualified manual aliases into the
  reserved namespace). The `jmscontainers-…` tag-prefix ownership checks
  in `gc_project_images` and `cmd_clean` keep working unmodified.
- `image_exists("jmscontainers-base:latest")` must match the
  `localhost/`-prefixed stored name; `podman image exists` does this
  natively (§5).

---

## 4. Runtime readiness (`runtime_ready`)

### Version parsing

- apple/container: `container CLI version X.Y.Z …` (unchanged).
- Podman: `podman --version` → `podman version X.Y.Z`, possibly with a
  distro suffix such as `5.4.2-dev` or `5.4.2+ds1` — accept and truncate a
  non-numeric suffix on the patch component; a string not starting with
  numeric `major.minor.patch` is rejected as unparseable. Only the local
  client version is checked — remote services are rejected at readiness,
  so client and engine are the same binary on every supported
  configuration.

### Qualification policy — deliberately different per backend

Keep the exact `RUNTIME_MIN == RUNTIME_MAX` pin for apple/container
(1.2.0): it is a single-channel Homebrew install and the pin has already
proven its worth. `JMS_RUNTIME_ACCEPT` remains meaningful only for this
backend; document that.

For Podman, an exact pin is wrong: versions are chosen by the
distribution, and the CLI surface jms uses (`run`, `build`,
`image exists`, `ps --format json`, `--userns=keep-id:uid=`) has been
stable across 4.9 → 5.x. Policy:

- `version_min = (5, 4, 0)` — Debian 13's packaged Podman, the only
  first-push host target. Every feature jms uses predates 5.4 by years
  (`--userns=keep-id:uid=` needs ≥ 4.3, `image exists` is ancient), so the
  floor is set by the support scope, not by feature availability. When a
  new host target is promoted, the floor is revisited.
- No maximum and no version-warning machinery: any version at or above
  the floor is accepted silently. Qualification lives in the release
  checklist, which records the newest *tested* version — not in runtime
  warnings for hypothetical future majors.

### Startup / health probe

apple/container keeps the `system status` / `system start` dance. Podman
is daemonless, so `ensure_started()` instead validates one invocation:

```sh
podman info --format json
```

The JSON is validated in full:

- `host.serviceIsRemote` must be false (remote Podman is unsupported, §2).
- `host.security.rootless` must be true.
- `host.idMappings.uidmap`/`gidmap` must each be well-formed and usable.
  **Usable** means contiguous container-ID coverage of `[0, 65536)`,
  validated per map independently: every entry must be a map with integer
  `container_id >= 0`, `host_id >= 0`, and `size >= 1`, and the union of
  the `[container_id, container_id + size)` intervals must cover every ID
  in `[0, 65536)`. Overlaps are harmless (union semantics), and no
  relationship between `host_id` values and the invoking UID/GID is
  asserted — rootless Podman constructs the singleton itself. 65536 is
  the conventional per-user subordinate allocation (what Debian's
  `adduser` provisions) and covers everything both launch variants need:
  `keep-id:uid=1000,gid=1000` requires container ID 1000 mapped, and the
  shipped Fedora image's static IDs run up to `nobody` (65534). A
  structurally malformed entry aborts as malformed engine output (fail
  closed); well-formed but insufficient coverage selects the
  undersized-range hint.
- `store.graphDriverName` must be present. This proves only that Podman
  initialized and reported its storage configuration — metadata is
  readable (MIR-050). Readiness makes no claim that image extraction,
  layer creation, or bind mounting works; storage-operation failures
  (including an NFS-broken graph root) surface at the first build or
  launch with Podman's own stderr, where the same evidence-keyed hint
  machinery applies.

No create/run probe is performed — it would add latency, an image
dependency, and cache-invalidation rules, and the residual failure classes
it would catch (OCI runtime, network helper) surface with full stderr at
the first real launch, where the same evidence-keyed hint machinery
applies.

On failure, surface Podman's stderr verbatim plus a hint keyed to the
check that failed — remote connection configured, rootful invocation,
missing/undersized `/etc/subuid`–`/etc/subgid` ranges, or storage
misconfiguration — never one universal diagnosis:

```
rootless podman is not usable: <stderr>
hint: rootless podman needs an entry of at least 65536 ids for your user
in /etc/subuid and /etc/subgid; on Debian the uidmap package provides
newuidmap/newgidmap and adduser provisions ranges for new users; see
podman(1).
```

Every Podman diagnostic targets the qualified Debian 13 contract: the
CLI-missing hint is the full qualified apt command (§2, verbatim the
README's install command), and the ID-map hint names the `uidmap` package
— not Fedora's `shadow-utils` — until a Fedora host is qualified.
Distro-neutral wording survives only where genuinely distro-neutral.

**Ordering.** Runtime-touching commands run, in order: side-effect-free
backend selection (§2, before consent), `approve()`, `runtime_ready()`,
then build/launch. An unapproved definition never contacts the runtime.
Consequence, accepted deliberately: a durable trust grant may be recorded
immediately before a readiness failure. That is safe because a grant
records consent to a project definition, not runtime state — the command
then fails without building or running anything, and the grant remains
valid for a retry once the host is fixed. For
`trust revoke --purge-images`, a *readiness* failure lands after
revocation and keeps today's "trust was revoked, but image purge failed"
split.

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

Replace the current `image_record_facts()` with a backend method
`image_facts()` returning already-normalized `(id, refs, created, labels)`
tuples — **one fact per image identity**, carrying all of its names.
Parsing is a strict fixture-backed normalizer: the parser accepts exactly
the shape proven by the checked-in fixtures and fails closed on anything
else. A malformed value in any ownership-relevant field (`Id`, `Names`,
`Labels`) aborts the operation with an error rather than being silently
skipped. Qualifying a new runtime version requires capturing a new fixture
first.

Fixture provenance (MIR-044): every fixture file has a one-command
reproducible capture recipe recorded in `tests/fixtures/README`, executed
on the qualified engine versions, and must preserve whole records for
every accepted schema variant its normalizer branches on — for Podman
images: named, multi-named, unlabeled, jms-labelled, and dangling records
(real 5.4.2 JSON spells danglings as `"Names": null` and never emits a
`<none>` name — pinned at capture time, so `<none>` filtering stays a
synthetic case in test code); for Podman `ps`: inherited image labels, the
`jms.container=launch` override, marker absence, and running/exited
states; plus the Podman `inspect` mounts fixture the leak sweep requires
and the apple/container 1.2.0 equivalents. Synthetic malformed cases live
in test code, never in fixture files. A normalizer lands only after its
fixtures do (§11).

- **apple/container** (fixture:
  `tests/fixtures/apple-container-1.2.0-images.json`): the identity is the
  record's top-level `id` — the 64-hex digest of the image's OCI index,
  always equal to `configuration.descriptor.digest` minus its `sha256:`
  prefix; the normalizer asserts that equality and fails closed on
  mismatch. The list is one-ref-per-record, so a multi-tagged image
  contributes several records to one fact; `image_facts()` groups records
  by `id` and collects each record's `configuration.name` into `refs`.
  Refs keep the runtime's mixed qualification verbatim (pulled/tagged
  names registry-qualified, built names unqualified) — prefix matching
  keys on `local_name()`-normalized refs. `created` parses the ISO-8601
  `configuration.creationDate`, which is OCI config creation time, not
  local build time — a label-only build inherits its parent's timestamp,
  so retention ordering must tolerate equal timestamps (stable sort, as
  today). Labels stay `variants[0].config.config.Labels`, absent treated
  as `{}`.
- **Podman** (fixture: `tests/fixtures/podman-5.4.2-images.json`): flat
  records with uppercase `Id`, `Names`
  array-or-null, integer `Created` (already epoch seconds), top-level
  `Labels` map-or-null. `refs` from `Names`; records with null/empty
  `Names` (dangling) are skipped — dangling layers are never jms-owned;
  `<none>` names are treated as absent; digests and `RepoTags` are
  ignored.

Null-label rule (MIR-053), both backends, both fact types: an absent or
JSON-null label map normalizes to `{}` — an unlabeled image or container
is normal engine output, never an error (Podman spells it
`"Labels": null`) — and any other non-map value aborts as malformed. The
key/value grammar below applies to entries of present maps.

**Shared validation, backend-scoped merging (MIR-038).** The per-backend
paragraphs above define how records are *read*; identity handling splits
into a shared validation layer and one backend-specific merge:

- Shared validation, both normalizers (completed by MIR-045): every image
  `id` must be a 64-character lowercase-hex string; every ref and every
  label key and value must be NUL-free valid-UTF-8 `str` values, label
  keys non-empty — a non-string key or value aborts. `created` must be an
  `int` that is not a `bool` (Python's `bool` subclasses `int` and is
  rejected explicitly) within `[0, 253402300799]` (year 9999);
  apple/container's `creationDate` must be strict ISO-8601 with an
  explicit UTC offset (naive, unparseable, or out-of-range dates abort)
  and converts into the same epoch range. A violation aborts the whole
  operation. Records with no refs (dangling, after `<none>` filtering)
  are dropped, so a fact's `refs` is always non-empty.
- apple/container is the only format that can legitimately yield several
  records per image ID (one ref per record), so only its normalizer
  merges: refs are unioned per ID, deduplicated, and sorted
  lexicographically — output is independent of record order — and two
  records for one ID that disagree on `created` or whose label maps are
  not exactly equal (a key present in one record and absent in another
  is a conflict — no union, MIR-045) abort as malformed engine output;
  ownership data is never arbitrarily chosen or synthesized. Identical
  repeats are tolerated, and a dangling
  record for an ID that also has named records contributes nothing.
- Podman 5.4.2 emits a multi-tagged image as one byte-identical record
  per tag, each carrying the full `Names` array (pinned by the
  recaptured images fixture; this amends the earlier one-record-per-
  identity premise). Exactly-identical duplicate records for one `Id`
  collapse to one fact; records for one `Id` that disagree in any
  normalized field abort as malformed engine output.
- Facts are emitted sorted by `id` on both backends.

`created` is one internal type — Unix epoch seconds — on both backends, so
sorting is uniform and never compares backend-local representations.

Retention in `gc_project_images` counts distinct image IDs (a multi-tagged
image is one retained unit, and duplicate-removal scheduling is impossible
by construction); ownership still requires label **and** tag prefix,
evaluated per ref within a fact. Deletion untags per jms-owned ref rather
than deleting by bare ID: the image disappears when its last name goes,
and an alias **outside the reserved namespace** survives — jms never
deletes by bare ID, and the Podman untag passes `--no-prune` (MIR-042),
so neither an unrelated alias nor an unselected dangling parent is ever
removed as a side effect.

Reserved namespace and concurrency (MIR-047): a ref is jms-reserved iff
its `local_name()` normalization begins with a jms tag prefix
(`jmscontainers-…`). All matching aliases are reserved user-visible state
— jms tracks no per-ref provenance, and a manual tag into the reserved
namespace is handed to jms; the README documents this (§10). Same-store
concurrent mutation during cleanup is an explicit documented limitation:
jms neither locks nor rechecks identity between enumerating `(id, ref)`
and untagging `ref`, and the residual retag race is accepted and named in
the README. The label-inheritance
caveat (`bin/jms:869`) applies identically to Podman — OCI labels inherit
through `FROM` there too — so the dual check stays load-bearing on both
backends.

### `container_records` → `ps()`

Podman: `podman ps --all --format json` → flat records with a full
64-character `Id` and a top-level `Labels` map (fixture:
`tests/fixtures/podman-5.4.2-ps.json`).
Normalize to the existing `[{"id": …, "labels": {…}}]` shape. Validation
(MIR-045): the Podman `Id` must be a 64-character lowercase-hex string;
the apple/container id is a non-empty NUL-free valid-UTF-8 string (that
engine's ID is a name — no truncated hex form exists); `labels` uses the
same key/value grammar as image labels (non-empty NUL-free UTF-8 `str`
keys, NUL-free UTF-8 `str` values), and an absent or null label map
normalizes to `{}` (MIR-053). A malformed ownership-relevant field
aborts the operation.

**Cleanup ownership requires launch provenance, not just the image
label.** The fixtures prove image labels are inherited into container
`Labels`, so `jms.project` alone would also match a container the user
started manually from a jms image. The predicate, identical on both
backends:

- Every jms-driven build (base and project) stamps the neutral value
  `jms.container=image` on the image, in the shared build-label assembly.
  Because the build-time stamp overrides any value from the
  Containerfile, no image — including a malicious project definition that
  tries to `LABEL` the marker — can carry the launch value.
- `jms launch` passes `--label jms.container=launch`, overriding the
  inherited neutral value on the container.
- The cleanup predicate requires the existing `jms.project` label
  (scoping: project-scoped `clean` matches its value, `clean --all`
  requires its presence) **and** `jms.container=launch` (provenance).
- A marker-absent container means "not created by jms" and is never
  selected: manual containers, and unrelated containers that merely have
  `jms-`-prefixed names, are left alone. Dry-run and real cleanup share
  the one predicate.

### Cleanup verbs

Commands drive removals exclusively through the protocol's `RemovalResult`
operations (§2, MIR-035); the argv each backend executes underneath:

| Operation | apple/container | podman |
| --- | --- | --- |
| `stop_container` | `container stop ID` | `podman stop --ignore ID` |
| `remove_container` | `container delete --force ID` | `podman rm --ignore --force ID` |
| `remove_image` | `container image delete REF` | `podman image rm --ignore --no-prune REF` |

Same "stop may fail, forced delete is authoritative" pattern on both: a
`failed` stop result never skips the forced remove, and a `failed` stop
followed by a successful forced remove of the same container is dropped
from the aggregate (MIR-043) — the goal state was reached. The Podman
`--ignore` flags (documented on 5.4's `stop`, `rm`, and `image rm`;
qualified as part of acceptance) make a vanished resource exit 0 at the
engine, which is what keeps `RemovalResult` two-state (§2, MIR-035);
`--no-prune` (MIR-042) keeps the untag from cascading into dangling
parents jms never classified as owned. apple/container's delete-by-ref
cascade behavior is determined by the R5.4 survivor-set acceptance run,
and a discovered cascade is a qualification failure to resolve before
release.

**Scheduling versus execution (MIR-048).** Image removal splits into
`image_removal_schedule(...)` — enumerate and select (readiness,
`image_facts()`, ownership/retention), raising on any failure — and
`execute_removal_schedule(schedule)`, which performs the removals, never
raises (the removal operations catch their own recheck failures — §2,
MIR-052), and returns the ordered `(ref, RemovalResult)` list. Policy is
explicit at each call site: background GC (post-build/launch retention)
wraps both steps, converting any raise — including an enumeration
failure — into one stderr warning while the already-successful
build/launch result stands; `clean`, `clean --all`, and
`revoke --purge-images` let schedule failures raise (exit 1) and
aggregate execution failures into the exit-1 report. Revocation commits
before the purge begins, so every purge-path failure keeps the "trust
was revoked, but image purge failed" split.

**Partial-failure semantics.** All four removal paths (project GC, project
`clean`, `clean --all`, `revoke --purge-images`) attempt every scheduled
operation and never abort mid-list:

- **Ordering:** containers before images; per container, `stop_container`
  then `remove_container`; image untags in the existing deterministic
  order (sorted refs for `clean`, newest-first retention order for GC).
  Within a multi-ref fact, each jms-owned ref's untag is attempted
  independently.
- **Diagnostics and exit:** `clean` and `revoke --purge-images` print
  successes as they happen — those lines remain valid when a later
  removal fails, and no overall summary claims success while the
  aggregate holds failures — then report every `failed` result (resource
  plus its terminal-safe `detail`) and exit 1 if any occurred. Project GC
  prints one warning line per failure to stderr and never fails the
  surrounding build/launch (MIR-048).
- **Vanished-resource race:** absence counts as success, folded into
  `removed` inside the backend (§2, MIR-035/043): Podman's `--ignore`
  flags make the engine exit 0, and apple/container rechecks existence
  after any failed removal operation, stop included (MIR-052). Commands
  never parse stderr to decide this.
- **Idempotency:** nothing is cached; a second invocation re-enumerates
  and acts only on survivors, so repeated runs converge.

---

## 6. Build (`run_build`)

| Aspect | apple/container | podman |
| --- | --- | --- |
| tag/file/context | `--tag`, `--file`, positional context | identical |
| labels | `-l key=value` | `--label key=value` |
| no cache | `--no-cache` | identical |
| pull (base only) | `--pull` | `--pull=always` |
| project builds | (no pull flag) | `--pull=missing` (explicit; a present local `jmscontainers-base:latest` always wins and is never re-pulled, external bases fetch on a clean store — §3) |

Every build runs with stdin redirected from `/dev/null` (MIR-041), so no
engine prompt — short-name or otherwise — can hang a build; the failure
itself carries no speed guarantee, since `--pull=missing` may attempt a
pull for an absent base first (MIR-055). When a project build fails,
`build_project()` checks `image_exists("jmscontainers-base:latest")` and
appends the conditionally worded missing-base hint only when the base is
observed absent (§3).

`build_argv()` on the backend assembles this; the surrounding logic —
context = `.jmscontainer/`, the pre-build fingerprint re-check in
`build_project`, `CONTEXT_NOTE` on failure — is untouched, and no
post-build image inspection exists (§7.4). The v2 context
rule ("COPY/ADD sources must live inside `.jmscontainer/`") is enforced by
both builders since the context directory is identical; the integration
escape test (§9) verifies the Podman error path still trips
`CONTEXT_NOTE`.

---

## 7. Launch (`launch_plan`) — the one genuinely different area

The good news: `--rm --interactive --tty --name --user --workdir
--entrypoint --label --env --mount` all exist in Podman with compatible
meanings, including string `--entrypoint`. Three real differences:

### 7.1 UID mapping (replaces virtiofs squashing)

On macOS, virtiofs squashes UIDs bidirectionally, so `/work` writes appear
with host ownership for free. Rootless Podman needs the mapping stated.

Both launch variants pass an **explicit** `--userns` flag: Podman's
default user namespace can be changed by `PODMAN_USERNS` or
`containers.conf`, so relying on the default would let ambient host
configuration silently alter the security-relevant mapping. (Qualified on
Podman 5.4.2: the explicit flag beats conflicting `PODMAN_USERNS` and
`containers.conf` values in both directions; the integration tests re-run
those conflicts.)

- **Default (isolation user):** `--userns=keep-id:uid=1000,gid=1000` — the
  invoking host user maps to container UID/GID 1000 (`isolation`, pinned
  in §3). Writes to `/work` and the agent-state mounts land on the host
  owned by the invoking user; container-side files owned by `isolation`
  are exactly the host user.
- **`--root`:** `--userns=host` — under rootless Podman, `host` mode runs
  the container in the rootless user namespace, mapping the invoking user
  to container root, which is precisely what `--root` means here; host
  ownership of writes is again the invoking user. This is the explicit
  spelling of the ambient default and is safe *only* because rootful
  Podman is rejected at selection (§2) — under rootful, `host` would mean
  no user namespace at all. Qualified on 5.4.2: `/work` writes are owned
  by the invoking user and `isolation` resolves to UID 1000 via the
  subordinate range. Fallback candidates if a future qualification run
  disagrees: `keep-id:uid=0,gid=0`, then an explicit `--uidmap`/`--gidmap`
  triple — never an omitted flag. (Rootless `--uidmap` values are relative
  to the *intermediate* namespace — 0 = the invoking user, not host
  uid 0 — so that fallback needs its own golden-argv pin if it ever
  becomes real.)

**`--user` is numeric on Podman** — the decision that supersedes the
attestation subsystem (MIR-034/036/037): `--user 1000:1000` by default
and `--user 0:0` under `--root`, both derived by the serializer from
`LaunchPlan.user`, the single user-mode authority (§2, MIR-046), and the
`ISOLATION_UID`/`ISOLATION_GID` constants (§3). Passed by name,
`--user isolation` would resolve
through the image's own `/etc/passwd`, letting a project Containerfile
decide which UID the process runs as — the entire surface the deleted
ABI probe existed to defend (§7.4). Passed numerically, the runtime UID
is fixed by jms's own argv regardless of image content. The corresponding
account metadata remains the image author's responsibility: an image whose
`isolation` passwd entry does not resolve UID/GID `1000:1000`,
`/home/isolation`, and `/bin/bash`, or whose home and sudo policy do not
satisfy §3, is nonconforming and unsupported. A numeric `--user` grants no
supplementary groups
(consistent with the declined `keep-groups` below); and an image without
a usable `/bin/bash` fails at launch with the runtime's own error.
apple/container keeps `--user isolation` / `--user root` unchanged — the
shared ABI ensures that name resolves to the same identity, while virtiofs
squashing makes the numeric value non-load-bearing for host ownership on
macOS.

Note `sudo` inside the container (the `isolation` user's passwordless
sudo) still works under `keep-id`: container root is a mapped subordinate
UID, not host root. State that explicitly in SECURITY.md (§8).

The 1.1.0 host-permission contract is **owner-based only**: supported
project trees, extra mounts, and shell/credential state are those
readable/writable through the invoking user's own UID (any value, not just
1000) and primary GID, which `keep-id:uid=1000,gid=1000` maps faithfully.
Access that exists only via supplementary groups, ACL grants, or setgid
directories is a documented limitation in README/SECURITY.md — no
preflight detection (owner/ACL heuristics false-positive too easily), and
no `--group-add keep-groups` (its portability across OCI runtimes is
unqualified). Supporting supplementary groups becomes entry criteria for a
future release if the limitation proves painful.

### 7.2 Mount grammar and SELinux

Backend-specific `mount_argument()`:

- apple/container: `source=S,target=T[,readonly]` (unchanged).
- Podman: `type=bind,source=S,target=T[,readonly]`.

Do **not** use `:z`/`relabel=shared` volume relabeling: it would `chcon`
the user's real project tree and the shared agent-state directories on the
host — mutating host state and fighting other tools. Instead, always pass

```
--security-opt label=disable
```

on the Podman backend. Rationale, which belongs in SECURITY.md verbatim:
the container is a full-permission agent sandbox whose boundary is the
user namespace; SELinux container separation adds little here, and
relabeling host project files is an unacceptable side effect. On
non-SELinux hosts the flag is a no-op — the first-push target (Debian 13)
is an AppArmor host, where this is qualified.

SELinux-**enforcing** hosts sit outside the 1.1.0 qualification matrix:
like every other local rootless Linux configuration beyond Debian 13/amd64,
they are **unqualified but allowed** (MIR-039). jms does not detect or
refuse enforcing hosts — the flag will typically work there, but no
qualification or support guarantee is made, and README/SECURITY.md record
exactly that classification. Enforcing-mode qualification is planned
alongside Fedora host support, deferred given the small population of
workstations running enforcing mode. The follow-up release's entry
criteria: a recorded decision comparing `label=disable` with relabeling
and non-mutating alternatives, plus an SELinux-enforcing-host integration
test.

The existing `,`/`=` path rejections in `runtime_path()` keep the Podman
mount string unambiguous too. NUL/UTF-8 rules are shared.

### 7.3 Hostname

apple/container has no hostname flag, hence the `HOSTNAME=container`
fakery in `/etc/profile.d/jms.sh`. Podman has one — pass
`--hostname container` for parity so the prompt and `$HOSTNAME` agree by
construction. The profile fallback stays (harmless, still needed on
macOS).

### 7.4 Image content is not attested — the numeric `--user` decision

Earlier revisions attested every built and launched image's `isolation`
user with a never-started create/`cp`/rm probe (MIR-034/036/037),
because `--user isolation` by name let the image's `/etc/passwd` decide
which UID the container process ran as. That subsystem — five `podman`
invocations per build and per launch, strict tar-stream parsing of three
files, probe-container lifecycle and orphan collection,
volume-suppression flags, and a seven-image integration matrix — is
deleted, not implemented: the Podman backend passes `--user 1000:1000`
(`--user 0:0` under `--root`), so the property the probe attested holds
by construction (§7.1) and image content cannot influence the runtime
UID at all.

Numeric `--user` enforces the runtime identity independently of image
content. The documented project-image ABI makes the corresponding account
name, passwd home and shell, home existence/ownership/writability, and sudo
policy the image author's responsibility. A mismatch is a nonconforming
image, and a missing or broken `/bin/bash` entrypoint can fail at launch with
the runtime's own error. jms therefore never inspects an image filesystem,
and `verify_image_abi` does not exist on any backend.

**Rejected alternatives, recorded:** (a) the attestation probe itself —
disproportionate machinery whose entire attack surface the numeric
`--user` removes; (b) an ABI label as a verified cache — forgeable by a
Containerfile `LABEL`; (c) running `id`/`getent` in a container —
executes image-controlled code, so the observation is forgeable. The
full probe design survives in git history and in the MIR-034/036/037
register entries, which double as constraints on any future feature that
creates non-`--rm` containers or parses `podman cp` streams.

### Resulting Podman argv shape

```text
podman run --rm --interactive [--tty]
  --name jms-<slug>-<hex> --user 1000:1000 --workdir /work  # --user 0:0 under --root
  --entrypoint /bin/bash --label jms.project=<pid>
  --label jms.container=launch
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
`execvp` works identically; `launch` still exits with the container's
status.

### Known caveat: nested sandboxes

`bubblewrap` (the Codex bwrap path) fails inside rootless Podman, and the
mechanism is reproduced (Podman 5.4.2 / bubblewrap 0.11.0): creating the
nested user namespace *works* under the default seccomp and capability
set, but mounting a fresh `/proc` inside it fails with
`Can't mount proc on /newroot/proc: Operation not permitted`, because
Podman masks `/proc` paths in the container. Launching the container with
`--security-opt unmask=ALL` makes the same bwrap invocation succeed — but
that unmasks kernel interfaces inside the boundary, so jms never passes it
and must not weaken the container defaults globally. 1.1.0 documents the
limitation only — agents should run without their inner sandbox, since
they are already inside jms's boundary — and no unmask workaround is
documented as a runnable command; a narrower `unmask=/proc/*` opt-in is
deferred until a concrete need appears. Codex's native Linux sandbox
(Landlock/seccomp) is expected to be unaffected — still to be verified
against the shipped agent CLIs (§9); if a launcher hard-requires bwrap,
the recorded behavior becomes part of the documented limitation, not
grounds for weakening container defaults.

---

## 8. Security model documentation (required, not optional)

The README's promise — "without handing them your Mac", "the VM boundary …
is what contains it" — is a VM claim that must not silently stretch to
cover Linux. Update SECURITY.md and the README with an explicit
per-platform statement:

- **macOS / apple/container:** boundary is a lightweight VM per container
  (unchanged text).
- **Linux / rootless Podman:** boundary is a user namespace plus Podman's
  seccomp filter and capability drops *as configured on the host* —
  kernel isolation, not hardware-virtualized isolation. SELinux label
  separation for mounts is deliberately disabled (§7.2), so it
  contributes nothing here. The precise claims, stated in SECURITY.md in
  these terms:
  - **Ambient Podman configuration is trusted host input (MIR-040):**
    `containers.conf` and its drop-ins, `mounts.conf`, `storage.conf`,
    `policy.json`/`registries.conf`, configuration-selecting environment
    variables, and OCI hooks belong to the invoking user and sit in the
    same trust class as the `podman` binary and the kernel, for `build`
    and `run` alike. jms neither validates nor neutralizes them; host
    configuration that mounts additional data into containers is the
    user's own configuration, outside jms's claims, and
    `LaunchPlan.mounts` and the argv goldens pin jms-requested mounts
    only. The two explicit overrides (`--userns`,
    `--security-opt label=disable`) pin the mapping and labeling
    contract jms itself relies on; they are not an audit of the rest.
  - **Trusted:** the host kernel and the OCI runtime. The boundary holds
    only as long as they do; a kernel or runtime exploit can cross the
    namespace boundary and potentially elevate beyond the invoking user.
    No claim of the form "an escape can never yield host root" is made.
  - **What the boundary aims to contain:** absent such an exploit,
    container processes — including container "root", which is an
    unprivileged mapped UID of the invoking user — hold at most the
    invoking user's authority on the host.
  - **What an escape yields:** everything the invoking user's account can
    do — their files, credentials, processes, and network access. For a
    single-user development machine that is most of what matters; "not
    host root" is a limited consolation and is not presented as more.
  - **What no boundary mitigates:** anything deliberately mounted in.
    Project files and mounted credentials are exposed to the agent by
    design; the existing credential-exfiltration warning applies
    regardless of boundary type.
  - This is a meaningfully weaker boundary than the macOS VM against
    kernel exploits, and the docs must say so in those words.
  - SELinux-enforcing hosts are unqualified but allowed in 1.1.0
    (§7.2, MIR-039); enforcing-mode qualification is planned alongside
    the Fedora host target.

Unchanged on both platforms, and worth restating: the credential-mount
warning ("never claim the VM meaningfully limits exfiltration of mounted
credentials") already doesn't depend on the boundary type; the
protected-source rules, read-only shell mount rationale, and trust store
location are identical.

---

## 9. Testing and CI

### Unit tests (`tests/test_jms.py`)

The `FakeRuntime` class is keyed on `argv` prefixes like
`["container", "--version"]`. Plan:

1. **Refactor first, behavior-neutral:** land the backend extraction with
   apple/container as the only backend and the entire existing suite
   green, including the golden fingerprints (`GOLDEN_TREE_TF` etc. —
   nothing in the trust path may move, and the goldens prove it).
2. **Parametrize the fake:** give `FakeRuntime` a backend name and canned
   outputs per backend (`podman --version` line, `podman images` flat
   JSON, `podman ps` flat JSON, `image exists` exit codes). Run the
   runtime-touching test classes under both fakes via a shared mixin;
   trust/discovery/manifest tests stay single-run (they never hit the
   seam).
3. **Golden argv tests per backend:** assert the exact `run` argv for the
   canonical launches (default, `--root`, manifest mounts, `--auth`) on
   both backends — this pins `keep-id`, the numeric `--user`,
   `label=disable`, mount grammar, and flag ordering, the places a
   regression would be silent and security-relevant.
4. **Selection tests:** platform defaults, unsupported platform (exit 2),
   root-on-Linux refusal, a Podman-info fixture with
   `serviceIsRemote=true` failing readiness, and
   `test_linux_scope_is_qualification_not_gate` (MIR-039): a Debian amd64
   host, a non-Debian distro, and an arm64 host all select
   `PodmanBackend` identically with no warning and no distro/arch
   detection call — alongside the already-decided SELinux non-gate.
5. **Laziness tests:** `--version`, `inspect`, `init`, `trust list`,
   `trust revoke` without `--purge-images`, and `trust prune` succeed with
   no runtime executable, on a mocked unsupported platform, and in a
   mocked uid-0 process.

`make test` still requires no runtime on either OS.

### Integration (`scripts/integration.sh`)

Parametrize on the platform instead of hard-requiring `container`:

- The two direct `container …` invocations become runtime-conditional: the
  bwrap smoke test uses `podman run` on Linux, and the final
  leaked-container sweep follows the "Leak-sweep contract" below — on
  Podman it lists IDs via `podman ps --all --format json` and reads mount
  sources via `podman inspect`, because on 5.4.2 the `ps`
  JSON `Mounts` field is only a list of target paths with no sources, so
  `ps` alone cannot identify jms mounts.
- Add a `FROM jmscontainers-base:latest` resolution check (§3): build one
  example through jms (real argv, `--pull=missing`) under the harness's
  egress denial (below; jms has no project-build network flag), asserting
  success with the base present — proving no registry contact is needed;
  with the base absent, assert a non-interactive failure carrying the
  conditional missing-base hint (the denied pull attempt fails; no speed
  assertion — MIR-055). A clean-store standalone-project build proving
  the external base fetches lands in tier B, without egress denial.

**Egress denial (MIR-056).** The FROM-resolution check's network
isolation is an nftables rule in a harness-owned table that drops all
non-loopback output traffic whose socket UID is the test user's,
installed via sudo immediately before the check and removed in the EXIT
trap. A namespace wrapper (`unshare --net`) is deliberately not used:
unprivileged network namespaces require a new user namespace, which
either maps the invoking user to euid 0 — tripping jms's uid-0 refusal
(§2) — or single-maps the invoking UID, destroying the subordinate-ID
ranges rootless Podman needs. A failure to install or remove the rule is
a harness failure, reported distinctly from any test failure.

The script is split into two tiers, selected by its single positional
argument — `scripts/integration.sh a|b|all`, default `all`; tier B
assumes tier A's base image already exists (MIR-056) — so the
launch-contract assertions do not pay for the example-image builds:

- **Tier A — fast, base image only.** Runs the readiness preflight, builds
  the base, and asserts the launch contracts against `--bin` shell
  launches of the base image: `/work` ownership (default and `--root`),
  in-container UID per variant, passwordless sudo, hostname, environment
  and entrypoint parity, exit-status propagation, the read-only
  shell-state mount, the ambient-config conflict runs, the bwrap probes,
  and the deliberate-failure cleanup check.
- **Tier B — expensive, example images.** The existing per-example
  build/inspect/launch/clean cycle, the context-escape test, the
  credential/agent-state mount assertions (which need `--auth` and real
  agent state directories), and the R5.4 survivor-set graph run
  (MIR-042/047): build a graph containing selected and unselected
  parents plus jms and non-jms aliases, remove one scheduled ref, and
  assert the exact survivor set. Its clean-store standalone-image run also
  verifies the complete §3 ABI and host ownership of a `/work` write.

Both tiers end in the leak sweep, and cleanup plus the sweep run from the
EXIT trap, so a failure in any step still sweeps and reports — a partial
failure can never skip leak detection; sweep failure stays distinct from
leak per the contract below.

The Linux-only tier-A launch-contract assertions, each keyed to a table
row below:

- **Ownership (default):** create a file in `/work` from inside the
  container (`--bin /bin/sh -- -c 'touch …'`) and verify host ownership
  equals the invoking user — the `keep-id` contract and the single most
  likely thing to break. Also assert `id -u` inside is 1000
  (`isolation`).
- **Ownership (`--root`):** the same write under `--root`, asserting
  `id -u` inside is 0 and host ownership is still the invoking user — the
  `--userns=host` contract, and the enforceable form of §8's "container
  root is an unprivileged mapped UID" claim.
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
- **Failed-run cleanup:** force one launch to fail mid-run (an entrypoint
  that exits nonzero after touching `/work`) and assert the trap-driven
  cleanup and sweep still run and report clean.
- **Security options:** every tier-A run passes
  `--security-opt label=disable` and succeeds — the 1.1.0 non-SELinux
  acceptance check (§7.2).
- **Non-1000 host UID/GID:** the harness's test user is created with a
  non-1000 UID and non-1000 primary GID, so the ownership assertions
  cover the general owner-based contract (§7.1), not just the
  coincidental-1000 case. Preconditions (MIR-056): the user is created
  with `adduser` (which provisions the 65536-ID subordinate ranges
  readiness requires), has a fresh home on a local filesystem with no
  prior container state, and runs the tiers from a real login session
  (ssh) so `pam_systemd` provides the `XDG_RUNTIME_DIR` and user D-Bus
  session rootless Podman's networking needs.

### Leak-sweep contract

The final integration step asserts that no test container survived the
run. This subsection is the testable specification of that step; the
parsing and predicate logic lives in one `python3` snippet per backend so
the same code can be exercised as a unit test against the checked-in
fixtures.

**Leak predicate.** Let `WORK` be the canonicalized (`realpath`) path of
the run's temporary workspace. jms canonicalizes every mount source
through `canon()` before launch, so the source recorded in engine metadata
is already canonical; the comparison is therefore an exact string test
with no compare-time normalization: a container **leaks** iff any of its
mount entries has a string source equal to `WORK` or beginning with
`WORK + "/"`. No globbing, no case folding, no symlink resolution at
compare time.

**Enumeration on Podman — two steps, both parsed strictly, fail closed.**
The `ps` JSON `Mounts` field carries target paths only, so sources come
from `inspect`:

1. `podman ps --all --format json` — must be a JSON array (empty passes:
   no containers) of maps whose `Id` is a 64-character lowercase-hex
   string.
2. Per ID, `podman inspect --type container --format json <id>` (the ID
   passed exactly as returned) — must be a single-element array of one
   map whose `Mounts` is an array of maps with string `Source` and
   `Destination`. Every entry is evaluated against the leak predicate
   regardless of its `Type` — a leak is a leak however it was mounted.

Any other shape at either step aborts as a **sweep failure** (below); a
malformed record is never skipped, because a skipped record could hide a
leak. The 5.4.2 `ps` and `inspect` fixtures captured during
implementation back the snippet's unit tests.

**The single tolerated race.** A container may exit and be removed between
steps 1 and 2 (jms launches pass `--rm`). The sweep never matches
`inspect` stderr (the MIR-043 rule shape, applied here by MIR-056);
instead a nonzero `inspect` exit triggers an existence recheck:
`podman container exists <id>` — exit 1 classifies the ID as gone (a
vanished container holds no mounts and is not a leak); exit 0 (the
container exists yet failed to inspect) and every other exit abort as a
sweep failure. That vanished-container recheck is the only failure the
sweep tolerates.

**Three mutually exclusive outcomes.**

| Outcome | Exit | Output contract |
| --- | --- | --- |
| Clean | 0 | nothing required |
| Leak found | nonzero | names every leaking container ID and each offending mount source |
| Sweep failure | nonzero | a diagnostic distinct from the leak message, quoting what failed to parse or execute |

A sweep that cannot complete must fail the integration run — fail
closed — and must never be conflated with "leak found", so a schema drift
in a future Podman shows up as its own signal rather than as a phantom
leak.

**apple/container is unchanged.** `container list --all --format json`
already embeds `configuration.mounts[].source`, so macOS stays
single-pass, applying the same leak predicate and the same three-outcome
contract to that schema.

**Coverage note.** Auto-removed containers never appear in `ps --all`
(re-verified on 5.4.2 during implementation), so the sweep observes
exactly the leak classes cleanup
is responsible for: containers still running and containers that failed
before removal. This matches the apple/container sweep's semantics.

### Requirements-to-tests table

This table is normative: every behavioral claim in §§3–8 maps to at least
one named test, and a change to §§3–8 that adds or alters a claim must
update its row in the same change. Test names are the planned identities;
existing names are reused where the test already exists. Tiers: **unit**
(fake-runtime/fixture tests in `tests/test_jms.py`), **conformance** (the
both-backend parametrized suite), **golden** (golden argv unit tests),
**int-A/int-B** (integration tiers above), **macOS-int** (manual macOS
integration run), **doc** (release-blocking documentation review — used
only for non-enforceable wording, never for a behavioral claim).

| ID | § | Claim | Tier | Test |
| --- | --- | --- | --- | --- |
| R3.1 | 3 | every repository-owned image pins `isolation` to UID/GID 1000; `ISOLATION_UID` and `ISOLATION_GID` agree with both Containerfiles | unit | `test_isolation_identity_constants_match_containerfiles` |
| R3.2 | 3, 7.1 | image content cannot influence the runtime UID: Podman launch argv passes numeric `--user` on both variants and no jms code path inspects an image filesystem | golden + conformance | launch argv goldens (R7.1); conformance case asserting no backend exposes an image-inspection operation |
| R3.4 | 3 | rebuilt base image behaves as designed on macOS | macOS-int | rebuild-and-verify run of the full integration script |
| R3.5 | 3 | Podman `local_name()` strips `localhost/` so tag-prefix ownership checks work unmodified | conformance | `local_name` cases in the conformance suite |
| R3.6 | 3 | `image_exists` matches the `localhost/`-prefixed stored name | int-A | base built then `image_exists` true via a `jms build` no-op path; unit exit-code cases in R5.1 |
| R3.7 | 3 | `FROM jmscontainers-base:latest` resolves locally under `--pull=missing` with no registry contact when present; base absent fails non-interactively with the conditional missing-base hint (no speed claim — MIR-055); a clean-store standalone project fetches its external base | unit + int-A + int-B | FROM-resolution check via jms under the harness egress denial; clean-store standalone build (tier B); unit test pinning the conditional hint wording |
| R3.9 | 3, 7.1 | a standalone image launched through jms resolves the numeric process and named account to `1000:1000`, declares `/home/isolation` and `/bin/bash`, has a writable `1000:1000` home, supports passwordless sudo, and writes `/work` files with invoking-host ownership | int-B + macOS-int | clean-store standalone ABI launch assertions (tier B on Podman); clean-slate example launch in the macOS integration run |
| R4.1 | 4 | version first-line parsing: both formats, distro suffix truncation, malformed/non-numeric rejected, invalid UTF-8 fails closed | conformance | version-line fixtures |
| R4.2 | 4 | apple/container exact `min == max` pin and `JMS_RUNTIME_ACCEPT` unchanged | unit | existing `test_version_gate`, `test_runtime_accept_pin_admits_one_exact_newer_version` |
| R4.3 | 4 | Podman floor (5, 4, 0); anything at or above the floor accepted silently, no warning machinery; `JMS_RUNTIME_ACCEPT` ignored on Podman | unit | `test_podman_version_floor` |
| R4.4 | 4 | `ensure_started()` validates `podman info` JSON: remote, rootful, malformed/insufficient ID maps (coverage of `[0, 65536)`), absent graph driver, invalid JSON each fail with their own hint and verbatim stderr; healthy engine passes — metadata readability only, no storage-usability claim (MIR-050) | unit + int-A | `test_podman_readiness_matrix` over info fixtures plus boundary fixtures (coverage through 65535 passes, through 65534 fails, per map independently; malformed entries fail distinctly); tier-A preflight on a fresh non-1000 user |
| R4.5 | 4 | side-effect-free `runtime()` selection precedes consent; `approve()` runs before `runtime_ready()` on both backends; grant-then-preflight-failure leaves a valid grant | unit | `test_consent_precedes_runtime_readiness` (accepted, declined, non-interactive failure, missing runtime, unusable rootless Podman) plus selection-failure rows asserting no prompt, store write, or process call |
| R4.6 | 4 | `canon()` fails with the coreutils hint when `/bin/realpath` is missing, on both platforms, before any prompt, store write, or runtime process | unit | `test_canon_missing_realpath_diagnostic` (matrix: `build`, `launch`, `inspect`, `init`, store-only trust forms) |
| R4.7 | 4 | Podman diagnostics name the Debian 13 contract: the CLI-missing hint is the full qualified apt command, the ID-map hint names `uidmap` and `/etc/subuid`/`/etc/subgid`, and both agree verbatim with the README | unit | `test_podman_diagnostics_match_debian_contract` |
| R5.1 | 5 | `image_exists` tri-state: 0 true, 1 false, other exit hard failure with stderr | conformance | existing `test_image_exists_distinguishes_absence_from_failure`, parametrized |
| R5.2 | 5 | `image_facts()` strict fixture-backed normalizer; dangling skipped by rule; null/absent `Labels` normalizes to `{}` (MIR-053); malformed ownership-relevant field aborts | unit | `test_podman_image_facts_normalizer` over fixtures + malformed variants, including null, absent, and non-map `Labels` |
| R5.3 | 5 | `created` is Unix epoch seconds on both backends; ordering never compares backend-local shapes | conformance | mixed-timestamp retention-ordering cases |
| R5.4 | 5 | retention counts distinct image IDs; deletion untags per jms-owned ref with `--no-prune` on Podman (MIR-042); an alias outside the reserved namespace survives (MIR-047); label **and** tag-prefix ownership per ref | conformance + int-B + macOS-int | multi-tag, duplicate ID, inherited labels, base-with-children, partial deletion failure; survivor-set graph run on both real runtimes (tier B on Podman, the macOS integration run on apple/container) |
| R5.5 | 5 | `ps()` strict normalizer: full 64-char `Id`, top-level `Labels` with null/absent normalizing to `{}` (MIR-053); malformed record aborts | unit | `test_podman_ps_normalizer` over `ps` fixtures + malformed variants, including null, absent, and non-map `Labels` |
| R5.6 | 5 | stop may fail, forced delete authoritative, on both backends: a `failed` stop result never skips `remove_container` | unit | existing `test_stop_failure_does_not_abort_deletion` under both fakes |
| R5.7 | 5 | schedule/execute split with per-call-site policy (MIR-048): warn-only GC (including enumeration failures), exit-1 aggregation for `clean`/purge, revocation durable through every purge failure; attempt-all, vanished resources tolerated as success, second run converges | conformance | `CleanupPartialFailureTests` (readiness, enumeration, and every stop/remove/untag position injected, every caller, both backends) |
| R5.8 | 5 | cleanup ownership requires `jms.project` **and** `jms.container=launch`; builds stamp the neutral value overriding any preseeded label; inherited-label, manual, and marker-absent containers never selected; dry-run and real cleanup select the same IDs | conformance + golden | `test_cleanup_provenance_predicate` (jms-launched, manual-from-jms-image, unrelated `jms-` name, malicious preseed, marker-absent) plus build/launch argv goldens pinning both label stamps on both backends |
| R5.9 | 2, 5 | removal operations return normalized `RemovalResult`s: success and absence → `removed` (Podman via `--ignore` at the engine, apple/container via post-failure existence recheck on all three operations, stop included — MIR-043/052); a failed stop superseded by a successful remove is dropped; a recheck that itself fails leaves `failed` with the original diagnostic plus an appended recheck-failure note and never raises (MIR-052); any other failure → `failed` with non-empty terminal-safe `detail` (stderr → stdout → fixed placeholder); command code never sees a `CompletedProcess`, raw stderr, or a backend branch | conformance + macOS-int | `RemovalClassificationTests` (all three operations, both backends; absent-stop → `removed`; recheck-present stays `failed`; injected recheck failures; empty-output and stdout-only cases); manual macOS race test proving idempotent cleanup under a vanished-mid-removal resource (MIR-043) |
| R5.10 | 5 | shared id/ref/label validation aborts on violations under both backends; apple/container grouping: reordered duplicates, repeated refs, and mixed dangling/named records for one ID yield the identical `ImageFact`, conflicting `created` or label data aborts; a duplicate Podman `Id` aborts as malformed | conformance | `test_image_fact_accumulator` |
| R6.1 | 6 | per-backend build argv: label flag spelling, `--pull=always` base-with-pull, `--pull=missing` project builds | golden | `test_build_argv_golden` per backend |
| R6.2 | 6 | v2 context-escape failure still trips `CONTEXT_NOTE` under Podman | int-B | existing escape test, parametrized |
| R7.1 | 7.1 | explicit `--userns` and numeric `--user` on both variants: `keep-id:uid=1000,gid=1000` + `--user 1000:1000` default, `host` + `--user 0:0` under `--root` | golden | launch argv goldens (default, `--root`, manifest mounts, `--auth`) |
| R7.2 | 7.1 | default launch: `/work` writes host-owned by the invoking user; in-container UID 1000 | int-A | ownership (default) assertion |
| R7.3 | 7.1 | `--root`: in-container UID 0; `/work` writes still host-owned by the invoking user | int-A | ownership (`--root`) assertion |
| R7.4 | 7.1 | conflicting `PODMAN_USERNS` and `containers.conf` lose to the explicit flag for both variants | int-A | ambient-config conflict runs |
| R7.5 | 7.1 | passwordless sudo works for `isolation` under `keep-id` | int-A | `sudo -n true` assertion |
| R7.6 | 7.2 | per-backend mount grammar (`type=bind` on Podman), readonly suffix; `,`/`=`/NUL/invalid-UTF-8 sources rejected with identical errors | conformance | existing `test_mount_argument_serialization`, parametrized + rejection cases |
| R7.7 | 7.2 | `--security-opt label=disable` always passed on Podman and accepted on the minimum version | golden + int-A | launch argv goldens; every tier-A run |
| R7.8 | 7.3 | `--hostname container` passed; `$HOSTNAME` inside agrees | golden + int-A | launch argv goldens; hostname assertion |
| R7.9 | 7 | env ordering (`CLAUDE_CONFIG_DIR` first, manifest env sorted) and entrypoint/command shape preserved verbatim | golden + int-A/B | launch argv goldens; env/entrypoint parity assertions (auth path in tier B) |
| R7.10 | 7 | `launch` exits with the container's status via `execvp`; an interrupted launch leaves no container | int-A | exit-propagation (`exit 7`) and SIGTERM assertions |
| R7.11 | 7 | shell-state mount is read-only inside the container | int-A | read-only shell-state write-failure assertion |
| R7.12 | 7 | credential/agent-state mounts (`--auth`) are present, writable, and host-owned by the invoking user | int-B | auth-mount assertions |
| R7.13 | 7 | cleanup and leak sweep run after partial failures; sweep failure distinct from leak; vanished-mid-sweep IDs classified by `container exists` recheck, not stderr matching (MIR-056) | unit + int-A | sweep-snippet unit tests over fixtures, covering all three `container exists` recheck outcomes; deliberate failed-run cleanup check |
| R7.14 | 7 | nested bwrap: `--unshare-user` works, full sandbox fails on masked `/proc`; jms never passes `unmask` | int-A + golden | bwrap probes recording agent/sandbox versions; goldens prove no `unmask` in any argv |
| R8.1 | 8 | container "root" is an unprivileged mapped UID of the invoking user | int-A | covered by R7.3 (UID 0 inside, invoking-user ownership outside) |
| R8.2 | 8 | sudo-inside-container claim as stated in SECURITY.md | int-A | covered by R7.5 |
| R8.3 | 8 | read-only shell mount behaves as documented | int-A | covered by R7.11 |
| R8.4 | 8 | threat-model wording: kernel/OCI-runtime trust, the ambient-configuration trust assumption (MIR-040), escape consequences, weaker-than-VM statement, mounted-data exposure, SELinux/supplementary-group limitations, reserved-namespace and concurrency limitation (MIR-047) | doc | release-blocking SECURITY.md/README review; non-enforceable by construction — no behavioral claim rides on it |

Every behavioral claim maps to a unit, conformance, golden, or integration
test; the only **doc** row is R8.4, which contains no enforceable
behavior. Selection, laziness, and remote rejection (§2) are covered by
the unit-test plan above.

### CI (`.github/workflows/test.yml`)

- Existing matrix (`make test` on Ubuntu 3.11/3.14 + macOS) unchanged; it
  now also exercises the Podman fake on the Ubuntu legs automatically.
- **No nested Linux integration job** (MIR-033, superseded): the earlier
  revision specified a full `integration-linux` contract — privileged
  rootful-Docker outer container, `scripts/ci-debian-nested.sh`,
  subordinate-ID plumbing, divergence records, a 4-green-run promotion
  protocol — that amounted to a second, lower-fidelity copy of the
  qualification the release checklist performs by hand. For 1.1.0, the
  Linux gates are real-host only (MIR-049): both integration tiers run
  green on a real Debian 13 amd64 host with a fresh non-root, non-1000
  user, plus the release-blocking manual clean-host walkthrough (§10).
  No nested harness is specified or gating. macOS integration remains
  manual (no nested virtualization on GH macOS runners). A CI job can be
  reintroduced, with the MIR-033 finding as its requirements list, if
  the project gains contributors who need PR-time Linux signal.

---

## 10. Documentation and packaging checklist

- `README.md`: platform section becomes "Apple Silicon Mac
  (apple/container) **or** Debian 13 (amd64) with rootless Podman ≥ 5.4",
  using the MIR-039 vocabulary throughout: **refused** covers exactly
  non-Linux/non-macOS platforms, uid 0 on Linux, and remote Podman;
  everything else outside the qualified matrix — other distributions,
  arm64, SELinux-enforcing hosts — is **unqualified but allowed** (no
  detection, no warning), naming recent Fedora and Ubuntu and the arm64
  architecture as mid-term qualification targets,
  supplementary-group/ACL-only project access as unsupported,
  and NFS/distributed home directories as unsupported (rootless Podman
  storage under `~/.local/share/containers` is known-broken on NFS; not
  detected — heuristics false-positive too easily — the failure surfaces
  at the first build or launch, or at `podman info` when storage
  initialization fails outright, with Podman's own stderr — MIR-050). Install
  instructions per platform — the Linux instructions name the explicit
  qualified package set with one command,
  `sudo apt install podman uidmap passt dbus-user-session fuse-overlayfs
  coreutils`. This list is load-bearing, not belt-and-braces: on
  Debian 13, `uidmap`, `passt`, and `dbus-user-session` are only
  *Recommends* of `podman`, so a Recommends-disabled minimal install
  silently lacks them. Note that Debian's `adduser` provisions
  subuid/subgid ranges for new users automatically. Stack line gains a
  Linux variant (`Linux → rootless podman (user namespace) → Fedora → …`);
  isolation wording per §8.
- `docs/cli.md`: new "Runtimes" section (platform selection rules,
  per-backend qualification policy); `JMS_RUNTIME_ACCEPT` marked
  apple/container-only; exit-code table unchanged.
- `SECURITY.md`: per-platform boundary statement (§8), including the
  ambient-configuration trust assumption (MIR-040); `label=disable`
  rationale and the SELinux-enforcing-host limitation (§7.2);
  rootless-only statement; the owner-based host-permission contract
  (§7.1); the NFS/distributed-home limitation; the nested-bwrap
  limitation with no unmask recommendation (§7's nested-sandbox
  caveat). README additionally documents the reserved image-ref
  namespace and the same-store concurrency limitation (MIR-047).
- `docs/release-checklist.md`: record the tested Podman version,
  architecture (`uname -m`), and the remaining matrix dimensions (kernel,
  cgroup manager, OCI runtime, storage driver, network backend) per
  release; a Linux integration run; and the clean-host install
  walkthrough: a fresh Debian 13 VM plus a newly created user follows the
  README install instructions verbatim each release, recording date,
  Podman version, architecture, and outcome. No automated CI substitute —
  nested-container fidelity to a real workstation is limited, and the
  walkthrough is cheap at release cadence.
- `completions/jms.bash`: no runtime references — unchanged.
- `Makefile`: unchanged (`make install` already works on Linux;
  `~/.local/bin` is on PATH by default on most distros — soften the
  macOS-specific PATH note in the README).
- `CHANGELOG.md`: 1.1.0 entry; minor version bump (Linux support added,
  apple/container pin moves to 1.2.0, cleanup reports aggregated
  failures).

---

## 11. Implementation plan

Work proceeds on this branch and merges when complete; nothing is
released until the docs in §10 land, so no runtime gate or phased
enablement is needed.

1. **Backend seam + argv.** Extract the `Backend` protocol with lazy
   `runtime()` selection as a behavior-neutral refactor (full existing
   suite green, golden fingerprints unchanged), then implement the
   Podman backend's non-parsing surface per §§4–7 — selection,
   readiness policy, argv assembly — plus the golden argv tests,
   selection/laziness tests, and the fixture-independent conformance
   cases (version-line parsing, mount grammar). The normalizers are
   deliberately absent from this phase (MIR-054). Pin the `isolation`
   UID/GID in the Containerfile (§3) and rebuild-and-verify on macOS.
2. **Fixtures, then normalizers, then Linux integration.** First
   capture, review, and commit the complete fixture set per the MIR-044
   provenance contract (images, `ps`, `inspect`) on the qualified
   engines — Debian 13's Podman and apple/container 1.2.0; only then
   implement the normalizers and removal classification against those
   fixtures, with the parametrized fakes and the fixture-dependent
   conformance suite (a normalizer lands only after its fixtures —
   MIR-044/054). Then parametrize `scripts/integration.sh`; add the
   ownership and FROM-resolution assertions; move
   `examples/clean-slate` to its fully qualified base (MIR-041); run
   both tiers on a real Debian 13 amd64 host (no CI job and no nested
   harness — MIR-033/049). Fix whatever reality disagrees with (most
   likely: short-name FROM resolution details, seccomp interactions
   with the agent CLIs).
3. **Docs + release.** Land §§8 and 10 in full — SECURITY.md, README, CLI
   docs, installation docs, changelog — then release 1.1.0 per the
   release checklist, recording the tested Podman version (Debian 13's
   packaged 5.4.x).

## 12. Explicit non-goals

- **Docker support.** Docker's rootless mode, JSON schemas, and label
  semantics differ; nothing here precludes a later `DockerBackend`, but
  qualifying it is separate work.
- **Root Podman.** Refused at selection (§2); it would silently change
  the security story.
- **Remote Podman.** Refused at readiness via `host.serviceIsRemote`
  (§§2, 4); a remote service invalidates the local-path mount semantics
  and the rootless threat model.
- **Fedora and Ubuntu as host platforms (for 1.1.0).** Mid-term targets;
  1.1.0 qualifies Debian 13 only. Unqualified but allowed, not refused
  (MIR-039).
- **SELinux-enforcing hosts (for 1.1.0).** Desired, deferred with the
  Fedora host target. A documented limitation — unqualified but allowed,
  not detected or refused.
- **Linux architectures other than amd64 (for 1.1.0).** arm64 is a
  mid-term target, unqualified but allowed (MIR-039); the base image's
  npm tools and example downloads get their arm64 audit at promotion
  time.
- **NFS/distributed home directories.** Unsupported and documented, not
  detected. A qualified `storage.conf` relocation is possible follow-up
  work if the limitation proves painful.
- **Cross-runtime image sharing.** Images are per-runtime-store; a user
  on both platforms builds the base twice. Fingerprint-derived tags make
  this transparent.
- **Weakening container defaults for nested bwrap** (§7's nested-sandbox
  caveat).
- **Image-content attestation.** jms never inspects an image's
  filesystem: the numeric `--user` (§7.1) makes the runtime UID
  independent of image content, superseding the earlier probe design
  (MIR-034/036/037). Account name, home, shell, ownership, and sudo state
  remain the image author's responsibility under the documented ABI; a
  mismatch makes the image nonconforming rather than changing the runtime
  identity.
- **Automated Linux integration in CI (for 1.1.0).** The nested
  `integration-linux` job is dropped (MIR-033, superseded), and no local
  nested harness is specified or gating (MIR-049); the real-host
  integration run and the §10 clean-host walkthrough qualify the
  release. Reintroduction awaits contributors who need PR-time signal.
