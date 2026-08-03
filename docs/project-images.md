# Project image guide

A project opts into a custom image by committing
`.jmscontainer/Containerfile`. Start with:

```sh
jms init
```

The next `jms build` or `jms launch` displays the definition's capabilities
and asks for approval. Consent is bound to the SHA-256 fingerprint of every
file under `.jmscontainer/`; any byte change requires fresh approval.

## Discovery and build context

jms searches for the nearest `.jmscontainer/`, starting at the workdir and
walking upward to the enclosing VCS checkout root. It never selects a
definition above that root. Outside a checkout, it checks only the workdir.

The `.jmscontainer/` directory—not the full checkout—is the build context.
`COPY` and `ADD` sources must live inside it. Copy required inputs there or
fetch them in a `RUN` instruction. Never put credentials or other secrets in
the definition: build inputs and image layers are not secret channels.

Most definitions should use the shared base:

```Dockerfile
FROM jmscontainers-base:latest
USER root
RUN dnf -y install your-tool && dnf clean all
USER isolation
```

jms tags a project image from the project ID and definition fingerprint. It
keeps the newest two images for each project after successful builds.

## Runtime configuration

An optional `.jmscontainer/jmscontainer.toml` controls extra mounts,
environment variables, the launch entrypoint, and whether agent state is
mounted by default. It is still fingerprinted and included in the build
context. See the [complete schema](jmscontainer.toml.md).

jms always replaces an image's `ENTRYPOINT` and does not append its `CMD`.
Choose the entrypoint with `[run].entry` or `jms launch --bin PROGRAM`.

## Project image user ABI

Images launched in the default mode must provide:

- a user named `isolation` with UID 1000 and primary GID 1000;
- a passwd entry with home `/home/isolation` and shell `/bin/bash`;
- an existing, writable `/home/isolation` owned by `1000:1000`; and
- passwordless sudo (`sudo -n true` must succeed).

The group with GID 1000 should be named `isolation`. Finish with
`USER isolation` for a safe default outside jms. Images based on
`jmscontainers-base:latest` already satisfy the contract.

A standalone Fedora image can create the account explicitly:

```Dockerfile
RUN dnf -y install bash sudo && dnf clean all && \
    groupadd --gid 1000 isolation && \
    useradd --create-home --shell /bin/bash \
            --uid 1000 --gid 1000 isolation && \
    printf 'isolation ALL=(ALL) NOPASSWD: ALL\n' \
        > /etc/sudoers.d/isolation && \
    chmod 0440 /etc/sudoers.d/isolation
USER isolation
```

The numeric identity lets rootless Podman map the invoking host user to
container identity `1000:1000`. Writes to `/work` and persistent state then
retain host ownership without letting image account data select the runtime
identity. jms does not inspect or repair a standalone image's account data;
an incompatible image is unsupported and may fail at launch or in the
container.

See [the examples](../examples/) for both base-derived definitions and a
clean-slate standalone image.
