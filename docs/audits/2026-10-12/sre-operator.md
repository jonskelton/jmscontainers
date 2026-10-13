# SRE / platform operator audit — jmscontainers 2.0.1 (2026-10-12)

## Verdict

jms fails loudly and correctly on a *broken* runtime, but has no answer for
a *slow or hung* one: there is not one timeout in `bin/jms`. Also, killing
jms orphans the runtime child it was waiting on. For a fleet, the next gaps
are visibility: no debug or log output, `launch` exit codes that overlap
the container's own, and images with no record of which jms or base inputs
built them. There are no High findings. Correctness, cleanup ownership and
trust-store integrity are solid.

## Scope & method

- **Read:** `bin/jms` (all 2803 lines, focused on the runtime seam, backends,
  store, build/launch, clean, `main`), `scripts/integration.sh`,
  `scripts/leak_sweep.py`, `Containerfile`, `Makefile`, `README.md`,
  `docs/{linux,macos,agent-state,cli,host-outflow-register,deferred-work}.md`.
- **Ran:** `make test` passed (382 tests, OK). I also ran fake-runtime probes
  with a scratch `HOME` and a `PATH` holding only a stub `podman`:
  - hung runtime under `timeout 8`: `exit=124 after 8s`, so jms never gave up
    by itself;
  - missing runtime: `error: podman CLI not found; install …`, exit 1;
  - runtime exits 125 with ENOSPC text: `error: command failed: "podman info
    --format json" -- "Error: no space left on device\x0a"`, exit 1;
  - SIGTERM to jms while the runtime hangs: jms is gone, but the stub is still
    running, reparented to PID 1 (`3836366 1 /usr/bin/sleep 600`).
- **One incidental observation (unplanned):** an earlier version of the probe
  reached the real podman through `/bin`. It started a real base build against
  the scratch `HOME`'s separate storage, and I stopped it with SIGTERM. The
  killed build left an overlay `merged` mount inside rootless podman's mount
  namespace, and `rm` failed with "Device or resource busy" until I unmounted
  it via `podman unshare`. The scratch store is gone. The real store showed
  nothing (`podman ps -a --external` was empty).
- **Not run:** integration tiers A and B, and macOS. Claims about macOS come
  from reading the code and are marked where they matter.

## Findings

| ID | Severity | Title | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| OPS-01 | Med | No timeout on any runtime call; a hung engine hangs jms forever | `bin/jms:131` (`subprocess.run` without `timeout`), `:324-331`, `:605`; `grep -n timeout bin/jms` returns nothing; probe: `exit=124 after 8s` | Bound readiness probes (`--version`, `info`, `system status/start`, `ps`, `images`) with a timeout and a named error |
| OPS-02 | Med | SIGTERM/SIGHUP to jms orphans the runtime child; a killed build can leave mounted storage | `bin/jms:2798-2799` (only `KeyboardInterrupt` handled); probe: survivor reparented to PID 1; incidental build kill left an overlay mount | Forward TERM/HUP to the child (or exec a process group) and wait; document recovery |
| OPS-03 | Med | `launch` exit codes collide with jms's own 1/2/3 | `docs/cli.md:310-318`; `bin/jms:2420` (`execvp`); `scripts/integration.sh:354-357,420` (container `exit 3` propagates, the same number as a trust error) | Document 125/126/127, and the fact that nonzero codes after exec belong to the container; consider a distinct prefix line on stderr for jms errors |
| OPS-04 | Med | No diagnostics mode: no `--verbose`/`--debug`, no log, no `doctor` | Parser `bin/jms:2704-2768` has no such flag; errors are single lines from `bin/jms:2790` | Add `JMS_DEBUG=1` to echo each runtime argv and its exit to stderr; consider a `jms doctor` around `runtime_ready()` |
| OPS-05 | Med | Base and project images carry no jms/source provenance; the fleet cannot inventory drift | `bin/jms:1925-1927` (base gets only `jms.container=image`, `:1899-1900`); `Containerfile:6,14,28-29` float; `docs/deferred-work.md` DW-003 | Stamp `jms.version` and the checkout commit (and a dirty flag) as labels on every build |
| OPS-06 | Med | Image disk growth is unbounded for dangling bases and orphaned projects | ref-less images are dropped from facts (`bin/jms:416-417,731-732`); untag uses `--no-prune` (`:764`); GC runs only on a successful build (`:2153`); `trust prune` deletes records, not images (`:2450-2459`); `docs/cli.md:280-284` | Add a `jms clean --dangling` (or document a prune cadence), and offer image purge on `trust prune` |
| OPS-07 | Med | No resource limits on launched containers | `run_argv` adds no `--memory/--cpus/--pids-limit` (`bin/jms:280-303,548-581`); the manifest accepts only `schema,name,env,mounts,run` (`:1512`) | Add an optional `[run]` limits table, or document runtime-level defaults (containers.conf) |
| OPS-08 | Med | No documented way to upgrade jms itself; the base builds from the live checkout | `Makefile:8-12` (symlink install); `README.md:182-191` covers images only; `bin/jms:1927` (`checkout_root()` is the build context, so a dirty tree builds the base) | Document `git pull --ff-only` plus a base rebuild, and warn when building the base from a dirty checkout |
| OPS-09 | Low | macOS runtime auto-start prints to stdout during launch | `bin/jms:326` `print("starting container runtime...")` without `file=sys.stderr`, which contradicts `:596-597` (stdout belongs to the program) | Send to stderr |
| OPS-10 | Low | macOS `container system start` output is captured; any first-run prompt would be invisible (unverified) | `bin/jms:327` (`capture=True`, stdin inherited) | Run it with stdin from `/dev/null` and stream its output to stderr, or fail with a hint to run it by hand |
| OPS-11 | Low | Trust-store write is atomic but not durable | `bin/jms:1139-1141` (`os.replace` without `fsync` on the file or directory) | `flush` + `os.fsync(fd)` before replace; fsync the directory after |
| OPS-12 | Low | Concurrent builds of one project both run; there is no per-project build lock | `bin/jms:1987-1991` documents the tie race; `docs/linux.md:90-92` (concurrent store mutation unsupported) | Optional per-project `flock` around build+GC under `~/.local/share/jmscontainers` |
| OPS-13 | Low | `make uninstall` leaves trust store, agent state and images | `Makefile:14-17`; state roots at `bin/jms:1078-1079,1156-1168` | Document a full-removal recipe (`jms clean --all --images`, then remove the two dirs) |
| OPS-14 | Note | Docker is not a supported engine; Linux is rootless podman only | `bin/jms:100-105`; `docs/linux.md:94-100`; a `DOCKER_HOST` socket is treated as a protected socket (`:1232`) | State this in fleet onboarding; docker-only hosts need podman installed |
| OPS-15 | Note | Proxy/egress behaviour is inherited from the runtime and undocumented | No proxy handling in `bin/jms` (grep shows none); build and run proxy env come from podman defaults; apple/container behaviour unverified | Add one paragraph on proxies and offline mirrors to `docs/linux.md` and `docs/macos.md` |
| OPS-16 | Note | Runtime version policy is floor-only and warns above the qualified major | `bin/jms:585-601`, `:308-321`; `docs/cli.md:43-56` | Good for fleets; keep `_version_qualified` bumps tied to releases |

## Finding details

### OPS-01 — No timeouts

Every runtime call goes through `runtime_run` (`bin/jms:116-136`), which
calls `subprocess.run` without a `timeout`. A wedged podman (a stale lock in
`/run/user/<uid>/containers`, an NFS home) or an apple/container daemon stuck
in `system start` blocks jms indefinitely. The probe confirmed it: only the
external `timeout 8` ended the run. Interactive users can press Ctrl-C.
Automation (cron rebuilds, CI) cannot. Bound the readiness and query calls.
Leave `build` and the exec'd `run` unbounded on purpose.

### OPS-02 — Orphaned runtime children

`main` handles only `KeyboardInterrupt` (`bin/jms:2798`). A SIGINT from a
terminal reaches the whole foreground process group, so Ctrl-C is fine. A
SIGTERM or SIGHUP sent to the jms PID (systemd stop, a closed SSH session, a
supervisor) kills only Python, and the probe shows the child carrying on
under PID 1. For `podman build` (`bin/jms:1909`), that means a build keeps
running unattended. A killed build was also seen leaving an overlay mount
that `rm` cannot remove. `launch` is unaffected because jms has exec'd into
podman by then, and the integration test covers TERM there
(`scripts/integration.sh:359-374`).

### OPS-03 — Exit-code overlap

`docs/cli.md:314` says `launch` returns the container's status. A wrapper
script therefore cannot tell `error: … trust` (3) from a program that exited
3, and the integration suite itself uses `exit 3` and `exit 7` as container
statuses. Podman's own 125/126/127 for run-time failures are not in the
table.

### OPS-04 — No diagnostics mode

A one-line `error: command failed: "<argv>" -- "<stderr>"` is all an
operator gets. It shows the failing argv, which is good, but none of the
steps before it: which readiness checks passed, which image was resolved, or
why a rebuild happened (those notes go to stderr only in some paths,
`bin/jms:2136-2146`). A fleet ticket needs a reproducible trace.

### OPS-05 — No build provenance

The base comes from `fedora:latest` plus `dnf upgrade` plus unpinned npm
installs (`Containerfile:6,14,28-29`). That is a deliberate choice
(DW-003). But nothing stamped on the image records which jms version or
commit built it, or when. Two workstations reporting different agent
behaviour cannot be compared without `podman image inspect` and guesswork.

### OPS-06 — Disk growth

Retention keeps the two newest images per project (`KEEP_IMAGES`,
`bin/jms:40`). It runs only after a successful project build. Rebuilding the
base turns the old one into a dangling image, and jms can never see that
image again because ref-less facts are filtered out. Projects whose
directories were deleted keep their images until someone runs
`clean --images` or `trust revoke --purge-images`. On a fleet, disk fills
silently, and there is no `jms`-level usage report.

### OPS-07 — No resource limits

An autonomous agent running `make -j` or a runaway test in the container
competes with the host without limit on Linux. A manifest cannot express a
limit either, so the operator's only lever is a global `containers.conf`,
which `docs/linux.md:58-62` says jms trusts.

### OPS-08 — Upgrade path

Install is a symlink into the checkout (`Makefile:9`), so upgrading jms
means `git pull`. Nothing documents that, or that the base should be rebuilt
afterwards. Because `checkout_root()` is the base build context, local edits
in the checkout silently become every user's base on that machine. The
trust-store schema guards are good: a newer store refuses with "upgrade jms"
(`bin/jms:1112-1113`), and a newer manifest refuses the same way
(`:1515`).

## What works well

- **Fail-closed readiness validation of `podman info`:** rootless, local,
  subordinate-ID coverage and graph driver, each with an actionable hint
  (`bin/jms:603-655`).
- **A single process seam** (`runtime_run`) with consistent, terminal-safe
  error text and documented exit classes (`docs/cli.md:310-318`).
- **Cleanup that is idempotent and aggregated:** `--ignore` makes absence
  success, every removal is attempted, and the command exits 1 with a list
  (`bin/jms:750-769`, `:2669-2693`). Ownership needs both labels, not a name
  prefix (`:2638-2647`).
- **Containers are always `--rm`** (`bin/jms:281,549`), and TERM-during-launch
  cleanup is tested (`scripts/integration.sh:359-374`), backed by a trap-driven
  leak sweep (`:158-179`).
- **The trust store is locked with `flock`, written via temp+rename, and
  consent prompts run outside the lock** (`bin/jms:1119-1146`, `:1737-1751`).
- **Version policy is floor-only,** so an OS package upgrade never strands a
  workstation (`bin/jms:585-601`).
- **Build stdin is `/dev/null`,** so no engine prompt can hang a build
  (`bin/jms:1905-1909`).

## Top 3 recommendations

1. **Add timeouts and signal forwarding** (OPS-01, OPS-02). Bound the
   readiness and query calls. On TERM/HUP, forward the signal to the running
   runtime child and wait before exiting.
2. **Make failures diagnosable at fleet scale** (OPS-03, OPS-04, OPS-05):
   - `JMS_DEBUG` argv tracing;
   - a documented exit-code split for `launch`;
   - `jms.version` and commit labels on every image.
3. **Close the disk and upgrade loop** (OPS-06, OPS-08):
   - a jms-owned way to reclaim dangling bases and images of vanished
     projects;
   - a short "upgrading jms" section (pull, rebuild base, rebuild projects)
     with a dirty-checkout warning.
