# Changelog

## Unreleased

- **A rebuilt base makes project images stale.** Project images built `FROM
  jmscontainers-base` record the base image id as a `jms.base` label; `jms
  build` and `jms launch` compare it against the current local base and
  rebuild automatically on mismatch, so `jms build --base --pull --no-cache`
  followed by a plain `jms build` per project is now a complete update.
  Previously an existing fingerprint-tagged image was always reused and only
  `--no-cache` picked up a refreshed base. Images from earlier releases have
  no label and rebuild once. Projects whose Containerfile does not name the
  base in a `FROM` line (external or `ARG`-indirected bases) keep the
  fingerprint-only rule, and a missing local base never forces a rebuild.

- **apple/container 1.2.2 is qualified on macOS.** The exact fail-closed pin
  now matches the release installed by the documented Homebrew command, so a
  new installation reaches `jms build --base` without
  `JMS_RUNTIME_ACCEPT`. Later apple/container versions still require an exact
  one-invocation override until they are qualified.

- **The live macOS gate now exercises the shared launch contract.** Darwin no
  longer returns from tier A after the base build: ownership and identity,
  sudo, exit and signal cleanup, inherited host time zone,
  read-only shell state, and failed-run cleanup run against both backends.
  Podman-specific user-namespace, nested-bwrap, and nftables assertions stay
  on Linux. Tier B also proves `run.preserve_host_path` keeps the canonical
  `PWD` and provides a writable host round trip.

- **The macOS qualification guide is release-neutral.** It no longer names a
  historical branch, fixed unit-test count, or already-closed 1.1.0 release
  issues; it now derives candidate facts at run time and defines the reusable
  interactive gate, clean-install walkthrough, and evidence record.

- **The macOS qualification gate is green.** The 2026-08-14 Apple Silicon
  run used macOS 26.5.2, apple/container 1.2.2, and Python 3.14.7. `make test`
  passed 233 tests plus compilation and shellcheck; the full interactive
  `scripts/integration.sh all` run, credential prompt, survivor set,
  inherited time zone, preserved host path, leak sweep, and ten-iteration
  removal race all passed with `JMS_RUNTIME_ACCEPT` unset. The candidate tree
  is based on `e8aeb42`; rerun the gate if later runtime-affecting changes
  land before release.

- **Containers now run in the host's time zone.** The base image selects no
  zone, so every container labelled its instants UTC: the clock agreed with
  the host to the minute while `date` named the wrong *day* for anyone whose
  evening is the next UTC morning — and a tool writing dates wrote them
  wrong, confidently. `jms launch` resolves the host's IANA zone (from `TZ`,
  the `/etc/localtime` symlink, or `/etc/timezone`) and passes it as `TZ`,
  so `date`, language runtimes, and git commit stamps all render your local
  calendar date. Only a name present in the host's own zoneinfo tree is
  accepted; a host that states no resolvable zone gets no `TZ` and behaves
  exactly as before. A manifest `[env] TZ` replaces the inherited value
  rather than competing with it, for a project whose dates must not vary
  with the machine the session runs on. `/etc/localtime` inside the
  container is unchanged and still reads UTC.

- **The login banner states the day and the zone.** A container whose zone
  did not arrive answers `date` just as confidently as one configured
  correctly, so interactive logins now open with `Thu 2026-08-13 18:34 PDT`.
  The base image also names `tzdata` in its package list instead of relying
  on it arriving transitively: an inherited zone with no zoneinfo entry
  behind it degrades silently to UTC.

- **A project can keep its host path inside the container.** New manifest key
  `run.preserve_host_path` (boolean, default `false`) mounts the checkout at
  its own absolute host path instead of `/work`. It exists for tools that key
  per-project state on the working directory: Claude Code stores memory and
  transcripts under `~/.claude/projects/<cwd with slashes as dashes>`, which
  is `-work` for every jms project at once while the same checkout on the host
  has a key of its own — so no per-project state can be shared between host
  and container, and unrelated projects collide on one key inside. Matching
  the paths makes the keys agree. The manifest chooses only whether to
  preserve the path, never what it is, so no new target is reachable; jms
  still refuses a preserved path that would shadow container system state
  (`/etc`, `/usr`, `/proc`, …), overlap a reserved mount target (including
  `/home`, which would swallow the agent-state mounts), or collide with a
  manifest `[[mounts]]` target. `--root` re-checks against `/root`. Those
  refusals run before the trust prompt and the image build, so a layout
  that can never mount costs neither consent nor a build. The key
  is manifest content, so enabling it changes the trust fingerprint and the
  consent summary names the path that will be mounted. Default behavior is
  unchanged: without the key the project still mounts at `/work`.

- **A build can no longer garbage-collect the image it just produced.**
  Runtime creation times are whole seconds, so a project build landing in
  the same second as an earlier one tied in the retention ordering and fell
  back to image-digest order. The tag `jms build` was about to return —
  and `jms launch` about to run — could therefore sort into the eviction
  window and be untagged immediately after being built. Retention now takes
  the current tag as protected: it is kept regardless of ordering and
  consumes one of the two retention slots, so the store stays bounded.
  `jms trust revoke --purge-images` is unaffected and still removes every
  project image.

- **A newer Podman major is no longer accepted silently.** The floor stays
  at 5.4 and there is still no ceiling — nothing at or above the floor is
  refused, since Podman is OS-packaged and a distribution upgrade must not
  strand you — but a major above the qualified series (5.x, newest
  qualified 5.4.2) now prints a one-line stderr warning naming the newest
  qualified version. New majors can change the cleanup, user-namespace, and
  mount semantics this backend parses strictly. Minor and patch bumps
  within the qualified major remain silent, and `JMS_RUNTIME_ACCEPT` stays
  apple/container-only: it neither suppresses the warning nor is required.

- **Documentation corrections.** `SECURITY.md` said the qualified Debian 13
  target "runs AppArmor"; the checked-in qualification captures report
  AppArmor unavailable and an empty container `AppArmorProfile`, so no
  mandatory access control applies to a jms container there at all. That is
  now stated as its own Linux claim. The README separates *qualified*
  (tiers green on Debian 13/amd64/Podman 5.4.2) from *accepted* (any local
  rootless Podman ≥ 5.4), and the Linux guide states as a prerequisite that
  jms does not enforce a Podman sandbox profile.

- **Integration harness checks its nftables prerequisites up front.**
  `scripts/integration.sh` now probes `sudo -n nft` before creating any
  state, so a missing `nftables` package or missing passwordless sudo exits
  3 with a hint naming which of the two is absent, instead of failing
  partway through after a base build. The probe covers the `a` and `all`
  selections only: the egress denial belongs to tier A, and
  `scripts/integration.sh b` needs no host privileges. The requirement is
  also named in
  `CONTRIBUTING.md` and the release checklist, neither of which previously
  mentioned the package or that the sudo access must be passwordless.
  Affects the manual qualification run only.

- **Integration harness reports a cleanup failure it used to swallow.**
  `scripts/integration.sh` sets exit status 3 whenever the nftables
  egress-denial table survives the EXIT trap, instead of only when the
  tiers otherwise passed. Previously a tier failure (1) or a leak-sweep
  failure (2) masked it, so a run that left an egress-blocking rule
  installed on the host could be classified as an ordinary test failure —
  contrary to §9, which specifies the harness failure be reported
  distinctly. Affects the manual Linux/macOS qualification run only; jms
  itself is unchanged.

- **License simplified to MIT.** 1.0.0 and 1.1.0 were released under
  `MIT OR Apache-2.0`; the dual license is dropped in favor of MIT alone.
  GitHub's license detector only recognizes a single known text, so the
  pointer-style `LICENSE` resolved to `NOASSERTION` and the repository
  advertised "Other" — a needless obstacle for anyone whose compliance
  process filters on the detected value. Recipients of the earlier tags keep
  the terms those tags shipped under; the Apache-2.0 option is simply no
  longer offered going forward. Done now because the project has no install
  base.

## 1.1.0 — 2026-08-03

Linux support: jms now runs on Debian 13 (amd64) with local rootless
Podman ≥ 5.4, alongside the existing apple/container backend on Apple
Silicon Macs. The trust model, fingerprinting, consent flow, manifest
schema, and project discovery are shared and identical on both platforms;
only the runtime layer is per-backend.

- **Rootless Podman backend.** Selected automatically on Linux (no override
  switch). Launches pin the user-namespace mapping explicitly
  (`--userns=keep-id:uid=1000,gid=1000`, or `--userns=host` under
  `--root`) and pass `--user` numerically, so image content can never
  choose the runtime UID; `/work` writes land on the host owned by the
  invoking user. `--hostname container` and
  `--security-opt label=disable` are always passed. Refused outright:
  uid 0 on Linux, remote Podman services, and non-Linux/non-macOS
  platforms. Other distributions, arm64, and SELinux-enforcing hosts are
  unqualified but allowed. See the new per-platform boundary statement in
  SECURITY.md — the Linux boundary is kernel isolation, not a VM.
- **apple/container pin moves to 1.2.0** (the only version Homebrew
  ships). `JMS_RUNTIME_ACCEPT` remains apple/container-only; the Podman
  backend is qualified min-only and accepts newer versions silently.
- **Cleanup reports aggregated failures.** `clean` and
  `trust revoke --purge-images` attempt every scheduled removal, report
  each failure, and exit 1 instead of aborting mid-list; background image
  retention warns and never fails a successful build or launch. Container
  ownership now requires the `jms.container=launch` provenance marker in
  addition to the project label, so containers started manually from
  jms-built images are never selected. Podman image untags pass
  `--no-prune`, so removing a project image never sweeps up dangling
  parents.
- **Project images now have an explicit user ABI.** The `isolation` account
  must be UID/GID `1000:1000`, use `/home/isolation` and `/bin/bash`, own a
  writable home, and have passwordless sudo. The base image already satisfies
  this contract; `examples/clean-slate` now pins it explicitly and moves to a
  fully qualified external base reference. Standalone images created for 1.0
  that relied on distribution-assigned IDs must pin the account to
  `1000:1000` before using the Linux backend. This retains 1.1.0 because the
  numeric identity was already required by Linux's explicit rootless Podman
  mapping, though it was not previously documented.
- **Integration harness split into tiers** (`scripts/integration.sh
  a|b|all`): tier A asserts the launch contracts on the base image
  (ownership, UID mapping, sudo, hostname, exit propagation, read-only
  shell state, ambient-config conflicts, nested-bwrap probes, and
  FROM-resolution under egress denial); tier B runs the example cycle,
  auth-mount and manifest-env parity checks, and the image survivor-set
  run. Both tiers end in a strict three-outcome leak sweep.

### Qualification

Both real-host gates are green. macOS: apple/container 1.2.0 on Apple
Silicon, full interactive `scripts/integration.sh all` (2026-07-31). Linux:
the matrix below, full `scripts/integration.sh all` plus the clean-host
install walkthrough, run as a fresh `adduser` account with a non-1000 UID
and non-1000 primary GID over a real ssh login session (2026-08-03).

| Dimension | Tested value |
| --- | --- |
| Podman | 5.4.2 |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.100+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` (extfs backing, native overlay diff) |
| Network backend | netavark 1.14.0, aardvark-dns 1.14.0, pasta |
| Rootless | yes |
| Python | 3.13.5 |

Other distributions, arm64, and SELinux-enforcing hosts remain unqualified
but allowed. See `docs/release-critical-issues.md` for the full evidence.

## 1.0.0 — 2026-07-29

Initial release.

jms runs throwaway containers for claude-code, codex, and opencode in
full-permission ("yolo") mode inside `apple/container` VMs on Apple Silicon
Macs, without handing the agent the host. What ships:

- **Consent-gated project definitions.** A project opts in to its own image
  by committing `.jmscontainer/` (a Containerfile plus an optional
  `jmscontainer.toml` runtime manifest). Nothing builds or runs until the
  user approves the directory's SHA-256 trust fingerprint; any change to the
  definition re-asks. Build/run approval and the agent-state (credentials
  and configuration) mount are two separate grants, managed with
  `jms trust list|revoke|prune` and stored in
  `~/.config/jmscontainers/store.json`. Non-interactive use pins an audited
  fingerprint via `JMS_TRUST_FINGERPRINT`; the one-shot `--trust` flag never
  persists anything to the store.
- **Ephemeral containers over a shared base image.** `jms launch` starts an
  `--rm` container with the project mounted read-write at `/work`; nothing
  else survives exit. The Fedora base image (`jms build --base`) carries the
  three agents, their `yolo-*` full-permission launchers (usable as
  entrypoints: `jms launch -b yolo-claude`), bubblewrap for the Codex
  sandbox, and a general CLI toolset; project images layer on top of it.
  jms keeps the newest two images per project and evicts older ones after
  each successful build.
- **Path-based discovery bounded by the checkout.** Workdir operands are
  ordinary paths; the upward search for `.jmscontainer/` stops at the root
  of the enclosing VCS checkout and never passes `$HOME` or a filesystem
  boundary. Optional `JMS_PROJECT_ROOTS` restores a bare-name shorthand,
  with the current directory always winning and a stderr note whenever the
  search path is what resolved a name.
- **Persistent agent state, deliberately shared.** Credentials and
  configuration live under `~/.local/share/jmscontainers/agents/` on the
  host — outside any checkout — and mount read-write only under the
  credential grant, so one login per tool covers every later container.
  Host-side shell customization from `~/.local/share/jmscontainers/shell/`
  mounts read-only into every container.
- **Safety properties around the runtime.** Protected roots (the jms
  checkout, the config and state dirs) are refused as workdirs; image
  cleanup requires both the `jms.project` label and the project's tag
  prefix before deleting anything; `clean --all` never touches unlabelled
  containers or other projects' images; the accepted `container` runtime
  range is qualified, with `JMS_RUNTIME_ACCEPT` as a one-invocation
  escape hatch.
- **Tooling.** `jms init` scaffolding, Bash completion, `make
  install`/`uninstall`, a runtime-free `make test` (unit tests plus shell
  lint) run by CI on macOS and an Ubuntu Python matrix, an opt-in
  `make integration` that exercises the bundled examples (Go, Rust, Odin,
  data-science, clean-slate), and reference docs for the
  [CLI](docs/cli.md) and the
  [manifest schema](docs/jmscontainer.toml.md).

Requires macOS 15+ on Apple Silicon, Python 3.11+, and Apple's `container`
runtime.
