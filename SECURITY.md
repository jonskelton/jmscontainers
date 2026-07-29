# Security policy

## Trust model

`.jmscontainer/` is project-controlled input — the one untrusted input in the
threat model. jmscontainers fingerprints its exact contents and requires an
explicit build/run grant before the project can be built or launched; the
fingerprint is re-checked immediately before the build and a changed
fingerprint requires fresh consent. Credential mounting is a second, distinct
grant and defaults to no. In non-interactive automation, use an audited exact
fingerprint; do not use a boolean bypass.

Everything else running as the invoking user on the host — the filesystem
outside project definitions, the `container` runtime and its output, and other
jms processes — is trusted. An attacker who can tamper with those already has
the user's account; jms does not defend the user's machine against itself.

Granting both grants hands the project's image — and every transitive
dependency it pulls in — read/write access to your agents' persistent state:
their credentials and their configuration. The `isolation` user is not a security boundary
(passwordless sudo is by design);
the VM limits blast radius to the *host*, not to anything mounted into the
container. Credential mounts stay read-write because the agent CLIs refresh
tokens in place (`--mount …,readonly` exists but would break auth
persistence); recovery from corruption is "delete the dir and log in again."
Prefer dedicated, least-privileged agent accounts for third-party work;
per-project auth profiles are future work. Never claim the VM meaningfully
limits exfiltration of mounted credentials.

Do not put secrets in Containerfiles, manifests, or files under
`.jmscontainer/`: the whole directory is the build context, so build inputs
and image layers are not a secret channel. Network access is available to
approved builds and containers.

The trust store lives at `~/.config/jmscontainers/store.json`; agent state —
credentials and configuration — lives under
`~/.local/share/jmscontainers/agents/`, outside any git checkout. Neither
location, the jms checkout, nor the agent-state directories can ever be
mounted into a container — not by a project manifest, not as a project
root, and not as the workdir of a base-image `jms launch` (explicit or
defaulted from the current directory). The one jms-controlled exception is
`~/.local/share/jmscontainers/shell/`, which jms itself mounts **read-only**
at `~/.config/jms-shell` so user shell config reaches every container.
Read-only is load-bearing there: those files execute at shell startup in
every container, so a writable mount would let one compromised container
persist into all future ones. Projects still cannot mount that source or
claim its target. Those sources are rejected before
the consent prompt and before any container starts, so neither an approved
definition nor a container-side agent can grant itself further trust by
editing the trust store or the jms code the host will run next. To hack on
jms itself inside a container, work from a scratch clone of the checkout
rather than the live one.

## Reporting a vulnerability

The supported version is the latest release; older releases receive no
fixes.

Please do not file public issues for suspected vulnerabilities. Contact the
maintainer privately through the repository's security advisory/reporting
channel, including a minimal reproduction, affected revision, impact, and any
suggested mitigation. We will acknowledge the report, investigate it, and
coordinate disclosure after a fix or mitigation is available.
