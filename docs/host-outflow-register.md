# Host information-outflow register

Proposals for cleaning up unnecessary leaking of information, and for
containing the outflow of potentially sensitive information, from inside
jms containers to the host OS.

Opened 2026-08-30 from an observation on a live host: a Codex session run
inside a container left its complete conversation transcript on the host at
`~/.local/share/jmscontainers/agents/codex/sessions/2026/08/30/rollout-<timestamp>-<uuid>.jsonl`,
via the credential-grant mount. The transcript channel is real, is shared
across projects, and is not named by the consent prompt or the
documentation. This register generalizes from that observation to every
container-to-host outflow channel and proposes remedies.

Proposals are ordered by **criticality first, ROI second**. Nothing here is
a release blocker — release blockers live in
[release-critical-issues.md](release-critical-issues.md). Items accepted
here should either be scheduled directly or moved to
[deferred-work.md](deferred-work.md) with a cross-reference.

## Scope and non-goals

The [security model](../SECURITY.md) trusts the host: containers run under
the host kernel, under the invoking user's account, and jms does not defend
container work against a hostile host. **No proposal in this register
claims, or may grow into a claim, that container activity can be hidden
from the host.** That claim would be false on both backends and violates
the project's no-overclaim discipline.

What *is* in scope — the gap between "the host is trusted" and "everything
a container does silently accumulates on the host":

1. **Cross-container disclosure through host state.** State one container
   writes that a *later container from a different project* can read.
   This is the sharpest problem: the host is trusted, but other approved
   projects' images and agents are not.
2. **Incidental persistence.** Work product that outlives the container
   without the user having knowingly chosen that — and the accuracy of
   the consent language covering it.
3. **Host-side secondary spread.** Persisted state reaching backup, sync,
   and indexing tools, or other accounts on a shared host.

Out of scope: network egress from containers (approved containers have
network access by design), inflow from host to container (covered by the
trust model and the read-only shell mount), and Podman/apple-container
internals jms does not control.

## Channel inventory

The channels through which container work reaches the host, from source
(`bin/jms`) and the qualified-platform docs:

| Channel | Persistence | Assessment |
| --- | --- | --- |
| Project tree bind mount | Permanent, by design | The product; not a leak |
| Agent state mount (`agents/`) | Permanent, shared across all projects | **Primary subject of this register**: credentials, configuration, hooks, and full session transcripts |
| Container filesystem | None — `--rm` on every launch (`bin/jms:272,532`) | Adequate; writes outside mounts vanish at exit |
| Podman/apple-container image storage | Image layers and build cache persist | Image content, not session work product; out of scope |
| Manifest extra mounts | User-approved per project | Covered by the existing grant flow |
| Trust store (`store.json`) | Project paths and fingerprints | Host-side metadata about projects, not container output; minor |

Existing mitigations and their conditions: for custom project definitions,
build/run approval and agent-state access are separate grants; a new
interactive credential question defaults to no. A launch without a project
definition uses the shared base and mounts persistent agent state by default,
without a project credential prompt. `--no-auth` suppresses jms-managed
agent-state mounts for that launch. For a custom definition,
`run.mount_auth = false` suppresses the default mount, but an explicit
`--auth` can override it when credential access has been granted. New state
directories are created with mode `0700`; launches use `--rm`, and the
shared shell mount is read-only. See
[persistent agent state](agent-state.md#persistent-agent-state).

## Issue tracking

Status values:

- **Proposed** — recorded for judgment; not yet agreed to be worth doing.
- **Accepted** — should be done; the open question is when, not whether.
- **Implemented** — change landed; not yet in a release. Record the
  commit.
- **Closed** — released, or rejected with the reasoning recorded here.
  Closing evidence (commit, release, or qualification run) is recorded in
  the item.

Register (criticality first, ROI second):

| ID | Proposal | Criticality | ROI | Effort | Status |
| --- | --- | --- | --- | --- | --- |
| HO-001 | Name transcripts in the credential-grant consent and docs | High | High | Small | Proposed |
| HO-002 | Per-project agent-state profiles | High | Medium | Large | Proposed |
| HO-003 | `jms` session-history pruning | Medium | High | Small | Proposed |
| HO-004 | Credentials-only mount mode | Medium | Medium | Medium | Proposed |
| HO-005 | Documented outflow inventory and host-hygiene guidance | Medium | High | Small | Proposed |
| HO-006 | Verify permissions on pre-existing state directories | Low | Medium | Small | Proposed |
| HO-007 | Ship history-retention defaults into agent configuration | Low | Low | Small | Proposed |

Suggested order: **HO-001 and HO-005 immediately** (both are documentation
and prompt text; together they make the current behavior honest), then
**HO-003** (removes accumulated data cheaply), then **HO-002** (the real
fix for cross-project disclosure; HO-004 becomes largely redundant if
HO-002 lands first, and should be re-judged at that point).

---

## HO-001 — The credential grant undersells what it persists and shares

- **Criticality:** High — informed consent is the project's core trust
  mechanism; the current wording is materially incomplete.
- **ROI:** High. Text-only change.
- **Affected:** `bin/jms:1382,1460,1465`, `docs/agent-state.md:1-32`,
  `SECURITY.md` (credential-mount warning)

### Finding

The consent prompt reads "credentials and configuration for claude, codex,
and opencode" (`bin/jms:1460,1465`), and `docs/agent-state.md` frames the
mount the same way. In practice the mounted directories also accumulate
**complete session transcripts**: Codex rollout JSONLs under
`codex/sessions/`, Claude Code session history under `claude/projects/`,
and opencode session storage under `opencode/`. Transcripts routinely
contain source code, command output, and secrets pasted into prompts.

Because the pool is shared across every approved project, the grant also
hands each credential-granted container read-write access to the
transcripts of **every prior session from every other project**.
`SECURITY.md` discloses cross-contamination for settings and hooks
(integrity) but not the transcript pool (confidentiality).

### Proposal

1. Extend the consent prompt and the `jms trust` listing to name session
   history: e.g. "credentials, configuration, and accumulated session
   transcripts for claude, codex, and opencode — shared across all
   approved projects".
2. In `docs/agent-state.md`, state explicitly that the state directories
   contain full conversation history, that the history is readable and
   writable by every later credential-granted container from any approved
   project, and how to remove it (see HO-003).
3. Extend the `SECURITY.md` credential-mount warning to cover transcript
   confidentiality alongside credential exfiltration.

Keep the proposed wording consistent with the mount conditions above:
shared-base launches mount state by default without a project credential
prompt; custom definitions require a credential grant, and an authorized
`--auth` can override `mount_auth = false`. Describe `--no-auth` as suppressing
jms-managed agent-state mounts for the invocation.

### Acceptance

Prompt text, `agent-state.md`, and `SECURITY.md` all name transcripts and
the cross-project sharing; the existing consent-flow tests updated to match
the new wording.

## HO-002 — Cross-project agent-state pooling

- **Criticality:** High — one shared pool means project A's container can
  read project B's credentials, hooks, and transcripts. This is the one
  channel where container work leaks to *other containers*, not merely to
  the trusted host.
- **ROI:** Medium. Highest-impact structural fix, but the largest item:
  profile selection, trust-store schema, migration, and per-profile logins.
- **Affected:** `bin/jms` (state-root resolution at `bin/jms:1130`, mount
  assembly, trust flow), `docs/agent-state.md`, `SECURITY.md` (which
  already names "per-project auth profiles" as future work)

### Finding

All agent state lives in one tree keyed only by agent
(`~/.local/share/jmscontainers/agents/<agent>/`). Every credential-granted
container mounts the same directories read-write. Consequences:

- **Confidentiality:** any approved project's container can read every
  other project's session transcripts and agent configuration.
- **Integrity (already documented):** one container can plant global
  settings or hooks that execute in later containers from other projects.
- **Blast radius:** a compromised dependency in one project exposes
  credentials and history for all work, not that project's work.

### Proposal

Introduce named state profiles: `agents/profiles/<name>/<agent>/`, with
profile selection per project (trust-store field set at grant time,
overridable by `--profile`; a manifest may *request* a profile name but the
grant decides, since a hostile manifest must not steer itself into a
privileged profile). A `default` profile preserves current behavior for
users who opt out of separation; existing state migrates to it. Each
profile is an independent login domain — the documented cost is logging in
once per profile rather than once per host. New profiles are created empty:
jms copies nothing into them from `default` or any other profile, and a
per-profile login is the intended way to populate them (R3). A manual
host-side copy is the user's own action; the docs warn that `default` may
hold settings or hooks planted by other projects' containers. A
credentials-only seed is re-judged after HO-004.

This supersedes the "dedicated, least-privileged agent accounts" guidance
as the primary mitigation: it turns per-client separation from a manual
discipline into a mechanism.

### Acceptance

Two projects granted different profiles cannot see each other's state from
inside their containers (asserted by a real-runtime test); migration of a
pre-profile state tree is exercised; docs and `SECURITY.md` updated.

- **Starts empty (R3).** A newly created non-default profile contains
  nothing copied from another profile, asserted by a test.
- **Mount sources (R5).** Rejection of profile-crossing mount sources stays
  inside the existing protected-source rules; no profile-specific rule is
  added. Those rules compare canonical paths on both sides, so a symlinked
  `~/.local`, `~/.local/share` or `~/.config` cannot carry a manifest mount
  or `-w` into the state tree. That comparison fix is a pre-existing defect
  and lands first, in its own commit, with regression tests.
- **Test location (R7).** Unit tests use `sandbox()` and `FakeRuntime` in
  `tests/test_jms.py`. The real-runtime test is a standalone integration
  tier `p` in `scripts/integration.sh`: exempt from the nft gate, no TTY,
  non-interactive `jms trust --fingerprint` grants, a temp `HOME` with
  `XDG_DATA_HOME` and `XDG_CONFIG_HOME` pinned. Project B sees none of
  project A's markers in any agent-state target, and on Podman B's
  mountinfo shows no foreign profile source. Passing evidence is a green
  unit suite and `scripts/integration.sh p </dev/null` exiting 0 with a
  clean leak sweep on the Debian/Podman host, recorded in the CHANGELOG.

### Consumer note (2026-10-06)

A downstream project now requires that its sessions cannot read other
projects' agent state. With no profiles available, it uses the levers jms
already has: `run.mount_auth = false` in its manifest and a declined
credential grant, so its sessions mount no agent state at all. The cost is
a login per launch and no persisted memory, transcripts or resume state.

Two points for this proposal:

- `run.mount_auth = false` is a default, not enforcement. An `--auth` launch
  with a recorded grant remounts the shared pool. A declined grant is not
  sticky either: a later `--auth` launch on a TTY asks the credential
  question again and records a yes durably, and `--auth` with a matching
  `JMS_TRUST_FINGERPRINT` pin mounts the pool for that launch without
  asking. Separation therefore rests on the user never accepting, a
  discipline rather than a mechanism. Until profiles exist, a project that
  needs separation has no middle ground between the whole shared pool and
  nothing.
- HO-002 is the change that would let such a project keep persistence
  without rejoining the shared pool. It would want a profile used by that
  project alone, with nothing migrated from `default` except what the user
  selects.

Under the recommendations below, a project bound to the reserved profile
`none` cannot be returned to the pool by `--auth`, a pin or a launch-time
`--profile` (R4). A project bound to its own named profile mounts that
profile, not `default`, when a later credential question is answered yes
(R2). The "except what the user selects" need is met by an empty profile
and a fresh login (R3). A gap that applies to the consumer today: a launch
from a nested checkout inside the project, or from an explicit parent
directory, finds no definition and mounts the shared pool with no prompt
(R6).

### Recommendations (2026-10-07)

Seven open design questions were each investigated by an independent
agent against `bin/jms` at `9c4350b`, then checked by an adversarial critic
that re-opened the cited lines, tried to refute each recommendation, and
reconciled conflicts between them. Confidence below is the critic's
adjusted figure. The percentage is the reviewers' estimate that the
recommendation survives implementation unchanged; it is not a measured
probability. **The high-confidence items R3, R5 and R7 were accepted on
2026-10-07 and folded into the Proposal and Acceptance above.** The medium
items remain recommendations, and the Proposal and Acceptance do not
reflect them until the owner accepts them.

| # | Question | Recommendation | Confidence | Status |
| --- | --- | --- | --- | --- |
| R1 | State layout and migration | `default` stays at `agents/<agent>/` in place; named profiles at `agents/profiles/<name>/<agent>/`; nothing moves | Medium, 70% | Proposed |
| R2 | Profile selection and trust-store schema | Schema 3, required per-record `profile` field; `--profile` > record > manifest request (new profiles only) > `default` | Medium, 65% | Proposed |
| R3 | Seeding a new profile from `default` | No seeding in HO-002; new profiles start empty | High, 80% | Accepted |
| R4 | Sticky decline | Reserved profile value `none`, shipped with named profiles | Medium, 55% | Proposed |
| R5 | Cross-profile mount sources | No new rule; fix the protected-source comparison to use canonical paths (pre-existing defect) | High, 85% | Accepted |
| R6 | Launches without a project definition | Keep mounting `default` without a record, behind a guard for overlapping separated projects | Medium, 60% | Proposed |
| R7 | Test strategy | Unit tests on `sandbox()`/`FakeRuntime`, plus a new standalone integration tier `p` needing no TTY or nft | High, 78% | Accepted |

#### R1 — State layout: `default` in place (medium, 70%)

**Recommendation.** Do not move existing state. The `default` profile is
the existing `agents/<agent>/` tree. Named profiles live at
`agents/profiles/<name>/<agent>/`, created empty on first use with mode
`0700` and the same lstat no-symlink check leaves get today
(`state_directory_state`, `bin/jms:1825-1834`), applied to every
intermediate directory. `profiles` must never be an entry in
`AGENT_STATE_LEAVES` (`bin/jms:1122`); enforce that in code and a test, so
no mounted `default` leaf can contain the named-profile tree.

**Evidence.** Mounts are per leaf, never the `agents/` root
(`bin/jms:1795-1802`). The protected-source list already covers the whole
data root (`bin/jms:1144-1147`). `ensure_agent_state_root()` does no lstat
on intermediates today (`bin/jms:1133-1137`). jms holds no lock for a
container's lifetime, so a rename could race a run that already computed
the old path.

**Rejected.** Eager or lazy rename into `profiles/default/` (five leaves
cannot move atomically as a set, races in-flight launches, effect on live
apple/container virtiofs shares unqualified); copying (doubles transcripts,
two diverging copies); symlinking (refused by the existing lstat checks).

**Why not higher.** It departs from two literal Proposal statements (all
profiles under `profiles/`, and "existing state migrates to it"), which
the owner must accept. The downgrade benefit is small because R2's schema
bump already makes older jms fail closed on custom projects
(`bin/jms:1085-1086`).

**Would change if** later tooling (HO-003 pruning, a profile listing) must
walk one uniform directory, or the owner requires a physical move.

#### R2 — Profile binding on the trust record (medium, 65%)

**Recommendation.** Bump the trust store to schema 3 with a required
`profile` field on every record. Schema-2 records read as `default`. The
field is stored on declined grants too, and `record_approval` carries it
forward across fingerprint changes and re-approval. Resolution order:
`--profile`, then the record, then a manifest `run.profile` (honored only
for a brand-new profile at an interactive first grant), then `default`.
`--profile` persists only when the same invocation writes a durable
record; under `--trust` or a pin it is one-shot. Names match the manifest
`name` grammar (`bin/jms:1331`); `default` and `none` are reserved. The
profile is resolved before `validate_agent_state_sources()` and
`approve()` run (`bin/jms:2021`, `2027`). An explicit `--profile` on a
launch counts as the user's consent to mount that profile. The schema-3
validator accepts the full name grammar from its first release, so later
work needs no second bump.

**Evidence.** `valid_store` requires an exact key set and `schema == 2`
(`bin/jms:1056-1070`); a newer schema gets "upgrade jms" rather than the
reset-all hint (`bin/jms:1085-1088`). `record_approval` replaces the whole
record (`bin/jms:1463-1468`), so without an explicit carry-forward a
re-trust silently drops the binding. The pid is `sha256(root)`
(`bin/jms:1434`), so the record survives fingerprint changes.

**Undocumented consequences to write down.** Bindings key on the path: a
clone, move or git worktree gets no binding and falls back to `default` at
its first grant. `trust prune` and `trust revoke` drop the binding with
the record (`bin/jms:2060-2068`).

**Why not higher.** The opt-in default (new grants get `default`) is the
most contestable choice.

**Would change if** the owner decides separation should be the default
for new grants. Step four would then become a new per-project profile
instead of `default`.

#### R3 — No seeding in HO-002 (high, 80%)

**Accepted 2026-10-07.**

**Recommendation.** A new non-default profile starts empty, and the user
logs in once per agent inside it, the cost the Proposal already names.
jms copies nothing into it, and a test asserts that. A manual host-side
copy from `default` is the user's own action; the docs say it may carry
settings or hooks planted by other projects' containers. Re-judge a
credentials-only seed after HO-004 qualification.

**Evidence.** Every granted container can write `default`, and its hooks
carry into later containers (HO-002 Finding; `docs/agent-state.md:23-25`).
Each leaf mixes credentials, config, hooks and transcripts (HO-003 and
HO-004 name paths in the same leaves), so a per-leaf copy imports exactly
what the profile exists to keep out. A finer-grained copy needs a
per-CLI-version path list, which HO-003 and HO-004 already treat as a
standing qualification burden.

**Why not higher.** The argument rests on documents only; no
qualification ran. That is acceptable because it argues against adding
code.

**Would change if** qualification shows each agent keeps credentials in
one stable, non-executable file that stays valid across token refresh in
two profiles, or the consumer finds a login per profile unacceptable (MFA
or provisioning constraints). Neither would justify copying config, hooks
or transcripts.

#### R4 — Reserved profile `none` (medium, 55%)

**Recommendation.** Add `none` as a reserved value of R2's `profile` field,
meaning "never mount agent state". It changes only through
`jms trust PATH --profile <name>`. A launch-time `--profile`, `--auth` or
`JMS_TRUST_FINGERPRINT` pin cannot override it, and `--auth` exits 3 with
a message naming the undo. `trust revoke` clears it, and the docs say so.
Ship it in the same release as named profiles. Ship it earlier only if
named profiles slip, and then still with R2's full-grammar validator.

**Evidence.** A grant counts only while its fingerprint matches
(`bin/jms:1442`); `--auth` re-asks on a TTY and records a yes
(`bin/jms:1492-1498`); a pin grants one-shot access (`bin/jms:1452`).
A manifest asking for *less* privilege is safe to honor as a pre-selected
default, but it cannot be the mechanism, because the grant decides.

**Why not higher.** A separate first slice costs a second rollout. Under
R1 named profiles are smaller than the register's "Large" estimate. Under
R2 a declined-then-escalated grant already mounts the project's own
profile. Together these weaken the case for `none` beyond "no persistence
wanted at all".

**Would change if** HO-002 will not start within a release or two and the
consumer reports a real or near-miss pool mount. Ship `none` standalone in
that case.

#### R5 — Canonical protected-source comparison (high, 85%)

**Accepted 2026-10-07.**

**Recommendation.** Add no profile-specific rule. The protected list
already covers `~/.local/share/jmscontainers` and so every profile under
it. The one change needed fixes a **pre-existing defect**:
`protected_sources()` builds entries as canonical `$HOME` plus a literal
suffix (`bin/jms:782-786`, `1144-1147`), while mount sources and workdirs
are fully resolved (`bin/jms:1192`, `896`). When `~/.local`,
`~/.local/share` or `~/.config` is a symlink, a manifest mount of
`~/.local/share/jmscontainers/agents/claude`, or `-w` there, passes the
check. Fix by also listing the non-strict `os.path.realpath()` of each
entry, with regression tests for a manifest mount of
`profiles/<other>/claude`, `-w` into `profiles/<other>`, and the
symlinked-share case.

**Evidence.** Reproduced independently by the investigating agent and the
critic with a scratch `HOME` whose `~/.local/share` is a symlink:
`reserved_root()` returns false for both the canonical mount source and
the canonical workdir. Existing protected-source tests pass and do not
cover the case.

**Sequencing.** This does not depend on profiles. Land it first, in its
own commit.

**Would change if** a profile directory could nest inside another
profile's mounted leaf (prevented by R1's invariant), or profile roots
become configurable outside the data root.

#### R6 — Launches without a project definition (medium, 60%)

**Recommendation.** Shared-base launches keep mounting `default` without a
trust record, as today. Add one guard on that path, skipped under
`--no-auth`: if the workdir is an ancestor or descendant of any trust
record whose profile is not `default`, refuse with exit 2. An explicit
`--profile` (one-shot) lifts a named-profile overlap; only `--no-auth`
lifts a `none` overlap.

**Evidence.** A nested checkout or worktree inside a project gets its own
VCS root, so discovery finds no definition and the launch is a
shared-base launch (`bin/jms:952-977`). An explicit parent-directory
launch is allowed because only implicit operands are refused
(`bin/jms:2016-2018`). The shared-base launch mounts the pool with no
prompt (`bin/jms:2031-2033`). The 2026-09-13 review requires the
separation claim to cover base-image launches
(`docs/project-review-2026-09-13.md:269-271`).

**Costs to record.** Shared-base launches would read the trust store for
the first time, so a corrupt or newer-schema store would block them
(`bin/jms:1085-1088`). A moved or deleted record root is not protected.

**Why not higher.** "Use `default`" is solid (about 85% on its own). The
guard is the uncertain half.

**Would change if** the owner rules that sessions launched from a parent
or nested directory are outside the separation claim (drop the guard and
disclose), or the consumer reports real launches from such paths (require
a record instead).

#### R7 — Test strategy (high, 78%)

**Accepted 2026-10-07.**

**Recommendation.** Two layers.

- **Unit** (`tests/test_jms.py`, `sandbox()` temp `HOME`, `FakeRuntime`):
  mount sources per leaf under a named profile, including `--root`;
  grant-decides; schema-2 store read as `default`; binding carried across
  a fingerprint change; new profile starts empty; manifest request for an
  existing profile ignored with a notice; `none` resisting `--auth`, pin
  and launch `--profile`; the R6 guard (nested checkout and parent
  launch); the R5 symlinked-share case; `profiles` absent from
  `AGENT_STATE_LEAVES`.
- **Integration**: a new standalone tier `p` in `scripts/integration.sh`,
  exempt from the nft gate (`scripts/integration.sh:28-30`, `50` both need
  changing) and needing no TTY. Grants go through
  `jms trust --fingerprint <tf> --auth --profile <name>`, under a temp
  `HOME` with `XDG_DATA_HOME` and `XDG_CONFIG_HOME` pinned to the real
  values. Projects A and B hold different profiles; A writes a marker into
  every agent-state target, and B sees none of them. On Podman, B's
  `/proc/self/mountinfo` shows no A-profile or `default` source. A
  pre-existing `default` tree is visible to a `default` project and absent
  from a separated one. A shared-base launch from a nested checkout is
  refused or mounts no `default` source.

**Passing evidence:** unit suite green (baseline today: 296 passed,
114 subtests) and `scripts/integration.sh p </dev/null` exiting 0 with a
clean leak sweep on the Debian/Podman host, recorded in the CHANGELOG.
`all` still exits 3 on this host, so the evidence comes from running `p`
on its own.

**Evidence.** Checked on this host: a temp `HOME` with pinned XDG dirs
gives a real Podman launch with no TTY and no sudo, Podman still sees all
66 images, and the temp `HOME` stays empty. `--trust --auth` cannot be
used because `--trust` clears the pin (`bin/jms:1438-1439`).

**Would change if** a temp `HOME` breaks the Apple `container` backend (run
the macOS pass with the real `HOME` and unique profile names), or the owner
requires the Acceptance evidence from the qualified fresh-account Debian
run.

#### Open questions no recommendation covers

- **Profile lifecycle.** Nothing lists or removes profile directories.
  `trust revoke` and `trust prune` leave orphaned `agents/profiles/<name>/`
  trees that still hold live credentials. Smallest fix: `trust list` and
  `inspect` show the profile, and the docs give manual removal and the
  orphaned-credential risk.
- **Replacement security text.** `SECURITY.md:26-27` ("per-project auth
  profiles are future work") and the dedicated-accounts advice in
  `docs/agent-state.md:27` need rewriting. The residual risks to state:
  projects on one profile still pool, `shell/` is shared read-only across
  all projects, the host user can read every profile, and an unrecorded
  root falls back to `default`.
- **Other register items.** HO-003 pruning must walk each profile root
  without following symlinks; HO-006's `0700` check must cover the
  `profiles/` intermediates; HO-001's consent text should name the
  profile; HO-004 is re-judged afterwards. HO-002's "Large" effort
  probably drops under R1.

#### Recommended order

1. **R5** standalone: canonical protected-source comparison and its
   regression test. It fixes a hole that exists today.
2. **R2** with R4's reserved values: schema 3, `profile` field, carry-
   forward, `trust list` and `inspect` show it. Mounts unchanged.
3. **R1**: resolver, per-profile mounts, intermediate checks, the
   `profiles` invariant, `--profile` on `launch`, `build` and `trust`,
   `none` enforced in `approve()`.
4. **R6**: the shared-base overlap guard.
5. **R3**: the starts-empty test and the manual-copy docs.
6. **R7**: unit tests land with each step; tier `p` last, once there is a
   profile to test.
7. Docs: Proposal and Acceptance edits, `docs/agent-state.md`,
   `SECURITY.md`, `docs/cli.md` (schema 3), `run.profile` in the manifest
   reference.

## HO-003 — No supported way to remove accumulated session history

- **Criticality:** Medium — the data is already on disk and growing;
  users who want the login persistence but not the history archive have
  no supported operation, and hand-deleting inside a credential directory
  invites deleting the wrong thing.
- **ROI:** High. Small, self-contained CLI addition; it also gives HO-001's
  new documentation a concrete remedy to point at.
- **Affected:** `bin/jms` (new subcommand), `docs/agent-state.md`,
  `docs/cli.md`

### Finding

The only documented state operation is "delete the agent's state directory
and log in again" — which destroys credentials along with history. There
is no operation that removes transcripts while preserving auth and
configuration, and no documentation of which paths inside each agent's
state are history versus credentials.

### Proposal

Add `jms state prune [--agent <name>] [--dry-run]`, deleting only the
known history locations (initially: `codex/sessions/`, `claude/projects/`,
opencode's session storage) and printing what was removed. Maintain the
path list in one place, per agent, with a comment that it tracks upstream
agent-CLI layouts and must be re-verified when the base image bumps an
agent CLI version. The command operates on host state only; document that
it should not run concurrently with a credential-granted container.

### Acceptance

Prune removes history and leaves logins working on both backends
(exercised in the integration script); `--dry-run` output lists exact
paths; docs name it from `agent-state.md`.

## HO-004 — Credentials-only mount mode

- **Criticality:** Medium — a middle ground between the all-or-nothing
  choices of the full grant and `--no-auth`.
- **ROI:** Medium. Qualification-heavy for its size, and largely
  superseded by HO-002 profiles; judge after HO-002.
- **Affected:** `bin/jms` (mount assembly, grant flow), `docs/agent-state.md`

### Finding

Today the credential grant mounts each agent's *entire* state directory.
A user who wants only login persistence — no shared hooks, no shared
config, no transcript accumulation visible to later containers — has no
mode that provides it.

### Proposal

An opt-in mode (e.g. `--auth=credentials`) that mounts only credential
material (Codex `auth.json`, Claude Code credentials file, opencode auth
storage) rather than the state roots.

**Known risk that must be qualified per agent CLI, per backend:** agent
CLIs refresh tokens by atomic rename; a single-file bind mount pins the
old inode, so a rename-based refresh either fails or silently diverges
from the host copy. The likely workable shape is mounting a minimal
per-launch directory assembled from the credential files, synced back at
exit — which introduces concurrent-container semantics that need explicit
definition. If qualification shows this cannot be made reliable, close
this item as Rejected in favor of HO-002 and record the evidence.

### Acceptance

For each supported agent CLI: login persists across a token refresh inside
a container, on both backends, with a recorded qualification run — or a
recorded rejection.

## HO-005 — No single documented inventory of what container work leaves on the host

- **Criticality:** Medium — users cannot contain outflow they cannot
  enumerate; today the facts are scattered across `SECURITY.md`,
  `agent-state.md`, and source.
- **ROI:** High. Documentation only.
- **Affected:** `docs/agent-state.md` or a new user-guide section, linked
  from `SECURITY.md` and `docs/README.md`

### Finding

No user-facing document answers: "after my container exits, what remains
on the host, where, and how do I limit it?" The `--rm` ephemerality of the
container filesystem — a genuine outflow *control* — is not documented as
such anywhere user-facing.

### Proposal

Publish the channel inventory (the table above, in user-guide form):
project mount by design; agent state including transcripts (per HO-001);
container filesystem ephemeral via `--rm`; image storage. Include
host-hygiene guidance: exclude `~/.local/share/jmscontainers` from backup,
sync, and indexing tools (extending the existing "never sync" credential
advice to transcripts); rely on full-disk encryption for theft; pointers
to each agent CLI's own history-retention settings, stated as "verify
against your installed version" rather than as jms claims.

Describe the shared-base default and custom-project credential conditions
alongside this inventory, including the authorized `--auth` manifest override
and the scope of `--no-auth`. Suppressing jms-managed agent-state mounts does
not prevent writes through approved project or extra mounts or neutralize
trusted ambient runtime configuration.

### Acceptance

The inventory exists in the user guides, is linked from `SECURITY.md` and
the docs index, and every claim in it cites either source or a qualified
platform behavior.

## HO-006 — Pre-existing state directories are not verified `0700`

- **Criticality:** Low — jms creates the tree `0700`
  (`bin/jms:1095,1135-1136`), so this concerns only trees created loose by
  hand, by older versions, or by restore tools, and only matters on
  multi-user hosts.
- **ROI:** Medium. Small check at mount time.
- **Affected:** `bin/jms` (state-root preparation)

### Finding

`mkdir(mode=0o700, exist_ok=True)` does not tighten a directory that
already exists with looser permissions. A state tree restored from backup
as `0755` would expose credentials and transcripts to other local accounts
with no warning.

### Proposal

At credential-mount time, check the state root and per-agent directories;
warn (not fail) when group/other bits are set, naming the path and the
`chmod` to run. Warn-only preserves deliberate configurations while
surfacing accidents.

### Acceptance

A loosened fixture directory produces the warning; a `0700` tree stays
silent; covered in `tests/test_jms.py`.

## HO-007 — jms could ship history-retention defaults into agent configuration

- **Criticality:** Low.
- **ROI:** Low — recorded mainly so the judgment is on file.
- **Affected:** would touch agent configuration files inside `agents/`

### Finding

Some agent CLIs expose history-retention settings. jms could write
conservative defaults into the mounted configuration on first creation of
an agent's state directory.

### Proposal

Recorded for judgment, with a recommendation **against**: jms editing
agent configuration crosses from mounting state into managing it, breaks
the "delete the directory and log in again" recovery story's simplicity,
silently fights users' own settings, and depends on per-CLI knobs that
change upstream. HO-005's documentation of the knobs, plus HO-003's prune
command, deliver most of the value without jms owning agent config.
Expected disposition: Closed (Rejected) unless a concrete case emerges.
