# macOS qualification guide (1.1.0, multi-runtime branch)

Audience: the agent (or human) working on the macOS qualification host.
Goal: produce the recorded evidence that closes **RC-003** and the macOS
half of **RC-004** in [release-critical-issues.md](release-critical-issues.md).
Everything here is running and recording — no code changes are expected
unless a check fails.

## What is already done

- All code/doc register items are closed: RC-002 (SELinux vocabulary),
  RC-005 (shellcheck), RC-006 (cold-launch stdout).
- A prior macOS pass at `c5157cd` ran `scripts/integration.sh all` green
  through tiers A and B **up to** the credential-mount step, which needs a
  tty. The credential-mount assertion itself was validated out-of-band.
- The apple/container survivor-set acceptance (RC-003) is now automated in
  integration tier B, and the manual removal-race procedure is in the
  [release-checklist appendix](release-checklist.md#appendix-manual-removal-race-test-r59-mir-043).
  Neither has ever executed against the real engine — that is this session's
  job.

## What this session must produce

1. One full **interactive** `scripts/integration.sh all` run, green through
   both tiers, at the commit under qualification. This single run covers:
   - the RC-003 survivor-set acceptance (automated in tier B), and
   - the recorded macOS integration gate for RC-004.
2. One recorded run of the **manual vanished-mid-removal race test**
   (RC-003, second half).
3. Register updates in `docs/release-critical-issues.md` recording both,
   committed on the `multi-runtime` branch.

## Preconditions — verify before running anything

```sh
cd <repo>/jmscontainers && git switch multi-runtime && git pull
git log --oneline -1          # record this hash; it is the commit under test
container --version           # must be 1.2.0 (the qualified pin)
python3 --version
command -v shellcheck         # should be present so `make test` runs its shellcheck leg
```

- **You must be in a real interactive terminal** (Terminal.app or ssh with a
  tty). Tier B's auth-mount assertion runs `jms launch --trust --auth`,
  which prompts by design and fails non-interactively with "credential
  access is required but prompting is unavailable". A non-interactive run
  cannot satisfy the RC-004 gate.
- The apple/container system service must be running (`container system start`
  if needed).
- No sudo is required on macOS (the nftables egress-denial part of tier A is
  Linux-only; tier A on Darwin is the base build plus a bwrap presence
  check).

## Step 1 — unit suite

```sh
make test
```

Expected: 189 unit tests pass, plus a clean shellcheck leg over
`scripts/integration.sh` and `completions/jms.bash`. Any failure blocks:
stop and report rather than proceeding to integration.

## Step 2 — full interactive integration run

```sh
scripts/integration.sh all 2>&1 | tee /tmp/jms-itest-$(date +%Y%m%d).log
```

Answer the credential prompt when the tier B auth-mount step reaches it.

Expected output ends with `== tier A passed ==`, `== tier B passed ==`, and
`integration tier(s) 'all' passed on container`. Notes on what tier B now
exercises beyond the previous pass:

- **Auth-mount step** (previously blocked on tty): after the prompt, the
  harness asserts the agent-state write landed in
  `~/.local/share/jmscontainers/agents/claude/`, owned by you, with
  `CLAUDE_CONFIG_DIR` visible inside.
- **Survivor-set acceptance** (never run live): builds a labeled project
  image, aliases it outside the reserved namespace with
  `container image tag ... itest-survivor-alias:keep`, runs
  `jms clean --images`, then asserts from `container image list --format
  json` that the alias survives on the same image identity, that no
  `jmscontainers-*` ref survives on it, and that the unselected base image
  still inspects.

**If the survivor-set step fails with the "delete-by-ref cascaded" MIR-042
message**: this is the one outcome that forces a design change, not a
retry. Do not close anything, do not work around it. Record the failure
verbatim in RC-003's status, note that the release checklist classifies a
discovered cascade as a qualification failure to resolve before release,
and stop for a design decision (the cleanup must untag rather than delete,
or equivalent).

Exit codes if something else goes wrong: 1 = test failure or leaked
resource, 2 = leak-sweep failure, 3 = harness failure. The EXIT trap cleans
project images and runs the leak sweep even on failure, so a red run should
leave the store clean; verify with `container image list` before retrying.

## Step 3 — manual removal-race test

Follow the
[release-checklist appendix](release-checklist.md#appendix-manual-removal-race-test-r59-mir-043)
**exactly as written** — it is the authoritative procedure (throwaway
project under `/tmp/jms-race`, capture the jms-owned ref, ten iterations of
`container image delete "$ref"` racing `jms clean --images`). Do not
improvise variants; the recorded evidence must match the checked-in steps.

Pass criteria (all required, from the appendix):

- every `jms clean` exits 0, whichever process deleted the image first;
- no iteration reports a failed removal for the vanished ref;
- after the loop, no `jmscontainers-jms-race` ref remains and a final
  `jms clean --images -w /tmp/jms-race` exits 0 (convergence).

Capture the loop output to a log, then `rm -rf /tmp/jms-race`.

## Step 4 — record the evidence

Edit `docs/release-critical-issues.md`:

1. **RC-003** — flip **Status** to `Closed` and add a `### Resolution`
   section (match the style of RC-002/RC-005): date, apple/container
   version, commit under test, one sentence per procedure (survivor-set via
   the tier B run; race via the manual appendix procedure) with the
   observed outcomes. State explicitly that delete-by-ref did **not**
   cascade.
2. **RC-004** — update the implementation status: the macOS gate is now
   recorded (date, commit, container 1.2.0, full interactive
   `scripts/integration.sh all` green through both tiers including the
   credential prompt). Leave the item **Awaiting qualification** — the
   Debian gates are still open and are the remaining blocker.
3. **Verification log** — add rows for this session's `make test` and the
   full interactive apple/container integration run at the tested commit.
4. Update the register header's "updated ..." line and, if RC-003 was the
   last macOS-side concern, leave "Merge disposition: **not ready**" as is
   (Debian still gates).

Then commit on `multi-runtime` and push:

```sh
git add docs/release-critical-issues.md
git commit -m "Record the macOS RC-003 acceptance runs and integration gate"
git push
```

## Caveat: "final candidate commit"

RC-004 requires the macOS gate green **on the final candidate commit**. The
Debian gates (RC-001, RC-004 Linux half, install walkthrough) have not run
yet; if they force any code change, this interactive macOS run must be
repeated at the new candidate commit. Running macOS first is still the
right order — RC-003 is the only remaining gate that can force a design
change — but record the tested hash prominently so a later re-run is a
known cost, not a surprise.
