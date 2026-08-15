# macOS qualification guide

Audience: maintainers qualifying a jms release on Apple Silicon. This is the
platform-specific companion to the [release checklist](release-checklist.md),
which remains authoritative for deciding when qualification is required.

## Evidence required

Record the date, candidate commit, macOS version and build, Darwin kernel,
architecture, Python version, shellcheck version, apple/container CLI and
service versions, host time zone, and the outcome of every command below.
Test counts are observed evidence, not fixed acceptance criteria.

The final record belongs in the release's changelog qualification section or
linked release-evidence document. Keep the exact tested commit visible. A
later runtime-affecting code change invalidates the run and requires another
qualification at the new candidate; evidence-only edits may follow the tested
commit if the record says so explicitly.

## Preconditions

Use a real Apple Silicon Mac and an interactive Terminal.app or ssh session
with a tty. Tier B deliberately prompts for credential access; piping stderr,
detaching stdin, or running from a noninteractive command wrapper does not
satisfy the gate.

From the candidate checkout, record the environment before creating runtime
state:

```sh
git status --short
git log --oneline -1
sw_vers
uname -srm
python3 --version
container --version
container system status
shellcheck --version
date +%Z
```

The worktree must contain exactly the candidate changes, Python must meet the
README floor, and `container --version` must equal both exact
`ContainerBackend.version_min` and `version_max` values in `bin/jms`. Do not
set `JMS_RUNTIME_ACCEPT`: an override proves compatibility, not qualification.
jms starts a stopped apple/container service itself, so a stopped service is
valid initial state and should be recorded.

## Qualification run

1. Run the repository gate:

   ```sh
   make test
   ```

   Compilation, all unit tests, and shellcheck must pass. Record the observed
   unit-test count.

2. Run both live tiers while preserving a tty and a transcript:

   ```sh
   script -q /tmp/jms-itest-$(date +%Y%m%d).log scripts/integration.sh all
   ```

   Answer the credential prompt affirmatively. Success requires both
   `== tier A passed ==` and `== tier B passed ==`, followed by
   `integration tier(s) 'all' passed on container`. The EXIT trap's leak sweep
   must also pass. Do not substitute ad hoc probes for a failed harness
   assertion.

3. Whenever the apple/container pin or cleanup interaction changes, run the
   [manual removal-race procedure](release-checklist.md#appendix-manual-removal-race-test-r59-mir-043).
   Tier B already supplies the survivor-set/delete-by-ref acceptance. A
   discovered cascade is a qualification failure requiring a cleanup design
   change, not a result to waive.

4. On a clean macOS host or clean qualification account, follow the README
   Homebrew installation path verbatim through `jms build --base`. The command
   must succeed with the Homebrew-provided qualified runtime and without
   `JMS_RUNTIME_ACCEPT`. Record whether jms successfully starts the runtime
   service when the walkthrough begins with it stopped.

## Completion and cleanup

Confirm integration-owned containers and project images are absent. The
shared `jmscontainers-base:latest` image and apple/container's own service
containers may remain because the documented installation creates or owns
them by design. Remove manual race resources as directed by the checklist.

Add the complete evidence record and reconcile the README, macOS guide,
backend pin, runtime fixtures, changelog, and release notes in the same change.
Qualification is complete only when all recorded checks are green without a
runtime override and the candidate has no later runtime-affecting changes.
