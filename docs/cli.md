# jms CLI reference

```text
jms build   [-w|--workdir PATH] [--base] [--trust] [--no-auth]
            [--no-cache] [--pull]
jms launch  [-w|--workdir PATH | PATH] [--trust] [--auth|--no-auth]
            [--no-cache] [--no-network] [--git-writable] [-r|--root]
            [-b|--bin PROGRAM] [-n|--name NAME] [-- ARGS...]
jms inspect [-w|--workdir PATH | PATH]
jms trust   [PATH] [--fingerprint HEX64] [--auth|--no-auth]
jms trust   list
jms trust   revoke PATH [--purge-images]
jms trust   prune
jms init    [-w|--workdir PATH] [--with-manifest]
jms clean   [-w|--workdir PATH | --all] [--images] [--dry-run] [-y|--yes]
```

Every `PATH` is any nonempty path, and the positional and `--workdir` forms
share one grammar. Absolute paths are used as given; relative paths —
including `.`, `..`, and bare names — resolve against the current directory,
as in any other command-line tool. Omitting the operand means the current
directory. A bare name that matches nothing in the current directory falls
back to the `JMS_PROJECT_ROOTS` search path when one is configured; jms
reports on stderr when that fallback is what resolved the name. jms has no
built-in project directory and no layout convention of its own. A path that
does not exist is a usage error (exit 2).

`--auth` and `--no-auth` are mutually exclusive. A supplied `--bin` must be
nonempty UTF-8 without NUL. `launch` and `inspect` take the workdir either
positionally or as `--workdir`, never both; `build`, `init`, and `clean`
take only `--workdir`, and `trust` takes only a positional `PATH`. `-n NAME`
on `launch` names the container, not the project. `build --base` and
`clean --all` cannot be combined with `--workdir`. `--pull` is valid only
with `--base`.

## Runtimes

jms selects its container runtime from the platform, lazily on first use
and with no override switch: macOS selects **apple/container**, Linux
selects **local rootless Podman**. Selection is side-effect-free and
precedes every consent prompt or trust-store write, so a selection refusal
(exit 2) never leaves partial state. Selection refuses platforms other
than Linux and macOS, and uid 0 on Linux. Readiness, checked when a command
first uses the runtime, then refuses (exit 1) a runtime below its minimum
version and, on Podman, a remote service (`host.serviceIsRemote`),
non-rootless mode, subordinate ID maps that do not cover 65536 ids, and
`podman info` output that is malformed or names no storage graph driver; see
[What jms refuses](linux.md#what-jms-refuses). Any other local rootless
Linux configuration is unqualified but allowed, with no warning.
Docker is not a supported runtime on either platform; jms has no Docker
backend.

Both runtimes have a minimum version and no ceiling: nothing at or above
the floor is ever refused, because each runtime arrives from a package
manager (Homebrew or apt) that carries one version, and an upgrade there
must not strand you. Acceptance is silent within the qualified major; a
newer major is still accepted but prints a one-line warning to stderr,
since it can change the flags, JSON, cleanup, user-namespace, and mount
semantics the backends parse strictly.

- **apple/container:** ≥ 1.2.2; qualified major 1.x, newest qualified 1.5.0.
- **Podman:** ≥ 5.4 (Debian 13's packaged version); qualified major 5.x,
  newest qualified 5.4.2. Readiness validates
  `podman info`: local service, rootless mode, subordinate ID coverage of
  at least 65536 ids per map, and readable storage metadata.

Commands that never touch the runtime — `--version`, `--help`, `inspect`,
`init`, `trust PATH` (including its `--fingerprint`, `--auth`, and
`--no-auth` forms), `trust list`, `trust revoke` without `--purge-images`,
`trust prune` — work with no runtime installed, on unsupported platforms,
and under uid 0.

## Project discovery

jms looks for a `.jmscontainer/` directory at the workdir and then upward,
stopping at the root of the enclosing VCS checkout (`.git`, `.hg`, `.jj`, or
`.svn` — `.git` may be a file, as in worktrees and submodules). The nearest
definition wins, so a nested project shadows an outer one. Outside a checkout
there is no defensible project boundary above the workdir, so only the workdir
itself is considered.

The search for the checkout root never climbs past `$HOME` (for paths inside
it) or past a filesystem boundary (for paths outside it), and that bound is
exclusive: a git-managed `$HOME` is not itself a checkout root, so one
dotfiles repository cannot make every directory beneath it one project.

The practical consequence is that a `.jmscontainer/` above your checkout root
is invisible from inside it, wherever you keep your code.

## Implicit workdir

Commands that mount or delete act on the current directory when given no
operand. Without a discovered definition, `launch` mounts the workdir itself
read-write, so a bare `jms launch` requires the current directory to be inside
a checkout; `$HOME` never qualifies, even when it is a repository. `clean`
applies the same rule before falling back to the workdir as its scope. Pass an
explicit path to act on a directory that does not meet the bar.

## build

`build` realizes the discovered project's image, or the shared base when
`--base` is passed or no definition is discovered. The build context is the
project's `.jmscontainer/` directory itself (the repository checkout for the
base, whose `.containerignore` excludes every file); `COPY`/`ADD` sources
must live inside it. An image whose tag matches the current trust
fingerprint is reused only when its `jms.project` and `jms.fingerprint`
labels match the project and fingerprint in full; otherwise it is rebuilt
over; `--no-cache` forces a rebuild without
reusable layers. `--pull` refreshes `FROM` references and is valid only with
`--base`: project Containerfiles reference the local-only tag
`jmscontainers-base:latest`, which a pull-mode build would try to resolve
against a remote registry. After a successful project build, jms keeps the
newest two images per project and deletes older ones.

To refresh container software, run the update recipe:

```sh
jms build --base --pull --no-cache
```

Each project image built from the shared base records the base image id it
was built from (the `jms.base` label). A later `jms build` (or `jms launch`)
compares that record against the current local base and rebuilds the project
image automatically when the base has changed, so the recipe above followed
by a plain `jms build` in each project is a complete update. The comparison
is skipped for projects whose Containerfile does not name
`jmscontainers-base` in a `FROM` line (including `ARG`-indirected bases);
those rebuild only on a fingerprint change or `--no-cache`.

Every image jms builds, base and project alike, also carries a `jms.version`
label with the jms version that built it and, when the jms checkout is a git
working tree, a `jms.commit` label with its `HEAD` commit (suffixed `-dirty`
when tracked files have local changes). Read them with
`podman image inspect --format '{{json .Labels}}' <image>` to compare what
built the images on two machines. The commit is best effort: when git is
missing or the checkout is not a repository the label is left off and the
build goes ahead.

Builds of one image are serialized: a second `jms build` (or an implicit
build from `jms launch`) of the same project, or of the base, prints
`waiting for another jms build of this image to finish...` and waits for the
first to finish. It then rechecks, so it normally finds the image up to date
and reuses it rather than building it twice. The lock files live in
`~/.local/share/jmscontainers/locks/`; builds of different projects do not
wait for each other.

The runtime resolves every candidate `FROM` reference exactly. A qualified
spelling such as `docker.io/library/jmscontainers-base:latest` counts as the
shared base only when it resolves to the same image ID as the canonical local
`jmscontainers-base:latest` reference. If the two spellings resolve to
different images, the qualified image is treated as an independent external
base and the project is not stamped with the canonical ID. An absent
canonical local base never forces an existing project image to rebuild.

## launch

During `launch`, jms build progress, automatic image-retention diagnostics
and the macOS runtime auto-start notice go to stderr, leaving the launched
program's stdout available for capture.
The container runtime and launched program can also write to stderr.

`launch` discovers the nearest definition, applies the consent gate, builds
(or reuses) the project image, and replaces itself with the runtime's
`run --rm` invocation.
Without a definition it launches the shared base, and agent state is
mounted only with consent: a recorded answer for the checkout root (the
nearest enclosing checkout, else the workdir), an explicit `--auth` for that
launch, or a default-No question asked once on a terminal and then recorded.
Off a terminal with no recorded answer, it mounts no agent state and prints
one `note:` line. A trust record for a definition that is no longer present
at the workdir or an ancestor inside the checkout prints a warning and
mounts nothing without `--auth`; it is never re-asked. `--no-auth` skips the
trust store entirely. See
[Launches without a definition](agent-state.md#launches-without-a-definition).
Arguments after `--` are
appended to the selected entry argv. `--root` runs as root instead of the
`isolation` user, which moves the agent-state and shell-config mount targets
from `/home/isolation` to `/root`. Manifest mount targets are never rewritten:
they are re-checked against the effective home, so a manifest mount aimed at
`/home/isolation/...` is rejected under `--root` rather than silently landing
somewhere else.

`--no-network` runs the container with no network: only loopback exists
inside it (`--network none` on both runtimes). It applies to the run only;
a project image that needs building is still built with the network, so
run `jms build` first if that matters. It does not change credential
mounting: agents that need their cloud service will not work, so pair it
with `--no-auth` for offline work on code you do not trust.

The project's top-level `.git` is mounted read-only by default, so the
container cannot plant hooks or change config that host git later runs.
`git status`, `log`, and `diff` work inside; `git add` and `git commit` fail
with `Read-only file system`. `--git-writable` mounts it read-write for one
launch; a definition can set
[`run.git_writable`](jmscontainer.toml.md#read-only-git) instead, which the
approval prompt names. Only a real `.git` directory at the project mount
root is covered: a `.git` file (linked worktree, submodule), a `.git`
symlink, or a launch from a checkout's subdirectory with no definition gets
no read-only bind.

`--bin` becomes the runtime entrypoint verbatim. The base image ships
full-permission agent launchers — `yolo-claude`, `yolo-codex`,
`yolo-opencode`, and `yolo-pi` — so `jms launch -b yolo-claude` starts directly
in an agent session with permission prompts disabled; extra agent arguments
go after `--`. An entrypoint bypasses the login-shell profile, and the
container exits when the entry program does. Pi runs with full process
permissions by default, so `yolo-pi` forwards arguments without a bypass flag.

Every launch passes the host's IANA time zone into the container as `TZ`, so
`date`, language runtimes, and git commit stamps render your local calendar
date rather than the image default of UTC. The zone is resolved from `TZ`,
then the target of the `/etc/localtime` symlink, then `/etc/timezone`, and
only a name that exists in the host's own `/usr/share/zoneinfo` is used: a
POSIX rule string such as `PST8PDT,M3.2.0,M11.1.0` is not a zone name and the
next source is tried instead. A host that states no resolvable zone gets no
`TZ` argument and the container stays UTC. A project that must not vary with
the machine it runs on pins the zone in its manifest — `[env] TZ` replaces
the inherited value rather than competing with it, and exactly one `TZ`
reaches the runtime. `/etc/localtime` inside the container is untouched and
still points at UTC; `TZ` is what the C library, Python, and git read.

Every launch also mounts `~/.local/share/jmscontainers/shell/` (created on
first use) read-only at `~/.config/jms-shell` in the container; the base
image sources `bashrc`/`zshrc` from it in interactive shells. This mount is
jms-controlled and identical for every container — it is not a project
capability and never appears in the consent summary. Its target is reserved:
a manifest mount cannot claim or shadow `~/.config/jms-shell`.

## inspect

`inspect` reports discovery, the trust fingerprint, and trust status without
prompting, writing, or contacting the runtime. It prints one `key: value`
line per field on stdout. The output is written for people: later versions
may add keys, so a script should look keys up by name, not by line.

| Key | Value |
| --- | --- |
| `workdir` | the resolved operand |
| `root` | the project root (the workdir itself without a definition) |
| `spec` | the `.jmscontainer/` directory, or `shared base` |
| `project_id` | SHA-256 of the root path; keys the trust store |
| `trust_fingerprint` | SHA-256 of the definition (definition only) |
| `trust_store` | `readable`, or `error: ...`; without a definition an error ends the output here |
| `trust_source` | `trust store`, `stale trust-store record`, `JMS_TRUST_FINGERPRINT (one-shot)`, `JMS_TRUST_FINGERPRINT mismatch`, or `none` (definition only) |
| `build_run_grant` | `held` or `required` (definition only) |
| `credential_root` | where a no-definition credential answer is keyed: the enclosing checkout root, else the workdir (no definition only) |
| `credential_grant` | with a definition, `held` or `required`; without one, `held`, `declined`, `unrecorded`, or `declined (definition at PATH vanished)` |
| `target_image` | the image tag `build` and `launch` would use |

## trust

`jms trust PATH` interactively (re)approves a definition; with
`--fingerprint HEX64` it records durable trust non-interactively when the
value matches the current fingerprint. Combined with `--auth`, it also
records the credential grant without asking — the strongest
non-interactive grant jms offers, so pin only a definition you have
reviewed; without `--auth` it records the credential grant as declined,
replacing any earlier answer. `list`, `revoke`, and `prune` are
reserved words in the `trust` grammar: a project directory literally named
`list` must be passed as an absolute path. During any interactive approval,
`--no-auth` suppresses the credential question and records the credential
grant as declined. Interactive approval requires TTY stdin and stderr; the
consent UI is written to stderr. EOF at a question is its default-No answer.

The boolean `--trust` flag on `build` and `launch` is the one deliberate
consent bypass: it grants build/run approval for that single invocation
without prompting and without persisting anything — the store is not
written, and the next unflagged invocation prompts as usual. It never
satisfies a custom definition's credential grant: combined with `--auth`
it still asks the credential question on a TTY and fails closed without
one. Without a credential grant, manifest mounts of host credential paths
are dropped with a notice; see
[Credential-path mounts](jmscontainer.toml.md#credential-path-mounts). Use it for
throwaway experiments on definitions you just read; for automation, prefer
a durable `jms trust --fingerprint HEX64` grant or a per-invocation
`JMS_TRUST_FINGERPRINT` pin, both of which name the exact fingerprint they
approve.

`trust revoke --purge-images` commits and reports the revocation before it
contacts the runtime; if image deletion then fails, trust remains revoked.
Every other `trust` form is store-only and works without the runtime CLI.

`trust revoke PATH` without a definition removes the records of every
vanished definition at PATH and its ancestors inside its checkout, naming
each one, if there are any; a remembered answer for the checkout root then
applies there again, and a `note:` says so. Otherwise it removes the
remembered credential answer for PATH's checkout root; the next launch
there on a terminal asks again. `trust PATH --auth` (or
`--no-auth`) without a definition records that answer for PATH's checkout
root directly, replacing any earlier one, and needs no terminal; it refuses
while a vanished definition's record covers PATH (revoke that first), and
rejects `--fingerprint`. Plain `trust PATH` without a definition fails.
`trust list` shows remembered answers alongside
project grants, marking each remembered answer `no-definition`.

The trust store is `~/.config/jmscontainers/store.json` (schema 2). A
remembered answer for a launch without a definition is an ordinary record
whose fingerprint is that of an empty definition, which no real definition
can produce; a definition added later at that root needs full consent.

## init

`init` scaffolds `.jmscontainer/Containerfile` in the workdir, plus
`jmscontainer.toml` beside it with `--with-manifest`, prints one `created`
line per file on stdout, and suggests the next step on stderr. It fails rather than
overwriting an existing `.jmscontainer`, and removes anything it created if a
later step fails. It refuses to scaffold at `$HOME`, at `/`, or inside a
protected jms host directory (the jms checkout, `~/.config/jmscontainers`,
`~/.local/share/jmscontainers`). When a definition is already discoverable
from the parent directory, `init` still proceeds but reports that the new
nested project will shadow the outer one.

## clean

`clean` removes this project's containers (or all jms containers with
`--all`); `--images` also removes the project's images (plus the shared base
under `--all`). `--dry-run` reports the selection without mutating.

On a terminal (stdin and stderr both a TTY), `clean` lists what it selected
and asks `Remove these? [y/N]` before it stops or removes anything; the
default is no. Selected containers are usually live sessions, since
`launch` runs them with `--rm`. Declining removes nothing and exits 1.
`-y`/`--yes` skips the question. Off a terminal, `clean` does not ask and
proceeds, as before. When nothing matches, `clean` (and `clean --dry-run`)
prints `nothing to remove` on stderr and exits 0.

Container ownership requires two labels jms applies to every container it
creates: the `jms.project` scope label **and** the `jms.container=launch`
provenance marker — never a `jms-` name prefix, which anything can claim.
Image labels inherit onto containers, so a container you start manually from
a jms-built image carries `jms.project` but only the neutral
`jms.container=image` value, and is never selected. Removal failures are
aggregated: `clean` attempts every scheduled removal, reports each failure,
and exits 1, rather than aborting mid-list. Without
`--images`, `clean` performs no image operations at all; it never prunes
images it does not own, under any scope (image untags on Podman pass
`--no-prune`, so removing a project image never sweeps up dangling
parents). Run your runtime's own `image prune` yourself if you want a
global sweep.

## Timeouts and signals

jms bounds the calls it makes to check or query the runtime: the version
probe, `podman info`, `container system status`, image inspect, exists and
list, and container listing. Each may run for 60 seconds (`container system
start`, which may boot the VM, three times that) before jms kills it and
exits 1 with `error: runtime command timed out after 60s: "<command>"`. A
runtime that hits this is wedged (a stale storage lock, for example); check
it by hand. `JMS_RUNTIME_TIMEOUT` changes the limit. Image builds, container
stops and removals, and the container `launch` runs are never timed out.

When jms receives SIGTERM or SIGHUP while a runtime command such as a build
is running, it passes the signal on to that command and waits for it to
exit, so stopping jms (a closed SSH session, a service manager) does not
leave a build running on its own. jms then exits with 128 plus the signal
number (143 for SIGTERM, 129 for SIGHUP) after printing
`error: terminated by SIGTERM` (or `SIGHUP`). Ctrl-C is unchanged: the
terminal delivers it to the runtime directly. `launch` replaces jms with the
runtime, so a signal sent during a session goes to the runtime itself.

## Environment variables

- `JMS_DEBUG`: set to `1` (any value except empty or `0`) to print every
  runtime command to stderr as jms runs it, as `jms-debug: run: "podman"
  "info" ...` (or `exec:` for the command `launch` replaces itself with),
  followed by `jms-debug: exit <status> (<seconds>s)`. Use it to see which
  runtime step failed or hung. The trace includes the full arguments,
  including manifest `[env]` values passed as `--env`.
- `JMS_RUNTIME_TIMEOUT`: seconds each runtime readiness or query call may run
  before jms gives up (see Timeouts and signals). A whole number from 1 to
  999999; the default is 60. Any other value is a usage error (exit 2).
- `JMS_PROJECT_ROOTS`: colon-separated absolute directories (a leading `~` is
  expanded) searched for a bare-name operand that matches nothing in the
  current directory, first match wins. Unset by default. Set it to keep every
  checkout in one place and still type `jms launch myproject` from anywhere:
  `export JMS_PROJECT_ROOTS=~/git`. A name that does exist in the current
  directory always wins over the search path, so the shorthand can never
  silently mount a different directory than the one you named.
- `JMS_TRUST_FINGERPRINT`: one-invocation exact trust fingerprint pin. This is
  also the only non-interactive path to a one-shot credential grant: with a
  matching pin, `--auth` mounts the persistent agent state (credentials and
  configuration) and keeps manifest credential-path mounts without
  prompting; a pin without `--auth` drops those mounts with a notice unless
  a credential grant is already recorded. For a durable non-interactive
  grant, use `jms trust PATH --fingerprint HEX64 --auth`. The
  boolean `--trust` flag never grants credential access; combined with
  `--auth` it still asks the credential question on a TTY and fails closed
  without one. `--trust` takes precedence over the pin: with `--trust`,
  `JMS_TRUST_FINGERPRINT` is ignored, even when it does not match.
- `TZ`: read from the host, not defined by jms. When it names a zone present
  in the host's `/usr/share/zoneinfo`, it is the first source `launch` uses
  for the zone it passes into the container; otherwise `/etc/localtime` and
  `/etc/timezone` are tried in that order. Setting it changes only which zone
  is inherited — it is never passed through unexamined, and a manifest
  `[env] TZ` overrides it.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | operational failure: the runtime, a build, host I/O, or an invalid manifest or trust store |
| 2 | usage error: bad flags or operands, including a workdir that does not exist or a missing project definition where a command needs one |
| 3 | trust error: consent declined, prompting unavailable, or a fingerprint mismatch |
| 130 | interrupted (Ctrl-C) at any point before `launch` hands over to the runtime |
| 129, 143 | terminated by SIGHUP or SIGTERM; jms forwards the signal to the running runtime command and waits for it first |

When jms itself exits 1, 2 or 3, the last line it writes to stderr starts
with `error: ` (`jms <command>: error: ` for a flag error caught by the
argument parser). An interrupt prints nothing.

**`launch` passes the container's exit status through.** Once its checks
pass, `launch` replaces itself with the runtime's `run` command, so from
then on the exit status is whatever the runtime returns. That is usually
the launched program's own status, which can be any number, including 1, 2,
3 or 130. A program that exits 3 is indistinguishable by status alone from
a jms trust refusal. The runtime also uses codes of its own: Podman exits
125 when `podman run` itself fails, 126 when the entry program cannot be
executed, and 127 when it is not found. To tell jms's refusals apart in a
script:

- Look for the `error: ` line. It is only a strong signal: a program in
  the container may print a line that looks the same.
- Or split the gates off: `jms build` runs the same trust and build steps
  without starting a container, and `jms inspect` reports the grants
  `launch` would need. After those succeed, a nonzero `launch` status
  almost always comes from the container.
