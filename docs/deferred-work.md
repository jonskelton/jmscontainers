# Deferred work

Work that has been identified, judged worth doing, and deliberately not
scheduled for 1.1.0. Nothing here blocks a release — release blockers live in
[release-critical-issues.md](release-critical-issues.md), and release gates in
the [release checklist](release-checklist.md).

Opened 2026-08-03 from a review of the rootless Podman backend at `b54c1c0`.
The four items that review raised as cheap and verifiable from source were
fixed on `1.1.x-bugfixes`; these are the ones that were not, because each
needs a qualified host, changes launch behavior, or is a product decision
rather than a defect.

Status values:

- **Accepted** — should be done; the open question is when, not whether.
- **Proposed** — recorded for judgment; not yet agreed to be worth doing.

| ID | Item | Status | Effort | Blocked on |
| --- | --- | --- | --- | --- |
| DW-001 | Enforce a minimum Podman launch profile | Accepted | Medium | DW-002 |
| DW-002 | Real rootless-Podman smoke test in CI | Accepted | Medium | — |
| DW-003 | Reproducible base-image inputs | Accepted | Medium | A product decision (see below) |
| DW-004 | Qualify `--group-add=keep-groups` | Accepted | Small | Next Debian 13 qualification run |
| DW-005 | `jms doctor` diagnostic | Proposed | Small–medium | Judgment; DW-002 may cover most of the need |

Suggested order: **DW-002 → DW-001**, since changing launch argv without a
real-Podman feedback loop is how a boundary regression ships unnoticed.
DW-003 is independent and has the best value-per-effort of the group. DW-004
should ride the next Debian gate rather than being scheduled on its own.

---

## DW-001 — The effective Podman sandbox is ambient

**Status:** Accepted. **Interim mitigation shipped** (`ac8c494`): the README
now states as a Linux prerequisite that jms does not enforce a Podman sandbox
profile. That makes the gap disclosed rather than hidden; it does not close
it.

### Why it matters

`PodmanBackend.run_argv()` pins the numeric user, the user-namespace mapping,
the hostname, and `label=disable`, and accepts everything else from the host:
`containers.conf` and its drop-ins can set `privileged`, `default_capabilities`,
`devices`, host `pidns`/`ipcns`/`cgroupns`/`utsns`/`netns`, automatic mounts
and volumes, and OCI hook directories. `ensure_started()` verifies local,
rootless operation and ID-map coverage, and checks none of that.

So two users can run the same jms release and the same approved project
definition and get materially different host exposure. Rootless privileged
mode still cannot exceed the invoking account's authority — but on a
single-user development machine that account's authority is most of what the
boundary is protecting.

This is accurately disclosed in `SECURITY.md`, so it is not a hidden bug. It
is a product risk for a tool whose value proposition is a predictable
isolation boundary.

### What to do

Define an explicit jms Linux launch profile and force every setting essential
to the boundary. At minimum investigate and qualify: explicit unprivileged
mode; private PID, IPC, UTS, and cgroup namespaces; a known capability
bounding set (`cap-drop=all` plus what the documented passwordless-sudo
workflow needs); seccomp enabled with a known profile; and no implicit host
devices, mounts, or hooks.

Two viable strategies — prefer explicit `podman run` flags where 5.4 has
reliable CLI overrides and fail readiness when a required feature is absent;
or run Podman under a jms-owned minimal configuration overlay, keeping only
the host settings that are operationally necessary. The overlay is more
deterministic and costs more compatibility. Either way, `storage.conf` and
registry policy stay in the trusted-host class: they are not container
isolation defaults and should not be conflated with them.

If the current policy is instead retained deliberately, this item closes as
*won't do* and the README prerequisite becomes the permanent answer.

### Done when

- Golden argv tests pin every isolation-critical override.
- An integration case injects hostile-but-valid `containers.conf` defaults and
  proves the effective container is still unprivileged, privately namespaced,
  seccomp-filtered, and free of an injected mount, device, or hook.
- Assertions read `podman inspect` — the effective result — not just the argv
  jms requested.
- `SECURITY.md` documents the smaller residual ambient surface.

---

## DW-002 — Real Podman behavior is absent from continuous testing

**Status:** Accepted.

### Why it matters

`.github/workflows/test.yml` runs `make test` on Ubuntu and macOS and never
installs or starts a container runtime. `scripts/integration.sh` is
deliberately not in PR CI, and the real-host gate is manual and
release-scoped. The unit suite validates the 5.4.2 JSON fixtures thoroughly,
but by construction it cannot detect changed flag interactions, runtime
cleanup behavior, signal forwarding, mount ownership, or effective security
settings. Runtime drift is currently first detected during a release.

### What to do

Keep the clean-host release gate exactly as it is, and add two cheaper loops
underneath it:

- A **PR smoke job** on a Linux runner using rootless Podman directly (not
  nested Podman): exercise `runtime_ready`, build a minimal local image,
  validate default and `--root` ownership, check read-only mounts and exit
  propagation, then clean and sweep. It need not build the large base image.
- A **scheduled or self-hosted Debian 13 job** running tier A, with the full
  tier A/B qualification still required for releases.

Upload `podman info`, `podman inspect` output, and integration logs as job
artifacts so a failure caused by runner drift is diagnosable without a local
repro.

### Done when

A PR that breaks a Podman launch contract fails CI rather than passing to the
release gate.

---

## DW-003 — Base-image inputs are mutable and unauditable

**Status:** Accepted, but it requires a product decision first — see below.

### Why it matters

`Containerfile` starts from `registry.fedoraproject.org/fedora:latest`, runs
`dnf -y upgrade`, and installs five unversioned global npm packages
(`@anthropic-ai/claude-code`, `@openai/codex`, `opencode-ai`, `pnpm`,
`@ast-grep/cli`). Identical repository source can therefore produce materially
different images on different days. Those tools then run against the user's
project tree and, when `--auth` is granted, against real agent credentials.

### The decision to make first

Floating inputs here are **intentional**, not an oversight: the Containerfile
header states "Rebuild = update", and `jms build --base --pull --no-cache` is
documented as the way to pick up the latest Fedora packages and agent CLIs.
Pinning changes that contract — updates stop being a side effect of rebuilding
and become an explicit, reviewed step. That trade (reproducibility and
auditability, at the cost of a refresh workflow) is the actual decision; the
mechanics below are easy once it is made.

### What to do, if pinning is chosen

- Pin the Fedora base by digest, keeping a readable tag alongside it.
- Pin the npm packages to exact versions in a checked-in manifest or lock.
- Refresh both automatically via a reviewed PR on a regular cadence.
- Publish the resolved base digest and agent versions in build output or an
  image label.
- Optionally generate an SBOM for release qualification.

Pinning every Fedora RPM is not worth the maintenance cost. The base digest
and the five npm tools capture most of the value.

---

## DW-004 — Supplementary groups are excluded without having been tested

**Status:** Accepted. Should ride the next Debian 13 qualification run rather
than be scheduled separately — it needs that host anyway.

### Why it matters

`SECURITY.md` documents the host-permission contract as owner-based only:
supplementary-group, ACL-only, and setgid workspace access are excluded, with
no preflight detection. Podman provides `--group-add=keep-groups` precisely to
preserve the invoking user's supplementary group access for rootless bind
mounts, and documents it as `crun`-only in the 5.x series — and the qualified
Debian record already runs `crun 1.21`. The limitation may therefore be
removable on the exact stack that is already qualified, which would fix a
common failure mode for corporate and shared development trees without
widening access beyond authority the invoking user already holds.

### What to do

Test the flag with both default and `--root` launches against a group-owned,
setgid directory. If it preserves the current ownership contract, enable it on
the qualified `crun` path, or expose it as an explicit opt-in with a clear
diagnostic on OCI runtimes that do not support it.

Do **not** claim ACL support on the strength of this flag. Named-user and
named-group ACLs depend on how the host identity is represented through the
user namespace and must be tested separately.

---

## DW-005 — An actionable Linux diagnostic (`jms doctor`)

**Status:** Proposed — recorded, not accepted. Recommend deciding this after
DW-002 lands.

### The case for it

`runtime_ready()` proves Podman answers, is local and rootless, reports
sufficient ID-map coverage, and names a graph driver. It deliberately proves
nothing about storage, mount, network, or launch usability, so those failures
surface only after a potentially expensive build, or at launch. A
`jms doctor` (or `jms inspect --runtime`) could print one copyable report:
versions, kernel, distribution, architecture, OCI runtime, cgroup manager,
graph driver and backing filesystem, network backend, rootless state and
effective ID maps, `XDG_RUNTIME_DIR` and user-session readiness, seccomp and
MAC status, a disposable ownership and read-only-mount probe, and a plain
verdict of qualified / unqualified-but-allowed / refused. It could also
generate most of the release qualification table.

### The case against it

It is net-new CLI surface on a tool whose auditability is part of its value,
and much of what it would report is exactly what DW-002 proposes to upload as
CI artifacts. If DW-002 lands first, the remaining unique value is
support-facing rather than development-facing, and may not justify the
surface.

### Done when

A decision is recorded here either way.
