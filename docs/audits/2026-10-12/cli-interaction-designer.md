# CLI interaction designer audit — jmscontainers 2.0.1 (2026-10-12)

## Verdict

**The consent prompt is honest and complete, but the recovery paths are weak.**
It lists every capability, refuses closed when there is no TTY, and keeps
stdout clean. The weak spots are around it: errors that block automation
don't say how to proceed, the hint shown when the base image is missing names
the wrong command, `clean` stops running containers without asking, and the
bash completion offers words the parser then rejects.

## Scope & method

- Read `bin/jms` (parser 2700–2803, consent 1600–1860, `cmd_*` 2366–2700),
  `docs/cli.md`, `completions/jms.bash`, `Makefile` install targets.
- Ran `bin/jms --help` for every subcommand plus ~35 deliberate error cases
  with `HOME` pointed at a scratch dir and a fake checkout (`mkdir .git`).
- Drove the interactive approval under a pseudo-TTY (`script -qec`) with a
  manifest that sets env, a read-write mount, a `~/.ssh` mount,
  `git_writable` and `preserve_host_path`.
- Called `_jms_completion` directly under bash-completion for 10 command lines.
- I launched no containers. One `launch --trust` case reached `podman build`,
  which failed on a missing base and left no image. `make test` not run.
  Paths below are shortened to `$S`.

## Findings

| ID | Severity | Title | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| UX-01 | **Med** | The no-TTY trust refusal gives no next step | `bin/jms:1728`, `:1749`; `jms launch </dev/null` → `error: project trust is required but prompting is unavailable` (rc 3) | Name the way out: `jms trust`, `--fingerprint <tf>`, `JMS_TRUST_FINGERPRINT`, `--trust` |
| UX-02 | **Med** | A fingerprint mismatch doesn't show the expected value or how to get it | `bin/jms:1689`, `:1695`; `jms trust . --fingerprint 0000` → `error: --fingerprint does not match this project spec` | Print the current fingerprint (or point to `jms inspect`) |
| UX-03 | **Med** | The missing-base hint names the wrong command | `bin/jms:49-51`: "run \`jms build\` in the base directory first"; observed after a failed project build | Say `jms build --base` (works from any directory) |
| UX-04 | **Med** | `clean` stops and removes running containers with no confirmation | `bin/jms:2620-2690` (`stop_container` then forced remove); `--all --images` also deletes the shared base | Confirm on a TTY when running containers or the base are selected; add `-y/--yes` |
| UX-05 | **Med** | Positional `name` clashes with `-n/--name NAME` | `jms launch --help`: `[-n NAME] [name]`; "name: project root …"; error "a positional project name cannot be combined with --workdir" | Use metavar `PATH`, as `docs/cli.md` already does |
| UX-06 | **Med** | Bash completion offers words the parser rejects | see UX-06 detail; `jms build <TAB>` → dirs, then `jms build .` → `unrecognized arguments: .` | Complete per-position; stop after `--`; no flags after `-w`/`-b`/`-n` |
| UX-07 | **Med** | `--help` hides `--`, environment variables, exit codes and examples | `jms launch --help` never mentions `-- ARGS`; `JMS_TRUST_FINGERPRINT` and exit code 3 appear only in `docs/cli.md` | Add an argparse `epilog` per subcommand with 2–3 examples, env vars and exit codes |
| UX-08 | Low | The PATH operand is accepted inconsistently | `launch`/`inspect` take a positional or `-w`; `build`/`init`/`clean` only `-w`; `trust` only a positional (`jms trust -w .` → `unrecognized arguments: -w`) | Accept both forms on every workdir command |
| UX-09 | Low | Silent success on empty results | `jms trust list`, `jms clean`, `jms clean --dry-run --all` → no output, rc 0 | Print "no trust records" / "nothing to remove" |
| UX-10 | Low | `init --with-manifest` reports only the Containerfile, and no next step | `bin/jms:2612` prints only `created …/Containerfile` | Report every created file; suggest `jms launch` |
| UX-11 | Low | Consent block: the header comes after the list, and emphasis is uneven | Prompt order: capability list, then "`$S/proj` defines a custom container (trust fingerprint …)"; `SOCKET`/`HOST CREDENTIAL PATH` in caps but writable `.git` in lower case; `preserve_host_path` and `git_writable` repeated in prose | Header first; one marker (e.g. `!`) on every escalation beyond the default |
| UX-12 | Low | Prompts and notes are 150–300 character single lines | `CREDENTIAL_SCOPE_NOTE`, `credential_question()` (`bin/jms:1652-1662`) | Wrap at ~76 columns, or split note from question |
| UX-13 | Low | Exit codes are inconsistent for the same condition | "no project container definition found": rc 1 in `trust` (`:2520`), rc 2 in `clean` (`:2630`); `init` at `$HOME` → rc 1 | Use 2 for operand refusals, as `docs/cli.md` defines |
| UX-14 | Low | Subcommand typos show top-level usage and no suggestion | `jms launch --git-writeable` → `usage: jms [-h] [--version] {build,…}` | Report from the subparser (e.g. `parse_known_args` per subcommand) |
| UX-15 | Low | Error wording doesn't match the flag | `jms launch -b ''` → `error: binary must be nonempty …` (`:2235`); the flag is `--bin` | "--bin must be nonempty …" |
| UX-16 | Low | `init` notice goes to stdout | `bin/jms:2590` `print("notice: nested …")`; other `note:`/`warning:` lines use stderr | Send it to stderr |
| UX-17 | Low | Bash-only completion; macOS's default shell is zsh | `completions/` has only `jms.bash`; `Makefile:3` installs to `share/bash-completion` | Ship a zsh completion, or document `bashcompinit` |
| UX-18 | Low | A failed build error ends in an empty detail | `error: command failed: "podman build …" -- ""` (output was streamed, not captured) | Omit `-- ""` when nothing was captured |
| UX-19 | Note | `--trust` (bypass flag) vs `trust` (subcommand) | Same word for opposite effects; help text is clear ("one-shot … never grants credentials") | Consider `--trust-once` in a future major |

## Finding details

### UX-01 — The no-TTY trust refusal gives no next step

In CI, an agent harness or any piped call, the first `build`/`launch` prints
the capability list, then:

```text
error: project trust is required but prompting is unavailable
```

The tool has three non-interactive ways forward. None is named here, and none
is in `--help` (see UX-07). Append something like
`-- run 'jms trust' on a terminal, or pin it: jms trust PATH --fingerprint <tf>`.
The credential variant at `:1749` needs the same, pointing to
`JMS_TRUST_FINGERPRINT` with `--auth`.

### UX-02 — A fingerprint mismatch is a dead end

`--fingerprint does not match this project spec` doesn't show the value it
expected, and `JMS_TRUST_FINGERPRINT does not match …` has the same gap. The
user has to know to run `jms inspect`. Showing the 12-character prefix of
both values tells them whether they mistyped or the definition changed.

### UX-03 — The missing-base hint is wrong

`MISSING_BASE_NOTE` says to run `jms build` "in the base directory". The CLI
has `jms build --base` for this, and the README's update recipe uses it. "The
base directory" isn't a term defined anywhere a user would see. This note
appears exactly when a new user is stuck.

### UX-04 — `clean` destroys without asking

`clean` (project scope) stops any running container of the project. That
includes an agent session open in another terminal, and it happens without a
prompt. `clean --all --images` also removes `jmscontainers-base:latest`,
which forces a full base rebuild. `--dry-run` exists, but clig.dev convention
is to confirm on a TTY for broad or irreversible deletions, with `--yes` for
scripts. At minimum, confirm when a selected container is running or `--all`
is set.

### UX-05 — Two different things are both called `name`

`launch --help` renders `[-n NAME] [name]`. One is the container name, the
other is the project path. The parse error repeats the confusion ("positional
project name"). `docs/cli.md` already uses `PATH`; set `metavar="PATH"` and
rename the error.

### UX-06 — Completion offers words the parser rejects

Observed with `_jms_completion`:

| Line | Offered | Problem |
| --- | --- | --- |
| `jms build ` / `jms init ` | flags + `subdir` | No positional, so picking a dir errors |
| `jms launch -w ` | all flags + dirs | Expects a dir only |
| `jms launch -b ` | all jms flags | Expects a program name |
| `jms launch -- ` | jms flags + dirs | Everything after `--` goes to the container program |
| `jms trust revoke ` / `trust list ` | `list revoke prune --fingerprint …` | Re-offers verbs; `list` takes nothing |
| `jms --v` | nothing | `--version`/`--help` missing |

### UX-07 — `--help` is thinner than the CLI

`--help` has no examples, no exit-code table, no `JMS_TRUST_FINGERPRINT` /
`JMS_PROJECT_ROOTS`, and doesn't mention `launch -- ARGS`. That `--` tail is
the main way to pass agent arguments (`jms launch -b yolo-claude -- …`). All
of this exists in `docs/cli.md`, which an installed user may never open.
argparse `epilog` with `RawDescriptionHelpFormatter` covers it.

## What works well

- **Fail-closed consent.** Approval needs TTY stdin *and* stderr. EOF counts
  as No, the default is `[y/N]`, Ctrl-C exits 130, and declining exits 3 with
  a clear `project trust declined`.
- **The capability list is complete and literal.** It shows mount sources →
  targets with ro/rw, socket/FIFO wording that admits mount flags don't
  restrict them, credential paths flagged in caps, and `--git-writable` named
  separately from `run.git_writable`.
- **Clean stream separation.** Prompts, notes and build progress go to stderr,
  so `launch` stdout belongs to the container. jms emits no colour, so
  `NO_COLOR` and piping need no handling.
- **Terminal-safe output.** `quote()` and `SafeArgumentParser` escape hostile
  bytes in paths and argparse errors.
- **Good conflict errors.** `--pull` without `--base` explains why and gives
  the exact recipe. `--auth`/`--no-auth`, `--base -w` and `--all -w` are
  all rejected with exit code 2.
- **Typo suggestions at the top level.** `jms lanch` → "maybe you meant
  'launch'?" (Python 3.12+ argparse).

## Top 3 recommendations

1. **Make every refusal actionable** (UX-01, UX-02, UX-03). Each trust or
   build error should end with the exact command that gets past it.
2. **Confirm destructive `clean`** when it would stop running containers or
   delete the base image, with `-y/--yes` and the existing `--dry-run`
   (UX-04).
3. **Make help and completion match the parser.** Use the `PATH` metavar, add
   epilogs with examples, env vars and exit codes, and add position-aware
   completion that stops after `--` (UX-05, UX-06, UX-07).
