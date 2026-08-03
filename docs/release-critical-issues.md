# 1.1.0 release-critical issues

Review target: `main...multi-runtime` at `c5157cd`
Reviewed: 2026-07-30; updated 2026-07-31 after a live macOS validation
pass, then again 2026-07-31 closing RC-002/RC-005 and landing the RC-003
procedures, then again 2026-07-31 recording the macOS RC-003 acceptance
runs and the RC-004 macOS gate at `b144a27`, then again 2026-08-03
recording the Debian 13 gate at `8b52ffe` and closing RC-001/RC-004
Merge disposition: **ready**, with one recommended re-check — every
RC-001 through RC-007 issue is closed with recorded evidence, and the
only outstanding item is replaying the RC-007 README fix on a pristine
Debian 13 VM (see that issue's residual risk).

This register contains only issues that must be resolved or explicitly closed
with qualification evidence before 1.1.0 is merged for release.

Status values:

- **Open** — a code, documentation, or test change is required.
- **Awaiting qualification** — the implementation may be complete, but a
  required real-host gate has not been recorded.
- **Closed** — the resolution and its validation evidence are recorded here.

## RC-001 — Standalone images have an undeclared `1000:1000` runtime ABI

- **Severity:** Blocker
- **Status:** Closed
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

### Resolution

2026-08-03: the qualifying run is recorded. `scripts/integration.sh all`
passed at `8b52ffe` on a fresh Debian 13 (trixie) amd64 host with Podman
5.4.2, run as `jmsqual` (uid 4242, primary gid 4242 — both non-1000) from a
real ssh login session, exit 0 with no `FAIL:` lines and a clean leak sweep.

The tier B standalone user-ABI assertions all executed against
`examples/clean-slate` on a store from which `registry.fedoraproject.org/
fedora:latest` had been deleted, so the fully qualified external base was
re-fetched first. Inside the container the assertions confirmed `id -u`,
`id -g`, `id -u isolation`, and `id -g isolation` are all `1000`, `id -un`
is `isolation`, the passwd home is `/home/isolation` and the shell
`/bin/bash`, `/home/isolation` exists, is writable, and is owned `1000:1000`,
and `sudo -n true` succeeds. On the host side the `/work` probe written by
that container came back owned `4242:4242` — the invoking user, not
`1000:1000` — which is the keep-id mapping behaving as designed for a
non-1000 account. This is the case the register was opened for: it could not
have passed had the ABI been left implicit.

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
- **Status:** Closed
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

### Resolution

2026-07-31: both recorded acceptance runs are green against apple/container
1.2.0 at `b144a27` on the macOS qualification host. The survivor-set
acceptance ran inside the full interactive `scripts/integration.sh all`
pass (tier B): after `jms clean --images`, the manual alias
`itest-survivor-alias:keep` survived on the same image identity, no
`jmscontainers-*` ref survived on it, and the unselected base image still
inspects — delete-by-ref did **not** cascade. The manual
vanished-mid-removal race test followed the release-checklist appendix
exactly (ten external-delete iterations racing `jms clean --images`):
every cleanup exited 0 whichever process deleted the image first, no
iteration reported a failed removal for the vanished ref, no
`jmscontainers-jms-race` ref remained after the loop, and the final
convergence clean exited 0.

## RC-004 — Mandatory real-host release qualification is not recorded

- **Severity:** Blocker
- **Status:** Closed
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

2026-07-31, macOS gate recorded: one full interactive
`scripts/integration.sh all` run at `b144a27` against apple/container 1.2.0
is green through both tiers, including the answered credential prompt (the
tier B auth-mount assertion passed live) and the RC-003 survivor-set
acceptance. The gate flushed out one real defect en route, fixed in
`b144a27`: apple/container's attached `run --interactive` exits leaving
`O_NONBLOCK` on the shared terminal description, which turned the next
consent read into an instant default-No EOF and silently launched without
the credential mounts; `consent_input` now restores blocking mode on a tty
stdin before reading (unit regression test added). Note the Darwin tier A
path early-returns before the `== tier A passed ==` echo, so the recorded
log ends with `== tier B passed ==` and `integration tier(s) 'all' passed
on container`. The Debian gates (RC-001, the Linux integration tiers, the
clean-host install walkthrough, and the release-notes matrix) remain the
blocker; if they force a code change, this macOS run must be repeated at
the new candidate commit.

### Resolution

2026-08-03, Debian gate recorded. All four required Linux gates are green at
`8b52ffe`. No executable code changed to achieve them, so the macOS gate
recorded at `b144a27` stands (the only deltas since are the documentation
commits recording these results and the README fix under RC-007).

Host: fresh Debian 13 (trixie) amd64, kernel 6.12.100+deb13-amd64. Test
account `jmsqual` created with `adduser` — uid 4242, primary gid 4242, both
non-1000 — with `/etc/subuid` and `/etc/subgid` ranges `165536:65536`
provisioned automatically, a fresh home on local ext4, and no prior
container state. All commands ran over a real ssh login session; `pam_systemd`
supplied `XDG_RUNTIME_DIR=/run/user/4242` and the user D-Bus session
(`loginctl` reports `Remote=yes`, `Type=tty`). The harness's nftables
egress-denial rule ran via a `NOPASSWD: /usr/sbin/nft` sudoers grant, since
`scripts/integration.sh` uses `sudo -n` by design.

- **Both integration tiers:** `scripts/integration.sh all` exit 0. Tier A and
  tier B both printed their pass banners, followed by `integration tier(s)
  'all' passed on podman`. No `FAIL:` or `harness failure` lines in 1837
  lines of output. The leak sweep runs from the harness EXIT trap and is
  silent on success; a sweep failure would have exited 2. Post-run the host
  showed no containers, no `itest-*` images, and no leftover
  `jms-integration-*` nft table.
- **Credential-consent prompt answered live.** The tier B `--trust --auth`
  launch prompted exactly once and was answered `y` through a pty, so the
  auth-mount assertion passed interactively rather than via a
  `JMS_TRUST_FINGERPRINT` pin: the probe landed in
  `~/.local/share/jmscontainers/agents/claude/`, owned by uid 4242, with
  `CLAUDE_CONFIG_DIR` visible inside.
- **Survivor-set graph (Podman half).** The manual alias
  `itest-survivor-alias:keep` outside the reserved namespace survived
  `jms clean --images` on the same image identity, and the unselected
  dangling image survived unpruned — delete-by-ref did not cascade on
  Podman either.
- **Clean-host install walkthrough:** performed as `jmsqual` following the
  README verbatim. It exposed two README defects, recorded and fixed as
  RC-007; with those corrected the walkthrough runs end to end — base image
  built, and `jms launch` in a fresh checkout mounted the project at `/work`
  as `isolation` 1000:1000 with the host file readable.
- **`make test` with shellcheck present:** 190 unit tests plus a clean
  shellcheck 0.10.0 leg, exit 0. This is the first Linux run of the RC-005
  gate on a host that actually has shellcheck installed.

Release-notes matrix (also recorded in CHANGELOG.md):

| Dimension | Value |
| --- | --- |
| Podman | 5.4.2 (`5.4.2+ds1-2+b2`) |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.100+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` on extfs, native overlay diff |
| Network backend | netavark 1.14.0 (aardvark-dns 1.14.0, pasta 0.0~git20250503) |
| Rootless | true (graph root `~/.local/share/containers/storage`) |
| Python | 3.13.5 |

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

## RC-007 — The README Debian install block fails when followed verbatim

- **Severity:** Blocker
- **Status:** Closed
- **Affected:** `README.md:18-25`, `README.md:54-59`

### Finding

Found by the RC-004 clean-host install walkthrough on 2026-08-03 — the gate
exists precisely to catch this, and nothing else would have. The Debian
block did not survive a literal reading on a fresh host; it failed twice:

1. **`make` is missing.** The block runs `make install`, but `make` is not
   in its `apt` list and is not part of a base Debian 13 install. A new user
   following the README gets `bash: make: command not found`, exit 127, at
   step two. The macOS block is unaffected because Xcode Command Line Tools
   ship `make`, which is likely why this went unnoticed.
2. **`jms` is not on `PATH` in the installing shell.** `make install`
   symlinks into `~/.local/bin`, and Debian's default `~/.profile` prepends
   that directory only `if [ -d "$HOME/.local/bin" ]` — evaluated at login.
   On a fresh account the directory does not exist yet, so the shell that
   runs `make install` never picks it up and the very next line,
   `jms build --base`, fails with `command not found`. It works in any
   *subsequent* login shell, which makes this easy to miss when testing on
   an account that has installed something into `~/.local/bin` before.

Both are release-blocking on the same grounds as RC-002: the install
instructions are a public support surface, and the release checklist makes
the clean-host walkthrough mandatory.

### Resolution

2026-08-03: `make` added to the Debian `apt` line, and an explicit
`exec "$SHELL" -l` step added after `make install`. The load-bearing-packages
paragraph now explains both, so neither reads as noise a reader might skip.

### Residual risk

The walkthrough that found these ran against the README as of `8b52ffe`; the
corrected text has not itself been replayed on a pristine host, because doing
so needs a Debian 13 VM that has never had Podman or `make` installed, and
the qualification host no longer qualifies. The fix is a superset of what the
recorded run proved works — that run succeeded once `make` was installed and
a login shell was used, which is exactly what the two added lines automate —
but a literal re-run on a fresh VM is the honest way to close this to the
same standard as the rest of the register, and is recommended before tagging.

## Verification log

| Check | Result | Notes |
| --- | --- | --- |
| `make test` | Pass | 188 tests on Python 3.13.5; review environment lacked shellcheck (see RC-005) |
| `git diff --check main...HEAD` | Pass | No whitespace errors |
| Real Podman integration | Not run | Sandbox makes `/run/user/1000/libpod` read-only; this would not satisfy the required fresh non-1000 host gate in any case |
| apple/container integration | Not run | No macOS runtime available in the review environment |
| Unit suite at `c5157cd` (2026-07-31) | Pass | 188 tests on macOS |
| apple/container integration at `c5157cd` (2026-07-31) | Pass to the interactive gate | container 1.2.0; tiers A and B green through the credential-mount prompt, which needs a tty (see RC-004 implementation status); found and fixed RC-006 en route |
| Unit suite at `b144a27` (2026-07-31) | Pass | 190 tests plus a clean shellcheck leg on macOS |
| apple/container integration at `b144a27` (2026-07-31) | Pass | container 1.2.0; full interactive run, both tiers green including the answered credential prompt and the RC-003 survivor-set acceptance; found and fixed the consent `O_NONBLOCK` leak en route (see RC-004) |
| Manual removal-race test at `b144a27` (2026-07-31) | Pass | container 1.2.0; ten-iteration external-delete race per the release-checklist appendix; every cleanup exited 0, no failed removals, converged clean (RC-003) |
| `make test` at `8b52ffe` (2026-08-03) | Pass | 190 tests on Python 3.13.5, Debian 13, **with shellcheck 0.10.0 installed** — first Linux run of the RC-005 gate on a host that has it |
| Podman integration at `8b52ffe` (2026-08-03) | Pass | podman 5.4.2; full `scripts/integration.sh all`, both tiers green on a fresh Debian 13 amd64 host as uid/gid 4242 over a real ssh login session; live-answered credential prompt; survivor-set did not cascade; clean leak sweep; no leaked containers, images, or nft tables (RC-001, RC-004) |
| Clean-host install walkthrough (2026-08-03) | Pass with defects | Debian 13 + fresh `jmsqual`; README followed verbatim, exposing the two RC-007 defects; end-to-end green once corrected. Corrected text not yet replayed on a pristine VM (RC-007 residual risk) |
| `git diff --check main...HEAD` at `8b52ffe` (2026-08-03) | Pass | No whitespace errors |
