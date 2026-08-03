# GitHub presence review

An outside read of `github.com/jonskelton/jmscontainers` as a drive-by open
source developer sees it — repo page first, README second, code third —
ranked by return on effort. Reviewed 2026-08-03 against `main` at `9b24c4a`.

**Status (2026-08-03):** steps 1–4 of the suggested order are done — v1.1.0
tagged and released, description and topics corrected, badges added, license
collapsed to MIT (see item 6), Discussions and private vulnerability
reporting enabled. Steps 5–9 remain open.

The engineering here is unusually strong: a real threat model, a written
trust boundary, per-platform security prose, adversarial tests, an
integration tier system, and a CHANGELOG that reads like someone who has
shipped before. Almost none of that is visible from the repo page. Every
item below is about closing that gap, not about the code.

Effort is calibrated as: **XS** ≈ minutes, **S** ≈ under an hour, **M** ≈ an
afternoon, **L** ≈ multi-day.

---

## Tier 1 — do these first (hours of work, disproportionate payoff)

### 1. Ship 1.1.0 as a tag and a GitHub release — **XS**

`CHANGELOG.md` documents 1.1.0 as released today. `git tag` has only
`v1.0.0`, and the repo page's sidebar still shows **v1.0.0** as the latest
release. The single most valuable artifact you have — "this thing runs on
Linux now" — is invisible to anyone who does not read the changelog file.

The release page is also the only durable, linkable, citable version
surface: it is what people paste into issues, what packagers consume, and
what "is this maintained?" resolves to in about two seconds.

```sh
git tag -a v1.1.0 -m "v1.1.0"
git push origin v1.1.0
gh release create v1.1.0 --title v1.1.0 --notes-file <(...1.1.0 changelog section...)
```

Your v1.0.0 release notes are excellent — genuinely better than most
projects' — so this is purely a matter of doing it again.

### 2. Fix the stale repo description and topics — **XS**

Current description:

> Throwaway containers for running claude-code, codex, and opencode in yolo
> mode — **without handing them your Mac**

As of 1.1.0 that is wrong, and wrong in the expensive direction: it tells
every Linux developer who lands here that the project is not for them.
Topics have the same problem — `macos` and `apple-container` are there,
`linux` and `podman` are not.

Suggested description:

> Throwaway containers for running claude-code, codex, and opencode in yolo
> mode — without handing them your machine. macOS (apple/container) and
> Linux (rootless Podman).

Topics to add: `linux`, `podman`, `rootless-containers`, `devcontainers`,
`agent-sandbox`, `cli`. The `devcontainers` topic in particular is where
people browsing for exactly this are already looking, and your README
already positions against Dev Containers.

This is the highest impact-per-keystroke item in the document. Repo
description and topics feed GitHub search, the topic pages, and the
"related repositories" rail.

### 3. Add a terminal demo to the top of the README — **S**

The README's pitch is `jms launch` → "you're in." That is a *visual* claim
made entirely in prose. For a CLI tool, a 15–25 second recording placed
immediately under the first paragraph is the single largest conversion
lever on GitHub — it answers "what is the experience" before anyone decides
whether to read 378 lines.

Use [`asciinema`](https://asciinema.org) + [`agg`](https://github.com/asciinema/agg)
to produce a GIF, or `svg-term` for a crisp scalable SVG that renders in
dark mode. Script it tightly:

```
$ cd ~/git/myproject
$ jms launch
  <trust prompt appears — capability summary, y/N>
  <prompt flips to isolation@container>
$ ls /work          # their project, right there
$ yolo-claude       # agent starts in full-permission mode
$ exit              # gone; nothing survives
```

That recording also does your security messaging for you: the trust prompt
appearing on screen is far more persuasive than a section titled "How trust
works."

### 4. Add a custom social preview image — **S**

`usesCustomOpenGraphImage: false`. Every link to this repo posted in Slack,
on X, in Discord, or on Hacker News currently renders GitHub's generic
auto-card. A project whose distribution channel is "someone shares the
link" pays for that on every share.

Settings → Social preview, 1280×640. Name, one line of positioning, the
three agent names. Half an hour in any design tool.

### 5. Add README badges — **XS**

No badges at all today. Three is the right number; more reads as noise.

```markdown
[![test](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml/badge.svg)](https://github.com/jonskelton/jmscontainers/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/jonskelton/jmscontainers)](https://github.com/jonskelton/jmscontainers/releases)
[![license](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue)](LICENSE)
```

The CI badge is the load-bearing one — it is the fastest available answer to
"is this maintained and does it work."

### 6. Resolve the license to something GitHub can detect — **XS, but a decision**

GitHub reports `"license": {"key": "other", "spdx_id": "NOASSERTION"}` and
the sidebar renders **Other**. The cause is that `LICENSE` is a pointer file
describing a dual license rather than a license text; GitHub's detector only
recognizes a single known text.

"Other" is a real friction point. Corporate users scanning for permissive
licenses filter on the detected value, not on file contents, and "Other"
routes to legal review.

Two honest options:

- **Keep MIT OR Apache-2.0** (the Rust-ecosystem convention). Accept the
  "Other" label; it is the known cost of dual licensing. Mitigate with the
  license badge above and an explicit SPDX line in the README.
- **Collapse to one license** — you have no install base (a 1.1.0 design
  premise), so this is cheap now and expensive later. Making `LICENSE` the
  verbatim MIT text gets you a detected license, a real sidebar badge, and
  the shortest possible path through anyone's compliance process.

Recommendation: collapse to MIT unless the Apache patent grant is
deliberate. If it is deliberate, keep the dual license and stop optimizing
this.

**Resolved:** collapsed to MIT. `LICENSE` is now the verbatim MIT text and
`LICENSE-MIT`/`LICENSE-APACHE` are gone; recorded in the changelog.

---

## Tier 2 — high value, an afternoon each

### 7. Restructure the README: pitch above, reference below — **M**

378 lines, and the second thing a reader meets is a dense paragraph
explaining why `uidmap`, `passt`, and `dbus-user-session` are only
*Recommends* of Debian's `podman` package. That paragraph is correct,
hard-won, and genuinely useful — to someone already installing. To someone
deciding whether to care, it reads as "this is going to be difficult."

The GitHub-native shape is: **hero → demo → install → five commands → one
security callout → links out.** Everything else moves to `docs/` and is
linked, not inlined.

Specifically, relocate:

- the Debian *Recommends* / `exec "$SHELL" -l` / `PATH` reasoning →
  `docs/install.md`
- "Known Linux limitations" (NFS, owner-based access, reserved image
  prefix, nested sandboxes) → `docs/platform-support.md`
- "Project image user ABI" → `docs/project-images.md`
- the full agent-state and shell-customization tables → `docs/`

That takes the README to roughly 120 lines without deleting a single
sentence of the content you worked hard to get right. Nothing is lost;
it is sequenced for a reader who has not yet decided to install.

Add a short table of contents after the badges — GitHub renders a built-in
outline widget now, but an explicit TOC still helps on mobile and in
mirrors.

### 8. Separate maintainer docs from user docs — **S**

`docs/` currently mixes two audiences with no signposting:

| User-facing | Maintainer/process |
|---|---|
| `cli.md` | `release-critical-issues.md` (503 lines, RC-001…RC-007 register) |
| `jmscontainer.toml.md` | `multi-runtime-implementation.md` (2445 lines) |
| | `macos-qualification-guide.md` |
| | `release-checklist.md` |
| | `standalone-image-user-abi-proposal.md` |

A newcomer clicking `docs/` sees a 2445-line implementation guide and a
release-blocker register and concludes the project is mid-surgery. Those
documents are *assets* — they demonstrate rigor — but they need a frame.

Move process docs to `docs/internal/` (or `docs/development/`) and add a
`docs/README.md` index that says, in two lines, which half is which. Keep
the working docs in-repo; that transparency is a genuine differentiator for
a security-sensitive tool. Just label it.

### 9. Turn "unqualified but allowed" prose into tracked issues — **S**

The repo has **zero issues, zero stars, zero forks**. The issue tracker is
the primary "is anyone home?" signal on GitHub, and an empty tracker on a
project with 500 lines of qualification records reads as abandoned rather
than as pristine.

You already have a roadmap — it is written as prose in the README and
SECURITY.md. Convert it:

- Qualify Fedora / Ubuntu on the Podman backend
- Qualify arm64 Linux
- Qualify SELinux-enforcing hosts
- Per-project agent auth profiles (SECURITY.md calls this future work)
- Homebrew tap / formula
- NFS home directory detection (or a documented decision not to)

Label the tractable ones `help wanted` and `good first issue` — the labels
already exist in the repo, unused. Newcomers filter GitHub globally by
those labels; an unused `good first issue` label is free discovery left on
the table.

This also gives you somewhere to point people, which is what an issue
tracker is actually for.

### 10. Issue templates that demand the right diagnostics — **S**

No issue or PR templates today. For a tool spanning two container runtimes,
two operating systems, and version-pinned backends, the first three replies
to any bug report are predictable: which platform, which runtime version,
what does `jms inspect` say.

Add `.github/ISSUE_TEMPLATE/bug_report.yml` with required fields for
platform (macOS/Linux), runtime and version, Python version, and a textarea
pre-labeled for `jms inspect` output. Add `config.yml` pointing security
reports at SECURITY.md so they never land in public issues — you ask for
this in CONTRIBUTING.md, but the template chooser is where it gets enforced.

A PR template is worth one file too: CONTRIBUTING.md already specifies what
a PR must explain (user-visible behavior, security implications, tests,
matching updates to `docs/cli.md` and `completions/jms.bash`). That is a
checklist. Make it one.

### 11. Enable Discussions and private vulnerability reporting — **XS**

Discussions is off. Your CONTRIBUTING.md has an explicit **Scope** section
rejecting compose/orchestration features and asking for proposals instead —
Discussions is where those proposals go, and it keeps the issue tracker
meaning "defects and committed work."

Private vulnerability reporting: SECURITY.md asks for private reports, so
turn on GitHub's native flow (Settings → Security → Private vulnerability
reporting). It adds a "Report a vulnerability" button, gives reporters a
credible channel without email, and costs one checkbox. Secret scanning and
push protection are already on — good, and rarer than it should be.

Consider enabling Dependabot security updates as well, though with no
package dependencies it is near-nil value today.

---

## Tier 3 — worth doing, aligned with the project's own security posture

### 12. Pin GitHub Actions by commit SHA — **S**

`test.yml` uses `actions/checkout@v7` and `actions/setup-python@v7`. Mutable
tags mean a compromised or retagged action executes in your CI.

For most projects this is a nitpick. For *this* project it is a
credibility item: the README's central argument is that a cloned repo's
build definition should not execute until a human approves an exact
SHA-256 fingerprint. Trusting a floating tag in your own CI is the same
mistake at a different layer, and a security-minded reader will notice.

```yaml
- uses: actions/checkout@<40-char-sha>  # v7.0.0
```

Dependabot already handles bumping SHA-pinned actions and keeps the version
comment current, so the maintenance cost is zero beyond the initial edit.

While in there: add [`zizmor`](https://github.com/zizmorcore/zizmor) or
`actionlint` as a CI step. Cheap, and on-brand.

### 13. Add a Python lint gate — **S**

`make test` runs `py_compile`, `unittest`, and `shellcheck` — shell is
linted, Python is not, and `bin/jms` is 1994 lines of it. Add `ruff check`
(and optionally `ruff format --check`) to the `test` target with a graceful
skip when ruff is absent, mirroring the existing shellcheck fallback.

This lowers review cost on inbound PRs more than it catches bugs: style
arguments in review are what burn contributor goodwill, and a linter ends
them before they start.

### 14. Automate release notes from CHANGELOG.md — **S**

Item 1 is manual today, which means it will be skipped again. A
tag-triggered workflow that extracts the matching CHANGELOG section and
calls `gh release create` makes shipping a release the same cost as pushing
a tag. Keep `permissions: contents: write` scoped to that one job.

### 15. Offer an install path that is not `git clone` — **M**

Today: clone, `make install`, which symlinks into the checkout. That is a
developer's install, and it means the tool disappears if the checkout moves.

`bin/jms` is a single self-contained Python file with no dependencies, which
makes packaging unusually easy. A Homebrew tap (`brew install
jonskelton/tap/jms`) fits the macOS-primary audience and is roughly an
afternoon, including the formula and a release workflow to bump it. Attach
the script plus a SHA-256 checksum to each GitHub release as the
platform-neutral path.

Explicitly do *not* add `curl … | sh`. For a tool that exists to argue about
what you should be willing to execute, it would be self-refuting — and
someone will say so in public.

---

## Deliberately not recommended

- **CODE_OF_CONDUCT.md** — GitHub's community-profile score wants it (you
  are at 71%). At zero contributors it is scoring, not community-building.
  Add it when a second contributor arrives; it takes two minutes then.
- **CODEOWNERS / FUNDING.yml** — single maintainer, no funding ask. Noise.
- **Splitting `bin/jms` into a package** — the single-file design is a
  feature for an auditable security tool. Auditability is the pitch; a
  reviewer can read one file. Do not let packaging convenience erode it.
- **Shrinking SECURITY.md** — at 136 lines it is longer than most projects'
  and better than nearly all of them. The per-platform boundary statement
  ("the Linux boundary is kernel isolation, not a VM") is exactly the kind
  of honesty that earns trust from the audience this tool needs. Leave it.

---

## Suggested order

1. Tag and release 1.1.0 (#1)
2. Description + topics (#2)
3. Badges (#5), license decision (#6)
4. Discussions + private vulnerability reporting (#11)
5. Record the demo (#3), social preview (#4)
6. README restructure (#7) and `docs/` split (#8)
7. Seed the roadmap issues (#9), issue/PR templates (#10)
8. SHA-pin actions (#12), ruff (#13), release automation (#14)
9. Homebrew tap (#15)

Items 1–4 are under an hour combined and address the largest gap here: a
project that is meaningfully more mature than its repo page admits.
