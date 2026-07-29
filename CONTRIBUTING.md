# Contributing

Thanks for helping make jmscontainers easier to audit and safer to use.

## Development checks

Run the test suite before opening a pull request:

```sh
make test
```

It runs the unit and fake-runtime tests without requiring macOS or
`apple/container`. PR CI runs exactly that, on Ubuntu (Python 3.11 and 3.14)
and on macOS. On a macOS host with the runtime installed, run
`make integration` as well; it builds the example gallery against the real
runtime and is intentionally not part of PR CI.

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
proposal rather than a drive-by feature addition. Keep runtime-specific calls
behind the existing CLI seam so an alternate backend remains possible later.

## Pull requests

Explain the user-visible behavior, security implications, and tests in the PR.
Keep commits and generated changes focused. Report security vulnerabilities
privately as described in [SECURITY.md](SECURITY.md), rather than opening a
public issue.
