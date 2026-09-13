# Review issues: Podman image-inspect qualification (2026-09-09)

Review target: the uncommitted working tree on `main` at `6102bd9` (the
Podman absent-image fix: `bin/jms`, `tests/test_jms.py`, the two
`podman-5.4.2-image-inspect*` fixtures, `CHANGELOG.md`, and the four
updated documents)
Reviewed: 2026-09-09
Disposition: the backend change is **correct and mergeable**; the items
below are documentation, bookkeeping, and test-hygiene defects in the same
work, plus the one live gate that is still open. None of them changes
runtime behavior.

Updated 2026-09-12: RI-001, RI-005, and RI-006 were resolved in the same
working tree before it was committed, since each was internal to this
change. RI-004 was fixed immediately afterwards in its own commit. RI-002
and RI-003 remain open as separable follow-ups, and RI-007 remains the
release gate.

This register follows the conventions of
[release-critical-issues.md](release-critical-issues.md), which is closed
for 1.1.0. Items here are scoped to the next bugfix release.

Status values:

- **Open** — a code, documentation, or test change is required.
- **Awaiting qualification** — the implementation may be complete, but a
  required real-host gate has not been recorded.
- **Closed** — the resolution and its validation evidence are recorded here.

What was verified and found sound, so it is not repeated below:

- `PodmanBackend.resolve_image()` decides absence with `podman image exists`
  (exit 0/1, any other status a loud failure), then treats every nonzero
  inspect as a failure carrying the exit status and both streams. Both
  commands resolve the reference through the same engine lookup, so the
  probe cannot disagree with the inspect about which image a name means.
  The probe-then-inspect race is documented and fails loudly rather than
  reporting absence.
- `tests/fixtures/podman-5.4.2-image-inspect.json` is authentic 5.4.2
  output. The `GraphDriver.Data` paths without a layer id are what the
  overlay driver emits for an image whose top layer is empty (`FROM scratch`
  with only a `LABEL`), so the "only the username was edited" provenance
  claim is consistent with the record.
- The absent-ref stderr fixture is one verbatim line, and the tests prove
  that the genuine diagnostic, the same diagnostic for another ref, the
  previously assumed prefixed form, and an unexpected probe status all still
  abort after a positive probe.
- `make test` passes: 272 tests.

## RI-001 — The fix is described as a shipped 1.1.0 regression, but 1.1.0 never had the defect

- **Severity:** Medium (misleading release record)
- **Status:** Closed 2026-09-12
- **Affected:** `CHANGELOG.md` Unreleased entry (lines 5-15),
  `docs/podman-image-inspect-qualification.md` "Resolution (2026-09-09)",
  `JMS_BUILD_FIXES.md` header (see RI-003)

### Finding

`git tag` places `v1.1.0` at `b2e4b6f`, before every PR since #4. The
Podman `resolve_image()` parser was introduced by #13 (`6102bd9`) and never
existed in a tagged release. Yet the new text says:

- CHANGELOG: "project builds on Podman 5.4.2 are no longer refused" and
  "every first build of a project ... aborted", phrased as a user-visible
  regression being repaired;
- qualification doc: "with `v1.1.0` tagged, the first `jms build` ... failed";
- `JMS_BUILD_FIXES.md`: "Affects: `jmscontainers` 1.1.0 at `81fdb11`".

A reader of the next release notes will conclude 1.1.0 refused first builds
on Podman. It did not. The confusion has a mechanical cause: `__version__`
still reads `1.1.0` on post-tag `main`, so a development install reports
itself as the release (see RI-002).

### Required resolution

Reword the CHANGELOG entry so it describes the exact-identity change as it
will ship, not as a repair of a released defect. The simplest form folds it
into the existing "Shared-base freshness now follows exact runtime image
identity" entry as the Podman absence-contract paragraph, since both land in
the same release. If a separate entry is kept, state that the defect existed
only on unreleased `main` between `6102bd9` and this change. Apply the same
correction to the qualification doc's Resolution section ("with the
exact-identity change merged to `main`" rather than "with `v1.1.0` tagged").

### Close when

Neither `CHANGELOG.md` nor any document under `docs/` implies that a tagged
release exhibited the absent-image refusal.

### Resolution (2026-09-12)

The separate CHANGELOG entry was folded into the existing "Shared-base
freshness now follows exact runtime image identity" entry as its Podman
absence-contract paragraph, phrased as the contract that ships rather than
as a repair. The qualification doc's Resolution now reads "with the
exact-identity change merged to `main` (`6102bd9`) but unreleased" and
states that the defect existed only between `6102bd9` and the fix. A scan of
`CHANGELOG.md` and `docs/` finds no remaining text tying the refusal to a
tag. RI-002 (the `__version__` window) stays open separately.

## RI-002 — Post-tag `main` reports `__version__ = "1.1.0"`

- **Severity:** Low
- **Status:** Open
- **Affected:** `bin/jms:31`, the `jms_version` field stamped into trust
  records (`bin/jms:1430`), `docs/release-checklist.md`

### Finding

Ten PRs have merged since `v1.1.0`, several of them runtime-affecting, and
`jms --version` on `main` still prints `1.1.0`. Every trust record written
by a development install therefore claims it was granted by 1.1.0, and the
incident write-up in `JMS_BUILD_FIXES.md` inherited the wrong version for
the same reason. The release checklist says to "set and review
`__version__`" at release time only, which is what allows the window.

### Required resolution

Pick one and record it in the release checklist:

1. Bump `__version__` to the next patch version (`1.1.1`) on the first
   runtime-affecting commit after a tag, so the working tree never
   identifies as a release it is not; or
2. Add a development marker (for example `1.1.1.dev`) after tagging and
   strip it in the release commit.

Either way, add a checklist line so the post-tag bump is part of cutting a
release rather than something remembered later.

### Close when

`bin/jms` on `main` reports a version that is not an existing tag, and the
release checklist names the post-tag step.

## RI-003 — `JMS_BUILD_FIXES.md` should not be committed at the repository root as written

- **Severity:** Medium (if committed as-is)
- **Status:** Open
- **Affected:** `JMS_BUILD_FIXES.md` (untracked)

### Finding

The file is the incident diagnosis that led to the fix. It was useful for
that purpose and its durable content is now captured in the qualification
doc's Resolution section, the fixtures README provenance paragraph, and the
CHANGELOG. As a repository file it has four problems:

- Its `bin/jms:NNN` and `tests/test_jms.py:NNN` line references and quoted
  code describe the pre-fix tree and are already stale.
- It records another project's details (the `beadrail` fingerprint move,
  its `AGENTS.md` ladder, its accepted interpreter build) and absolute host
  paths containing the developer's username, which the fixtures README's
  sanitization rule exists to keep out of the repository.
- Section 6 documents a `podman run` invocation that bypasses the jms trust
  gate and provenance labels. The text says it "should not become routine",
  but publishing it in the tool's own repository makes it the first search
  hit for anyone who wants exactly that.
- "Fix 2" (a tolerant regex fallback) and "Fix 5" (skip the target-tag
  probe under `--no-cache`) are listed as required but were not adopted; the
  first was rejected by design (see the qualification doc's revisited
  non-goal) and the second is tracked as RI-004. A reader cannot tell which
  of the five fixes shipped.

### Required resolution

Do not add the file to the commit. If an incident record is wanted, move a
trimmed version to `docs/` (the captured five-row diagnostic table in §2 is
the one part not already preserved elsewhere and is worth keeping, for
example as an appendix to the qualification doc), drop the beadrail
sections and the workaround, replace the username in any remaining path
per the sanitization rule, and mark each proposed fix as adopted, rejected,
or tracked.

### Close when

`git status` no longer shows the file untracked at the root, and any
surviving copy under `docs/` meets the sanitization rule and states the
disposition of every proposed fix.

## RI-004 — `build_project()` still resolves the target tag under `--no-cache`

- **Severity:** Low
- **Status:** Closed 2026-09-12
- **Affected:** `bin/jms:1724-1746` (`build_project`)

### Finding

`project = resolve_image(tag)` runs unconditionally, but its result is only
consulted when `--no-cache` is absent. Under `--no-cache` the call costs two
Podman invocations and, more to the point, can still abort an explicitly
requested rebuild on any inspect failure, which is the exact class of
problem the diagnosis flagged as its "Fix 5". The absence-probe change
removes the specific trigger, not the dependency.

### Required resolution

Skip the resolution when `args.no_cache` is set, and add a unit test
asserting that `jms build --no-cache` issues no `image exists` or
`image inspect` call for the project tag before the build. The
`shared_base_dependency()` resolutions must stay: they feed the `jms.base`
label regardless of cache mode.

### Close when

The test exists and passes, and `--no-cache` reaches `run_build()` without
inspecting the project tag.

### Resolution (2026-09-12)

`resolve_image(tag)` moved inside the `not args.no_cache` branch, so an
explicitly requested rebuild never resolves the image it is about to
replace. `shared_base_dependency()` still runs unconditionally, since its
result becomes the `jms.base` label on the new image.
`test_no_cache_never_resolves_the_project_tag` in `BuildTests` (so on both
backends, via `BuildTestsPodman`) asserts that no `image inspect` or
`image exists` call names the project tag during a `--no-cache` build, and
that the shared base is still resolved. It fails on both backends without
the change. `make test` passes (274 tests).

## RI-005 — The fixture-backed absence test never routes the absence fixture through the resolver

- **Severity:** Low (test hygiene)
- **Status:** Closed 2026-09-12
- **Affected:** `tests/test_jms.py:2828-2855`
  (`test_podman_qualified_fixture_resolves_and_absence_fixture_is_none`,
  renamed by the resolution below)

### Finding

The fake runtime in this test has a branch that returns the captured
absent-ref stderr from `image inspect`, but the resolver never reaches it:
`image exists` answers 1 for the absent ref first, so the third recorded
argv is the only call made for that ref. The fixture bytes are pinned only
by a literal `assertEqual` against the file contents, and the test name
promises that the absence fixture drives a `None` result when it cannot.
The loud-failure case that *does* exercise the captured diagnostic
(`test_absence_is_narrowly_classified_per_backend`) uses a hand-typed copy
of the line rather than the fixture.

### Required resolution

Remove the unreachable branch and rename the test to say what it proves
(probe absence returns `None`; the success fixture resolves). Feed the
fixture bytes into the loud-failure case so the checked-in diagnostic, not
a transcription of it, is what the failure-message assertion runs against.

### Close when

No fake-runtime branch in `ResolveImageTests` is unreachable, and the
absent-ref fixture file is read by the test that asserts on its wording.

### Resolution (2026-09-12)

The unreachable inspect-absent branch is gone and the test is renamed
`test_podman_success_fixture_resolves_and_probe_decides_absence`, with a
comment saying why the absence fixture cannot appear in it.
`test_absence_is_narrowly_classified_per_backend` now reads
`podman-5.4.2-image-inspect-absent.stderr` and drives its two genuine-absent
failure cases from those bytes against the fixture's own ref, so the
checked-in diagnostic is what the failure-message assertion matches. The
literal `assertEqual` on the fixture contents is removed as redundant.
`make test` passes (272 tests, 69 subtests).

## RI-006 — The qualification doc's acceptance criteria no longer match its Resolution

- **Severity:** Low (documentation consistency)
- **Status:** Closed 2026-09-12
- **Affected:** `docs/podman-image-inspect-qualification.md` "Issue
  statement", "Acceptance criteria", and "Handoff notes"

### Finding

The Status header and the new Resolution section describe the probe-first
design, but the body still reads as the pre-capture plan:

- the Issue statement says the backend "currently assumes ... `Error:
  inspecting object: <ref>: image not known`", in the present tense;
- the acceptance criterion "returns `None` for exactly the captured absence
  outcome" is now false by design: the resolver returns `None` on the probe's
  exit 1 and treats the captured inspect outcome as a failure;
- the final criterion, "no repository text still describes this interaction
  as synthetic, assumed, or pending", is contradicted by the Issue
  statement itself;
- the Handoff notes still tell a future implementer to decide "whether the
  existing parser needs to change".

### Required resolution

Either mark the Issue statement, Plan, and Handoff notes as the historical
plan (a one-line note under each heading suffices) or rewrite the acceptance
criteria to the shipped contract: `None` only on a probe exit 1, every
nonzero inspect after a positive probe a failure, and the captured absent
diagnostic pinned as evidence for the failure path.

### Close when

Every acceptance criterion in the document is either satisfied by the
shipped code or explicitly marked as superseded.

### Resolution (2026-09-12)

Both halves were applied. The Issue statement, Implementation plan, and
Handoff notes each carry a one-line historical marker pointing at the
Resolution section. The acceptance criteria are restated as a checklist
against the shipped contract -- `None` only on a probe exit 1, every nonzero
inspect after a positive probe a loud failure, the captured diagnostic
pinned as evidence for that path -- with the superseded third criterion
called out by name and the two live-gate items left unchecked for RI-007.

## RI-007 — Live Podman gate on the final candidate

- **Severity:** Blocker for the next tag
- **Status:** Awaiting qualification
- **Affected:** `scripts/integration.sh`, the release checklist, the
  qualification doc's "Still outstanding" paragraph

### Finding

`scripts/integration.sh` builds clean projects with `jms build --trust
--no-auth -w <project>` in at least five places (tiers A and B, the
clean-store case, and the examples sweep), so a Podman run of either tier
would have refused the first build and caught the defect the day #13
merged. The last recorded Podman integration run is at `8b52ffe`
(2026-08-03), before #9 through #13. The exact-identity proposal has said
"final live release qualification remains pending" since 2026-08-26, and
the defect reached `main` inside that window.

This is already listed as outstanding in the qualification doc; it is
repeated here so the register is complete and so the gap has a concrete
trigger: runtime-affecting changes merged to `main` for five weeks with the
Podman gate unrun.

### Required resolution

1. Run `scripts/integration.sh all` from the fresh account on the qualified
   Debian 13 / rootless Podman 5.4.2 host against the commit that will be
   tagged, and record the candidate, date, and environment dimensions in the
   verification log below.
2. Perform the clean-host installation walkthrough for the same candidate.
3. Consider adding to `CONTRIBUTING.md` (or the checklist) the rule that a
   PR touching a backend's runtime argv or parsers is not merged without a
   recorded integration run on that backend, since the unit suite's test
   double can only ever confirm the assumptions the implementer already made.

### Close when

The verification log records both tiers green and the walkthrough passing
on the tagged commit.

## Verification log

| Check | Result | Notes |
| --- | --- | --- |
| `make test` at working tree (2026-09-09) | Pass | 272 tests, 69 subtests, Python 3.13 on Debian 13; two `load_module` deprecation warnings from the test loader, unrelated |
| `make test` after RI-001/005/006 (2026-09-12) | Pass | 272 tests, 69 subtests; same host and interpreter. The RI-005 rewrite changed test bodies and one test name, not the count |
| `make test` after RI-004 (2026-09-12) | Pass | 274 tests, 69 subtests; the two new tests are the per-backend `--no-cache` resolution assertions |
| Podman integration on this candidate | Not run | See RI-007 |
| apple/container integration on this candidate | Not run | The change does not touch `ContainerBackend` argv or parsing; only its failure message gained the exit status |
