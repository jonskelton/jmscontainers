# Project: Qualify Podman exact image inspection

Status: Ready for implementation; release-blocking qualified-host work remains
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

The project is complete when all of the following are true:

- Successful and absent image-inspection fixtures come from the qualified
  Debian 13/rootless Podman 5.4.2 host.
- Fixture provenance records exact commands, statuses, output channels,
  capture date, environment, sanitization, and cleanup.
- `PodmanBackend.resolve_image()` accepts the captured success shape and
  returns `None` for exactly the captured absence outcome.
- Unexpected nonzero results and malformed successful output still fail
  closed with terminal-safe diagnostics.
- A fixture-backed Podman test exercises both success and absence.
- `make test` passes.
- `scripts/integration.sh all` passes on the final candidate on the qualified
  host, including a clean project's first build.
- The clean-host installation walkthrough passes and the release evidence is
  recorded.
- No repository text still describes this interaction as synthetic, assumed,
  or pending.

## Rejected shortcuts

- Do not broaden absence detection to a substring, generic nonzero status, or
  every exit status 125. That could hide storage or runtime failures as normal
  absence.
- Do not call `podman image exists` before inspection merely to avoid learning
  the absent inspection contract. It adds a race and a duplicate query and
  does not qualify successful inspection output.
- Do not repurpose `podman-5.4.2-inspect.json`; it describes a container, not
  an image.
- Do not substitute Podman documentation, synthetic mocks, another Podman
  release, a nested runtime, or a green macOS run for real-host evidence.
- Do not edit captured values beyond the repository's documented fixture
  sanitization rule.

## Handoff notes

The likely implementation area is small: `PodmanBackend.resolve_image()` in
`bin/jms`, `ResolveImageTests` in `tests/test_jms.py`, new fixtures under
`tests/fixtures/`, and the status/provenance documentation named above. The
essential work is obtaining and preserving qualified-host evidence before
deciding whether the existing parser needs to change.
