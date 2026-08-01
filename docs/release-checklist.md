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
  survivor-set acceptance run (automated in integration tier B) — a
  discovered cascade is a qualification failure to resolve before release,
  not a silently accepted behavior — and exercise the manual removal-race
  test (idempotent cleanup under a vanished-mid-removal resource); its
  exact steps are in the appendix below.
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

## Appendix: manual removal-race test (R5.9, MIR-043)

Proves cleanup is idempotent when a selected resource vanishes mid-removal:
jms classifies an already-absent resource as removed via the post-failure
existence recheck, exits 0, and a repeat invocation converges. Run on the
macOS qualification host with apple/container at the qualified version.

1. Create a throwaway project and build it:

   ```
   mkdir -p /tmp/jms-race/.jmscontainer
   printf 'FROM jmscontainers-base:latest\nLABEL jms.itest=race\n' \
       > /tmp/jms-race/.jmscontainer/Containerfile
   jms build --trust --no-auth -w /tmp/jms-race
   ```

2. Capture the jms-owned ref of the built image:

   ```
   ref=$(container image list --format json | python3 -c '
   import json, sys
   for record in json.load(sys.stdin):
       name = record["configuration"].get("name") or ""
       if name.startswith("jmscontainers-jms-race"):
           print(name)
           break
   ')
   ```

   The ref is stable across the loop below: an unchanged project
   definition keeps the same trust fingerprint, and the tag ends in it.

3. Race an external delete against the cleanup, ten times (rebuild between
   iterations; the background delete lands inside jms's
   enumerate-then-remove window on some iterations and before or after it
   on others — every ordering must converge):

   ```
   for i in 1 2 3 4 5 6 7 8 9 10; do
       jms build --trust --no-auth -w /tmp/jms-race
       container image delete "$ref" >/dev/null 2>&1 &
       jms clean --images -w /tmp/jms-race || echo "FAIL: exit $? on iteration $i"
       wait
   done
   ```

4. Pass criteria, all required:
   - no iteration prints a FAIL line (every `jms clean` exits 0 whichever
     process deleted the image first, including when the delete lands
     between enumeration and removal);
   - no iteration reports a failed removal for the vanished ref;
   - after the loop, `container image list` shows no
     `jmscontainers-jms-race` ref, and a final `jms clean --images -w
     /tmp/jms-race` exits 0 with nothing left to remove (convergence).

5. Record the run (date, apple/container version, outcome) in the release
   register or release notes, then remove `/tmp/jms-race`.

After a push that creates or first publishes the repository:

- Enable Private Vulnerability Reporting in the repository settings, so the
  reporting channel [SECURITY.md](../SECURITY.md) points at actually exists.
- Watch the first CI run on every matrix leg; a red first run is a release
  blocker, not a follow-up.
- Set the repository description and topics.
