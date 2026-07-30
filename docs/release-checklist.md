# Release checklist

- Set and review `__version__` in `bin/jms`.
- Add a dated entry to [CHANGELOG.md](../CHANGELOG.md) describing user-visible
  changes; breaking changes bump the major version.
- Run `make test` (the CI matrix covers the supported Python floor and current
  on Ubuntu, plus macOS).
- Reconcile the docs with the behavior actually shipping: `README.md`,
  [SECURITY.md](../SECURITY.md), [docs/cli.md](cli.md),
  [docs/jmscontainer.toml.md](jmscontainer.toml.md), and
  `completions/jms.bash`. The SECURITY.md/README review of the per-platform
  boundary statement (ambient-configuration trust, escape consequences,
  weaker-than-VM wording, reserved namespace and concurrency limitations)
  is release-blocking (R8.4).
- Run `make integration` on a macOS host with the qualified apple/container
  release when the runtime interaction surface changed; keep the
  `ContainerBackend` version pin matching the newest release it passed
  against. The first macOS run of the multi-runtime release must also
  determine apple/container's delete-by-ref cascade behavior via the
  survivor-set acceptance run — a discovered cascade is a qualification
  failure to resolve before release, not a silently accepted behavior — and
  exercise the manual removal-race test (idempotent cleanup under a
  vanished-mid-removal resource).
- Run both integration tiers (`scripts/integration.sh all`) green on a real
  Debian 13 amd64 host: a fresh user created with `adduser` (which
  provisions the 65536-id subordinate ranges), non-1000 UID and non-1000
  primary GID, a fresh home on a local filesystem with no prior container
  state, running from a real ssh login session so `pam_systemd` provides
  `XDG_RUNTIME_DIR` and the user D-Bus session. The harness needs sudo for
  its nftables egress-denial rule. No nested or CI substitute counts.
- Perform the clean-host install walkthrough: a fresh Debian 13 VM plus a
  newly created user follows the README install instructions verbatim,
  recording date, Podman version, architecture, and outcome.
- Record in the release notes the tested Podman version, architecture
  (`uname -m`), and the remaining matrix dimensions: kernel, cgroup
  manager, OCI runtime, storage driver, network backend.
- Tag the release commit `vX.Y.Z` and push the tag with the release.

After a push that creates or first publishes the repository:

- Enable Private Vulnerability Reporting in the repository settings, so the
  reporting channel [SECURITY.md](../SECURITY.md) points at actually exists.
- Watch the first CI run on every matrix leg; a red first run is a release
  blocker, not a follow-up.
- Set the repository description and topics.
