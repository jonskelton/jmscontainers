# Contributing

Thanks for helping make jmscontainers easier to audit and safer to use.

## Development checks

Run the test suite before opening a pull request:

```sh
make test
```

It runs the unit tests and shell lint against the fake backends, so it needs
no container runtime and no particular host: the apple/container and Podman
surfaces are both exercised by fakes. PR CI runs exactly that, on Ubuntu
(Python 3.11 and 3.14) and on macOS.

Real-runtime checks are opt-in and intentionally not part of PR CI. Run
`make integration` — or `scripts/integration.sh a|b|all` for one tier — on
either qualified host: a macOS host with the qualified apple/container
release, or a Debian 13 (amd64) host with rootless Podman. Tier A is the
fast one and asserts the launch contracts on the base image; tier B is
expensive and builds the example gallery, and assumes tier A's base image
already exists. `make integration` runs both. The Linux launch contracts and
the egress-denied FROM-resolution check need `sudo` for a harness-owned
nftables rule. Release-qualifying runs have further host requirements — see
the [release checklist](docs/release-checklist.md).

## Changes to trust-sensitive code

Treat project definitions as hostile until the user has granted trust. Keep
approval, fingerprinting, and runtime argv derived from the same validated
data. New CLI or manifest behavior needs adversarial tests, and changes to
`jmscontainer.toml` require updating its versioned reference. Changes to the
command grammar, flags, environment variables, or defaults belong in
[docs/cli.md](docs/cli.md) and `completions/jms.bash` in the same commit. Do
not add broad trust bypasses, implicit credential mounts, or build-time secret
channels.

## Scope

jmscontainers is not a compose/orchestration tool. Services, compose files,
multi-container networking, and declarative package/build DSLs require a new
proposal rather than a drive-by feature addition.

Every call into a container runtime goes through the backend protocol —
`ContainerBackend` for apple/container, `PodmanBackend` for rootless Podman.
Do not reach past it to a runtime CLI from shared code: behavior that is not
per-runtime belongs above the seam, and a new runtime-specific method belongs
on the protocol with both backends implementing it. Both backends are covered
by fakes in `make test`, and per-backend differences that users can observe
(mount grammar, version qualification, cleanup semantics) need tests
asserting the two agree wherever they are supposed to.

## Pull requests

Explain the user-visible behavior, security implications, and tests in the PR.
Keep commits and generated changes focused. Report security vulnerabilities
privately as described in [SECURITY.md](SECURITY.md), rather than opening a
public issue.
