# Release checklist

- Set and review `__version__` in `bin/jms`.
- Add a dated entry to [CHANGELOG.md](../CHANGELOG.md) describing user-visible
  changes; breaking changes bump the major version.
- Run `make test` (the CI matrix covers the supported Python floor and current
  on Ubuntu, plus macOS).
- Reconcile the docs with the behavior actually shipping: `README.md`,
  [docs/cli.md](cli.md), [docs/jmscontainer.toml.md](jmscontainer.toml.md),
  and `completions/jms.bash`.
- Run `make integration` on a macOS host with the qualified apple/container
  release when the runtime interaction surface changed; keep `RUNTIME_MAX`
  matching the newest release it passed against.
- Tag the release commit `vX.Y.Z` and push the tag with the release.

After a push that creates or first publishes the repository:

- Enable Private Vulnerability Reporting in the repository settings, so the
  reporting channel [SECURITY.md](../SECURITY.md) points at actually exists.
- Watch the first CI run on every matrix leg; a red first run is a release
  blocker, not a follow-up.
- Set the repository description and topics.
