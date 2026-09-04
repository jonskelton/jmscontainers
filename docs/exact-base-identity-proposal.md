# Proposal: Resolve shared-base freshness by exact image identity

Status: Accepted and implemented in code on 2026-08-26; the qualified Podman
image-inspect capture and final live release qualification remain pending.
Target: Next bugfix release after acceptance
Related changes: `9b55c6d` (Base staleness rebuild) and `d33c1a6`
(stage-alias exclusion)

## Summary

Replace the lossy name-normalization step in shared-base freshness decisions
with exact image-reference resolution through the selected container runtime.
Name normalization may continue to identify Containerfile spellings that are
possible references to the shared base, but it must not choose an image ID or
an image's labels.

For each candidate `FROM` reference, jms will ask the runtime which exact image
identity that reference currently resolves to. It will also resolve the
canonical local shared-base reference, `jmscontainers-base:latest`. A project
will carry and compare the existing `jms.base=<image-id>` label only when at
least one candidate source resolves to the same identity as the canonical
shared base. The existing project tag will likewise be resolved exactly when
its `jms.base` label is read.

This corrects a macOS-specific ambiguity observed with apple/container 1.2.2:
the local store can simultaneously contain an unqualified name and a
`docker.io/library/`-qualified name that normalize to the same string but
resolve to different images. The current implementation silently chooses one
according to image-ID sort order.

No command-line flag, environment variable, project configuration key, trust
fingerprint rule, or label name is added by this proposal.

## Review finding

The issue was found while reviewing the commits from the seven days ending
2026-08-26 and retesting macOS support at candidate commit `d33c1a6`.

The relevant host and runtime configuration was:

- macOS 26.5.2, build 25F84;
- Darwin 25.5.0, arm64;
- Python 3.14.7;
- ShellCheck 0.11.0;
- apple/container CLI 1.2.2 and API server 1.2.2;
- `JMS_RUNTIME_ACCEPT` was not used; and
- host time zone `PDT` (`America/Los_Angeles`).

The repository gate passed 251 unit tests, compilation, and shellcheck. Both
live integration tiers in [`scripts/integration.sh`](../scripts/integration.sh)
also passed. Those successes do not cover the identity collision described
below.

### Live store evidence

On the qualification host, this command:

```sh
container image list --format json
```

reported both of the following records at the same time:

| Image ID | `configuration.name` |
| --- | --- |
| `0f4a7d65b114e37b51330ecb2bbaf5fa7a5c76209ff58cc0e09472ac96d0760d` | `docker.io/library/jmscontainers-base:latest` |
| `cbded357f09dece0c053702e8a32a14b4f88e0a94958339aa6ae6ac07add421e` | `jmscontainers-base:latest` |

Exact runtime inspection confirmed that this was not duplicate presentation
of one identity:

```text
container image inspect jmscontainers-base:latest
    -> cbded357f09dece0c053702e8a32a14b4f88e0a94958339aa6ae6ac07add421e

container image inspect docker.io/library/jmscontainers-base:latest
    -> 0f4a7d65b114e37b51330ecb2bbaf5fa7a5c76209ff58cc0e09472ac96d0760d
```

The two names therefore have distinct runtime resolution even though jms
currently normalizes them to the same local name.

This store shape is consistent with the apple/container fixture notes in
[`tests/fixtures/README.md`](../tests/fixtures/README.md): pulled or manually
tagged names may be registry-qualified, while locally built names may remain
unqualified. Qualification is a property of a reference's presentation; it
is not proof that two references are aliases for one image identity.

## Current implementation

### Canonical names

[`bin/jms`](../bin/jms) defines:

```python
BASE_REPOSITORY = "jmscontainers-base"
BASE = BASE_REPOSITORY + ":latest"
```

`BASE` is the canonical reference created by `jms build --base`, used by the
example Containerfiles, and launched when no project definition is present.

### Backend normalization

`ContainerBackend.local_name()` strips the exact prefix
`docker.io/library/`. `PodmanBackend.local_name()` separately strips the
Podman-specific `localhost/` prefix. These functions were designed to map the
qualified names emitted by each runtime into jms's reserved local namespace.
They are appropriate for ownership and display comparisons where the
backend's emitted spelling is the relevant input.

They are not an image-reference resolver. In particular, stripping a prefix
does not establish that the runtime resolves the qualified and unqualified
references to the same object.

### Containerfile detection

`containerfile_uses_base()` in [`bin/jms`](../bin/jms) reads
`.jmscontainer/Containerfile`, joins the limited supported continuation
syntax, walks `FROM` instructions, and excludes references to aliases declared
by earlier `FROM ... AS` stages. For every remaining source it currently
calls `local_name(source)` and compares the result with `BASE_REPOSITORY` and
`BASE`.

As a result, both of these sources are classified as the shared base on
apple/container:

```dockerfile
FROM jmscontainers-base:latest
FROM docker.io/library/jmscontainers-base:latest
```

The classification is textual. It does not confirm that either exact source
resolves to the canonical local base image.

### Base and project selection

`base_and_stamp(tag)` obtains the normalized facts returned by
`image_facts()`. For every fact it normalizes all refs with `local_name()`.
When a normalized ref matches `BASE`, it assigns that fact's ID to `base_id`.
When a normalized ref matches the project tag, it reads that fact's
`jms.base` label into `stamp`.

Both backend `image_facts()` implementations deliberately sort facts by image
ID. Consequently, if distinct identities have refs that collapse to the same
normalized name, `base_and_stamp()` selects the lexicographically last ID.
That order is deterministic but has no relationship to exact runtime
reference resolution, recency, ancestry, or which image a build will use.

The same ambiguity exists on both sides of the comparison:

1. distinct base refs can select the wrong `base_id`; and
2. distinct qualified and unqualified project refs can select the wrong
   project's `jms.base` label.

### Build behavior

`build_project()` calls `containerfile_uses_base()` and, when it returns true,
calls `base_and_stamp(tag)`. An existing project image is rebuilt when its
recorded `jms.base` label differs from the selected base ID. A new or rebuilt
project is stamped with that selected ID.

The user-visible contract is documented in [`docs/cli.md`](cli.md), the root
[`README.md`](../README.md), and [`CHANGELOG.md`](../CHANGELOG.md): after
refreshing the shared base, a plain `jms build` or `jms launch` rebuilds a
base-derived project onto the current base.

The selection ambiguity means the label can describe an image other than the
one named by the project's `FROM` instruction, so the comparison cannot
reliably enforce that contract.

## Failure modes

### 1. Incorrect stamp for a qualified source

Given the observed store and this project definition:

```dockerfile
FROM docker.io/library/jmscontainers-base:latest
```

apple/container resolves the `FROM` source to `0f4a...`. The current
`base_and_stamp()` happens to select `cbded...` because that ID sorts later.
The built project can therefore be stamped with `jms.base=cbded...` even
though its exact source resolved to `0f4a...`.

A later invocation sees a matching stamp and can report the project image as
up to date although it was not built from the recorded identity.

### 2. Sort-dependent selection for an unqualified source

The observed IDs happen to put the exact unqualified image last. A later base
rebuild can produce any valid digest. If its ID sorts before the stale
qualified record, `base_and_stamp()` selects the stale qualified identity for
an ordinary `FROM jmscontainers-base:latest` project.

This can cause a false rebuild, stamp the rebuilt project with the stale ID,
and cause repeated rebuilds on subsequent invocations. The behavior changes
with digest ordering rather than runtime resolution.

### 3. False reuse

If a colliding project-image ref contributes a stamp that happens to equal
the incorrectly selected base ID, `build_project()` can reuse an exact project
tag whose actual label does not match the actual shared base. This is the most
consequential outcome because a plain `jms launch` can continue running stale
software after the documented base refresh recipe.

### 4. Missing-base rule violation

The implementation promises that a missing canonical local base does not
force an existing project rebuild. If `jmscontainers-base:latest` is absent
but a distinct `docker.io/library/jmscontainers-base:latest` record remains,
normalization can report a non-`None` base ID and incorrectly trigger a
rebuild.

### 5. Backend behavior depends on stale store history

A clean store with only one spelling does not expose the defect. A Mac that
has retained images from older builds, manual tags, pulls, or runtime naming
changes can expose it later without any project-definition change. This makes
the failure history-dependent and explains why the fake-backed unit suite and
the normal integration path remained green.

## Why existing tests do not catch it

`BuildTests.base_project()` in [`tests/test_jms.py`](../tests/test_jms.py)
creates at most one base record, keyed by `JMS.BASE`. The changed-base,
pre-stamp, absent-base, and first-build cases all inherit that single-record
shape.

`ContainerfileBaseDetectionTests.test_backend_qualified_base_names()` proves
only textual classification. It does not resolve the qualified source.

`test_apple_qualified_base_change_rebuilds_and_stamps()` uses an Apple backend
but still populates the fake store with only `JMS.BASE`; the
`docker.io/library/` spelling exists only in the Containerfile. It therefore
assumes the equivalence that needs to be tested.

The captured [`tests/fixtures/apple-container-1.2.2-images.json`](../tests/fixtures/apple-container-1.2.2-images.json)
pins one-ref-per-record and multi-tag behavior, but it does not contain two
different image IDs whose refs normalize to the same local name.

Finally, [`scripts/integration.sh`](../scripts/integration.sh) builds the
canonical shared base and projects that normally use its unqualified name. It
does not construct a divergent qualified/unqualified pair or rebuild a base
after a project image has been stamped.

## Goals

1. Select the identity and labels for an exact runtime reference without
   relying on normalized-name uniqueness.
2. Preserve automatic rebuilds for projects that actually resolve a direct
   `FROM` source to the current canonical shared base.
3. Treat a qualified lookalike that resolves to a different ID as an
   independent image, not as the shared base.
4. Preserve the existing behavior for earlier stage aliases, comments,
   continuations, `--platform`, and `ARG`-indirected sources.
5. Preserve the missing-base rule: an unavailable canonical base never forces
   an existing image to rebuild.
6. Preserve the `jms.base` label format as the full 64-character image ID.
7. Apply the exact-resolution rule to both Apple Container and Podman through
   the backend protocol rather than branching in shared command code.
8. Fail closed on malformed or ambiguous runtime inspection output.

## Non-goals

- General Containerfile parsing or `ARG` evaluation.
- Tracking freshness for arbitrary external base images.
- Inferring ancestry from OCI layers or configuration history.
- Removing old, qualified, or manually created image refs from a user's
  store.
- Changing cleanup ownership predicates or retention ordering.
- Adding a new `.jmscontainer/jmscontainer.toml` key.
- Making base refresh and project build atomic across concurrent processes.
- Broadening the supported apple/container or Podman version ranges.

## Proposed semantics

### Exact reference resolution

Add one method to the runtime backend protocol:

```python
def resolve_image(self, ref: str) -> ResolvedImage | None:
    """Resolve ref exactly; return None only when that exact ref is absent."""
```

The shared normalized result should contain only the fields needed here:

```python
@dataclasses.dataclass(frozen=True)
class ResolvedImage:
    ident: str
    labels: dict[str, str]
```

`resolve_image()` must use the runtime's reference resolver, not scan and
normalize the global image list. It must distinguish three outcomes:

- the exact ref resolves: return its validated full ID and normalized labels;
- the exact ref is absent: return `None`; and
- inspection fails or returns malformed/ambiguous output: abort with the
  runtime diagnostic.

The method name deliberately says `resolve`, not `inspect`: shared code relies
on the semantic result, while command spelling and JSON shape remain backend
details.

### Backend commands

For apple/container 1.2.2, the implementation should use:

```sh
container image inspect <ref>
```

This is already the command used by `ContainerBackend.image_exists()`, but
the current method discards successful output. A new fixture must capture the
successful JSON shape before its parser is accepted. Validation should reuse
the existing Apple image-ID, descriptor-digest, and label normalization rules
where the schemas overlap.

For Podman, use its exact image-inspection command and capture the qualified
Podman 5.4.2 JSON before implementing the parser. The existing
`podman-5.4.2-inspect.json` fixture is for a container, not an image, and must
not be repurposed. Podman absence classification must remain equivalent to
the current `podman image exists` behavior.

`image_exists()` can delegate to `resolve_image()` where that does not lose an
existing diagnostic contract. Otherwise it may remain separate. The
base-staleness path should not perform both an existence query and a resolving
query for the same project ref.

### Containerfile result

Replace the boolean-only helper with a helper that returns the ordered,
deduplicated exact source tokens that are candidate shared-base spellings:

```python
def containerfile_base_sources(spec: bytes) -> tuple[str, ...]:
    ...
```

Candidate discovery retains the current backend-specific spelling rule and
the ordered earlier-stage-alias exclusion. It does not claim that a candidate
is the shared base; it only decides which exact refs are worth resolving.

Returning all candidates matters for multi-stage files. A divergent qualified
lookalike in one stage must not hide a later stage that directly uses the
canonical base.

### Dependency decision

For a project build:

1. Resolve the canonical `BASE` exactly.
2. If it is absent, set the base dependency to `None`; do not force an
   existing project rebuild.
3. Obtain all candidate source tokens from the Containerfile.
4. Resolve each distinct candidate exactly. Reuse the canonical result when
   the source token is exactly `BASE`, avoiding a duplicate query.
5. The project depends on the shared base when at least one resolved candidate
   ID equals the canonical `BASE` ID.
6. A candidate that is absent or resolves to another ID is not evidence of a
   shared-base dependency. It remains the runtime's responsibility to resolve
   or reject that source if a build is otherwise required.

Thus, on the observed macOS store:

| Containerfile source | Exact source ID | Canonical ID | Shared dependency |
| --- | --- | --- | --- |
| `jmscontainers-base:latest` | `cbded...` | `cbded...` | yes |
| `docker.io/library/jmscontainers-base:latest` | `0f4a...` | `cbded...` | no |

If both spellings resolve to one ID on a clean store, either spelling counts
as a direct shared-base dependency. Equivalence is decided by the runtime's
identity result, not by the spelling alone.

### Exact project lookup

Resolve the computed project tag exactly and read `jms.base` only from that
result. Do not normalize every `image_facts()` ref while looking for the
project stamp.

The build decision becomes conceptually:

```python
base = resolve_shared_base_dependency(data["spec"])
project = resolve_image(tag)

if project is not None and not args.no_cache:
    if base is None or project.labels.get("jms.base") == base.ident:
        return tag, False
    print("base image changed; rebuilding " + quote(tag))
```

When a build is required, stamp `jms.base=base.ident` only when `base` is not
`None`, preserving the current label ABI.

### Qualified references that diverge

A `docker.io/library/jmscontainers-base:latest` ref that resolves to a
different identity is an independent image for freshness purposes, even
though its spelling is a candidate. Changes to that independent ref remain
under the existing fingerprint/`--no-cache` rule for external bases.

This is preferable to stamping the canonical ID: the canonical ID would make
a claim about ancestry that the runtime has disproved. It also avoids changing
or deleting user-managed refs merely because their normalized spelling enters
the reserved namespace.

### Concurrency

The current code obtains base and project data from one image-list result to
avoid comparing two list snapshots. That advantage is illusory when the
snapshot contains a normalized-name collision: it is internally consistent
but selects an unrelated fact.

Exact base and project inspection cannot make a concurrent base rebuild and
project build atomic. The accepted behavior remains eventual convergence:

- if the base changes after resolution but before the project build, the
  project is stamped with the earlier ID and the next invocation rebuilds it;
- if the runtime build consumes the newer base, the conservative old stamp
  can cause one extra rebuild, never false up-to-date reuse; and
- a process lock or transactional runtime snapshot remains out of scope.

The implementation should deduplicate identical resolution requests within
one `build_project()` call and document the remaining race explicitly.

## Compatibility and migration

The existing `jms.base` label remains a full image ID. Correctly stamped
project images continue to compare equal and are reused.

Images stamped incorrectly by the affected implementation behave as follows:

- a project whose exact source resolves to the canonical base rebuilds once
  when its incorrect stamp differs, then receives the correct ID;
- a project whose qualified source resolves to an independent image ignores
  the misleading old `jms.base` label because it no longer has a verified
  shared-base dependency; and
- an image with no `jms.base` label retains the existing one-time rebuild rule
  when its exact source is verified as the canonical base.

The project trust fingerprint does not change. It continues to cover the
bytes under `.jmscontainer/`, including the Containerfile source spelling.

No migration of `~/.config/jms/trust.json`, no manifest schema bump, and no
image-store cleanup are required.

## Implementation outline

1. Introduce the normalized `ResolvedImage` type in [`bin/jms`](../bin/jms).
2. Add `resolve_image(ref)` to `ContainerBackend` and `PodmanBackend`, with a
   module-level forwarding function beside `image_exists()` and
   `image_facts()`.
3. Capture successful and absent image-inspection fixtures for
   apple/container 1.2.2 and Podman 5.4.2; document provenance in
   [`tests/fixtures/README.md`](../tests/fixtures/README.md).
4. Refactor `containerfile_uses_base()` into
   `containerfile_base_sources()` while preserving the accepted ordered-alias
   behavior from [`docs/containerfile-stage-alias-proposal.md`](containerfile-stage-alias-proposal.md).
5. Add a shared helper that resolves the canonical base and candidate sources
   and returns the verified shared-base identity or `None`.
6. Replace `base_and_stamp()` with exact canonical, source, and project
   resolution. No staleness decision may scan normalized refs for an ID or
   labels.
7. Update `build_project()` to reuse the exact project resolution rather than
   invoke a second existence query.
8. Update the CLI documentation and changelog to define qualified-reference
   behavior by resolved identity.
9. Run the complete unit and live qualification matrix.

## Test plan

### Backend resolution conformance

For both backends, add tests proving:

- an exact present ref returns its validated full ID and labels;
- two exact refs that point to one identity return the same ID;
- two refs whose names normalize alike but point to different identities
  return their distinct IDs;
- absence returns `None` only for the runtime's documented not-found result;
- non-absence failures abort with terminal-safe diagnostics;
- malformed top-level shape, ID, descriptor digest, and labels abort; and
- no successful ambiguity is resolved by record order.

### Containerfile source extraction

Retain every case in `ContainerfileBaseDetectionTests` and change assertions
from booleans to exact ordered source tuples. Add multi-stage cases containing
both a divergent qualified candidate and a direct canonical source. Earlier
stage aliases must never appear in the result.

### Build-level collision matrix

Extend `BuildTests` under both fake backends with at least:

| Store and Containerfile shape | Expected result |
| --- | --- |
| exact canonical base and matching project stamp | reuse |
| exact canonical base changed | rebuild and restamp exact canonical ID |
| canonical and qualified refs share one ID | either source is tracked |
| canonical and qualified refs have different IDs; unqualified `FROM` | track canonical ID |
| same divergent store; qualified `FROM` | treat as independent; do not stamp canonical ID |
| divergent IDs arranged in both lexical orders | identical decisions |
| exact and qualified project tags collide | read labels from exact project tag only |
| canonical base absent, qualified lookalike present | reuse existing project |
| pre-fix incorrect label on verified canonical dependency | rebuild once |
| pre-fix misleading label on independent qualified dependency | ignore label and reuse |
| one divergent candidate followed by a canonical candidate | track canonical dependency |

The lexical-order cases are required because they directly prevent regression
to the current last-assignment behavior.

### Live macOS regression

Run a dedicated apple/container 1.2.2 qualification case with two refs that
normalize to the shared-base spelling but resolve to different IDs. The test
must prove, through user-visible `jms build` behavior and image labels, that:

1. an unqualified project records the exact canonical base ID;
2. a qualified project resolving to the other ID is not stamped with the
   canonical ID;
3. changing digest lexical order cannot change either decision; and
4. cleanup removes only harness-owned refs and restores any pre-existing
   qualification-host refs exactly.

Because constructing this state can overwrite an existing qualified ref, the
harness must either use a clean qualification account or save and restore the
pre-test ref graph by exact ID. It must never delete an unrecorded user ref.

Then run the complete procedure in
[`docs/macos-qualification-guide.md`](macos-qualification-guide.md):

- `make test`;
- both live integration tiers with a tty and transcript;
- leak sweep;
- any manual cleanup-race procedure required by the release checklist; and
- the clean-account Homebrew walkthrough through `jms build --base`.

The backend protocol changes for both runtimes, so the complete Podman unit
suite remains required. A live Debian qualification is required if the chosen
Podman inspect command or parsing behavior changes its qualified runtime
interaction surface under the release checklist.

## Documentation and release impact

When implemented:

- move this document's status to Accepted and implemented with the commit and
  release target;
- add a changelog entry describing the macOS collision fix;
- update [`docs/cli.md`](cli.md) to state that a qualified candidate counts as
  the shared base only when the runtime resolves it to the canonical identity;
- verify the root [`README.md`](../README.md) update recipe remains accurate;
- update [`tests/fixtures/README.md`](../tests/fixtures/README.md) with image
  inspect capture provenance; and
- record new macOS qualification evidence at the final runtime-affecting
  candidate commit.

No user-facing config documentation changes are needed because
`.jmscontainer/jmscontainer.toml`, environment variables, and CLI flags remain
unchanged.

## Risks and constraints

### Inspection is a security- and correctness-relevant parser

Image IDs and `jms.base` labels control whether a networked project build is
skipped. Both backend parsers must therefore validate the exact captured
runtime shape and fail closed. They must not accept a multi-record result and
arbitrarily choose the first or last item.

### Do not reuse `local_name()` as identity proof

`local_name()` remains useful elsewhere, particularly for normalizing runtime
output used by cleanup and reserved-namespace ownership. This proposal does
not remove it. The implementation constraint is narrower: no freshness code
may turn a normalized name match directly into an image ID or label map.

### Do not mutate collisions automatically

jms must not resolve this ambiguity by deleting or retagging either image.
Both refs may be intentional user state, and cleanup ownership requires more
than a reserved-looking name. Exact inspection makes mutation unnecessary.

### Preserve conservative absence behavior

An existing project remains usable when the canonical local base is absent.
A qualified lookalike must not defeat this rule. Conversely, a malformed or
failed inspection is not absence and must abort rather than silently reuse.

### Avoid a partial cross-backend protocol

The new resolver belongs on both backend classes, even though the reported
collision is macOS-specific. Shared `build_project()` code must not execute
`container` or `podman` commands directly, consistent with
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Alternatives considered

### Prefer exact names, then fall back to normalized names

This would select the correct unqualified base in the observed store, but it
would still classify a divergent qualified `FROM` as the canonical base and
could stamp an identity the build did not use. It fixes ordering, not the
underlying false equivalence.

### Fail whenever normalized names collide

Failing closed is safer than arbitrary selection, but the observed collision
can arise from legitimate store history. Refusing all project builds until a
user manually removes one ref would turn an internal ambiguity into a macOS
availability failure. Exact runtime resolution can decide correctly without
destroying state.

### Choose the newest image

`creationDate` is OCI configuration creation time, not local tag or build
time, as documented by the Apple fixture capture. It can be inherited from a
parent and cannot determine which ref the runtime resolves.

### Choose the lexicographically first or last image ID

Digest order is deterministic but semantically meaningless. This is the
current defect, not a resolution policy.

### Stop recognizing qualified candidates

This would avoid one collision class but discard the backend-specific naming
behavior introduced by `9b55c6d`. A qualified ref can genuinely resolve to
the canonical local identity. Exact resolution supports that case without
assuming it.

### Compare root filesystem ancestry

This was rejected by the original base-staleness design. It requires a wider
inspect surface, does not directly answer exact tag resolution, and cannot
reliably distinguish equivalent content from the intended shared-base
dependency.

### Change the `jms.base` label format

The existing full image ID is sufficient once the correct identity is
selected. A new reference label or versioned dependency encoding would add a
migration without addressing the selection bug.

## Acceptance criteria

The proposal is complete when all of the following are true:

1. No shared-base freshness decision obtains an ID or labels by choosing
   among normalized `image_facts()` refs.
2. Exact qualified and unqualified refs may resolve to different IDs without
   ambiguity, deletion, or ordering dependence.
3. A project receives `jms.base=<id>` only when an exact candidate `FROM`
   resolves to the canonical shared-base ID.
4. The exact project tag supplies the compared `jms.base` label.
5. A qualified lookalike alone does not defeat the missing-canonical-base
   reuse rule.
6. Existing correct labels remain compatible; affected images converge with
   at most one corrective rebuild when they truly depend on the shared base.
7. Fixture-backed conformance tests cover both runtimes and both lexical ID
   orders.
8. The full unit suite, shell lint, macOS live tiers, collision regression,
   cleanup verification, and required release qualification all pass at the
   final candidate commit.

## Decision

The accepted design uses exact runtime reference resolution as the authority
for shared-base identity, retains name normalization only for candidate
discovery, preserves the existing `jms.base` label ABI, and requires the
collision-specific macOS qualification before release.
