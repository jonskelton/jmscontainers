# 1.1.0 release-critical issues

Review target: `main...multi-runtime` at `c5157cd`
Reviewed: 2026-07-30; updated 2026-07-31 after a live macOS validation
pass, then again 2026-07-31 closing RC-002/RC-005 and landing the RC-003
procedures
Merge disposition: **not ready**

This register contains only issues that must be resolved or explicitly closed
with qualification evidence before 1.1.0 is merged for release.

Status values:

- **Open** — a code, documentation, or test change is required.
- **Awaiting qualification** — the implementation may be complete, but a
  required real-host gate has not been recorded.
- **Closed** — the resolution and its validation evidence are recorded here.

## RC-001 — Standalone images have an undeclared `1000:1000` runtime ABI

- **Severity:** Blocker
- **Status:** Awaiting qualification
- **Affected:** `bin/jms:493-503`, `README.md:197-199`,
  `examples/clean-slate/.jmscontainer/Containerfile:5-8`

### Finding

The Podman backend always launches the default user as numeric
`--user 1000:1000` and maps the invoking host user to that numeric identity.
Only the repository base image pins `isolation` to UID/GID 1000. The public
project-image contract says merely that the runtime user must exist and have a
home directory and `/bin/bash`, and the standalone example creates
`isolation` without explicit UID/GID values.

Consequently, a valid standalone definition whose `isolation` account is not
exactly `1000:1000` runs as the wrong account (or as an account absent from
`/etc/passwd`) on Linux. Its login-shell home, passwordless-sudo rule, and
mounted state paths can then disagree with the actual process identity. The
same image is selected by account name on macOS, so this also violates the
claim that the project contract is shared across backends.

### Required resolution

Choose and implement one contract:

1. Support arbitrary `isolation` UID/GID values consistently across both
   backends; or
2. Make `1000:1000` an explicit project-image ABI everywhere it is described,
   pin the standalone example with `groupadd -g 1000` and
   `useradd -u 1000 -g 1000`, and add a real-runtime assertion that the
   standalone example resolves `isolation` to `1000:1000`, has the expected
   home, and retains passwordless sudo.

### Close when

- The README, example, implementation record, and behavior state one
  consistent image-user contract.
- Unit coverage pins the chosen contract.
- The standalone image passes the Linux real-runtime launch assertions.

### Implementation status

The repository now declares the fixed `isolation` `1000:1000` ABI, pins both
repository-owned Containerfiles to the runtime UID/GID constants, and adds
the complete standalone launch assertions to integration tier B. `make test`
passes. RC-001 remains open pending a green `scripts/integration.sh all` run
on the qualified fresh non-1000 Debian/Podman host.

## RC-002 — The documented SELinux support state contradicts the release scope

- **Severity:** Blocker
- **Status:** Closed
- **Affected:** `SECURITY.md:79-80`, `README.md:60-67`,
  `docs/cli.md:39-42`, `CHANGELOG.md:17-21`,
  `docs/multi-runtime-implementation.md:334-362`

### Finding

The resolved MIR-039 contract says every local rootless Linux configuration
other than the three explicit refusals is **unqualified but allowed**, and its
done condition requires README, SECURITY.md, CLI docs, and release material to
use that vocabulary consistently. README, CLI docs, the changelog, and the
implementation record do so. SECURITY.md instead says SELinux-enforcing hosts
are “unqualified and unsupported.”

The release checklist makes this cross-document security-boundary review
release-blocking. Users cannot tell whether SELinux enforcement is an allowed,
unqualified configuration or an unsupported configuration.

### Required resolution

Use one support classification in SECURITY.md, README, CLI docs, changelog,
and the implementation record. If MIR-039 remains authoritative, SECURITY.md
must say “unqualified but allowed” and may separately describe the absence of
qualification/support guarantees. If “unsupported” is intended as the product
policy, revise MIR-039 and every public support statement together.

### Close when

- All support documents use one unambiguous classification.
- A documentation test or review assertion prevents the vocabulary from
  diverging again.

### Resolution

2026-07-31: MIR-039 remains authoritative. SECURITY.md now classifies
SELinux-enforcing hosts as **unqualified but allowed**, with the absence of
qualification/support guarantees described separately in the same bullet.
The two stale sites inside the implementation record itself (§7.2's
"record it as unsupported for now" instruction and the boundary-statement
decision copy) were aligned to the same vocabulary. A new unit test
(`SupportVocabularyTests.test_selinux_classification_is_unqualified_but_allowed`)
asserts every public support document (README, SECURITY.md, CLI docs,
changelog) contains "unqualified but allowed" and that no
SELinux-enforcing paragraph or bullet says "unsupported"; the guard was
mutation-tested against the old SECURITY.md wording and fails on it. The
189-test suite passes.

## RC-003 — Required apple/container cleanup-safety acceptance is absent

- **Severity:** Blocker
- **Status:** Awaiting qualification
- **Affected:** `scripts/integration.sh:268-299`,
  `docs/release-checklist.md:15-23`,
  `docs/multi-runtime-implementation.md:2245,2250`

### Finding

The release checklist requires the first 1.1.0 macOS qualification to prove
that deleting one jms-owned image ref does not delete an alias outside the
reserved namespace or cascade into unselected images. It also requires the
vanished-mid-removal race test. The requirements table assigns the
survivor-set graph to both real runtimes.

The only survivor-set implementation is inside
`if [ "$runtime" = podman ]`; no equivalent apple/container acceptance or
executable manual procedure exists. The removal-race test likewise has no
executable procedure or recorded result. Unit fakes cannot establish the
real engine's delete-by-ref behavior. Until this is proven, `jms clean
--images` and background retention may remove non-jms aliases on macOS.

### Required resolution

- Add an apple/container survivor-set acceptance to the integration harness,
  or check in exact executable manual steps with expected survivor identities.
- Add exact steps for the vanished-mid-removal race.
- Run both against apple/container 1.2.0 and record the results.
- If delete-by-ref cascades, change the cleanup design before qualification.

### Close when

- A recorded apple/container 1.2.0 run proves the external alias and every
  unselected image survive.
- A recorded race run proves cleanup converges when a selected resource
  vanishes during removal.

### Implementation status

2026-07-31: both procedures are now checked in; neither has run against
the real engine yet.

- Integration tier B gained an apple/container survivor-set acceptance
  mirroring the Podman branch: build a labeled project image, alias it
  outside the reserved namespace with `container image tag`, run
  `jms clean --images`, then assert from `container image list --format
  json` that the alias survives on the same image identity, that no
  `jmscontainers-*` ref survives on it, and that the unselected base image
  still inspects. A cascade fails the run with an explicit MIR-042
  message. The Podman dangling-image case has no apple equivalent by
  design (the apple normalizer excludes ref-less records). The embedded
  JSON parsers were validated against the checked-in
  `apple-container-1.2.0-images.json` fixture shapes.
- The manual vanished-mid-removal race test now has exact executable
  steps and pass criteria in the release-checklist appendix (ten-iteration
  external-delete race, idempotent-convergence criteria, recording
  requirement).

Closing still requires the recorded apple/container 1.2.0 runs of both.

## RC-004 — Mandatory real-host release qualification is not recorded

- **Severity:** Blocker
- **Status:** Awaiting qualification
- **Affected:** `docs/release-checklist.md:15-36`, `CHANGELOG.md:3-43`

### Finding

The branch contains fixtures and fake-runtime/unit coverage, but no evidence
for the mandatory release-host gates:

- full integration on macOS with apple/container 1.2.0;
- both integration tiers on a fresh Debian 13 amd64 host under a non-1000
  user and primary group;
- the clean-host Debian install walkthrough; and
- the tested Podman/runtime matrix dimensions required in the release notes.

The 1.1.0 changelog does not record the Podman version, kernel, cgroup
manager, OCI runtime, storage driver, network backend, architecture, or
walkthrough outcome.

### Required resolution

Run the checklist exactly as written after RC-001 through RC-003 are fixed,
then record:

- commit under test and date;
- platform/runtime versions and all required matrix dimensions;
- integration tier outcomes;
- clean-host install outcome; and
- any qualification exceptions.

### Close when

- macOS and Debian real-host gates are green on the final candidate commit.
- The required matrix and walkthrough evidence is present in the release
  notes or linked from this register.

### Implementation status

2026-07-31, macOS half: `scripts/integration.sh all` ran at `c5157cd` against
apple/container 1.2.0 with zero assertion failures through tier A and tier B
up to the credential-mount step, which requires an interactive terminal
(`--trust --auth` prompts by design) and fails non-interactively with
"credential access is required but prompting is unavailable". The
credential-mount assertion itself was validated out-of-band via the audited
`JMS_TRUST_FINGERPRINT` pin: the agent-state write landed in
`~/.local/share/jmscontainers/agents/claude/`, owned by the invoking user,
with `CLAUDE_CONFIG_DIR` visible inside. The recorded macOS gate still
requires one full interactive `scripts/integration.sh all` run on the final
candidate commit. The Debian gates remain not run.

## RC-005 — `make test` fails wherever shellcheck is installed

- **Severity:** Blocker
- **Status:** Closed
- **Affected:** `scripts/integration.sh:44,255,260,303`, `Makefile:19-27`

### Finding

The `test` target runs shellcheck over `scripts/integration.sh` when the tool
is present and treats any nonzero exit as failure. The current script trips
one SC2034 warning (`sweep_status_file` is assigned at line 44 and never
used) and six info-level SC2016/SC2015 notes, so `make test` — a required
release-checklist gate — is red on any host with shellcheck installed,
including the macOS validation host. The 2026-07-30 verification log recorded
`make test` as passing because the review environment lacked shellcheck.

### Required resolution

Remove the dead `sweep_status_file` assignment (or use it), and either fix or
explicitly annotate the SC2016/SC2015 sites so shellcheck exits zero.

### Close when

- `make test` passes on a host with shellcheck installed.

### Resolution

2026-07-31: the dead `sweep_status_file` assignment is removed (SC2034);
the egress-denial population was restructured from `A && B && C || {…}`
into an explicit `if ! … || ! … || ! …` chain (SC2015); and the five
SC2016 notes — all single-quoted `$VAR` strings deliberately expanded by
the shell inside the container, a systematic idiom in the harness — are
covered by one justified file-level
`# shellcheck disable=SC2016` directive. Validated: `make test` passes
with shellcheck 0.10.0 on PATH (189 unit tests plus a clean shellcheck
leg over `scripts/integration.sh` and `completions/jms.bash`).

## RC-006 — Cold-launch stdout carried the built image ref

- **Severity:** Blocker
- **Status:** Closed
- **Affected:** `bin/jms:1349-1356`

### Finding

`run_build` invoked the runtime with `capture=False`, so the build subprocess
inherited jms's stdout. Both engines print the built image ref on stdout
(apple/container prints the tag; Podman prints the image ID), so a cold
`jms launch` — which builds implicitly — prefixed the container's stdout with
the ref line, corrupting any `$(jms launch ...)` capture. Warm launches were
unaffected. Caught live by the tier B manifest env parity assertion on macOS
with apple/container 1.2.0; the Podman path shared the defect, meaning the
assertion could only have passed on a Linux host with the project image
already warm.

### Resolution

Fixed in `c5157cd`: `run_build` now routes the build subprocess's stdout to
stderr, keeping jms's stdout reserved for the container during launch.
Validated on macOS: a cold-launch `$(jms launch ... -c 'echo "$JMS_ITEST"')`
capture yields exactly the manifest value, and the 188-test unit suite
passes. The Linux side is covered by the RC-004 qualification rerun.

## Verification log

| Check | Result | Notes |
| --- | --- | --- |
| `make test` | Pass | 188 tests on Python 3.13.5; review environment lacked shellcheck (see RC-005) |
| `git diff --check main...HEAD` | Pass | No whitespace errors |
| Real Podman integration | Not run | Sandbox makes `/run/user/1000/libpod` read-only; this would not satisfy the required fresh non-1000 host gate in any case |
| apple/container integration | Not run | No macOS runtime available in the review environment |
| Unit suite at `c5157cd` (2026-07-31) | Pass | 188 tests on macOS |
| apple/container integration at `c5157cd` (2026-07-31) | Pass to the interactive gate | container 1.2.0; tiers A and B green through the credential-mount prompt, which needs a tty (see RC-004 implementation status); found and fixed RC-006 en route |
