# Runtime output fixtures

Captured runtime CLI output backing the multi-runtime qualification
evidence in `docs/multi-runtime-implementation.md` (MIR-006, MIR-007,
MIR-008, MIR-025).

Sanitization (all fixtures): the invoking username is replaced with `user`
and the hostname with `testhost`; JSON is re-serialized with sorted keys and
2-space indentation, values otherwise verbatim.

## apple/container 1.2.0 (macOS capture)

Provenance: container CLI 1.2.0 (Homebrew), Apple Silicon (arm64),
macOS 26.5, captured 2026-07-29.

| File | Command | Notes |
| --- | --- | --- |
| `apple-container-1.2.0-images.json` | `container image list --format json` | Whole records filtered from live output; nothing inside a record is edited (MIR-025). Top-level `id` is the OCI index digest and equals `configuration.descriptor.digest` minus `sha256:`. One ref per record: the alias-tagged image appears as two records with the same `id`. Pulled/tagged names are registry-qualified (`docker.io/library/…`); built names are unqualified. |

Capture recipe (probe-built, so no private image data enters the fixture;
synthetic label values are `sha256` of `jms-fixture-project-root` /
`jms-fixture-project-tf`):

1. Build `jmscontainers-fixture-base:latest` from
   `FROM fedora:latest` + one `LABEL` line.
2. Build `jmscontainers-fixture-a87d9b9a:8155454e44ff` from
   `FROM jmscontainers-fixture-base:latest` + a `LABEL` line setting
   `jms.project` and `jms.fingerprint` to the synthetic values.
3. `container image tag` it as `jms-fixture-alias:latest` (stored
   registry-qualified by the runtime — genuine 1.2.0 behavior).
4. Capture `container image list --format json`; keep only the whole
   records for `docker.io/library/fedora:latest` and the three probe
   refs; re-serialize per the sanitization rule above.
5. Delete the probe images.

Note: both probe builds are label-only, so their `creationDate` is
inherited from the fedora parent's OCI config — evidence that
`creationDate` is config creation time, not local build time (MIR-025).

## Podman 5.4.2 (current-release capture)

Provenance: Podman 5.4.2, rootless, Debian 13 (trixie), amd64, overlay
storage driver. `podman-5.4.2-info.json` captured 2026-07-29; the images,
`ps`, and `inspect` fixtures recaptured 2026-07-30 per the MIR-044
provenance contract (every accepted normalizer variant present in a
captured record).

| File | Command | Notes |
| --- | --- | --- |
| `podman-5.4.2-info.json` | `podman info --format json` | Healthy local rootless engine: `host.serviceIsRemote` false, `host.security.rootless` true, `host.idMappings` populated, `store.graphDriverName` present (MIR-008). |
| `podman-5.4.2-images.json` | `podman images --format json` | Raw 5.4.2 shape: uppercase `Id`, `Names` array-or-null, integer `Created`, RFC3339 `CreatedAt`, top-level `Labels` map-or-null. Variants: named (`fedora`), multi-named jms-labelled (`jmsfix-labelled` `:latest` + `:alias`), unlabeled named (`"Labels": null`, MIR-053), and dangling (`"Names": null`, `"Labels": null`). |
| `podman-5.4.2-ps.json` | `podman ps --all --format json` | Three containers: running with the `jms.container=launch` override and a bind mount; exited with inherited image labels only (marker stays `image`); exited with no jms labels at all (marker absent). Full 64-char `Id`; `Mounts` lists target paths only — no sources (MIR-007). |
| `podman-5.4.2-inspect.json` | `podman inspect --type container --format json <running-id>` | Single-element array; `Mounts[]` carries string `Source` and `Destination` — the leak-sweep contract's source of truth (§9). |

**Engine-reality notes pinned by this capture:**

- A multi-tagged image appears as **one record per tag, each record
  byte-identical and carrying the full `Names` array** — 5.4.2 does not
  emit one record per identity. The normalizer therefore tolerates
  exactly-identical duplicate records for one `Id` and aborts on any
  disagreement (amends MIR-038's original duplicate-`Id`-aborts rule).
- Dangling images are spelled `"Names": null`; no `<none>` string appears
  anywhere in the 5.4.2 JSON output, so the `<none>`-name case stays a
  synthetic variant in test code.
- Re-verified during capture: a `--rm` container never appears in
  `podman ps --all` (§9 leak-sweep coverage note).

Capture recipe (probe-built; synthetic label values are `sha256` of
`jms-fixture-project-root` / `jms-fixture-project-tf`):

1. `podman import` a one-file tar as `jmsfix-unlabeled:latest` (imports
   carry no labels, pinning the `Labels: null` spelling).
2. `podman import` two different tars under the same
   `jmsfix-dangle:latest` tag; the first becomes the dangling record.
3. `podman build` `jmsfix-labelled:latest` from
   `FROM registry.fedoraproject.org/fedora:latest` + one `LABEL` line,
   passing `--label jms.project=… --label jms.fingerprint=…
   --label jms.container=image`; `podman tag` it as
   `jmsfix-labelled:alias`.
4. `podman run -d --name jmsfix-running --label jms.container=launch
   --mount type=bind,source=<work>,target=/work jmsfix-labelled:latest
   sleep 300`; `podman run --name jmsfix-exited jmsfix-labelled:latest
   true`; `podman run --name jmsfix-plain
   registry.fedoraproject.org/fedora:latest true`.
5. Run one `--rm` container and assert it is absent from
   `podman ps --all --format json`.
6. Capture the three commands above; keep the fedora and `jmsfix-*`
   records (whole records, nothing inside a record edited); re-serialize
   per the sanitization rule, with the bind-mount source rewritten to
   `/home/user/jms-fixture-work`.
7. Remove the probe containers and images (`podman rm --force`,
   `podman image rm`, `podman image prune --force`).

A Podman 4.9.3 (Ubuntu 24.04) capture set previously lived here as
pre-qualification for a possible Ubuntu promotion; it was deleted in the
2026-07-30 proposal slim (see the doc's Provenance note) and survives in
git history. Fixtures for that target are recaptured if and when it is
actually qualified.
