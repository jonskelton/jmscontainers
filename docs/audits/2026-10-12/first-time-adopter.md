# First-time adopter audit — jmscontainers 2.0.1 (2026-10-12)

## Verdict

A competent newcomer on Debian 13 or an Apple Silicon Mac reaches a working
`jms launch -b yolo-claude` by copying two README blocks. Nothing on the
happy path blocks them. They will get stuck in three places: the first-launch
credential question, which does not say what "no" costs or how to undo it;
needing to log in again inside the container; and the examples, where a
missing cache directory gives an error that names a TOML field but not the
missing path. The README also never says that Docker is unsupported, which is
the runtime most newcomers already have.

## Scope & method

- Read `README.md` top to bottom as a newcomer would, then `docs/linux.md`,
  `docs/macos.md`, `docs/cli.md` (runtimes, trust), `docs/agent-state.md`,
  `docs/README.md`, `examples/README.md` and the example manifests,
  `Makefile`, `completions/jms.bash`, `Containerfile` (the `yolo-*` launchers).
- Ran `bin/jms --help`, `--version`, and `--help` for every subcommand.
- Made deliberate mistakes in throwaway directories (outputs below; scratch
  paths shortened to `$SCRATCH`): malformed TOML, an unknown manifest key, an
  empty `.jmscontainer/`, a nonexistent workdir, a non-checkout directory,
  an unknown `-b` program, conflicting flags, no `podman` on `PATH`, and a
  copied `go` example with a fresh `HOME`.
- Did one real launch on the Linux host (`jms launch -b true .` with the base
  already built, no TTY). Did not build the base from scratch, run the
  macOS path, run `make test`, or run the integration tiers. macOS findings
  come from reading the docs and code only and are **unverified at runtime**.

## Findings

| ID | Severity | Title | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| ADOPT-01 | Med | The first-launch credential question hides what "no" costs and how to undo it | `bin/jms:1828-1831`; `README.md:86-88`; the undo is only at `docs/cli.md:237-245` | Say "answer y to stay logged in between launches" in the prompt; print the undo command (`jms trust PATH --auth`) after recording a "no" |
| ADOPT-02 | Med | The README never says you must log in again inside the container | `README.md:76-88` says nothing about logging in; `docs/agent-state.md:5-19` says state is separate and you "log in once inside a container" | One sentence under **Use**: host `~/.claude`/`~/.codex` are not reused; log in on the first launch |
| ADOPT-03 | Med | A missing mount source is reported as an invalid field, without the path | `bin/jms:1576-1578` swallows `mount source does not exist: PATH` (`bin/jms:1362`); run output below | Keep the underlying message: `mounts[0].source: does not exist: "~/.cache/..."` |
| ADOPT-04 | Med | Docker is never ruled out | `README.md:23` says "one supported container runtime"; `grep -i docker README.md docs/linux.md docs/macos.md` finds only a Dockerfile code fence | State it in Install: "Podman (Linux) or apple/container (macOS); Docker is not supported" |
| ADOPT-05 | Low | Bare `jms launch` refuses a non-git directory, but `jms launch .` works there | `bin/jms:2400-2402`, `993-1004`; run: `error: the current directory is not inside a checkout -- cd into a project or pass a workdir` (rc 2), then `jms launch -b true .` gives rc 0 | Change the hint to name `jms launch .`; define "checkout" in the README |
| ADOPT-06 | Low | Time and disk cost of the first `jms build --base` are unstated | The built base is 3,212,160,406 bytes (`podman image inspect ... {{.Size}}`); `Containerfile:6-29` pulls Fedora plus npm agents; neither README nor platform guide gives a size or time | Add "first build downloads ~3 GB and takes several minutes" next to `jms build --base` |
| ADOPT-07 | Low | Jargon appears before it is defined | `README.md:16-19` (fingerprints, persistent agent credentials), `:67` (`isolation` user), `:94-97` (project definition, grants); help text: `build` = "realize an image from current local inputs" (`bin/jms --help`) | Add a short glossary line under **Use**; use plain words in `--help` |
| ADOPT-08 | Low | The examples README stops at `build` and orders the cache `mkdir` after it | `examples/README.md:6-11` (build only, `--trust` is one-shot), `:32-38` mkdir afterwards; no `jms launch` line | Put the mkdir first and end with `jms launch -w "$tmp/go"` |
| ADOPT-09 | Low | A manifest key a newcomer guesses gets no "did you mean" | `run.entrypoint` gives `error: invalid jmscontainer.toml fields: "run.entrypoint"`; the key is `run.entry` (`docs/jmscontainer.toml.md:43-44`); README `:155` says "a different entrypoint" | Name the allowed keys in the unknown-key error |
| ADOPT-10 | Low | The stale missing-base hint gives the wrong command | `bin/jms:49-51`: "run \`jms build\` in the base directory first"; the right command is `jms build --base` | Change the hint to `jms build --base` |
| ADOPT-11 | Low | `-b` gives no hint about the `yolo-*` launchers, and a typo surfaces a raw crun error | `jms launch --help`: "-b, --bin BIN  entry program to run…"; `jms launch -b yolo-nothing --no-auth .` prints `Error: crun: executable file \`yolo-nothing\` not found in $PATH` (rc 127) | List `yolo-claude`/`-codex`/`-opencode`/`-pi` in the `-b` help |
| ADOPT-12 | Low | Shell completion is bash-only and the install sections never mention it | `Makefile:3,11` links into `~/.local/share/bash-completion/completions`; `completions/` has only `jms.bash`; README mentions completion only in `make uninstall` (`:187`); macOS's default shell is zsh | Say "bash completion installed; zsh not provided" under Install |
| ADOPT-13 | Low | The macOS troubleshooting text contradicts the version policy | `docs/macos.md:27-31` (any version ≥ 1.2.2 accepted) vs `:51-52` ("must match the qualified version (or be explicitly accepted)") | Align `:51-52` with the version policy |
| ADOPT-14 | Note | The missing-podman hint is apt-specific even on other distros | `bin/jms:494-495`; run with no podman: `error: podman CLI not found; install the qualified package set: sudo apt install podman uidmap passt …` | Acceptable for the qualified target; maybe add "(Debian)" |
| ADOPT-15 | Note | `--help` never says "AI agent" | `jms --help`: "Build and run trust-gated development containers." | Add one line naming the agents and a `jms launch -b yolo-claude` example in an epilog |

### Run outputs referenced above

```text
$ jms inspect -w $SCRATCH/badtoml      # [run
error: invalid jmscontainer.toml: "Expected ']' at the end of a table declaration (at line 1, column 5)"
$ jms inspect -w $SCRATCH/emptycf      # empty .jmscontainer/
error: project spec requires a regular Containerfile: "$SCRATCH/emptycf/.jmscontainer/Containerfile"
$ jms launch nosuchproject              # JMS_PROJECT_ROOTS unset
error: workdir does not exist: "nosuchproject"
$ HOME=$SCRATCH/fakehome jms launch -w $SCRATCH/goex   # copied examples/go
error: invalid jmscontainer.toml fields: "mounts[0].source", "mounts[1].source"
# after mkdir -p of both cache dirs: capability summary prints, then
error: project trust is required but prompting is unavailable   (rc 3)
$ time jms launch -b true .             # base already built, Linux
note: not mounting agent state (credentials and configuration): no recorded answer for "…" and no terminal to ask on; pass --auth to mount it for this launch
real 0m15.811s   rc=0
```

## Finding details

### ADOPT-01 — the credential question

On the first launch in a checkout with no definition, the newcomer sees:

```text
"<path>" has no project definition and no recorded credential answer.
note: the answer is remembered for this checkout path, not for its code -- any branch or pull request later checked out here gets it without asking; launch with --no-auth to review code you did not write
Mount persistent agent state -- credentials and configuration for claude, codex, opencode, and pi -- with read-write access? [y/N]
```

The default is No and the answer is remembered. A cautious newcomer presses
Enter, logs in to Claude, exits, and then has to log in again on every launch
with no idea why. Nothing tells them that `jms trust PATH --auth` flips the
answer; the only place that says so is `docs/cli.md:237-245`. The security
framing is right. The missing pieces are what "no" costs and how to change it.

### ADOPT-02 — logging in again

Existing Claude Code or Codex users expect their host login to carry over.
It doesn't: state lives under `~/.local/share/jmscontainers/agents/`, which
is deliberately separate (`docs/agent-state.md:11-19`). `yolo-claude` then
opens a login flow the README never warned about. Together with ADOPT-01,
this is the most likely "is it broken?" moment.

### ADOPT-03 — the missing-mount error

`examples/README.md:28-38` does say to create the cache directories first.
A newcomer who copies the `go`, `rust` or `data-science` example and skips
that step gets `invalid jmscontainer.toml fields: "mounts[0].source"`. That
reads like a syntax error in a file they never edited. The precise message
(`mount source does not exist: "<path>"`, `bin/jms:1362`) exists, but
`bin/jms:1577-1578` catches it and keeps only the field name.

### ADOPT-04 — Docker

The README names Podman and the macOS VM only in passing (`:14-15`). It never
says Docker or Docker Desktop is unsupported, and the Install section's
"one supported container runtime" leaves that open. A Docker user reads the
whole Install section before working out that they need a second container
engine.

## What works well

- The Python version gate is immediate and plain: `jms requires Python 3.11+` (`bin/jms:23-24`).
- A missing runtime gives an actionable install command, and it is checked before any prompt or store write.
- `jms launch` builds the base if it is missing (`bin/jms:1930-1932`), so skipping `jms build --base` is not fatal.
- Usage errors are crisp and use exit 2: conflicting `--auth`/`--no-auth`, unknown subcommand, nonexistent workdir.
- TOML parse errors carry line and column. `jms init` refuses to overwrite and scaffolds a commented, minimal Containerfile.
- Consent fails closed without a TTY, and the notice names `--auth` as the way forward.
- "Know these three things" (`README.md:90-105`) is a good, short risk summary.
- After the base exists, a launch takes about 16 s on Linux.

## Top 3 recommendations

1. **Fix the first-run login story** (ADOPT-01, ADOPT-02). Add one README
   sentence saying you log in once inside the container. Change the prompt to
   say "y keeps agents logged in between launches", and after a "no" print
   `jms trust PATH --auth` as the undo.
2. **Pass through the real mount error** (ADOPT-03) and reorder the examples
   README so the mkdir comes first and it ends with a `jms launch` (ADOPT-08).
3. **Make the Install section state the runtime boundary and cost** (ADOPT-04,
   ADOPT-06): Podman or apple/container, not Docker; the first base build is
   about 3 GB.
