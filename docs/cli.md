# jms CLI reference

```text
jms build   [-w|--workdir PATH] [--base] [--trust] [--no-auth]
            [--no-cache] [--pull]
jms launch  [-w|--workdir PATH | PATH] [--trust] [--auth|--no-auth]
            [--no-cache] [-r|--root] [-b|--bin PROGRAM]
            [-n|--name NAME] [-- ARGS...]
jms inspect [-w|--workdir PATH | PATH]
jms trust   [PATH] [--fingerprint HEX64] [--auth|--no-auth]
jms trust   list
jms trust   revoke PATH [--purge-images]
jms trust   prune
jms init    [-w|--workdir PATH] [--with-manifest]
jms clean   [-w|--workdir PATH | --all] [--images] [--dry-run]
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
positionally or as `--workdir`, never both. `build --base` and `clean --all`
cannot be combined with `--workdir`. `--pull` is valid only with `--base`.

## Runtimes

jms selects its container runtime from the platform, lazily on first use
and with no override switch: macOS selects **apple/container**, Linux
selects **local rootless Podman**. Selection is side-effect-free and
precedes every consent prompt or trust-store write, so a selection refusal
(exit 2) never leaves partial state. What is refused is exactly:
platforms other than Linux and macOS, uid 0 on Linux, and remote Podman
services (`host.serviceIsRemote`, checked at readiness). Any other local
rootless Linux configuration is unqualified but allowed, with no warning.

Qualification policy differs deliberately per runtime:

- **apple/container** is pinned to one exact qualified version (a
  single-channel Homebrew install); `JMS_RUNTIME_ACCEPT` can admit one
  newer version for one invocation.
- **Podman** has a minimum only (≥ 5.4, Debian 13's packaged version);
  anything at or above the floor is accepted silently, and
  `JMS_RUNTIME_ACCEPT` has no effect on this backend. Readiness validates
  `podman info`: local service, rootless mode, subordinate ID coverage of
  at least 65536 ids per map, and readable storage metadata.

Commands that never touch the runtime — `--version`, `inspect`, `init`,
`trust list`, `trust revoke` without `--purge-images`, `trust prune` —
work with no runtime installed, on unsupported platforms, and under uid 0.

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
base); `COPY`/`ADD` sources must live inside it. An image whose tag matches
the current trust fingerprint is reused; `--no-cache` forces a rebuild without
reusable layers. `--pull` refreshes `FROM` references and is valid only with
`--base`: project Containerfiles reference the local-only tag
`jmscontainers-base:latest`, which a pull-mode build would try to resolve
against a remote registry. After a successful project build, jms keeps the
newest two images per project and deletes older ones.

To refresh container software, run the update recipe:

```sh
jms build --base --pull --no-cache
```

A project image's tag derives from its definition fingerprint, so refreshing
the base does not rebuild existing project images by itself. Run
`jms build --no-cache` (or `jms launch --no-cache`) in a project to rebuild it
onto the refreshed base.

## launch

`launch` discovers the nearest definition, applies the consent gate, builds
(or reuses) the project image, and replaces itself with the runtime's
`run --rm` invocation.
Without a definition it launches the shared base. Arguments after `--` are
appended to the selected entry argv. `--root` runs as root instead of the
`isolation` user, which moves the agent-state and shell-config mount targets
from `/home/isolation` to `/root`. Manifest mount targets are never rewritten:
they are re-checked against the effective home, so a manifest mount aimed at
`/home/isolation/...` is rejected under `--root` rather than silently landing
somewhere else.

`--bin` becomes the runtime entrypoint verbatim. The base image ships
full-permission agent launchers — `yolo-claude`, `yolo-codex`, and
`yolo-opencode` — so `jms launch -b yolo-claude` starts directly
in an agent session with permission prompts disabled; extra agent arguments
go after `--`. An entrypoint bypasses the login-shell profile, and the
container exits when the entry program does.

Every launch also mounts `~/.local/share/jmscontainers/shell/` (created on
first use) read-only at `~/.config/jms-shell` in the container; the base
image sources `bashrc`/`zshrc` from it in interactive shells. This mount is
jms-controlled and identical for every container — it is not a project
capability and never appears in the consent summary. Its target is reserved:
a manifest mount cannot claim or shadow `~/.config/jms-shell`.

## inspect

`inspect` reports discovery, the trust fingerprint, and trust status without
prompting, writing, or contacting the runtime.

## trust

`jms trust PATH` interactively (re)approves a definition; with
`--fingerprint HEX64` it records durable trust non-interactively when the
value matches the current fingerprint. `list`, `revoke`, and `prune` are
reserved words in the `trust` grammar: a project directory literally named
`list` must be passed as an absolute path. During any interactive approval,
`--no-auth` suppresses the credential question and records the credential
grant as declined. Interactive approval requires TTY stdin and stderr; the
consent UI is written to stderr. EOF at a question is its default-No answer.

The boolean `--trust` flag on `build` and `launch` is the one deliberate
consent bypass: it grants build/run approval for that single invocation
without prompting and without persisting anything — the store is not
written, and the next unflagged invocation prompts as usual. It never
satisfies the credential grant: combined with `--auth` it still asks the
credential question on a TTY and fails closed without one. Use it for
throwaway experiments on definitions you just read; for automation, prefer
a durable `jms trust --fingerprint HEX64` grant or a per-invocation
`JMS_TRUST_FINGERPRINT` pin, both of which name the exact fingerprint they
approve.

`trust revoke --purge-images` commits and reports the revocation before it
contacts the runtime; if image deletion then fails, trust remains revoked.
Every other `trust` form is store-only and works without the runtime CLI.

The trust store is `~/.config/jmscontainers/store.json` (schema 2).

## init

`init` scaffolds `.jmscontainer/Containerfile` in the workdir, plus
`jmscontainer.toml` beside it with `--with-manifest`. It fails rather than
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

## Environment variables

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
  configuration) without prompting. The
  boolean `--trust` flag never grants credential access; combined with
  `--auth` it still asks the credential question on a TTY and fails closed
  without one.
- `JMS_RUNTIME_ACCEPT` (apple/container only): accept one exact `container`
  version newer than the newest runtime this jms release is qualified
  against, for one invocation, with a "not qualified" warning (e.g.
  `JMS_RUNTIME_ACCEPT=1.3.0`). Use it to keep working (including
  `jms clean`) after Homebrew upgrades `container` before a matching jms
  release ships. The Podman backend is min-only qualified and ignores this
  variable.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success (for `launch`, the container's own exit status, since jms `exec`s the runtime) |
| 1 | operational failure: the runtime, a build, host I/O, or an invalid manifest or trust store |
| 2 | usage error: bad flags or operands, including a workdir that does not exist |
| 3 | trust error: consent declined, prompting unavailable, or a fingerprint mismatch |
| 130 | interrupted at a prompt (Ctrl-C) |
