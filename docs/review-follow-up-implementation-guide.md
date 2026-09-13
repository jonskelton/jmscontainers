# Implementation guide: September 13 review follow-up

Status: Ready for implementation; neither finding is fixed by this guide.
Source: [Project review — 2026-09-13](project-review-2026-09-13.md), findings
PR-001 and PR-002, against `6af7b7e`.

## Intended outcome and delivery

Deliver one focused follow-up PR with two implementation commits:

1. `Keep launch progress and automatic cleanup messages on stderr`
2. `Clarify when launches mount persistent agent state`

The first fixes a functional output defect and supplies regression tests.
The second corrects documentation of existing credential behavior. Each
commit should be independently reviewable and pass the relevant checks.

The review and this guide are preparatory documentation commits on
`review/2026-09-13-follow-up`; they are not the two implementation commits.
Base the implementation branch on the documentation once it lands. If work
starts earlier, use a stacked PR targeting this documentation branch so the
implementation diff still contains just the two follow-up commits.

Keep this effort limited to output routing and accurate mount documentation.
Transcript consent expansion (HO-001), profiles (HO-002), pruning (HO-003),
credentials-only mounting (HO-004), and a comprehensive outflow inventory
(HO-005) remain separate work. No credential policy, CLI grammar, manifest
schema, backend selection, or release-version change is needed here.

## Commit 1: correct launch output routing

### Production change

In [bin/jms](../bin/jms), add `file=sys.stderr` to these progress reports:

| Function | Message |
| --- | --- |
| `build_base()` | `building "<base>"` |
| `build_project()` | `base image changed; rebuilding "<project-tag>"` |
| `build_project()` | `building "<project-tag>"` |
| `gc_project_images()`'s report callback | `removed image "<ref>"` after successful automatic retention |

These helpers run during implicit builds in `cmd_launch()`, so their output
must not become part of the launched program's stdout. Direct stderr routing
is sufficient; no new logging abstraction or launch-only mode is necessary.
The same progress messages should use stderr during explicit builds.

Preserve the intentional stdout results in `cmd_build()` and `cmd_clean()`,
including explicit build summaries, up-to-date reports, and explicit cleanup
reports. Do not globally replace every `print()` or modify
`execute_removal_schedule()`: the automatic-retention and explicit-cleanup
callers have different reporting purposes.

Keep `run_build()`'s existing `stdout=sys.stderr` forwarding for the runtime
build subprocess. Keep warning paths on stderr and automatic cleanup
warn-only. Neither the trust decision nor final runtime argv should change.

### Regression strategy

Add focused subprocess coverage in [tests/test_jms.py](../tests/test_jms.py).
Existing `LaunchTests.launch_argv()` redirects stdout to `StringIO` and uses a
fake replacement call, so it does not test Python's buffering at a real exec
boundary. Reuse the existing sandbox and backend fixtures, but exercise the
launch in a child Python process whose stdout/stderr the parent captures.

The test arrangement should:

1. Create a temporary home, checkout, project, and fake image store. Keep the
   temporary directory owned by the parent test so it is removed even when
   the child execs; child context-manager cleanup does not run after exec.
2. Select each backend explicitly with the existing test seam. Do not invoke
   an installed engine, inspect the user's state, or depend on host runtime
   availability. Use `--no-auth` and temporary project trust where needed.
3. Run the real `cmd_launch()` path against fake runtime queries/builds.
   At the final replacement call, perform a real `os.execv()` into a small
   payload process using `sys.executable`. Emit deterministic output such as
   `PAYLOAD\n`, without an extra flush before exec.
4. Pass `PYTHONUNBUFFERED=1` in the child environment for the regression
   cases. Include a normal-buffered control with that variable removed; the
   old implementation can otherwise appear correct by losing its buffered
   messages during exec.
5. Assert exact stdout bytes, the expected process exit status, and the
   relevant progress messages on stderr. A substring assertion on stdout
   would miss precisely the unwanted prefix this test is meant to detect.

Exercise this matrix on both backends:

| Scenario | Required setup and assertions |
| --- | --- |
| Cold project | Shared base present, project tag absent; payload only on stdout; project build progress on stderr |
| Warm project | Project tag present with matching `jms.base`; payload only; no build progress |
| Stale project | Project tag present with mismatched `jms.base`; payload only; stale-base and build messages on stderr |
| Missing shared base | Plain workdir without a definition, base absent; payload only; base build progress on stderr |
| Automatic retention | Force a project build with enough older jms-owned identities to exceed `KEEP_IMAGES`; payload only; successful removal on stderr; launched tag retained |

For retention, use distinct identities, matching ownership labels and tag
prefixes, and controlled timestamps so removal definitely occurs. Do not
stub out retention in this case. Include a nonzero payload exit case to
ensure the launch still propagates the process status.

Update `test_background_gc_warns_on_removal_failure_and_continues()`: it
currently requires the successful removal message on stdout. Require it on
stderr and assert stdout is empty, while retaining the assertions that all
removals are attempted and failures only warn. Preserve existing explicit
`clean` stdout assertions and check explicit build result output as well.

Keep or add a focused assertion that `run_build()` forwards runtime build
stdout to stderr; the main `FakeRuntime` currently accepts but does not
record those stream arguments. Capture them with a small wrapper or emit a
fake build marker through the supplied stream. Avoid relying solely on
silent fake build output to protect the original RC-006 fix.

Demonstrate that the new unbuffered regression fails on the pre-fix code and
passes after the four routing changes. Use a disposable copy or worktree if
needed; do not reset unrelated working-tree changes for this demonstration.

### Documentation and completion

- Add a short `launch` output-contract paragraph to [cli.md](cli.md): jms
  progress/automatic-retention diagnostics use stderr; launched-program
  stdout remains available for capture. Do not promise that all stderr is
  jms output, since the launched program and runtime also use it.
- Add an Unreleased fix entry to [CHANGELOG.md](../CHANGELOG.md), identifying
  cold/stale launches and unbuffered output as the trigger. Describe it as
  a pre-existing defect rather than a regression introduced by the recent
  Podman fix.
- Run `make test` and `git diff --check`. Record the actual test count and
  whether ShellCheck or the Makefile's syntax fallback ran.
- Close PR-001 in the review with a dated resolution and validation record.
  Keep its original reproduction as historical evidence and label the
  opening assessment as applying to the originally reviewed revision.
  PR-002 remains open until commit 2.

Include the implementation, tests, CLI documentation, changelog, and PR-001
resolution in this first commit. Record the resulting hash in the PR
description; do not try to embed a commit's own hash in its contents.

## Commit 2: correct agent-state documentation

### Required wording

Replace the “Existing mitigations” paragraph in
[host-outflow-register.md](host-outflow-register.md) with wording that
captures all four conditions. Suggested text:

> For custom project definitions, build/run approval and agent-state access
> are separate grants; a new interactive credential question defaults to no.
> A launch without a project definition uses the shared base and mounts
> persistent agent state by default, without a project credential prompt.
> `--no-auth` suppresses jms-managed agent-state mounts for that launch.
> For a custom definition, `run.mount_auth = false` suppresses the default
> mount, but an explicit `--auth` can override it when credential access has
> been granted. New state directories are created with mode `0700`;
> launches use `--rm`, and the shared shell mount is read-only.

Link to [agent-state.md](agent-state.md#persistent-agent-state). Add the
shared-base default there, retaining its existing explanation of the
authorized manifest override. Keep `--no-auth` scoped to jms-managed agent
state: it does not prohibit arbitrary writes to approved project/extra
mounts or neutralize trusted ambient runtime configuration.

Review the adjacent HO-001 and HO-005 proposal text for consistency with
these conditions, but leave their status Proposed and do not implement their
broader consent or inventory work. The historical review finding remains
useful evidence even after the register is corrected.

### Validation and completion

Check the wording against `cmd_launch()`, `approve()`, and the
`auth and (config["mount_auth"] or args.auth)` decision in `launch_plan()`.
Use the review's fake-backend matrix as the acceptance record:

| Launch | Expected jms-managed agent-state mounts |
| --- | --- |
| Shared base, default flags | All four |
| Shared base, `--no-auth` | None |
| Custom project with a current credential grant and `mount_auth = false` | None |
| Same custom project/grant plus `--auth` | All four |
| Same custom project/grant plus `--no-auth` | None |

`--auth` does not grant itself authority: for a custom definition without
a current credential grant or an applicable exact-fingerprint auth grant,
the existing consent path still applies and unavailable prompting fails.
Describe this accurately; do not change that behavior to simplify the table.

Reuse existing consent/launch coverage and the review's recorded matrix.
This documentation correction does not need tests that merely assert prose.
If a behavior is uncertain, repeat the isolated matrix against both fakes
using a temporary home and matching grants rather than real credentials.

Check local links and run `git diff --check`. Close PR-002 in the review
with the corrected conditions and validation evidence. Add an explicit
follow-up status note saying both findings have been addressed, while
preserving the original review date, revision, and observations. Update this
guide's status to Implemented only when both commits are complete. Include
these documentation changes in commit 2.

## Final PR and release handling

Run `make test` on the final two-commit candidate and check the complete diff.
Verify both commits remain focused and that the implementation PR contains
only its intended changes relative to its base. No completion changes are
needed because this effort adds no command, flag, environment variable, or
default.

Suggested PR title: **Keep launch stdout clean and clarify agent-state mounts**.
Suggested description, filled in with actual results:

```text
Cold launches and stale-image rebuilds could prefix captured program output
with jms progress when Python output was unbuffered. Send build progress and
automatic-retention reports to stderr, with subprocess regression coverage
for both backends.

Correct the outflow register and agent-state guide: shared-base launches
mount state by default, --no-auth suppresses it, and an authorized --auth
can override a custom manifest's mount_auth = false.

Validation: <make test result and count>; <unbuffered regression evidence>;
<documentation/mount-matrix verification>. Resolves PR-001 and PR-002 from
the September 13 project review. RI-007 remains open.
```

The fake subprocess tests establish output routing, not real-runtime
qualification. Keep the fresh-account Debian integration and clean-host
walkthrough requirements in [release-checklist.md](release-checklist.md)
and RI-007 unchanged. Any live validation added to this effort should record
the tested revision, working-tree status, environment, invocation, exit
status, and log location; it counts toward the release gate only if it meets
that gate's existing requirements.
