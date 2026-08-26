# Proposal: Exclude earlier stage aliases from shared-base detection

Status: Accepted and implemented on 2026-08-26; not yet released.
Target: Next bugfix release after acceptance
Related change: `9b55c6d` (Base staleness rebuild)

## Summary

Teach `containerfile_uses_base()` to distinguish a shared-image reference from
a reference to an earlier named build stage. Process `FROM` instructions in
order, remember aliases declared with `AS`, and exclude a later `FROM` whose
source is an already-declared alias from shared-base detection.

This is a narrow correction to the existing textual detector. It does not
turn jms into a general Containerfile parser, resolve `ARG` values, or infer
the ancestry of arbitrary external images.

## Problem statement

The base-staleness feature added in `9b55c6d` calls
`containerfile_uses_base()` to decide whether a project image should record
and later compare the local `jmscontainers-base:latest` image ID. Before this
fix, the detector considered each `FROM` source in isolation and normalized it
through the selected backend's `local_name()` implementation.

A valid multi-stage Containerfile can use the shared base's repository name
as a stage alias:

```dockerfile
FROM fedora AS jmscontainers-base
RUN dnf -y install make

FROM jmscontainers-base
RUN make install
```

The second `FROM` refers to the preceding stage, not to the local shared
image. The old detector nevertheless returned true because it saw the token
`jmscontainers-base` and did not know that the name was declared by an earlier
`AS` clause.

`build_project()` consequently stamps the project image with the unrelated
local shared-base ID. When that shared image is refreshed, a later `jms build`
or `jms launch` treats the project image as stale and rebuilds it. That rebuild
may be expensive and may contact a registry even though the project's actual
base ancestry did not change.

This is a false-positive freshness decision. It does not cause jms to launch
the wrong existing image, but it violates the expectation that an unrelated
base refresh cannot force project work.

## Goals

1. Return false when every apparent shared-base reference is actually a
   reference to an earlier stage alias.
2. Continue returning true when any `FROM` instruction directly names the
   backend-specific local shared image.
3. Preserve the existing behavior for comments, line continuations,
   `--platform`, qualified image names, and `ARG`-indirected sources.
4. Keep the detector small, auditable, and independent of a container engine
   or third-party parser.

## Non-goals

- Fully parsing Dockerfile or Containerfile syntax.
- Resolving global or stage-local `ARG` values.
- Following external image ancestry.
- Detecting whether a stage that does not directly name the shared image was
  built from an equivalent image.
- Changing the `jms.base` label or staleness comparison.
- Rejecting malformed Containerfiles before the runtime sees them.

## Proposed behavior

Walk logical instructions in source order. Maintain a set of aliases declared
by completed, earlier `FROM` instructions.

For each `FROM` instruction:

1. Identify its source using the existing treatment of leading flags.
2. If the source exactly matches an alias already in the set, classify it as
   an earlier-stage reference and do not run shared-base detection on it.
3. Otherwise normalize the source with `local_name()` and compare it with
   `BASE_REPOSITORY` and `BASE`, as today. Return true on a match.
4. If the instruction has an `AS <alias>` clause, add that alias to the set
   only after classifying its source. This ordering ensures an alias cannot
   shadow the source within the instruction that declares it.

The direct shared-base use remains decisive even when the stage is later
referenced through an alias:

```dockerfile
FROM jmscontainers-base:latest AS build
FROM build
```

This must return true because the first instruction directly uses the shared
image. Conversely, the reported example must return false because neither
instruction directly uses it.

Alias lookup must happen before backend normalization. An alias is a
Containerfile-local identifier, so applying registry or local-store name
normalization to it could create a second false match.

## Implementation outline

Refactor the existing logical-line loop in `containerfile_uses_base()` rather
than introducing a new parser dependency. For each `FROM`, retain the source
token and inspect the remaining tokens for the grammar-defined `AS <alias>`
suffix. Record only a present, non-empty alias from a syntactically shaped
clause; leave final syntax validation to the runtime.

The helper should continue to return a single boolean. Returning ancestry or
parse metadata would broaden its contract without a current consumer.

## Test plan

Extend `ContainerfileBaseDetectionTests` with at least these cases:

| Containerfile shape | Expected |
| --- | --- |
| `FROM fedora AS jmscontainers-base` then `FROM jmscontainers-base` | false |
| `FROM fedora AS other` then `FROM jmscontainers-base` | true |
| `FROM jmscontainers-base:latest AS build` then `FROM build` | true |
| Alias declaration and reference split across supported continuations | false |
| Alias named `jmscontainers-base`, followed by `FROM jmscontainers-base:latest` | true |
| Alias declared only after an apparent base reference | true |

Add one `build_project()` regression test with an existing unlabelled project
image and a present shared image. For the reported multi-stage definition,
the image must be reused and no build command or `jms.base` stamp emitted.
That test pins the user-visible consequence rather than only the helper.

Run the full unit suite with `make test`. No live runtime qualification is
required because the change affects only local textual classification and
build scheduling, not generated runtime arguments.

## Risks and constraints

### Do not grow a partial parser casually

The current helper deliberately supports a small syntax surface. Adding
general comment stripping, escape-directive handling, heredoc awareness,
variable expansion, or arbitrary flag parsing in this fix would make it look
more authoritative without making it complete. That is a larger design and
test obligation. This proposal rejects bundling such work into the alias fix.

### Alias comparison must match runtime semantics

Changing case or normalizing aliases could disagree with an engine's stage
name rules. The safe default is exact token comparison: it fixes the reported
valid file without inventing equivalence rules. If cross-case aliases are to
be supported, acceptance should be based on both qualified runtimes and added
as an explicit compatibility rule.

### A false negative is more consequential than this false positive

The present defect causes unnecessary work. An over-broad exclusion could
hide a real shared-base dependency and leave a project on an old base. The
implementation must therefore exclude only references to aliases declared by
earlier `FROM` instructions, never future aliases, normalized lookalikes, or
an alias declared on the same instruction before its source is classified.

### Malformed input remains the runtime's responsibility

The detector should not reinterpret malformed `AS` clauses in ways that hide
a clear direct base reference. If alias extraction is uncertain, the
conservative freshness choice is to retain shared-base detection and let the
runtime reject the file if a build occurs.

## Documentation and release impact

The fix aligns behavior with the existing CLI documentation; no user workflow
changes. The implementation:

- records this document as Accepted and implemented;
- adds a changelog entry describing the eliminated false rebuild; and
- leaves the broader shared-base freshness documentation unchanged.

## Decisions

Accepted on 2026-08-26:

1. Use the narrow ordered-alias fix.
2. Use exact alias matching; do not case-fold or backend-normalize stage
   identifiers without runtime evidence that both supported engines do so
   identically.
3. Keep broader Containerfile parsing out of scope. Record additional parser
   limitations separately when backed by a concrete valid-file failure.
4. Require a build-level regression in addition to detector tests so the
   no-rebuild contract is protected directly.
