# Long-term maintainer audit — jmscontainers 2.0.1 (2026-10-12)

## Verdict

**Healthy enough to inherit. The real risk is people and process, not code.**
`bin/jms` is disciplined: 165 functions, only 4 over 70 lines, one process
seam, and fail-closed parsing. The 382-test suite runs in about 9.5 s with no
container runtime. What makes it hard to own for three years: one human
maintainer, a release that needs two specific physical hosts, a few
security-relevant tables copied by hand across the file, and 6,000 lines of
closed review and proposal docs mixed in with the live ones.

## Scope & method

Read:
- all of `bin/jms` (2,803 lines) and the structure and fixtures of
  `tests/test_jms.py` (4,679 lines)
- `Makefile`, `.github/workflows/test.yml`, `.github/dependabot.yml`
- `scripts/integration.sh` (header and layout), `scripts/leak_sweep.py`
  (header), `completions/jms.bash`
- `CONTRIBUTING.md`, `CHANGELOG.md` (headings and the 2.0.x entries),
  `docs/release-checklist.md`, `docs/README.md`, plus the status header of
  every file in `docs/`

Ran:

| Command | Result |
| --- | --- |
| `time make test` (Python 3.15.0) | `Ran 382 tests in 9.278s` / `OK`; real 0m9.575s |
| `python3.13 -B -m unittest discover -s tests` | `Ran 382 tests in 9.920s` / `OK` |
| Line coverage via `sys.monitoring` (scratch script, not committed) | 1,418 of 1,580 statements inside functions hit; about 93% once the 60 docstring lines that never fire are excluded |
| Function sizes via `ast` (scratch script) | 165 functions, 9 classes. Largest: `cmd_trust` 114, `parse_manifest` 89, `approve` 76, `cmd_clean` 74 |
| Walk `parser()` and compare against `completions/jms.bash` and `docs/cli.md` (scratch script) | No drift today: every subcommand reports `comp-missing []`, `doc-missing []` |
| `git log` authorship and tags | 50 commits, one human author (two name spellings) plus dependabot; tags v1.0.0 to v2.0.1 |

Not run: integration tiers A and B (tier B is excluded by the audit rules,
and tier A needs a real runtime session). Nothing was changed except this file.

## Findings

| ID | Severity | Title | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| MAINT-01 | Med | Bus factor 1, and a release needs two specific physical hosts | `git log --format=%an` shows one human author. `docs/release-checklist.md:29-46` requires a macOS host with apple/container plus a real Debian 13 amd64 host with a fresh non-1000 user over ssh ("No nested or CI substitute counts"). Real-runtime tests never run in CI (`test.yml`; tracked as DW-002) | Script the host provisioning, write down who holds which host, and run tier A on a self-hosted Debian runner |
| MAINT-02 | Med | The production process seam and agent-state creation are never executed by tests | Coverage misses every line of the `runtime_run` body (`bin/jms:118-136`: argv check, NUL/UTF-8 gate, `FileNotFoundError` and `CalledProcessError` mapping, exec). It is patched about 46 times. `ensure_agent_state_directory` (`2201-2208`) is always mocked (`tests/test_jms.py:701, 2024`). Also missed: the apple `system start` path (`326-331`), `SafeArgumentParser.error` (`2700-2701`), and the `OSError`/`KeyboardInterrupt` arms of `main` (`2796-2799`) | Test `runtime_run` against a stub `podman`/`container` script on `PATH`. Test `ensure_agent_state_directory` on a real tmpfs with a planted symlink and with a planted file |
| MAINT-03 | Med | Both backends duplicate their argv serializers by hand, and the protocol exists only as a test frozenset | `run_argv` at `280-303` and `548-581`, `mount_argument` at `260-267` and `524-531`, `validate_version` at `308-321` and `585-601`: identical apart from flags. There is no base or `Protocol` class; the surface is defined at `tests/test_jms.py:4563-4567`. `version_max` (`238`, `497`) is never read by `bin/jms` and survives only because that frozenset lists it | Add private helpers (`_argv_tail(plan, mount_fn)`, `_mount_spec`, `_warn_unqualified`); the underscore keeps them outside the surface test. Remove `version_max` |
| MAINT-04 | Med | `approve()`, the trust decision core, mixes deciding, rendering, prompting and persisting | `bin/jms:1681-1756`: 76 lines, `config or default_config()` six times, and part of the file's 18 `getattr(args, …)` calls | Extract a pure `trust_decision(record, tf, flags, env_pin)` and test it as a truth table; keep the I/O in a thin wrapper |
| MAINT-05 | Med | The roster of five agents is hard-coded in about seven places | `AGENT_STATE_LEAVES` (`1149`, read only by tests), `agent_state_mounts` (`2157-2164`), `reserved_mount_targets` (`1381-1385`), `CREDENTIAL_PATHS` (`1304`), and the prose at `1643`, `1659` and `1831` | One table of `(leaf, home-relative target, display name)` that drives every site. Today a missed reserved target when adding an agent is a silent security hole |
| MAINT-06 | Med | 75% of `docs/` is closed history, indexed alongside the live docs with no status | `docs/*.md` totals 8,388 lines. Implemented proposals, closed reviews and implementation records total 6,039. `docs/README.md` lists them under "Contributors and maintainers". `github-presence-review.md` is in no index and frozen at 2026-08-03 ("Steps 5–9 remain open"). `macos-support-review.md:47,81` documents `JMS_RUNTIME_ACCEPT`, which no longer exists (`grep -c` in `bin/jms` = 0) | Move closed material to `docs/history/`. Add a status column to the index. Mark the load-bearing ones (see details) |
| MAINT-07 | Low | `cmd_trust` packs four subcommands into one 114-line function, with hand-rolled positional reinterpretation | `bin/jms:2423-2536`; `2429-2431` rewrites `trust_action` into `path` | Split it into `trust_list`, `trust_prune`, `trust_revoke` and `trust_approve`; keep the parsing quirk in one place |
| MAINT-08 | Low | The trust-record shape is written out in at least six places | `record_approval` (`1715-1717`), `record_base_answer` (`1839-1841`), the validator `valid_store` (`1083-1097`), and `tests/test_jms.py` (8 `"granted_at"` literals, e.g. `116`, `417`, `2078`, `2536`) | One `make_record(root, tf, auth)` used by code and tests; a schema-3 change then touches two places |
| MAINT-09 | Low | Code cites rationale IDs without naming the doc that defines them | 25 `MIR-` cites plus `§2`/`§5`, `R6/RC-006` and `HO-002 R5` in `bin/jms` (e.g. `499`, `597`, `1188`, `1872`). `bin/jms` names no `docs/` file except the release checklist (`33`) | Add a 5-line legend at the top of `bin/jms` mapping each prefix to its doc |
| MAINT-10 | Low | The release checklist carries a step for a release that already shipped | `docs/release-checklist.md:30` says "The first macOS run of the multi-runtime release must also…", but multi-runtime shipped in 1.1.0 (`docs/multi-runtime-implementation.md:3`) | Prune one-time steps after each release. Move the conditional steps into a "when X changed" table |
| MAINT-11 | Low | The `.dev` marker is restored by hand in a separate PR after every tag | Commits `7a0e3f4` and `90255df`. The test only checks the format (`tests/test_jms.py:1437-1441`) | A tag-triggered workflow or a `make release` script that bumps, tags and restores in one go |
| MAINT-12 | Low | The CI matrix skips the default interpreter of the qualified Linux host | Matrix is `3.11, 3.14, 3.15` (`test.yml:21`). Debian 13's `/usr/bin/python3` is 3.13, and the 2.0.1 qualification used 3.15.0 (`CHANGELOG.md:30`). Verified passing on 3.13 locally | Add `'3.13'` to the matrix |
| MAINT-13 | Low | Parity between the CLI, completions and `cli.md` is enforced only by a rule in CONTRIBUTING | `CONTRIBUTING.md` asks for same-commit updates, but no test does it. A parser walk found no drift today | Add a test of about 20 lines that walks `parser()` and asserts every option appears in `jms.bash` and `docs/cli.md` |
| MAINT-14 | Low | No lint, type check or formatter; `fail()` claims to return `None` | `bin/jms:88` returns `None` but always raises. 70 single-line compound statements; lines up to 260 characters (`2604`); no linter config in the repo | Annotate `fail` as `NoReturn`. Optionally run a CI-only linter: it is a dev tool, not a runtime dependency, so stdlib-only still holds |
| MAINT-15 | Low | One 4,679-line test module, with jms diagnostics leaking into the test output | `tests/test_jms.py`, 42 classes. `make test` output interleaves `building "jmscontainers-demo-…"` and `removed image "p:1"` with the dots | Split by area (trust, manifest, launch, backends) when next touched; capture stderr in the `quiet()` helper consistently |
| MAINT-16 | Note | The single-file, stdlib-only rationale lives only in an orphaned review doc | `docs/github-presence-review.md:323` ("the single-file design is a feature for an auditable security tool"). Not in CONTRIBUTING. `checkout_root()` (`1152`) also ties the base build to a git checkout | State the constraint and its reason in CONTRIBUTING; a future packaging effort must first solve the base-image build context |
| MAINT-17 | Note | The base image floats on `fedora:latest` | `Containerfile:6`; already tracked as DW-003 (`docs/deferred-work.md:130`) | Decide DW-003 before the next Fedora release: a rebuild can break with no code change |
| MAINT-18 | Note | Release bursts make the CHANGELOG hard to scan | 1.2.0, 2.0.0 and 2.0.1 are all dated 2026-10-12. The 1.2.0 entry is 314 lines (`CHANGELOG.md:168-481`) | Keep each entry to its user-visible bullets and link the qualification evidence instead of inlining it |

## Finding details

### MAINT-01 — bus factor and release hosts

Every release is qualified by one person on hardware they own: an Apple
Silicon Mac for apple/container, and a dedicated Debian 13 host where a
fresh non-1000 user logs in over ssh. PR CI proves only the parsers and
serializers against fakes; `test.yml` says so itself ("neither job starts a
container runtime").

If that person or either host is unavailable, nobody can cut a qualified
release. The way to provision a qualifying host lives only in prose in the
checklist.

### MAINT-02 — untested seams

`runtime_run` is described as "the sole process boundary" (`bin/jms:117`).
It holds the last NUL/UTF-8 argv check and maps runtime failures to jms
errors. Because tests replace it wholesale, a regression there, such as a
changed `check=` default or a broken `CalledProcessError` detail, would pass
CI.

`ensure_agent_state_directory` creates the credential directories and
refuses symlinks. It is the only code that writes there, and it is never run
for real. Both gaps can be closed without a container runtime.

### MAINT-03 — backend duplication

The two `run_argv` bodies share their ordering contract line for line:
`CLAUDE_CONFIG_DIR` first, then the project mount, the env, the extra mounts
and `--network none`. The golden argv tests catch drift after the fact. A
shared private tail removes the chance of drift and halves the review
surface for the most security-relevant output jms produces.

`version_max = None` on both classes is a leftover from the dropped
version-ceiling policy.

### MAINT-04 — `approve()`

It answers four questions in one pass:
- Is build/run granted?
- Is auth granted?
- Must the user be prompted?
- What gets recorded?

The answers depend on the stored record, `--trust`, `--fingerprint`,
`JMS_TRUST_FINGERPRINT`, `--auth`/`--no-auth` and the action. That is a
truth table, so it should be code shaped like one. A pure decision function
would make the SECURITY.md rule "the boolean --trust never grants
credentials" a single assertion over every input combination.

### MAINT-05 — agent roster

Adding a sixth agent today means editing a tuple read only by tests, the
mount list, the reserved-target set, the credential-path list and three
user-facing sentences. If the reserved-target edit is forgotten, a manifest
can mount over the new agent's state path. The consent text would still
read correctly, so nothing would flag the omission.

### MAINT-06 — docs sprawl

Load-bearing (cited by code, tests or the checklist; keep live):
- `multi-runtime-implementation.md` (MIR-/§ cites)
- `host-outflow-register.md` (HO-)
- `release-critical-issues.md` (RC-, R8.4 release-blocking)
- `standalone-image-user-abi-proposal.md` (marked "normative")
- `deferred-work.md`, `release-checklist.md`, `macos-qualification-guide.md`
- `tests/fixtures/README.md`

Historical (closed or implemented):
- `review-issues-2026-09-09.md`, `project-review-2026-09-13.md`
- `review-follow-up-implementation-guide.md`, `macos-support-review.md`
- `podman-image-inspect-qualification.md`
- `containerfile-stage-alias-proposal.md`, `exact-base-identity-proposal.md`

Stale and orphaned: `github-presence-review.md`.

## What works well

- **Fast and hermetic:** 382 tests in about 9.5 s. Both backends run the
  same scenarios by subclassing (`BuildTestsPodman`, `LaunchTestsPodman`,
  `CleanTestsPodman`).
- **Golden contracts:** pinned trust fingerprints
  (`tests/test_jms.py:42-43`) and golden launch and build argv tests make
  consent-breaking changes loud.
- **Architecture as tests:** `SeamTests` forbids `sys.platform` outside
  `select_runtime()` and pins the backend's public surface.
- **Fixture provenance:** captured runtime output with recipes, sanitization
  notes and re-observation dates (`tests/fixtures/README.md`).
- **Consistent error model:** `fail()` maps to exit codes 1, 2 and 3, all
  output passes through `quote()`/`terminal_safe_text()`, and `main()` turns
  host I/O races into a clean exit.
- **Hardened CI:** read-only token, actions pinned by SHA, dependabot on
  actions, and a matrix covering the 3.11 floor plus macOS.
- **Rich commit history:** commit messages and the CHANGELOG record why each
  change was made and how it was qualified.

## Top 3 recommendations

1. **Close the two untested seams (MAINT-02).** A stub runtime on `PATH`
   plus real-filesystem agent-state tests is about a day's work and covers
   the code every launch passes through.
2. **Turn hand-copied tables into single sources (MAINT-03, -05, -08), then
   extract the pure trust decision from `approve()` (MAINT-04).** These are
   the refactors that pay for themselves: each removes a "remember to edit N
   places" hazard in security-relevant code. Do them inside the single file;
   none needs a package split.
3. **Reduce what a successor must hold in their head (MAINT-01, -06, -09,
   -10).** Script the qualification-host setup, move closed docs to
   `docs/history/` with a status index, add an ID legend at the top of
   `bin/jms`, and prune spent checklist steps.
