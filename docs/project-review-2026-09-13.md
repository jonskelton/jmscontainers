# Project review — 2026-09-13

Reviewed revision: `6af7b7e2117d2f6e8f370bddb80f5753c9d50ed8`
(`v1.1.0-16-g6af7b7e`, CLI version `1.1.1.dev`). The working tree was clean
when the review began. Source line numbers below refer to this revision.

## Assessment

The September 12–13 runtime fixes are sound within the exercised contracts.
Podman absence now depends on the explicit existence probe, and forced
rebuilds avoid inspecting the project image they will replace. The checked-in
fixtures and failure-path tests address the original mistaken assumption
directly. No new runtime regression was found in those changes.

Two actionable findings remain: launch stdout can contain jms build messages
when Python output is unbuffered, and the new outflow register overstates the
default protection against mounting agent state. The former predates these
commits; the latter is introduced by the new document. Neither finding has
been fixed as part of this review.

The tree is **not yet release-qualified** under its own checklist. The
September 13 developer-account integration results are useful evidence, but
the final-candidate fresh-account gate and clean-host installation walkthrough
remain open under RI-007. This review does not replace either gate.

## Scope and method

“Last few days” means September 10–13, 2026, using the repository's Pacific
commit dates. All six commits in that window landed September 12–13. The
primary diff is `6102bd9..6af7b7e`; the September 4 exact-image-identity change
(`6102bd9`) and earlier stage-alias/base-staleness work were also read for
context.

The review covered the recent diffs and their tests, backend resolution and
build/launch paths, discovery and trust checks, state-mount assembly, image
retention, the base Containerfile, test workflow, integration/leak-sweep
structure, and the relevant security, qualification, and issue documents.
It included source inspection, `make test`, and isolated reproductions using
the repository's fake backends and temporary homes.

No real container builds or integration tiers were run during this review.
The September 13 live results below are the repository's recorded evidence,
not independently repeated results. Upstream agent storage layouts, current
package versions, and external CI status were not independently verified.
This is a project/code review, not a complete security audit.

## Recent commit review

| Commit | Change | Review result |
| --- | --- | --- |
| `4b6cd1d` — September 12 | Probe Podman image absence; add real inspection fixtures and failure cases | Correct: exit 1 short-circuits before inspect; unexpected probe statuses fail; every nonzero inspect after a positive probe fails. Successful records still require one valid identity and label map. |
| `9d1ae5b` — September 12 | Skip project-tag resolution under `--no-cache` | Correct: shared-base resolution remains to determine `jms.base`, while project existence/inspection is skipped. Both backend test classes exercise the new assertion. |
| `1804ef0` — September 12 | Mark development version `1.1.1.dev` | Consistent with CLI output, trust-record stamping, and the updated release checklist. The format test checks syntax; release identity still depends on following the checklist. |
| `1acd0e4` — September 12 | Preserve absent-reference diagnostics in the qualification appendix | Useful separation of captured observations from adopted/rejected remedies. The record correctly attributes the defect to unreleased main rather than `v1.1.0`. |
| `36cfc0c` — September 13 | Record Podman tier A/B runs | Correctly leaves RI-007 open and identifies the developer-account limitations. Evidence traceability can be improved as described below. |
| `6af7b7e` — September 13 | Add host information-outflow register | Identifies a real consequence of mounting shared writable state. Correct the mitigation summary in PR-002 before treating it as the source for user guidance. |

## Findings

Severity: **Medium** means a concrete functional or documentation defect that
should be corrected; it does not automatically create a release blocker.
Release blockers retain their existing register and acceptance criteria.

### PR-001 — Launch stdout depends on Python buffering

- **Severity:** Medium
- **Status:** Open
- **Origin:** Pre-existing; not introduced by the September 12–13 fixes
- **Affected:** [bin/jms](../bin/jms), `build_base()` line 1551,
  `build_project()` lines 1749 and 1754, and `gc_project_images()` line 1660
- **Related:** [RC-006](release-critical-issues.md#rc-006--cold-launch-stdout-carried-the-built-image-ref)

`run_build()` correctly redirects the runtime build process's stdout to
stderr. However, jms itself still uses ordinary stdout `print()` calls for
“building”, “base image changed; rebuilding”, and successful background
image-retention messages. These helpers also run during `jms launch`.

With `PYTHONUNBUFFERED=1` (or `python3 -u bin/jms`), a cold launch therefore
prefixes the launched program's output with a build message; a stale-base
launch prefixes it with two. Capturing JSON or another machine-readable
result can fail depending on whether an image happened to need rebuilding.
The same paths run on both backends.

Ordinary pipe buffering masks the issue: the final `os.execvp()` replaces
Python without flushing its pending stdout buffer. A passing buffered
command-substitution check therefore does not establish that stdout is
reserved for the container, as RC-006's resolution describes.

**Reproduction performed:** used `tests/test_jms.py`'s temporary-home and
fake-runtime helpers, exercised `cmd_launch()`, and replaced only the final
runtime exec with a real `/bin/echo PAYLOAD` exec. Ran each case in a separate
Python subprocess with and without `-u`. This exercises actual Python
buffering and process replacement without using a container engine.

| Image state | Normal buffered pipe | Unbuffered pipe |
| --- | --- | --- |
| Project image absent; shared base present | `PAYLOAD` only | `building "<project-tag>"`, then `PAYLOAD` |
| Project image present with matching base label | `PAYLOAD` only | `PAYLOAD` only |
| Project image present with stale base label | `PAYLOAD` only | `base image changed; rebuilding "<project-tag>"`, `building "<project-tag>"`, then `PAYLOAD` |

All six cases were run for each backend, with the same results. The base-only
build and retention messages are additional occurrences found by source
inspection; they were not separate process-level reproduction cases.

**Recommended resolution:** route progress and automatic-retention messages
to stderr. Keep intentional command result output, such as explicit build
summaries and `clean` reports, on its chosen documented channel. Add a
subprocess-level regression that asserts exact launch stdout with
`PYTHONUNBUFFERED=1` for cold, warm, stale-base, and retention-triggering
launches on both backends. Cover a missing shared base as well.

**Close when:** those cases return exactly the launched payload on stdout,
with progress visible on stderr; `make test` remains green.

### PR-002 — The outflow register overstates agent-state suppression

- **Severity:** Medium
- **Status:** Open
- **Origin:** Introduced in `6af7b7e` (documentation only)
- **Affected:** [host-outflow-register.md](host-outflow-register.md),
  “Existing mitigations” paragraph, lines 62–67
- **Implementation evidence:** [bin/jms](../bin/jms), `launch_plan()` line
  1918 and `cmd_launch()` line 2002

The mitigation summary says the credential grant “defaults to no” and that
`--no-auth` and `run.mount_auth = false` suppress the agent-state mount
“entirely.” These statements need their conditions:

1. A launch without a discovered project definition uses the shared base
   and passes `not args.no_auth` as its auth decision. It mounts all four
   agent-state directories by default without a project credential prompt.
2. For a custom project, the effective decision is
   `auth and (config["mount_auth"] or args.auth)`. A valid credential grant
   plus `--auth` overrides a manifest's `mount_auth = false`.

This matters specifically to the register's purpose: a reader can wrongly
conclude that declining to opt into credentials, or setting the manifest
flag, always prevents transcripts from being persisted into shared host
state. These are existing runtime semantics, not a newly discovered trust
bypass. [agent-state.md](agent-state.md#persistent-agent-state) already
describes the manifest override accurately.

**Reproduction performed:** invoked `cmd_launch()` against each fake backend
and counted agent-state sources in the final runtime argv. Custom-project
cases had a matching durable credential grant established in the temporary
trust store before launch.

| Launch case | Agent-state mounts, on each backend |
| --- | --- |
| No project definition, default flags | 4 |
| No project definition, `--no-auth` | 0 |
| Custom definition, `mount_auth = false`, default flags | 0 |
| Same custom definition and grant, `--auth` | 4 |
| Same custom definition and grant, `--no-auth` | 0 |

**Recommended resolution:** say that a new custom definition's interactive
credential question defaults to no; shared-base launches mount state by
default; `--no-auth` suppresses jms-managed agent-state mounts for that
launch; and `mount_auth = false` suppresses the default mount but permits an
explicit, authorized `--auth` override. Carry these distinctions into
HO-001's consent wording and HO-005's user-facing inventory.

**Close when:** the register and resulting user guidance agree with this
matrix. No runtime policy change is required to fix the finding.

## Existing risks and release work

These items already have owners in the project documents and should not be
duplicated as newly discovered bugs.

- **RI-007 remains a release blocker.** Run both integration tiers on the
  final candidate from the required fresh Debian account with non-1000
  UID/GID and a real ssh login, and complete the clean-host installation
  walkthrough. The September 13 records explicitly identify the long-lived
  developer account and do not claim to meet this gate. See the
  [review register](review-issues-2026-09-09.md#ri-007--live-podman-gate-on-the-final-candidate)
  and [release checklist](release-checklist.md).
- **Runtime feedback remains manual (DW-002).** The checked-in CI workflow
  runs fake-backed tests on Ubuntu and macOS and no real engine. The actual
  absent-reference mismatch demonstrates the consequence. A small Podman
  smoke job is a useful next investment alongside the full release gate.
- **Shared state remains shared (HO-001/HO-002).** Source confirms that
  credential-enabled launches mount the same four writable directories
  across projects. The register's transcript observation is reported live
  evidence; this review verified the mount mechanism, not the exact history
  layout of each upstream agent. Naming history and cross-project access in
  consent and user documentation is the most immediate follow-up.
- **Linux isolation depends on trusted host configuration (DW-001).**
  `PodmanBackend.run_argv()` pins selected settings, while `SECURITY.md`
  explicitly accepts ambient configuration. This is an acknowledged product
  boundary, not a new omission in the recent fix.
- **Base builds intentionally use floating inputs (DW-003).** The
  Containerfile's “Rebuild = update” contract explains the unpinned Fedora
  and npm inputs. A decision about reproducibility belongs with that
  existing item, not an incidental pinning change during this review.

### Qualification evidence should identify the tested tree

The two passing September 13 integration rows record useful environment
details, but no tested commit ID, working-tree status, or durable log
location. Commit `36cfc0c` records the results; that is not itself an explicit
identification of the tree tested earlier.

For the next run, record `git rev-parse HEAD`, whether the tree was clean,
the exact invocation, interpreter/runtime versions, exit status, leak-sweep
result, and a retained log location or artifact reference. If existing logs
can establish the earlier candidate, add that evidence; otherwise leave the
historical candidate unspecified. This is an evidence-quality improvement,
not a claim that the reported passes were invalid.

### Refine the outflow proposals before implementing them

HO-001 and HO-005 can proceed with PR-002's corrected conditions. For later
work, HO-003's proposed host-side pruning deserves explicit safety criteria:
agent-state content is container-writable, so deletion must stay beneath
selected history roots even when directory entries are symlinks; a dry run
must describe the same selection as execution. Qualify history layouts and
login preservation against recorded agent versions before deleting them.
The repository's floating tool installs make this a continuing obligation.
This is a design requirement for a proposed command, not a defect in an
implemented prune command.

For HO-002, add acceptance cases for the legacy/default profile, base-image
launches without project definitions, `--root`, denied profile requests, and
concurrent sessions. Its separation claim must include all launch paths.
Retain HO-004's requirement to qualify credential refresh before committing
to a credentials-only mount design.

## Verification record

| Check performed in this review | Result |
| --- | --- |
| `make test` | Pass: 275 tests, Python 3.13.5; compilation and ShellCheck leg also passed |
| ShellCheck availability | 0.10.0 installed; the syntax-only fallback was not used |
| `./bin/jms --version` | `1.1.1.dev` |
| Launch stdout subprocess probe | 12 cases across the two fake backends; reproduced PR-001 for unbuffered cold/stale launches |
| Agent-state launch matrix | 10 cases across the two fake backends; confirmed PR-002's conditions |
| Real-runtime integration and clean-host installation | Not run during this review; existing RI-007 remains open |

The deliverable is this review and its documentation-index entry. Production
code, tests, grants, runtime state, and existing issue dispositions were not
changed.
