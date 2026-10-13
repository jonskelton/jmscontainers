# Changelog

## 2.0.2 — 2026-10-13

- **stdout belongs to the launched program on macOS too.** The
  "starting container runtime..." line printed on a cold start, and
  `jms init`'s nested-project notice, now go to stderr. A script that
  captures `jms launch ... -- cmd` no longer gets an extra line once per
  boot.
- **The missing-base hint names `jms build --base`.** It used to say to
  run `jms build` "in the base directory", which no document defines.
- **Refusals end with the command that gets past them.** The no-terminal
  trust refusals name `jms trust PATH` and the exact
  `--fingerprint`/`JMS_TRUST_FINGERPRINT` alternative; fingerprint
  mismatches show the supplied and current 12-character prefixes; a bare
  `jms launch` outside a checkout names `jms launch .`. Exit codes are
  unchanged.
- **Invalid manifest fields say why.** A missing mount source reports
  `mount source does not exist: PATH` and the `mkdir -p` that fixes it
  instead of only `"mounts[0].source"`; an unknown key lists the keys
  allowed there.
- **The credential question says what "no" costs.** Declining means
  agents keep no login between launches; the prompt now says so and
  names the `jms trust` command that changes the answer.
- **Podman readiness hints print on their own line.** The four
  "rootless podman is not usable" errors showed a literal `\x0a` where
  the `hint:` line should start; the hint is now a separate stderr line.
- **Smaller wording fixes.** `-b ''` names `--bin`; a failed build no
  longer ends in an empty `-- ""`.
- **Docs.** The CLI reference documents `jms trust PATH --fingerprint
  HEX64 --auth` (a durable credential grant without a question) and that
  `--trust` overrides `JMS_TRUST_FINGERPRINT`; the README says a
  subdirectory launch without a definition mounts only that subdirectory
  and binds no read-only `.git`, and that you log in once inside the container; the
  macOS guide no longer mentions the version-acceptance override removed
  in 1.2.0; SECURITY.md lists every argv pin.

### Qualification

Linux matrix of the release-preparation host (2026-10-13), unchanged from
2.0.1. On it, `make test` passed (389 tests), integration tier A passed,
and `podman image inspect` of an absent ref exited 125 with `[]` on stdout
and a stderr byte-identical to
`tests/fixtures/podman-5.4.2-image-inspect-absent.stderr`.

| Dimension | Tested value |
| --- | --- |
| Podman | 5.4.2 |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.107+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` |
| Network backend | netavark 1.14.0, aardvark-dns 1.14.0, pasta (passt 0.0~git20250503.587980c) |
| Rootless | yes |
| Python | 3.15.0 |

The changes are to wording, documentation and which stream two notices
use; the runtime argv and the readiness checks are unchanged, so macOS
integration was not rerun and `ContainerBackend._version_qualified` is
unchanged (CI's macOS leg runs `make test`).

## 2.0.1 — 2026-10-12

- **The approval summary names `--git-writable`.** A first launch with
  `jms launch --git-writable` mounted `.git` read-write, but the
  capability summary shown before consent still called it read-only.
  The `.git` line now says writable and names each source:
  `run.git_writable`, `--git-writable`, or both.

### Qualification

Linux matrix of the release-preparation host (2026-10-12), unchanged from
2.0.0. On it, `make test` passed (382 tests), integration tier A passed,
and `podman image inspect` of an absent ref exited 125 with `[]` on stdout
and a stderr byte-identical to
`tests/fixtures/podman-5.4.2-image-inspect-absent.stderr`.

| Dimension | Tested value |
| --- | --- |
| Podman | 5.4.2 |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.107+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` |
| Network backend | netavark 1.14.0, aardvark-dns 1.14.0, pasta (passt 0.0~git20250503.587980c) |
| Rootless | yes |
| Python | 3.15.0 |

The change is to consent text only; it does not touch the runtime
interaction surface, so macOS integration was not rerun and
`ContainerBackend._version_qualified` is unchanged (CI's macOS leg ran
`make test`).

## 2.0.0 — 2026-10-12

- **Breaking: a launch mounts the project's top-level `.git` read-only.**
  A container can no longer plant `.git/hooks/*` or set config such as
  `core.fsmonitor` that host git later runs. This breaks `git add` and
  `git commit` inside the container ("Read-only file system"): commit on
  the host, launch with `--git-writable`, or set `[run] git_writable =
  true` in the definition (the approval prompt names it). Without that
  key, a definition's read-write mount of `.git`, a path inside it, or a
  directory containing it is refused. Only a real
  `.git` directory at the mount root is covered: linked worktrees,
  submodules, a `.git` symlink and subdirectory launches without a
  definition get no bind. Verified on Podman 5.4.2 and apple/container
  1.5.0.

- **Breaking: manifest mounts of host sockets are refused unless the
  mount sets `allow_socket = true`.** A source that is a socket, FIFO or
  device node fails unless that mount opts in, and the consent line names
  the opt-in. A source that contains or sits inside `$XDG_RUNTIME_DIR`,
  `/run/user/<uid>`, `/run`, `/var/run`, `/tmp/tmux-<uid>` or
  `/tmp/.X11-unix` is refused outright, as is the socket named by
  `$SSH_AUTH_SOCK` or a `unix://` `$DOCKER_HOST`, or any directory above
  it. Only an exact opted-in socket is exempt, so ssh-agent forwarding
  means mounting `$SSH_AUTH_SOCK` itself; that is not possible on macOS,
  where apple/container binds only directories. An older jms rejects the new
  key. The list is best-effort; see docs/jmscontainer.toml.md.

- **Breaking: manifest mounts of host credential stores need the
  credential grant.** A `[[mounts]]` source that is, contains, or sits
  inside a listed credential path (`~/.ssh`, `~/.gnupg`, `~/.config/gh`,
  `~/.aws`, `~/.kube`, `~/.docker`, `~/.netrc`,
  `~/.cargo/credentials.toml`, the host agents' own sign-in directories,
  and others, plus `$GNUPGHOME`, `$DOCKER_CONFIG`, `$KUBECONFIG` and
  `$AWS_SHARED_CREDENTIALS_FILE`) is kept only when the project's recorded
  grant is `auth = yes`, or under a matching `JMS_TRUST_FINGERPRINT` pin
  with `--auth`. Otherwise it is dropped with a `note:` naming it. The
  consent summary and the credential question list these mounts;
  `run.mount_auth = false` does not affect them. Mounting all of
  `~/.cargo` or `~/.m2` now goes through the credential question. The
  list is best-effort.

- **Breaking: launches without a project definition no longer mount agent
  credentials without consent.** Before, a launch that found no
  `.jmscontainer/` mounted every agent's credentials and configuration
  read-write with no question, and deleting a trusted definition brought
  that back. Now the first such launch in a checkout asks the default-No
  credential question once and remembers the answer for the checkout root
  (the enclosing checkout, else the workdir); a remembered "yes" behaves as
  before. Off a terminal nothing is mounted and one `note:` line says so;
  pass `--auth` for a one-launch grant. A trust record for a definition
  that is no longer present prints a warning and mounts nothing rather than
  asking again. `--no-auth` and `--root` are unchanged. What breaks: scripts
  and other non-interactive launches without a definition that relied on
  the silent mount must now pass `--auth`, every existing checkout asks
  once, and such launches now read the trust store, so an unreadable store
  stops them unless `--no-auth` is passed. Answers are ordinary schema-2
  store records (no schema change); an older jms ignores them.
  `jms trust revoke PATH` forgets an answer and `jms inspect` shows it.

- **On macOS, `jms launch` refuses a `[[mounts]]` source that is not a
  directory before consent and before building.** apple/container
  (checked on 1.5.0) bind-mounts directories only, so a file or socket
  source used to fail at run, after a full build, with `path '...' is not
  a directory`. Linux is unchanged.

- **`jms trust list` marks remembered no-definition answers.** Those rows
  end in `no-definition`; rows for definitions are unchanged.

- **`jms trust PATH --auth` (or `--no-auth`) records the credential
  answer for a checkout without a project definition.** No terminal is
  needed, so automation can set it. Plain `jms trust PATH` there still
  fails, now pointing at those flags; `--fingerprint` is rejected, and it
  refuses while a vanished definition's trust record covers PATH (revoke
  that first).

- **`jms trust revoke PATH` without a definition removes every vanished
  definition's record from PATH up to the checkout root**, not just the
  nearest, and names each one. If a remembered no-definition answer for
  the checkout then applies again, a note says so.

### Qualification

Linux matrix of the release-preparation host (2026-10-12). On it, `make
test` passed (380 tests), and `podman image inspect` of an absent ref exited
125 with `[]` on stdout and a stderr byte-identical to
`tests/fixtures/podman-5.4.2-image-inspect-absent.stderr`.

| Dimension | Tested value |
| --- | --- |
| Podman | 5.4.2 |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.107+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` |
| Network backend | netavark 1.14.0, aardvark-dns 1.14.0, pasta (passt 0.0~git20250503.587980c) |
| Rootless | yes |
| Python | 3.15.0 |

The read-only `.git` bind and the socket-mount changes were run on macOS on
2026-10-12 on apple/container 1.5.0 (macOS 27.0, Apple Silicon), before the
non-directory mount preflight landed:

- Integration tier A passed, including its read-only `.git` probe. By
  hand, writes to `/work/.git/hooks` and `.git/config` fail with EROFS,
  renaming `/work/.git` fails with EBUSY, `/work` stays writable, and
  `git commit` fails with "Read-only file system"; with `--git-writable`
  it succeeds and the commit reaches the host.
- ssh-agent forwarding with `allow_socket = true` cannot work there:
  apple/container binds only directories, so any single-file `[[mounts]]`
  source failed after the build with "is not a directory". jms now refuses
  such a source before consent and build.

Integration tiers A and B, including tier A's read-only `.git` probe, passed on
2026-10-12 on the release-preparation host above, on the developer's own
account (UID 1000), without sudo; no integration-owned container or image
remained afterwards.

Integration tier A, including its read-only `.git` probe, passed again on
2026-10-12 on this candidate (`c1827a3`) on apple/container 1.5.0 (macOS
27.0, Apple Silicon), with `make test` passing (380 tests). A launch with the
documented ssh-agent forwarding mount now stops before consent and build
with "is not a directory; container mounts only directories", and no
integration-owned container or image remained afterwards.

The release checklist's fresh-account (non-1000 UID, ssh login) run and
clean-VM install walkthrough were not performed: the project has one
user, and the maintainer accepted own-account runs in their place for
this release, as for 1.2.0.

## 1.2.0 — 2026-10-12

Pi joins the shared base image, manifest mounts accept relative sources and
targets, and a project can keep its host path inside the container.
Containers run in the host's time zone, a rebuilt base now makes project
images stale by exact image identity, and jms accepts any apple/container
from 1.2.2 up instead of one exact version. `jms launch --no-network` runs a
container with loopback only. This release also fixes a protected-path check on
hosts with symlinked `~/.config` or `~/.local`, stops the examples from
mounting host toolchain caches, documents which files a container can
leave for host tools, and moves the license to MIT alone.

- **The examples no longer mount host toolchain caches.** The go, rust and
  data-science examples mounted the host's own `~/.cache/go-build`,
  `~/go/pkg/mod`, `~/.cargo/registry` and `~/.cache/pip` read-write, so a
  container could change code that host builds of every project later
  used. They now mount private directories under
  `~/.cache/jms-examples/<example>/`, which no host toolchain reads; create
  them first as `examples/README.md` shows. The odin example drops its
  `~/.cache/odin` mount, which it did not need. A copy of an example made
  before this change keeps its old mounts until edited.

- **SECURITY.md names the files a container can leave for the host.** A
  new section lists the host-executed channels in a read-write checkout
  (`.git/config`, `.git/hooks/`, nested repositories, `.vscode/`,
  `.claude/`, `.mcp.json`, `CLAUDE.md`, `AGENTS.md`, build files), advises
  inspecting them with non-git tools after an untrusted session, and states
  that executable agent configuration in the shared agent-state pool is
  shared by every project granted credentials.

- **Security: the protected-path check now resolves symlinked `~/.config`
  and `~/.local` the same way as mount sources and workdirs.** Affected
  1.0.0 through 1.1.0: with a symlinked `~/.config`, `~/.local` or
  `~/.local/share`, the check that keeps the trust store and agent state
  out of containers compared paths inconsistently.

- **Project images are reused only when their labels match in full.** The
  project tag carries only prefixes of the project id and trust
  fingerprint, so an image found at the tag is now reused only when its
  `jms.project` and `jms.fingerprint` labels equal the full values;
  otherwise jms rebuilds over the tag. An image at the tag without those
  labels (one tagged by hand or by another tool) is rebuilt once.

- **The credential question says what a grant covers.** Before either
  credential question, jms now notes that a recorded grant is tied to the
  project path and its `.jmscontainer/` contents, not to the code: a branch
  or pull request later checked out there with the same definition gets the
  same access without asking. README, SECURITY.md and
  `docs/agent-state.md` say the same and recommend `--no-auth` for reviews.

- **Manifest mounts accept relative sources and targets.** A
  `mounts[].source` that is not absolute resolves from the project root --
  never from `.jmscontainer/` or the invoking working directory -- so a
  sibling checkout is `source = "../sibling/"` regardless of where `jms`
  was run. A relative `mounts[].target` resolves lexically from the
  container project path, which with `run.preserve_host_path = true` mounts
  a sibling at the same path it has on the host, so path-keyed tools agree
  on both sides. Under the default `/work`, `../sibling/` becomes
  `/sibling`.

  Relative targets are the one way out of the absolute-target allowlist
  (`~/`, `/opt/`, `/mnt/`, `/srv/`), which is a deliberate relaxation: an
  absolute target still may not leave it. A relative target still may not
  be, contain, or sit inside container system state (`/etc`, `/usr`,
  `/proc`, `/root`, and the rest of `CRITICAL_CONTAINER_PATHS`), the
  agent-state or shell-config mounts under either `/home/isolation` or
  `/root`, the project mount, or another manifest mount; `.`/`..` and
  trailing slashes are normalized before every one of those checks, and
  resolution does not follow host symlinks. Sources keep the existing
  symlink-resolution, existence, and protected-host-directory checks.

- **Pi is included in the shared base image.** Launch it with
  `jms launch -b yolo-pi`. Credentials, settings, and sessions under
  `~/.pi/agent` persist through the existing agent-state credential controls,
  including `--no-auth` and `--root`.

- **Launch stdout stays available for program output when Python is
  unbuffered.** Cold launches and stale-image rebuilds could prefix captured
  stdout with jms progress; automatic image-retention reports could appear
  there too. These messages now go to stderr, as runtime build output already
  does. This fixes a pre-existing output defect, independent of the recent
  Podman absence-probe fix. Explicit build summaries and clean reports retain
  their stdout output.

- **Shared-base freshness now follows exact runtime image identity.** Qualified
  and unqualified image names that normalize alike can coexist on
  apple/container while resolving to different images. Project builds now
  inspect the exact canonical base, each candidate `FROM` ref, and the exact
  project tag; `jms.base` is stamped only when a candidate resolves to the
  canonical identity. Digest ordering can no longer select an unrelated
  image or defeat the missing-base reuse rule.

  On Podman, absence is decided by `podman image exists` (exit 0/1) rather
  than by the wording of the `podman image inspect` diagnostic, which has
  already moved between releases: 5.4.2 prints `Error: <ref>: image not
  known`, not the `Error: inspecting object: <ref>: image not known` assumed
  while the parser was unqualified. The real 5.4.2 success and absence
  outputs are now checked in as fixtures. Inspect failures on both backends
  report the exit status alongside the diagnostic.

- **`jms build --no-cache` no longer resolves the project tag.** An
  explicitly requested rebuild replaces that image regardless, so querying
  the runtime for it only cost invocations and gave an inspect failure a way
  to abort the rebuild. The shared-base resolutions still run; they decide
  the `jms.base` label.

- **Named build stages no longer look like the shared base.** A later `FROM`
  that exactly references an alias declared by an earlier `FROM ... AS` is
  excluded from shared-base staleness detection, preventing an unrelated base
  refresh from rebuilding multi-stage projects.

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

- **`jms launch --no-network` runs a container with loopback only.** It
  maps to `--network none` on both runtimes and covers the run, not a
  project image build that the launch triggers. Credential mounting is
  unchanged, so pair it with `--no-auth` for offline work on untrusted
  code.

- **apple/container has a minimum version instead of an exact pin.** jms
  1.1.0 accepted only 1.2.0, so once Homebrew moved on (it ships 1.5.0
  today) every new macOS install failed at the version check until the user
  set `JMS_RUNTIME_ACCEPT`. jms now accepts 1.2.2 or newer, like the Podman
  backend: silent within the qualified major, a one-line stderr warning on
  a newer major. The newest qualified release is 1.5.0. `JMS_RUNTIME_ACCEPT`
  is gone; setting it does nothing.

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
  within the qualified major remain silent.

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

### Qualification

Linux matrix of the release-preparation host (2026-10-09). On it, `make
test` passed, and `podman image inspect` of an absent ref exited 125 with
`[]` on stdout and a stderr byte-identical to
`tests/fixtures/podman-5.4.2-image-inspect-absent.stderr`.

| Dimension | Tested value |
| --- | --- |
| Podman | 5.4.2 |
| Architecture | amd64 (`x86_64`) |
| Kernel | 6.12.107+deb13-amd64 |
| Distribution | Debian GNU/Linux 13 (trixie) |
| cgroup | v2, `systemd` manager |
| OCI runtime | crun 1.21 |
| Storage driver | `overlay` (extfs backing, native overlay diff) |
| Network backend | netavark 1.14.0, aardvark-dns 1.14.0, pasta (passt 0.0~git20250503.587980c) |
| Rootless | yes |
| Python | 3.13.5 |

macOS qualification ran on 2026-10-12 at candidate `a7dd855`, with
apple/container upgraded in place from 1.2.2 to the 1.5.0 Homebrew ships and
its service stopped at the start (jms started it). The commit recording this
changes only `ContainerBackend._version_qualified` (1.2.2 to 1.5.0), the test
that reads it, and documentation.

| Dimension | Tested value |
| --- | --- |
| macOS | 27.0.1 (26A434), Darwin 27.0.0 |
| Architecture | arm64 (Apple Silicon) |
| apple/container | CLI and API server 1.5.0 (Homebrew) |
| Python | 3.14.7 |
| shellcheck | 0.11.0 |
| Host time zone | America/Los_Angeles (PDT) |

- `make test`: compilation, 311 unit tests, and shellcheck passed.
- `scripts/integration.sh all` under `script -q` in Terminal.app: the
  apple exact shared-base identity collision, tier A, and tier B passed,
  with the credential prompt answered live, and the EXIT-trap leak sweep
  was clean. Afterwards no integration-owned container or image remained.
- Removal race: the ten-iteration appendix procedure passed (every
  `jms clean` exited 0, no failed removal, no ref left, final clean exited
  0). On 1.5.0 the background delete finished before `jms clean`
  enumerated in all ten iterations, so a second ten-iteration pass delayed
  the delete by 0.1 to 1.6 s. In two iterations the external delete
  succeeded after enumeration and `jms clean` still reported the ref
  removed and exited 0; every other ordering converged too.
- The apple/container 1.2.2 fixtures still hold on 1.5.0: an absent-ref
  `container image inspect` exited 1 with empty stdout and stderr
  byte-identical to `apple-container-1.2.2-image-inspect-absent.stderr`, and
  live `image inspect` and `image list` records have the fixtures' shape.
- The README/Homebrew clean-account walkthrough through `jms build --base`
  was not performed: as for the Linux fresh-account gate below, the
  maintainer accepted the own-account run in its place for this release.

Integration tiers A and B both passed on 2026-10-12 on the
release-preparation host above, on the developer's own account (UID 1000)
under Python 3.15.0, without sudo; tier A used the proxy-based egress
check. The release checklist's fresh-account (non-1000 UID, ssh
login) run and clean-VM install walkthrough were not performed: the
project has one user, and the maintainer accepted the own-account runs in
their place for this release.

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
