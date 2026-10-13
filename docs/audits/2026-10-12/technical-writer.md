# Technical writer audit — jmscontainers 2.0.1 (2026-10-12)

## Verdict

The reference docs are unusually accurate: every flag, subcommand, manifest
key, default and refusal list in `docs/cli.md`, `docs/jmscontainer.toml.md`
and `completions/jms.bash` matches `bin/jms` exactly, and every internal link
and anchor resolves. The drift is at the edges. One macOS troubleshooting
line and one error hint still describe behavior that was removed. The
`launch` stdout promise is false on macOS. The durable
`--fingerprint --auth` credential path is missing from the reference. And
`docs/` mixes the 6 user guides with 15 internal reviews and proposals.
**0 High, 6 Med, 7 Low, 2 Note.**

## Scope & method

- Read in full: `README.md`, `docs/README.md`, `docs/cli.md`,
  `docs/jmscontainer.toml.md`, `docs/linux.md`, `docs/macos.md`,
  `docs/project-images.md`, `docs/agent-state.md`, `SECURITY.md`,
  `CONTRIBUTING.md`, `examples/README.md` and the example manifests,
  `completions/jms.bash`, `Makefile`, and `CHANGELOG.md` 2.0.0–2.0.1 (later
  sections spot-checked). In `bin/jms`, read the parser (2696–2782), every
  `cmd_*`, manifest parsing, consent, launch plan, and both backends.
- Cross-checked each documented flag, key, default, path, exit code and
  refusal against the code, and the reverse: parser → docs and parser →
  completion.
- Ran a link/anchor checker over every tracked `*.md`. There were no broken
  targets or anchors; its one hit was a regex inside a code span, a false
  positive.
- Ran parse-only CLI probes with a scratch `HOME` and no runtime: `--help`
  for each subcommand, conflicting-flag errors, `trust` without a
  definition, `init`, `inspect`, and a mismatched `--fingerprint`.
- `make test`: 382 tests, OK.
- Not run: anything that needs a container runtime. The `--root` ownership
  claim (DOCS-07) is inferred from the argv, not observed.

## Findings

| ID | Severity | Title | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| DOCS-01 | Med | macOS troubleshooting cites a removed acceptance override | `docs/macos.md:51` "the runtime must match the qualified version (or be explicitly accepted)"; `CHANGELOG.md:299-302` "`JMS_RUNTIME_ACCEPT` is gone"; `bin/jms:308-321` has a floor only and no override | Say: "the runtime must be 1.2.2 or newer; a 2.x prints a warning". |
| DOCS-02 | Med | Missing-base hint gives an obsolete procedure | `bin/jms:49-51` "run `jms build` in the base directory first"; the docs say `jms build --base` (`README.md:33`, `docs/cli.md:107`); the wording is pinned by `tests/test_jms.py:3917-3921` | Change it to "run `jms build --base` first" and update the test. |
| DOCS-03 | Med | `launch` stdout promise is false on macOS cold start | `docs/cli.md:129-131` says progress goes to stderr, "leaving the launched program's stdout available for capture"; `bin/jms:326` `print("starting container runtime...")` goes to stdout; Podman deliberately uses stderr (`bin/jms:596-597`) | Print to stderr, or document the exception. |
| DOCS-04 | Med | Durable non-interactive credential grant is undocumented in the reference | `bin/jms:1722-1725` (`trust --fingerprint X --auth` records `auth=true` without asking); only `--help` mentions it (`bin/jms:2750`); `docs/cli.md:210-231` omits it, and `:295-297` calls the env pin "the only non-interactive path to a one-shot credential grant" | Add one sentence to `## trust`, with the same path-not-code warning. |
| DOCS-05 | Med | Reader-facing and internal docs are mixed, and the index is incomplete | `docs/` has 22 files: 6 user guides plus 15 reviews, proposals and records (e.g. `multi-runtime-implementation.md`, 2456 lines); `docs/github-presence-review.md` is not in `docs/README.md`; internal docs present removed behavior as current (`docs/macos-support-review.md:47`, `docs/multi-runtime-implementation.md:1216`, both `JMS_RUNTIME_ACCEPT`) | Move internal docs to `docs/internal/` (or `docs/records/`), index every file, and add a one-line "historical record" banner to closed reviews. |
| DOCS-06 | Med | README headline overstates the `/work` and `.git` protections | `README.md:10-13` "mounts your checkout read-write at `/work`… top-level `.git` is read-only"; `:92` "Only `/work`… survive". Code: a no-definition launch from a subdirectory mounts only that subdirectory with no `.git` bind (`bin/jms:2302`, `2335-2341`), and `preserve_host_path` moves `/work`. `docs/cli.md:81-86,167-170` and `SECURITY.md:75-77` document this; README does not | Add one clause: "launch from the checkout root; a subdirectory launch mounts only that directory and gets no `.git` protection". |
| DOCS-07 | Low | Linux "container root files aren't yours" ignores `--root` | `docs/linux.md:80-86`; under `--root`, Podman runs `--userns=host` with `0:0` (`bin/jms:558-560`, `tests/test_jms.py:3385`), and in a rootless user namespace that is the invoking user (inferred, not observed) | Scope the bullet to `sudo` in default mode and verify `--root` ownership on the qualified host. |
| DOCS-08 | Low | "What is refused is exactly" omits readiness refusals | `docs/cli.md:39-42` lists platform, uid 0 and remote service; the code also refuses non-rootless mode, versions below the floor, short ID maps and a missing graph driver (`bin/jms:592-655`), as `docs/linux.md:96-98` says | Change "exactly" to "at selection", or link to the linux.md list. |
| DOCS-09 | Low | Exit-code table is imprecise | `docs/cli.md:318` says 130 means "interrupted at a prompt", but `bin/jms:2798-2799` returns 130 for any Ctrl-C. `jms trust .` with no definition exits **1** (probe), although it is a usage-shaped error. A `launch` container exit of 1–3 is indistinguishable from jms's own codes (`docs/cli.md:314` mentions only 0) | Reword 130 as "interrupted (Ctrl-C)" and add a note that `launch` passes the container's exit status through. |
| DOCS-10 | Low | `inspect` output contract is undocumented | `docs/cli.md:202-206` names only `credential_root` and `credential_grant`; the output also has `workdir`, `root`, `spec`, `project_id`, `trust_fingerprint`, `trust_store`, `trust_source`, `build_run_grant` and `target_image`, and `credential_grant` takes `held`/`required` with a definition (`bin/jms:2544-2579`) | List the fields and their value sets, or state that the output is not a stable format. |
| DOCS-11 | Low | "bare `--trust`" and "pin without `--auth`" drop credential mounts only when no grant is recorded | `docs/jmscontainer.toml.md:65` and `docs/cli.md:299`; `bin/jms:1700` keeps them when the store records `auth=true`. `--trust` also silently overrides a mismatched `JMS_TRUST_FINGERPRINT` (`bin/jms:1686-1687`), which is undocumented | Add "…and no credential grant is recorded"; document the `--trust` precedence. |
| DOCS-12 | Low | Terminology drift between errors, `--help` and docs | Errors say "project spec" (`bin/jms:1026,1689,1695`) where the docs say "definition". `launch --help` calls the positional `name` beside `-n NAME` for the container name (probe output). `-w` help omits `JMS_PROJECT_ROOTS` (`bin/jms:2712`), although `resolve_operand` applies it to `-w` too (`bin/jms:882-909`) | Use "definition" in user-facing text, set `metavar="PATH"`, and use one help string for both operand forms. |
| DOCS-13 | Low | SECURITY's "argv pins only…" list is incomplete; `CLAUDE_CONFIG_DIR` injection is undocumented | `SECURITY.md:135-136` names only `--userns` and `label=disable`; the code also pins numeric `--user` and `--hostname container` (`bin/jms:556-565`) and sets `CLAUDE_CONFIG_DIR` whenever agent state is mounted (`bin/jms:2313-2314`), which no user doc mentions | Complete the list and add `CLAUDE_CONFIG_DIR` to `agent-state.md`. |
| DOCS-14 | Note | Completion gaps | Flag parity with the parser is exact, but there is no `--version`/`-h`, and no zsh completion although zsh is the macOS default shell (`Makefile` installs bash only) | Add `--version` at position 1; zsh completion is optional. |
| DOCS-15 | Note | Small reference nits | `docs/cli.md:58-60` "never touch the runtime" list omits `trust PATH` and its `--auth`/`--no-auth`/`--fingerprint` forms (`:235` covers them); `docs/jmscontainer.toml.md:244` and `README.md:101` are unwrapped long lines | Fix in passing. |

## Finding details

### DOCS-01 — removed override still advertised (Med)

`docs/macos.md` is the page a macOS user opens when the version check
fails, and its last sentence tells them a runtime can be "explicitly
accepted". That mechanism (`JMS_RUNTIME_ACCEPT`) was removed in 1.2.0 and
"setting it does nothing" (`CHANGELOG.md:302`). The rest of the page
(`:27-32`) already describes the floor-only policy correctly, so the fix is
one line.

### DOCS-02 — the hint names a procedure that no longer exists (Med)

A new user who skips `jms build --base` and builds a project gets
`MISSING_BASE_NOTE`: "run `jms build` in the base directory first". No
document defines a "base directory". Running `jms build` in the jms checkout
does happen to build the base, because the checkout has no `.jmscontainer/`,
but every doc teaches `jms build --base`. Because a unit test pins the stale
wording, a doc-only fix would break CI, so the test must change too.

### DOCS-03 — stdout is not clean on a macOS cold start (Med)

`docs/cli.md:129-131` promises that `launch` stdout belongs to the launched
program. Podman honors this on purpose (the comment at `bin/jms:596-597`
cites R6/RC-006). On macOS, `ContainerBackend.ensure_started()` prints
`starting container runtime...` to stdout the first time after boot. The
exception is recorded only in the internal
`docs/multi-runtime-implementation.md:1289-1291`, so a script capturing
`jms launch … -- cmd` output gets an extra line once per boot.

### DOCS-04 — a credential path missing from the reference (Med)

`jms trust PATH --fingerprint HEX64 --auth` records a durable credential
grant with no question asked. That is the strongest non-interactive grant
jms offers. The CLI reference describes `--fingerprint` as recording
"durable trust" and calls the env pin "the only non-interactive path to a
one-shot credential grant". That is technically true, but a reader would
conclude no durable non-interactive credential grant exists. Only `--help`
says otherwise. Security-relevant grant paths belong in the reference.

### DOCS-05 — internal docs crowd the user docs (Med)

Of the 22 files in `docs/`, 6 are user guides. The rest are dated reviews,
proposals, qualification projects and a 2456-line implementation record.
On GitHub's file listing they sort together alphabetically, so
`agent-state.md` sits beside `containerfile-stage-alias-proposal.md`.
`docs/README.md` separates them, but it misses `github-presence-review.md`,
and closed reviews present superseded behavior in the present tense with no
banner. A drive-by reader cannot tell which pages are current.

### DOCS-06 — README headline vs subdirectory launches (Med)

README's first two paragraphs promise a `/work` mount of "your checkout"
with a read-only `.git`. A bare `jms launch` from `repo/src` with no
definition mounts only `src/`, binds no `.git`, and lets the container create
a `.git` that host git would then use. Three other docs state this
(`docs/cli.md`, `docs/jmscontainer.toml.md:226-229`, `SECURITY.md:75-80`).
The README, which most users read and stop at, does not. One clause fixes
it.

## What works well

- **Flag parity is exact** across parser, `docs/cli.md` synopsis, and
  `completions/jms.bash`, for all six subcommands.
- **Manifest reference matches `parse_manifest` key for key**: allowed keys,
  types, defaults, the `name` regex, the reserved targets, the four absolute
  prefixes, the critical paths, the socket roots, and the credential path
  list and variables.
- **All internal links and anchors resolve**, including cross-file anchors
  such as `jmscontainer.toml.md#read-only-git`.
- **Error messages are actionable**: most say what to do next (`--pull` and
  socket refusals, `.git` writable mounts), and the conflicting-flag
  errors match the documented constraints exactly.
- **CHANGELOG entries are precise and greppable**, with qualification
  matrices and named breaking changes. The 2.0.1 entry matches
  `bin/jms:1630-1634`.
- A **vocabulary test** (`SupportVocabularyTests`) already guards one
  doc/code invariant.

## Top 3 recommendations

1. **Fix the three stale or false statements** in one commit: the macOS
   "explicitly accepted" line (DOCS-01), the missing-base hint and its test
   (DOCS-02), and the stdout leak (DOCS-03). Each is a one-line change.
2. **Document every credential-granting path in `docs/cli.md#trust`**:
   `--fingerprint --auth` (DOCS-04), plus the recorded-grant qualifier on
   `--trust` and the env pin (DOCS-11). Add a README clause on subdirectory
   launches (DOCS-06).
3. **Split `docs/` into user and internal trees**, index every file, banner
   closed reviews (DOCS-05), and extend the existing doc-sync tests to assert
   parser ↔ `cli.md` synopsis ↔ completion parity, so the parity that holds
   today stays enforced.
