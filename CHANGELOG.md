# Changelog

## 1.1.0 — 2026-07-30

Linux support: jms now runs on Debian 13 (amd64) with local rootless
Podman ≥ 5.4, alongside the existing apple/container backend on Apple
Silicon Macs. The trust model, fingerprinting, consent flow, manifest
schema, and project discovery are shared and identical on both platforms;
only the runtime layer is per-backend.

- **Rootless Podman backend.** Selected automatically on Linux (no override
  switch). Launches pin the user-namespace mapping explicitly
  (`--userns=keep-id:uid=1000,gid=1000`, or `--userns=host` under
  `--root`) and pass `--user` numerically, so image content can never
  choose the runtime UID; `/work` writes land on the host owned by the
  invoking user. `--hostname container` and
  `--security-opt label=disable` are always passed. Refused outright:
  uid 0 on Linux, remote Podman services, and non-Linux/non-macOS
  platforms. Other distributions, arm64, and SELinux-enforcing hosts are
  unqualified but allowed. See the new per-platform boundary statement in
  SECURITY.md — the Linux boundary is kernel isolation, not a VM.
- **apple/container pin moves to 1.2.0** (the only version Homebrew
  ships). `JMS_RUNTIME_ACCEPT` remains apple/container-only; the Podman
  backend is qualified min-only and accepts newer versions silently.
- **Cleanup reports aggregated failures.** `clean` and
  `trust revoke --purge-images` attempt every scheduled removal, report
  each failure, and exit 1 instead of aborting mid-list; background image
  retention warns and never fails a successful build or launch. Container
  ownership now requires the `jms.container=launch` provenance marker in
  addition to the project label, so containers started manually from
  jms-built images are never selected. Podman image untags pass
  `--no-prune`, so removing a project image never sweeps up dangling
  parents.
- **Base image pins the isolation UID/GID to 1000** (previously implicit),
  and `examples/clean-slate` moves to a fully qualified external base
  reference.
- **Integration harness split into tiers** (`scripts/integration.sh
  a|b|all`): tier A asserts the launch contracts on the base image
  (ownership, UID mapping, sudo, hostname, exit propagation, read-only
  shell state, ambient-config conflicts, nested-bwrap probes, and
  FROM-resolution under egress denial); tier B runs the example cycle,
  auth-mount and manifest-env parity checks, and the image survivor-set
  run. Both tiers end in a strict three-outcome leak sweep.

## 1.0.0 — 2026-07-29

Initial release.

jms runs throwaway containers for claude-code, codex, and opencode in
full-permission ("yolo") mode inside `apple/container` VMs on Apple Silicon
Macs, without handing the agent the host. What ships:

- **Consent-gated project definitions.** A project opts in to its own image
  by committing `.jmscontainer/` (a Containerfile plus an optional
  `jmscontainer.toml` runtime manifest). Nothing builds or runs until the
  user approves the directory's SHA-256 trust fingerprint; any change to the
  definition re-asks. Build/run approval and the agent-state (credentials
  and configuration) mount are two separate grants, managed with
  `jms trust list|revoke|prune` and stored in
  `~/.config/jmscontainers/store.json`. Non-interactive use pins an audited
  fingerprint via `JMS_TRUST_FINGERPRINT`; the one-shot `--trust` flag never
  persists anything to the store.
- **Ephemeral containers over a shared base image.** `jms launch` starts an
  `--rm` container with the project mounted read-write at `/work`; nothing
  else survives exit. The Fedora base image (`jms build --base`) carries the
  three agents, their `yolo-*` full-permission launchers (usable as
  entrypoints: `jms launch -b yolo-claude`), bubblewrap for the Codex
  sandbox, and a general CLI toolset; project images layer on top of it.
  jms keeps the newest two images per project and evicts older ones after
  each successful build.
- **Path-based discovery bounded by the checkout.** Workdir operands are
  ordinary paths; the upward search for `.jmscontainer/` stops at the root
  of the enclosing VCS checkout and never passes `$HOME` or a filesystem
  boundary. Optional `JMS_PROJECT_ROOTS` restores a bare-name shorthand,
  with the current directory always winning and a stderr note whenever the
  search path is what resolved a name.
- **Persistent agent state, deliberately shared.** Credentials and
  configuration live under `~/.local/share/jmscontainers/agents/` on the
  host — outside any checkout — and mount read-write only under the
  credential grant, so one login per tool covers every later container.
  Host-side shell customization from `~/.local/share/jmscontainers/shell/`
  mounts read-only into every container.
- **Safety properties around the runtime.** Protected roots (the jms
  checkout, the config and state dirs) are refused as workdirs; image
  cleanup requires both the `jms.project` label and the project's tag
  prefix before deleting anything; `clean --all` never touches unlabelled
  containers or other projects' images; the accepted `container` runtime
  range is qualified, with `JMS_RUNTIME_ACCEPT` as a one-invocation
  escape hatch.
- **Tooling.** `jms init` scaffolding, Bash completion, `make
  install`/`uninstall`, a runtime-free `make test` (unit tests plus shell
  lint) run by CI on macOS and an Ubuntu Python matrix, an opt-in
  `make integration` that exercises the bundled examples (Go, Rust, Odin,
  data-science, clean-slate), and reference docs for the
  [CLI](docs/cli.md) and the
  [manifest schema](docs/jmscontainer.toml.md).

Requires macOS 15+ on Apple Silicon, Python 3.11+, and Apple's `container`
runtime.
