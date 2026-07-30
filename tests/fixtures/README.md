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

Provenance: Podman 5.4.2, rootless, Debian 13 (trixie), overlay storage
driver, captured 2026-07-29.

| File | Command | Notes |
| --- | --- | --- |
| `podman-5.4.2-info.json` | `podman info --format json` | Healthy local rootless engine: `host.serviceIsRemote` false, `host.security.rootless` true, `host.idMappings` populated, `store.graphDriverName` present (MIR-008). |
| `podman-5.4.2-images.json` | `podman images --format json` | Raw 5.4.2 shape: uppercase `Id`, `Names` array, integer `Created`, RFC3339 `CreatedAt`, top-level `Labels`, `RepoTags` may be null (MIR-006). |
| `podman-5.4.2-ps.json` | `podman ps --all --format json` | One running container (labelled `jms.project=testpid`, bind mount) and one exited. Full 64-char `Id`; image labels inherit onto container `Labels`; `Mounts` lists target paths only — no sources (MIR-007). |

A Podman 4.9.3 (Ubuntu 24.04) capture set previously lived here as
pre-qualification for a possible Ubuntu promotion; it was deleted in the
2026-07-30 proposal slim (see the doc's Provenance note) and survives in
git history. Fixtures for that target are recaptured if and when it is
actually qualified.
