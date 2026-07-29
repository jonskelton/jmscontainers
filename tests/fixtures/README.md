# Runtime output fixtures

Captured Podman CLI output backing the multi-runtime qualification evidence
in `docs/multi-runtime-implementation.md` (MIR-006, MIR-007, MIR-008).

Provenance: Podman 5.4.2, rootless, Debian 13 (trixie), overlay storage
driver, captured 2026-07-29. Sanitized: the invoking username is replaced
with `user` and the hostname with `testhost`; JSON is re-serialized with
sorted keys and 2-space indentation, values otherwise verbatim.

| File | Command | Notes |
| --- | --- | --- |
| `podman-5.4.2-info.json` | `podman info --format json` | Healthy local rootless engine: `host.serviceIsRemote` false, `host.security.rootless` true, `host.idMappings` populated, `store.graphDriverName` present (MIR-008). |
| `podman-5.4.2-images.json` | `podman images --format json` | Raw 5.4.2 shape: uppercase `Id`, `Names` array, integer `Created`, RFC3339 `CreatedAt`, top-level `Labels`, `RepoTags` may be null (MIR-006). |
| `podman-5.4.2-ps.json` | `podman ps --all --format json` | One running container (labelled `jms.project=testpid`, bind mount) and one exited. Full 64-char `Id`; image labels inherit onto container `Labels`; `Mounts` lists target paths only — no sources (MIR-007). |

Still needed per the review gate: equivalent captures from the matrix
minimum, Ubuntu 24.04's Podman 4.9.x.
