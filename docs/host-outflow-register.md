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
once per profile rather than once per host.

This supersedes the "dedicated, least-privileged agent accounts" guidance
as the primary mitigation: it turns per-client separation from a manual
discipline into a mechanism.

### Acceptance

Two projects granted different profiles cannot see each other's state from
inside their containers (asserted by a real-runtime test); migration of a
pre-profile state tree is exercised; docs and `SECURITY.md` updated.
Rejection of profile-crossing mount sources stays inside the existing
protected-source rules.

### Consumer note (2026-10-06)

A downstream project now requires that its sessions cannot read other
projects' agent state. With no profiles available, it uses the levers jms
already has: `run.mount_auth = false` in its manifest and a declined
credential grant, so its sessions mount no agent state at all. The cost is
a login per launch and no persisted memory, transcripts or resume state.

Two points for this proposal:

- `run.mount_auth = false` is a default, not enforcement. An `--auth` launch
  with a recorded grant remounts the shared pool, so the declined grant is
  what holds. Until profiles exist, a project that needs separation has no
  middle ground between the whole shared pool and nothing.
- HO-002 is the change that would let such a project keep persistence
  without rejoining the shared pool. It would want a profile used by that
  project alone, with nothing migrated from `default` except what the user
  selects.

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
