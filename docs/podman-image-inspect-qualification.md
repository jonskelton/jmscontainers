# Project: Qualify Podman exact image inspection

Status: Implemented 2026-09-09 (fixtures, backend, tests); the fresh-account
live integration run on the final candidate remains to be recorded
Opened: 2026-08-26
Target: Next bugfix release
Related design: [exact shared-base identity](exact-base-identity-proposal.md)

## Outcome

Qualify `PodmanBackend.resolve_image()` against real Podman 5.4.2 output on
the supported Debian 13 rootless host. Check in successful and absent image
inspection fixtures, make the parser conform narrowly to that evidence, and
complete the final local and live gates.

This project is complete only when the repository no longer describes the
Podman image-inspection behavior as synthetic or pending and the final
candidate passes both integration tiers on the qualified host.

## Issue statement

*Historical: this section states the problem as understood before the
2026-09-09 capture. The assumption it describes proved wrong; see
[Resolution](#resolution-2026-09-09) for the shipped contract.*

The exact shared-base identity change added a new Podman runtime interaction:

```sh
podman image inspect <ref>
```

[`PodmanBackend.resolve_image()`](../bin/jms) currently assumes that a
successful command returns a one-element JSON array whose record has a valid
64-character lowercase hexadecimal `Id` and a `Labels` map or `null`. It also
assumes an absent image produces exit status 125 and this first stderr line:

```text
Error: inspecting object: <ref>: image not known
```

Those assumptions have synthetic unit coverage, but neither outcome has been
captured from the qualified Debian 13/rootless Podman 5.4.2 host. The existing
`podman-5.4.2-inspect.json` fixture is container inspection output and cannot
qualify image inspection.

This is release-blocking because a clean project has no computed project image
yet. `build_project()` calls `resolve_image(project_tag)` before its first
build, so it immediately exercises the absent-image path. If the real exit
status or diagnostic differs from the synthetic assumption, jms treats normal
absence as a runtime failure and every first project build aborts.

Passing unit tests does not reduce this risk: the test double currently emits
the same unverified values that the implementation expects.

## Scope

This project includes:

- capturing successful and absent `podman image inspect` results on the
  qualified host;
- checking in sanitized fixtures with complete provenance;
- adjusting `PodmanBackend.resolve_image()` only as required by the captured
  output;
- adding fixture-backed success and absence tests;
- updating the exact-identity and fixture documentation to remove pending or
  synthetic status; and
- running the repository gate and both live integration tiers on the final
  candidate.

It does not redesign exact shared-base identity, broaden the supported Podman
range, or weaken fail-closed handling of unexpected runtime errors.

## Required qualification host

Use the real host required by the [release checklist](release-checklist.md):

- Debian 13 (trixie), amd64;
- rootless Podman 5.4.2 with overlay storage;
- a fresh user created with `adduser`, with non-1000 UID and primary GID and
  subordinate UID/GID ranges covering at least 65,536 IDs;
- a fresh home on a local filesystem with no prior container state;
- a real ssh login session providing `XDG_RUNTIME_DIR` and the user D-Bus
  session through `pam_systemd`; and
- the `nftables` and passwordless `sudo -n nft` prerequisites needed by the
  integration harness.

A nested container, CI runner, different Podman version, or locally fabricated
fixture does not qualify this runtime contract.

## Capture procedure

Start from the candidate checkout on the qualified host. Record at least the
candidate commit, date, architecture, kernel, Podman version, cgroup manager,
OCI runtime, storage driver, network backend, user UID/GID, and the fact that
the session is a real ssh login.

Use two refs dedicated to the fixture:

- present: `jms-resolve-fixture:latest`;
- absent: `jms-resolve-fixture-absent:latest`.

First verify that neither ref already exists. Refuse to overwrite a pre-existing
ref; do not delete an unrecorded user image. Then build the present probe from:

```dockerfile
FROM scratch
LABEL jms.fixture=exact-resolve
```

Capture stdout, stderr, and status independently for both commands. For
example, from a private temporary directory:

```sh
present_status=0
podman image inspect jms-resolve-fixture:latest \
    >present.stdout 2>present.stderr || present_status=$?

absent_status=0
podman image inspect jms-resolve-fixture-absent:latest \
    >absent.stdout 2>absent.stderr || absent_status=$?

printf 'present status: %s\nabsent status: %s\n' \
    "$present_status" "$absent_status"
wc -c present.stdout present.stderr absent.stdout absent.stderr
```

Preserve the raw files until the implementation and tests are complete. Do
not trim diagnostics, normalize whitespace, or infer an exit status from the
text. Remove the probe ref after the capture has been copied and verified.
Building and removing the probe still means that account has prior container
state; use another newly created account, or recreate the qualification
account, for the release checklist's fresh-account integration run.

## Implementation plan

*Historical: the plan as written before the capture. Step 2 was carried out
differently once the absent diagnostic turned out not to match the
assumption; see [Resolution](#resolution-2026-09-09).*

### 1. Add fixtures and provenance

Add these files under `tests/fixtures/`:

- `podman-5.4.2-image-inspect.json` containing the whole successful JSON
  result; and
- `podman-5.4.2-image-inspect-absent.stderr` containing the absent diagnostic
  bytes verbatim when stderr is the observed diagnostic channel.

If the absent command emits stdout or another material output not represented
by those names, preserve it in an additional fixture rather than discarding
it. Record the observed success and absence exit statuses in
[`tests/fixtures/README.md`](../tests/fixtures/README.md).

Apply the repository fixture sanitization contract: replace only the invoking
username and hostname, re-serialize JSON with sorted keys and two-space
indentation, and otherwise preserve values verbatim. Document the capture date,
host/runtime provenance, probe definition, exact commands, output channels,
statuses, and cleanup.

### 2. Conform the backend to observed behavior

Update `PodmanBackend.resolve_image()` in `bin/jms` after examining the raw
capture:

- On success, accept only the captured Podman 5.4.2 record shape needed for a
  full image identity and normalized labels. Retain one-record cardinality,
  full lowercase hexadecimal ID validation, and strict label validation unless
  the real fixture proves a narrowly different shape is required.
- On absence, return `None` only for the captured combination of exit status
  and diagnostic shape. Keep the classification narrow and fixture-backed.
- Continue to fail terminal-safely on invalid UTF-8, invalid or ambiguous JSON,
  malformed IDs or labels, storage errors, daemon errors, and every other
  nonzero result.
- Remove the comments calling the branch synthetic only after the fixture and
  conformance test exist.

If the capture agrees exactly with the current assumptions, retain the logic
and make this an evidence-and-test change. Do not manufacture a code diff when
the qualified behavior already matches.

### 3. Add fixture-backed tests

Extend `ResolveImageTests` in `tests/test_jms.py` with a Podman counterpart to
the Apple fixture test. The test must:

1. load the successful Podman fixture;
2. return the captured absent status and raw diagnostic from the absent
   fixture;
3. assert the successful ref resolves to the fixture's exact full ID and
   `{"jms.fixture": "exact-resolve"}` labels; and
4. assert the absent ref resolves to `None`.

Update the synthetic absence-classification cases to reflect the captured
contract. Retain negative cases proving that a similar diagnostic with the
wrong exit status and unrelated failures still abort.

### 4. Reconcile project documentation

Update all statements that currently call the Podman image-inspection fixture
or behavior pending or synthetic, including:

- `tests/fixtures/README.md`;
- `docs/exact-base-identity-proposal.md`; and
- any release notes or qualification record for the candidate.

Do not mark the exact-identity project fully qualified until the final live
run below is recorded against the same runtime-affecting candidate.

### 5. Run the gates

Run locally:

```sh
make test
```

Then put the final candidate on the qualified Debian host and run, from the
required fresh account and real ssh session:

```sh
scripts/integration.sh all
```

Both tiers, the leak sweep, and the clean-host README installation walkthrough
must pass. Record the candidate commit and full environment dimensions required
by the release checklist. A later runtime-affecting change invalidates the live
run and requires it to be repeated.

## Acceptance criteria

Restated 2026-09-09 against the shipped contract; the third criterion as
originally written ("returns `None` for exactly the captured absence
outcome") is superseded, because absence is now decided by the `podman image
exists` probe and the captured inspect outcome is evidence for the failure
path instead.

- [x] Successful and absent image-inspection fixtures come from the qualified
  Debian 13/rootless Podman 5.4.2 host.
- [x] Fixture provenance records exact commands, statuses, output channels,
  capture date, environment, sanitization, and cleanup.
- [x] `PodmanBackend.resolve_image()` accepts the captured success shape and
  returns `None` only for a `podman image exists` exit 1.
- [x] Every nonzero `podman image inspect` after a positive probe fails
  closed, reporting the exit status and the diagnostic; the captured absent
  diagnostic is pinned as evidence for that path.
- [x] Unexpected probe statuses and malformed successful output still fail
  closed with terminal-safe diagnostics.
- [x] A fixture-backed Podman test exercises the success record and the
  captured absent diagnostic.
- [x] `make test` passes.
- [ ] `scripts/integration.sh all` passes on the final candidate on the
  qualified host, including a clean project's first build.
- [ ] The clean-host installation walkthrough passes and the release evidence
  is recorded.
- [x] No repository text outside the sections marked historical above
  describes this interaction as synthetic, assumed, or pending.

## Rejected shortcuts

- Do not broaden absence detection to a substring, generic nonzero status, or
  every exit status 125. That could hide storage or runtime failures as normal
  absence.
- Do not call `podman image exists` before inspection merely to avoid learning
  the absent inspection contract. It adds a race and a duplicate query and
  does not qualify successful inspection output. *Revisited 2026-09-09:* the
  contract was learned (see Resolution below) and it differed from the
  assumption, so the probe was adopted deliberately -- it makes absence
  independent of diagnostic wording that has already moved between Podman
  releases and identical to the `image_exists()` decision `ensure_base()`
  already trusts. The race (an image removed between probe and inspect)
  surfaces as the inspect's loud failure, not as absence; the duplicate
  query costs ~20 ms per resolve. Successful inspection output is qualified
  by the checked-in fixture, not by the probe.
- Do not repurpose `podman-5.4.2-inspect.json`; it describes a container, not
  an image.
- Do not substitute Podman documentation, synthetic mocks, another Podman
  release, a nested runtime, or a green macOS run for real-host evidence.
- Do not edit captured values beyond the repository's documented fixture
  sanitization rule.

## Resolution (2026-09-09)

The gap this project described materialized before the capture was made.
With the exact-identity change merged to `main` (`6102bd9`) but unreleased,
the first `jms build` for a project whose fingerprint had moved failed with

```text
error: podman image inspect failed for "jmscontainers-<project>:<tf>":
  "Error: jmscontainers-<project>:<tf>: image not known\n"
```

Podman 5.4.2 exits 125 with `[]` on stdout and the stderr line
`Error: <ref>: image not known`; the assumed `inspecting object:` prefix does
not appear. The defect existed only on unreleased `main`, between `6102bd9`
and this change: `v1.1.0` predates the parser and never refused a build this
way. `podman image exists` on the same ref exits 1. Both outcomes and
the successful record were captured per the procedure above and checked in
as `tests/fixtures/podman-5.4.2-image-inspect.json` and
`tests/fixtures/podman-5.4.2-image-inspect-absent.stderr`; provenance,
including the caveat that the capture account was not fresh, is in
[`tests/fixtures/README.md`](../tests/fixtures/README.md).

`PodmanBackend.resolve_image()` now asks `podman image exists` first and
returns `None` on exit 1; a nonzero inspect after a positive probe is always
a failure that reports the exit status and the diagnostic. The synthetic
comment is gone. `ResolveImageTests` gained the fixture-backed Podman test,
an argv test proving the probe short-circuits before inspect, and negative
cases proving the genuine absent diagnostic, the same diagnostic for a
different ref, the old prefixed form, and an unexpected probe status all
still abort. `make test` passes (272 tests).

Still outstanding from the acceptance criteria: `scripts/integration.sh all`
from a fresh account on the qualified host against the final candidate, and
the clean-host installation walkthrough. The release checklist now requires a
live absent-ref inspect capture per qualified Podman version.

## Handoff notes

*Historical: written before implementation. The code, fixture, and test work
described here is done; what remains is the live gate named in the
Resolution.*

The likely implementation area is small: `PodmanBackend.resolve_image()` in
`bin/jms`, `ResolveImageTests` in `tests/test_jms.py`, new fixtures under
`tests/fixtures/`, and the status/provenance documentation named above. The
essential work is obtaining and preserving qualified-host evidence before
deciding whether the existing parser needs to change.

## Appendix: captured absent-reference diagnostics (2026-09-09)

Preserved from the working incident write-up that led to this change. That
file lived untracked at the repository root and was not committed: its line
references described the pre-fix tree, and it carried another project's
details, absolute paths containing the developer's username, and a
`podman run` recipe that bypasses the jms trust gate and provenance labels.
The table below is the part with durable value, and it is reproduced with no
edits — the commands carry no usernames or host paths, so the fixture
sanitization rule leaves them unchanged.

Captured on the qualified host (Podman 5.4.2, rootless, Debian 13 (trixie),
amd64, overlay storage driver) against references that do not exist:

| Command | Exit | stdout | stderr (first line) |
|---|---|---|---|
| `podman image inspect nonexistent:zz` | 125 | `[]` | `Error: nonexistent:zz: image not known` |
| `podman image inspect localhost/nonexistent:zz` | 125 | `[]` | `Error: localhost/nonexistent:zz: image not known` |
| `podman inspect --type image nonexistent:zz` | 125 | `[]` | `Error: nonexistent:zz: image not known` |
| `podman image inspect sha256:000…000` | 125 | `[]` | `Error: sha256:000…000: image not known` |
| `podman inspect nonexistent:zz` (untyped) | 125 | `[]` | `Error: no such object: "nonexistent:zz"` |

Two things are pinned here that the single-line
`podman-5.4.2-image-inspect-absent.stderr` fixture cannot show on its own.
The `inspecting object:` prefix assumed by the original parser appears in
none of the four typed forms, whether the reference is a bare tag, a
`localhost/`-qualified tag, or a digest. And the untyped `podman inspect`
emits an entirely different diagnostic (`no such object:`, quoted
reference), which is one reason this backend always inspects with the
`image` subcommand: the two spellings do not share an error contract.

The write-up proposed five fixes. Their disposition:

| Proposed | Disposition |
|---|---|
| 1 — probe absence with `podman image exists` before inspecting | Adopted. The shipped `PodmanBackend.resolve_image()` contract; see Resolution above. |
| 2 — keep a tolerant regex parse as defence in depth | Rejected by design. See "Rejected shortcuts": absence must not be derived from diagnostic wording at all once a typed probe decides it, and a second path that can report absence reintroduces exactly the coupling the probe removes. |
| 3 — recapture the fixture, retire the "synthetic" comment | Adopted, and generalized: the fixtures are checked in with provenance, the comment is gone, and the release checklist now requires a live absent-ref capture per qualified Podman version. |
| 4 — report the exit status alongside the diagnostic | Adopted, on both backends. |
| 5 — skip the target-tag resolution under `--no-cache` | Adopted later, tracked as RI-004 in [review-issues-2026-09-09.md](review-issues-2026-09-09.md) and fixed in its own commit. |

The write-up's header attributed the defect to "1.1.0". It did not exist in
any tagged release — only on unreleased `main`, on the tree carrying the
parser introduced by `6102bd9`. The wrong version came from `__version__`
still reading `1.1.0` after the tag, which is RI-002 in the same register.
