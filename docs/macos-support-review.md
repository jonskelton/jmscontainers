# macOS support review (2026-08-14)

Review target: `main` at `22286f814ef2cfc8a46af1736dc3a83634e1b762`
(`v1.1.0-6-g22286f8`).

## Resolution (2026-08-14)

All three findings are resolved in the follow-up candidate tree based on
`e8aeb420881b6dab9af16686d8f846a13314f99c` (this review's commit). Evidence
documentation was added after the live run; the release checklist still
requires another run if any later runtime-affecting code changes.

| Finding | Status | Resolution |
| --- | --- | --- |
| M-001 | Resolved | The exact backend pin and live fixture move to apple/container 1.2.2. Homebrew reports `container 1.2.2`; `jms build --base` and every runtime-backed integration command passed with `JMS_RUNTIME_ACCEPT` unset. |
| M-002 | Resolved | Tier A now runs the backend-neutral ownership, identity, sudo, exit, signal-cleanup, inherited-time-zone, read-only-state, and failure-cleanup assertions on Darwin. Tier B permanently asserts preserved `PWD` equality and writable host round trip. |
| M-003 | Resolved | The qualification guide is now version-neutral and derives the candidate, runtime, and observed test count at run time. Historical branch and RC closure instructions were removed. |

Follow-up qualification used the same host matrix recorded below: macOS
26.5.2 on Apple Silicon, Python 3.14.7, shellcheck 0.11.0, and
apple/container CLI and service 1.2.2. The recorded outcomes were:

- `make test`: 233 tests passed in 3.299 seconds; bytecode compilation and
  shellcheck also passed.
- Interactive `scripts/integration.sh all`: both tiers and the final leak
  sweep passed without a runtime override, including the credential prompt,
  inherited `America/Los_Angeles` time zone, preserved host path, and
  survivor-set acceptance. Delete-by-ref did not cascade.
- Manual removal race: all ten iterations exited cleanly, reported no failed
  removal, left no project ref, and the final cleanup converged.
- The apple/container 1.2.2 image-list fixture was recaptured from public
  Fedora probe images. Its normalized shape matches 1.2.0; only probe build
  annotations changed.

## Original verdict

The current code works on this Apple Silicon host with apple/container 1.2.2
when the newer runtime is explicitly accepted. The unit suite, both live
integration tiers, the credential-mount prompt, cleanup survivor test, manual
removal race, inherited host time zone, and preserved host path all passed.
No functional macOS regression was found in the recent Linux/Podman-developed
features.

The default documented first-run path is nevertheless blocked today. Homebrew
installed apple/container 1.2.2, while jms 1.1.0 accepts exactly 1.2.0. Every
runtime-backed command exits 1 until the user adds
`JMS_RUNTIME_ACCEPT=1.2.2`. This is a deliberate fail-closed qualification
gate, but it means the advertised `brew install container python` workflow is
not currently an out-of-box supported installation. Qualify and pin 1.2.2
before treating the present Homebrew path as release-ready.

## Host and scope

| Dimension | Value |
| --- | --- |
| Host | MacBook Pro, Apple Silicon (`arm64`) |
| macOS | 26.5.2 (build 25F84) |
| Darwin kernel | 25.5.0 |
| Python | Homebrew Python 3.14.7 |
| apple/container | 1.2.2 |
| shellcheck | 0.11.0 |
| GNU Make | 3.81 |
| Host time zone | `America/Los_Angeles` |

The review covered the six commits after `v1.1.0`, with particular attention
to timezone propagation (`a67643f`), host-path preservation (`1f8c835`), and
pre-consent mount-layout validation (`22286f8`). It also rechecked the
apple/container backend's version gate, mount grammar, service startup, image
normalization, removal rechecks, and runtime-specific integration branches.

## Original findings

### M-001 — Current Homebrew install is refused by default (High)

The README and macOS guide tell a new user to run `brew install container
python`, then `jms build --base`. On this clean first run, Homebrew supplied
apple/container 1.2.2. `ContainerBackend.version_min` and `version_max` are
both 1.2.0, so even a read-only runtime command failed with:

```text
error: container 1.2.2 is newer than the newest runtime this jms release is qualified against (1.2.0); upgrade jms, install container 1.2.0, or set JMS_RUNTIME_ACCEPT=1.2.2 to accept it for one invocation
```

The override is intentionally per invocation. A user following the quick
start verbatim is therefore stopped, and the suggested installation of 1.2.0
is not provided by the documented unversioned Homebrew command.

Recommendation: use the green evidence in this review as the start of an
apple/container 1.2.2 qualification, update the exact backend pin and fixture
set, rerun the release gate at the resulting commit, and update the README,
macOS guide, changelog, and release evidence together. Keep the explicit
override warning for versions newer than the newly qualified pin.

### M-002 — Darwin integration skips shared launch-contract coverage (Medium)

Tier A returns immediately on Darwin after the base build and a `bwrap`
presence check. The ownership, identity, sudo, exit propagation, signal
cleanup, timezone, read-only shell-state, failure cleanup, and related launch
assertions later in tier A run only on Podman. In particular, the inherited
timezone assertion added in `a67643f` is below the Darwin early return.
`run.preserve_host_path`, added in `1f8c835`, has extensive fake-backend unit
coverage but no live integration assertion on either backend.

The targeted live probes in this review passed, so this is a regression-risk
finding rather than an observed product failure.

Recommendation: factor backend-neutral launch assertions into a common path,
leaving only Podman-specific user-namespace, ambient-config, nested-bwrap, and
nftables checks behind the Linux branch. Add a small temporary project with
`run.preserve_host_path = true` to tier B and assert both `PWD` equality and a
writable host round trip. This would make future macOS qualification cover the
new features without ad hoc commands.

### M-003 — The checked-in macOS qualification guide is historical but presented as current (Low)

`docs/macos-qualification-guide.md` still directs a maintainer to the
pre-release `multi-runtime` branch, expects 189 tests, and asks them to close
RC-003/RC-004 even though the release register already records those issues as
closed. Main now has 232 tests and six unreleased commits after v1.1.0. The
guide is linked from the general documentation index without a historical or
superseded label.

Recommendation: replace it with a version-neutral procedure driven by the
release checklist, or mark it clearly as the archived 1.1.0 qualification
record. Test counts should be recorded as observed evidence rather than used
as a fixed success criterion.

## Verification evidence

| Check | Result | Notes |
| --- | --- | --- |
| `make test` | Pass | 232 tests in 3.534 seconds; bytecode compile and shellcheck also passed |
| `scripts/integration.sh a` | Pass with override | Runtime service began stopped; jms started it, built the Fedora 44 arm64 base, and launched it; `bwrap` was present |
| `scripts/integration.sh b` | Pass with override | All five examples built, inspected, launched, and cleaned; context escape failed as intended; manifest environment and `Asia/Tokyo` override passed; interactive credential mount and host ownership passed |
| apple/container survivor set | Pass | External alias survived on the same image identity, the jms-owned ref was removed, and the unselected base survived; delete-by-ref did not cascade on 1.2.2 |
| Manual removal race | Pass | Ten build/delete/clean iterations produced no `FAIL`, no failed-removal report, no remaining `jmscontainers-jms-race` ref, and a final convergence clean exited 0 |
| Inherited host timezone | Pass with override | Live container reported `TZ=America/Los_Angeles` and `OFFSET=-0700` |
| Preserved host path | Pass with override | A project canonicalized under `/private/tmp/...` saw the identical `PWD` in the VM and the mount was writable |
| Default 1.2.2 version gate | Expected fail | Exit 1 without `JMS_RUNTIME_ACCEPT`, confirming M-001 |
| Test cleanup | Pass | Integration-owned containers and project images were removed; the runtime's `buildkit` service container and the newly built shared base remain by design |

All live runtime checks used `JMS_RUNTIME_ACCEPT=1.2.2`, so they demonstrate
compatibility but do not by themselves change the project's declared
qualification boundary. The base image created by the first-run test was left
as `jmscontainers-base:latest`, matching the documented installation outcome.

## Positive observations

- macOS timezone discovery correctly handled `/etc/localtime` pointing into
  `/var/db/timezone/zoneinfo` and survived `/var` to `/private/var`
  canonicalization.
- BSD `realpath`, BSD `stat` fallback, `/tmp` canonicalization to
  `/private/tmp`, comma/equal mount rejection, and apple/container's string
  argv boundary all behaved as the implementation expects.
- The stopped runtime service was started automatically without sudo.
- Credential state written through virtiofs retained host ownership, while
  shell state stayed read-only in the normal integration path.
- The new mount-layout validation is backend-neutral and runs before consent,
  runtime readiness, or build. Its adversarial unit coverage includes
  preserved paths that shadow system state, effective-home collisions for
  both users, and overlap with manifest mounts.

## Original release recommendation

Do not change the trust or mount design based on this run; the implementation
behaved correctly. Before the next release, resolve M-001 by qualifying the
runtime version users actually receive, and address M-002 so the successful
timezone and preserved-path probes become permanent Darwin integration
coverage. M-003 can be corrected in the same documentation pass.
