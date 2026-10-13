# 2.1.0 macOS qualification

Status: open. This is the macOS half of qualifying 2.1.0; the
[macOS qualification guide](macos-qualification-guide.md) and the
[release checklist](release-checklist.md) stay authoritative. 2.1 changes
how jms drives the runtime (child supervision with timeouts, forwarded
SIGTERM/SIGHUP, build labels, a build lock), so a full macOS run is
required before the release commit.

## On the Mac

Use an Apple Silicon Mac at a real terminal (Terminal.app, or ssh with a
tty). Tier B asks a credential question; answer **y**.

```sh
cd ~/git/jmscontainers
git fetch origin
git switch main && git merge --ff-only origin/main
git merge --no-edit origin/qual/v2.1.0-macos
scripts/qualify-macos.sh
```

The script stops early if it is not on Apple Silicon or not on a
terminal. It writes everything to `~/jms-qual-<timestamp>/` and prints a
summary, which it also saves as `SUMMARY.txt` there.

| Check | What it proves |
| --- | --- |
| clean worktree | the run is of a committed candidate |
| `make test` | unit tests and shellcheck pass on macOS |
| integration all | tiers A and B, the shared-base identity collision case and the leak sweep pass on apple/container |
| cold start (OPS-10) | jms starts a stopped runtime without a hidden first-run prompt, inside the new 180 s bound |
| build labels | `jms.version` and `jms.commit` reach a real image |
| image prune exists | whether `container image prune` exists (docs/macos.md marks it unverified) |
| proxy forwarded | whether `HTTPS_PROXY` reaches the container (docs/macos.md marks it unverified) |
| SIGTERM forwarding | killing `jms build` stops the runtime's build (exit 143, no `container build` left) |

A `FAIL` blocks the release. An `OBSERVED` line is a fact for the docs,
not a gate.

## Terminal checks (by hand, 80-column window)

1. **Consent layout.** In a fresh project (`mkdir /tmp/jp && cd /tmp/jp &&
   jms init`), run `jms launch`. The "defines a custom container" header
   comes first, escalations carry `!`, and the notes wrap cleanly. Answer
   n to both questions.
2. **`clean` prompt.** After a launch there, `jms clean --images`:
   answer n (exit 1, nothing removed), run it again and answer y; then
   `jms clean --yes` asks nothing.
3. **zsh completion.** `make install`, add the `fpath` lines from the
   README's "Shell completion" section to `~/.zshrc`, open a new shell, and
   try `jms <TAB>`, `jms launch -w <TAB>`, `jms launch -- <TAB>` and
   `jms trust <TAB>`.

## Send back

- `SUMMARY.txt`;
- the `container --version` line and the last lines of `integration.log`;
- one line per terminal check: OK, or what looked wrong.

The release commit then records this in the 2.1.0 qualification section,
sets `ContainerBackend._version_qualified` to the tested apple/container
version when it is newer than the current value, and turns the
"unverified" lines in docs/macos.md into what this run observed.
