# Role-based audit, consolidated — jmscontainers 2.0.1 (2026-10-12)

Status: a snapshot of 2.0.1, kept as written. Its P1 batch shipped in
2.0.2 and most of the 2.1 plan in 2.1.0; [CHANGELOG.md](../../../CHANGELOG.md)
says what changed. Line references point at 2.0.1 (`90255df`).

## Verdict

**2.0.1 is sound at the core and rough at the edges. Five independent
audits found no High-severity issue.** Together they report 83 findings: 31
Medium, 41 Low and 11 Note. These collapse into 16 themes.

The consent model, the reference docs and the code structure each got praise
from the roles that looked at them. The weaknesses sit in four places:

1. what jms says when it refuses, or when it is wrong;
2. how it behaves when the runtime hangs or jms is killed;
3. what an operator can see afterwards;
4. how much a successor must hold in their head.

**The biggest surprise:** the missing-base hint (`bin/jms:49-51`) tells a
stuck newcomer to run a command that no longer exists. Three of the five
auditors found it on their own, and a unit test pins the wrong wording.

## The audits

| Role | File | Med | Low | Note | Verdict in one line |
| --- | --- | --- | --- | --- | --- |
| First-time adopter | [first-time-adopter.md](first-time-adopter.md) | 4 | 9 | 2 | Two README blocks reach a working launch; the login story and the Docker boundary are where newcomers stall |
| SRE / operator | [sre-operator.md](sre-operator.md) | 8 | 5 | 3 | Fails loudly when the runtime is broken; has no answer for a slow or hung one |
| Long-term maintainer | [long-term-maintainer.md](long-term-maintainer.md) | 6 | 9 | 3 | Healthy enough to inherit; the risk is people and process |
| Technical writer | [technical-writer.md](technical-writer.md) | 6 | 7 | 2 | Reference docs are exact; the drift is at the edges |
| CLI interaction designer | [cli-interaction-designer.md](cli-interaction-designer.md) | 7 | 11 | 1 | Consent is honest and complete; the paths a user takes to recover from an error are weak |
| **Total** | | **31** | **41** | **11** | **83 findings, 0 High** |

The security-auditor and pragmatic-developer perspectives were left out of
this round on purpose; they are covered by separate reviews. Each role ran
on its own branch (`audit/role-<slug>`) from `main` at `90255df`. No role
read another role's audit.

## Method and limits

- **Ran:** `make test` passed (382 tests) in three of the five audits. The
  CLI was probed with a scratch `HOME`. The interactive consent prompt was
  driven under a pseudo-TTY. One real `jms launch -b true .` ran on the
  Linux host.
- **Not run:** integration tiers A and B, and anything on macOS. Every
  macOS claim comes from reading the code. The findings marked unverified in
  the role audits are OPS-10 and DOCS-07, plus all macOS runtime behaviour.
- **Checked during consolidation:** I re-checked eight findings against
  `main`, and all eight hold:

  | Finding | What it claims |
  | --- | --- |
  | C-01 | The `MISSING_BASE_NOTE` text |
  | C-02 | `docs/macos.md:51-52` vs. `JMS_RUNTIME_ACCEPT`, which was removed in #24 |
  | C-03 | `bin/jms:326` prints to stdout |
  | C-04 | `bin/jms:1722-1725` (`trust --fingerprint --auth`) |
  | C-05 | `bin/jms:1576-1577` swallows the mount-source detail |
  | C-06 | `bin/jms` has no `timeout` and catches only `KeyboardInterrupt` |
  | C-10 | `clean` has no confirmation path |

- **One incident during probing (SRE audit):**
  - What happened: a probe reached the real podman through `/bin`. It
    started a base build against a scratch `HOME`, which pulled Fedora over
    the network.
  - Cleanup: the auditor stopped it, unmounted the overlay mount it left
    behind via `podman unshare`, and deleted the scratch store.
  - Real store: untouched. After all audits finished, `podman ps -a
    --external` was empty and no podman processes remained.
  - What it showed: the leftover mount is itself evidence for OPS-02.

## Themes, ranked

Priority key:
- **P1:** fix in the next patch; the change is small and the problem hits
  users.
- **P2:** worth a minor release.
- **P3:** backlog.

| # | Pri | Theme | Roles | Findings |
| --- | --- | --- | --- | --- |
| C-01 | P1 | The missing-base hint gives a command that doesn't exist | 3 | UX-03, ADOPT-10, DOCS-02 |
| C-02 | P1 | macOS docs still promise a removed version-acceptance override | 2 | DOCS-01, ADOPT-13 |
| C-03 | P1 | stdout is not always the launched program's | 3 | DOCS-03, OPS-09, OPS-10, UX-16 |
| C-04 | P1 | Credential grants and `/work`/`.git` protection are explained incompletely | 3 | DOCS-04, DOCS-06, DOCS-11, DOCS-13, ADOPT-01, ADOPT-02, UX-11, UX-12, UX-19 |
| C-05 | P1 | Refusals give no next step | 2 | UX-01, UX-02, UX-15, UX-18, ADOPT-03, ADOPT-05, ADOPT-09, ADOPT-11 |
| C-06 | P2 | A hung runtime hangs jms; killing jms orphans the runtime | 1 | OPS-01, OPS-02, OPS-11, OPS-12 |
| C-07 | P2 | Exit codes overlap and are inconsistent | 3 | OPS-03, DOCS-09, UX-13 |
| C-08 | P2 | No diagnostics mode, and images record nothing about what built them | 2 | OPS-04, OPS-05, MAINT-17 |
| C-09 | P2 | Lifecycle gaps: disk growth, upgrading jms, uninstalling, first-build cost | 2 | OPS-06, OPS-08, OPS-13, ADOPT-06 |
| C-10 | P2 | `clean` destroys without asking, and is silent when it has nothing to do | 1 | UX-04, UX-09 |
| C-11 | P2 | The supported-runtime boundary and the container's effect on the host are unstated | 2 | ADOPT-04, ADOPT-14, OPS-07, OPS-14, OPS-15, OPS-16 |
| C-12 | P2 | Help text and completion lag the parser | 4 | UX-05, UX-06, UX-07, UX-08, UX-10, UX-14, UX-17, ADOPT-07, ADOPT-12, ADOPT-15, DOCS-08, DOCS-10, DOCS-12, DOCS-14, DOCS-15, MAINT-13 |
| C-13 | P2 | Security tables are copied by hand across `bin/jms` | 1 | MAINT-03, MAINT-04, MAINT-05, MAINT-07, MAINT-08 |
| C-14 | P2 | The process seam and agent-state creation never run in tests | 1 | MAINT-02, MAINT-12, MAINT-14, MAINT-15 |
| C-15 | P3 | `docs/` is 75% closed history, mixed in with user guides | 3 | MAINT-06, MAINT-09, MAINT-10, MAINT-16, MAINT-18, DOCS-05, DOCS-07, ADOPT-08 |
| C-16 | P3 | Bus factor 1; a release needs two specific physical machines | 1 | MAINT-01, MAINT-11 |

All 83 role findings appear in exactly one theme.

## Theme details

### C-01 — The missing-base hint gives a command that doesn't exist (P1)

`MISSING_BASE_NOTE` (`bin/jms:49-51`) says "run `jms build` in the base
directory first". Every doc teaches `jms build --base`, and no doc defines
"base directory". The note appears exactly when a newcomer is stuck.
`tests/test_jms.py:3917-3921` pins the wording, so the fix changes the
string and the test together.

### C-02 — A removed override is still documented (P1)

`docs/macos.md:51-52` says the runtime "must match the qualified version (or
be explicitly accepted)". The policy is floor-only. The acceptance override
`JMS_RUNTIME_ACCEPT` was removed in 1.2.0. The same page already describes
the floor correctly at `:27-31`, so the page contradicts itself. Internal
docs still describe the removed override (`macos-support-review.md:47`,
`multi-runtime-implementation.md:1216`); see C-15.

### C-03 — stdout is not always the launched program's (P1)

`docs/cli.md:129-131` promises that `launch` stdout belongs to the launched
program. On a macOS cold start, `bin/jms:326` prints "starting container
runtime..." to stdout. `init` also prints its nested-checkout notice to
stdout (`bin/jms:2590`).

**The roles disagree here.** The CLI designer wrote that jms "keeps stdout
clean", because they only probed on Linux. The writer and the SRE each found
the macOS leak. The fix is `file=sys.stderr` at both sites. OPS-10 (the
captured output of `system start`, unverified) sits next to it.

### C-04 — Credential grants and protections are explained incompletely (P1)

This is the most security-adjacent theme. Each piece is small, but together
they affect whether a user consents with full knowledge.

| Gap | Where |
| --- | --- |
| `jms trust PATH --fingerprint HEX64 --auth` records a durable credential grant without asking, and `docs/cli.md` never mentions it | DOCS-04 |
| The README promises a read-write `/work` and a read-only `.git`. A subdirectory launch with no definition gets neither protection. `cli.md` and `SECURITY.md` say so; the README does not | DOCS-06 |
| "Bare `--trust` drops credential mounts" holds only when no grant is recorded. `--trust` silently overrides a mismatched env pin | DOCS-11 |
| The SECURITY argv-pin list is incomplete, and the `CLAUDE_CONFIG_DIR` injection is undocumented | DOCS-13 |
| The first-launch credential question never says what "no" costs or how to undo it | ADOPT-01 |
| The README never says you log in again inside the container | ADOPT-02 |
| In the consent block, the header comes after the list, emphasis is uneven, and lines run 150-300 characters | UX-11, UX-12 |
| `--trust` (a one-shot flag) vs `trust` (a subcommand) | UX-19 |

### C-05 — Refusals give no next step (P1)

Several refusals leave the user with no next step:

| Refusal | Where | What's missing |
| --- | --- | --- |
| No TTY: `project trust is required but prompting is unavailable` | `bin/jms:1728,1749` | Doesn't name `jms trust`, `--fingerprint` or `JMS_TRUST_FINGERPRINT` |
| A fingerprint mismatch | UX-02 | Doesn't show the expected value |
| A missing example cache directory becomes `invalid … fields: "mounts[0].source"` | ADOPT-03 | `bin/jms:1576-1577` throws away the "does not exist: PATH" detail |
| A non-git directory | ADOPT-05 | The hint doesn't name `jms launch .` |
| A guessed manifest key | ADOPT-09 | No "did you mean" |
| `-b` typo | ADOPT-11 | Surfaces a raw crun error |
| `-b ''` | UX-15 | The error says "binary", not `--bin` |
| A failed build | UX-18 | The error ends in `-- ""` |

**Rule to adopt:** every refusal ends with the exact command that gets past
it.

### C-06 — A hung runtime hangs jms; killing jms orphans it (P2)

- **No timeouts.** `bin/jms` contains no `timeout`. A probe against a hung
  stub runtime ran until an external `timeout 8` killed it.
- **Only Ctrl-C is handled.** `main` catches only `KeyboardInterrupt`
  (`bin/jms:2798`). A SIGTERM or SIGHUP leaves the runtime child running
  under PID 1. A killed build left an overlay mount behind (see the
  incident under Method and limits).
- **The fix.** Put timeouts on the readiness and query calls only; leave
  `build` and the exec'd `run` unbounded. Forward TERM and HUP to the child.
- **Smaller items.** The trust-store write has no fsync (OPS-11). There is
  no per-project build lock (OPS-12).

### C-07 — Exit codes (P2)

`launch` passes the container's exit status through, so a container that
exits 3 looks the same as jms's own trust refusal (also 3). Two more
problems: 130 is documented as "at a prompt", but any Ctrl-C returns it, and
podman's own 125/126/127 are not in the table. The same condition can also
exit 1 or 2 depending on the subcommand. For example, "no project container
definition found" exits 1 from `trust` and 2 from `clean`.

### C-08 — Diagnostics and build records (P2)

- **No diagnostics mode.** There is no `--verbose`, `JMS_DEBUG` or
  `doctor`. An operator gets only a one-line error.
- **Images record nothing about what built them.** No image carries the jms
  version or the checkout commit, and the base floats on `fedora:latest`
  (MAINT-17, deferred-work item DW-003). Two workstations whose agents behave
  differently can't be compared.

### C-09 — Lifecycle gaps (P2)

- **Disk growth.** Dangling bases are invisible to jms, and images of
  deleted projects linger (OPS-06).
- **Upgrades.** Nothing documents how to upgrade jms. The base builds from
  the live checkout, so local edits there become every user's base on that
  machine (OPS-08).
- **Uninstall.** `make uninstall` leaves the trust store, agent state and
  images (OPS-13).
- **First-build cost.** The first base is about 3.2 GB, and the README
  doesn't say so (ADOPT-06).

### C-10 — `clean` destroys without asking (P2)

Project-scope `clean` stops running containers, which can include a live
agent session in another terminal. `--all --images` deletes the shared
base. Neither asks first. `--dry-run` exists, but there is no confirmation
on a TTY and no `--yes`. When there is nothing to remove, `clean` prints
nothing.

### C-11 — Supported runtimes and host impact (P2)

- **Docker.** Docker is not supported, and the README never says so. It is
  the runtime most newcomers already have (ADOPT-04, OPS-14).
- **Resource limits.** Containers get no limits, and a manifest cannot set
  any (OPS-07).
- **Proxies.** Proxy behaviour is whatever the runtime does, and that isn't
  documented (OPS-15).
- **Install hint.** It assumes apt on every distro (ADOPT-14).
- **Positive.** The runtime version policy only sets a minimum, which suits
  a fleet (OPS-16).

### C-12 — Help text and completion lag the parser (P2)

Four roles touched this, which makes it the most widely shared theme. Flag
parity is exact today (MAINT-13, DOCS), but only a CONTRIBUTING rule keeps
it that way. Where help and completion fall short:

| Area | Problem | Findings |
| --- | --- | --- |
| Completion | Doesn't track argument position: it offers directories to `build` and flags after `--` | UX-06 |
| Completion | bash only, though macOS defaults to zsh | UX-17, ADOPT-12, DOCS-14 |
| `--help` | Shows no `--`, environment variables, exit codes or examples | UX-07 |
| `--help` | The positional `name` clashes with `-n NAME` | UX-05, DOCS-12 |
| `--help` | Jargon appears before it is defined, and "AI agent" is never said | ADOPT-07, ADOPT-15 |
| Arguments | PATH operand forms are inconsistent across subcommands | UX-08 |
| Arguments | A typo in a subcommand option shows the top-level usage | UX-14 |
| Docs | `inspect` fields are undocumented | DOCS-10 |
| Docs | The refusal list is described as "exactly" but is incomplete | DOCS-08 |
| Docs | Reference nits | DOCS-15 |
| Output | `init --with-manifest` reports only one of the files it creates | UX-10 |

**Fix:** add a parity test of about 20 lines that walks `parser()`
(MAINT-13), and argparse epilogs.

### C-13 — Security tables copied by hand (P2)

**Watch most closely: MAINT-05.** The five-agent roster is hard-coded in
about seven places. If someone adds an agent and forgets the
reserved-mount-target entry, a manifest can mount over that agent's
credentials. The consent text would still read correctly, so nothing would
flag it.

The rest of the theme:
- **MAINT-03:** each runtime backend has its own hand-written copy of the
  argv builder.
- **MAINT-08:** the trust-record shape is written out in six places.
- **MAINT-04:** `approve()` mixes deciding with I/O.
- **MAINT-07:** `cmd_trust` is a 114-line multiplexer.

Each fix is a refactor inside the single file. None needs a package split.

### C-14 — The process seam and agent-state creation never run in tests (P2)

- **`runtime_run`:** the only place jms starts another process, and the
  last argv check before it does. It is patched in about 46 tests and never
  actually executed.
- **`ensure_agent_state_directory`:** writes the credential directories and
  refuses symlinks. It is always mocked.
- **Coverage:** about 93% of lines overall.
- **Fix:** a stub `podman` script on `PATH`, and a real-filesystem test with
  a planted symlink. Neither needs a container runtime.
- **Related:**
  - CI skips Python 3.13, the default on Debian 13 (MAINT-12).
  - There is no linter, and `fail()` is not typed `NoReturn` (MAINT-14).
  - The test module is a single 4,679-line file (MAINT-15).

### C-15 — `docs/` is mostly closed history (P3)

Two roles independently measured this:
- 6,039 of the 8,388 lines in `docs/` are closed reviews, proposals and
  implementation records.
- 6 of the 22 files are user guides.
- `github-presence-review.md` is not indexed.
- Closed docs describe removed behaviour in the present tense.
- `bin/jms` cites ID prefixes (`MIR-`, `HO-`, `RC-`) without saying which
  doc defines them.
- The release checklist still has a one-time step from 1.1.0.

**Fix:** move closed docs to `docs/history/`, add a status column to the
index, and put a legend of ID prefixes at the top of `bin/jms`.

**Constraint:** some docs are cited by code or tests and must stay live.
The maintainer audit lists them in its MAINT-06 details.

### C-16 — Bus factor and release mechanics (P3)

- **One maintainer.** Every commit has one human author.
- **Two machines.** A qualified release needs an Apple Silicon Mac and a
  dedicated Debian 13 host, and CI cannot stand in for either.
- **Manual `.dev` step.** The marker is restored by hand in a follow-up PR
  after every tag. #32 and #35 were both that PR.
- **Fix:** script how to set up each qualifying machine, and record who
  holds each one. A self-hosted Debian runner for tier A is the larger
  option.

## Where the roles agreed

- **No High findings.** All five rated nothing above Medium.
- **The consent model is right.** Every role that looked praised it. It
  fails closed, `[y/N]` is the default, and the capability list is complete
  and literal. The complaints are about the text around it (C-04, C-05),
  never about the decision logic.
- **The reference docs are exact.** The writer and the maintainer both
  verified that the parser matches the docs and the completion flags with no
  drift.
- **The code is in good shape.** It has a single process seam, fail-closed
  parsing, and a hermetic test suite that runs in about 9.5 s.

## Recommended sequence

1. **2.0.2, wording and docs only, one PR:**
   - C-01: fix the hint and its test.
   - C-02: fix the macOS line.
   - C-03: send the two `print`s to stderr.
   - C-04: add the `--fingerprint --auth` reference, the README
     subdirectory clause, and the login-once sentence.
   - C-05: add next-step suffixes to the trust refusals, and pass through
     the mount-source detail.

   The only behaviour change is two `print`s moving to stderr.
2. **2.1, robustness and operability:**
   - C-06: timeouts and signal forwarding.
   - C-07: the exit-code split.
   - C-08: `JMS_DEBUG`, and labels recording the jms version and commit.
   - C-10: confirm before `clean` destroys anything, with `--yes`.
   - C-14: test the two missing seams first, so the C-06 change lands on
     tested code.
3. **Before the next agent is added:**
   - C-13: a single roster table (MAINT-05) and a shared argv tail
     (MAINT-03).
   - C-12: the parity test.
4. **Housekeeping, any time:** C-09 docs, C-11 statements, C-15 docs
   restructure, C-16 host scripts.

## Branches

| Branch | Contents |
| --- | --- |
| `audit/role-first-time-adopter` | `first-time-adopter.md` |
| `audit/role-sre-operator` | `sre-operator.md` |
| `audit/role-long-term-maintainer` | `long-term-maintainer.md` |
| `audit/role-technical-writer` | `technical-writer.md` |
| `audit/role-cli-interaction-designer` | `cli-interaction-designer.md` |
| `audit/consolidation` | All five merged, plus this file |

Every branch is additive. Each adds files under `docs/audits/2026-10-12/`
and changes nothing else.
