#!/bin/sh
# shellcheck disable=SC2016  # single-quoted $VAR is expanded by the shell
#                            # inside the container, never by this harness
# Real-runtime integration tiers (multi-runtime spec §9).
#
# Usage: integration.sh [a|b|all]   (default: all)
#
#   Tier A -- fast, base image only: readiness, base build, the Linux
#            launch-contract assertions, ambient-config conflicts, bwrap
#            probes, FROM-resolution under egress denial, failure cleanup.
#   Tier B -- expensive, example images: per-example build/inspect/launch/
#            clean cycle, context-escape, auth mounts, manifest env parity,
#            survivor-set graph run, clean-store standalone external base
#            and complete project-image user ABI.
#
# Exit codes: 0 pass; 1 test failure or leak; 2 sweep failure; 3 harness
# failure (egress-denial install/remove problems, unsupported platform).
# When more than one applies the highest number wins: a harness failure
# outranks a sweep failure, which outranks a tier failure.
# This intentionally does not run in PR CI; the qualified Linux run happens
# on a real Debian 13 amd64 host with a fresh non-root, non-1000 user over
# ssh (MIR-049/056).
set -eu

tier=${1:-all}
case "$tier" in
    a|b|all) ;;
    *) echo "usage: integration.sh [a|b|all]" >&2; exit 3 ;;
esac

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)

case "$(uname -s)" in
    Darwin) runtime=container ;;
    Linux)  runtime=podman ;;
    *) echo "harness failure: unsupported platform $(uname -s)" >&2; exit 3 ;;
esac
command -v "$runtime" >/dev/null 2>&1 || {
    echo "integration requires $runtime on this platform" >&2
    exit 1
}

# Tier A installs a harness-owned nftables egress denial partway through;
# discovering a missing prerequisite there wastes a base build and leaves the
# run half-done.  Check it up front -- before mktemp, so nothing is created
# and the EXIT trap is not yet armed.  Scoped to the selections that actually
# reach install_egress_denial: tier B never touches nftables, and `b` is a
# supported standalone invocation that must run on a host without sudo.
if [ "$runtime" = podman ] && [ "$tier" != b ]; then
    # The probe is what the harness actually needs, so it is authoritative:
    # nft lives in /usr/sbin and `command -v` can miss it for a user whose
    # PATH omits the sbin directories even though `sudo nft` works.  It only
    # classifies the failure for the hint.
    if ! sudo -n nft list tables >/dev/null 2>&1; then
        echo "harness failure: Linux tier A needs passwordless 'sudo nft' for the egress denial" >&2
        if command -v nft >/dev/null 2>&1 || [ -x /usr/sbin/nft ]; then
            echo "hint: grant this user NOPASSWD access to /usr/sbin/nft in sudoers" >&2
        else
            echo "hint: install nftables first (sudo apt install nftables)" >&2
        fi
        exit 3
    fi
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$HOME/.cache/odin" "$HOME/.cache/pip" \
    "$HOME/.cache/go-build" "$HOME/go/pkg/mod" "$HOME/.cargo/registry"
work=$(mktemp -d)
nft_table="jms-integration-$$"
nft_installed=0

install_egress_denial() {
    # Harness-owned nftables table dropping all non-loopback output whose
    # socket UID is the test user's (MIR-056).  Namespace wrappers are
    # rejected: unprivileged netns either maps the invoker to euid 0
    # (tripping jms's uid-0 refusal) or destroys the subordinate ranges.
    uid=$(id -u)
    if ! sudo -n nft add table inet "$nft_table" 2>/dev/null; then
        echo "harness failure: could not install the nftables egress denial (sudo nft)" >&2
        exit 3
    fi
    nft_installed=1
    if ! sudo -n nft "add chain inet $nft_table output { type filter hook output priority 0 ; }" ||
       ! sudo -n nft "add rule inet $nft_table output oif lo accept" ||
       ! sudo -n nft "add rule inet $nft_table output meta skuid $uid drop"; then
        echo "harness failure: could not populate the nftables egress denial" >&2
        exit 3
    fi
}

remove_egress_denial() {
    [ "$nft_installed" = 1 ] || return 0
    nft_installed=0
    if ! sudo -n nft delete table inet "$nft_table" 2>/dev/null; then
        echo "harness failure: could not remove the nftables egress denial table $nft_table" >&2
        harness_failed=1
    fi
}

harness_failed=0
on_exit() {
    status=$?
    remove_egress_denial
    for project in "$work"/*; do
        [ -d "$project" ] || continue
        "$root/bin/jms" clean --images -w "$project" >/dev/null 2>&1 || true
    done
    # The sweep runs from the trap so a partial failure can never skip leak
    # detection; sweep failure stays distinct from leak (§9).
    sweep_status=0
    python3 "$root/scripts/leak_sweep.py" "$runtime" "$work" || sweep_status=$?
    rm -rf "$work"
    # Precedence: a harness failure means the run itself is untrustworthy and
    # the host may still carry the egress-denial table, so it outranks both
    # the sweep result and the tier status (§9).
    if [ "$harness_failed" -ne 0 ]; then
        exit 3
    fi
    if [ "$sweep_status" -ne 0 ]; then
        echo "leak sweep exited $sweep_status" >&2
        exit "$sweep_status"
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 1' HUP INT TERM

jms() { "$root/bin/jms" "$@"; }

launch_out() {
    # Run a --bin launch and capture its stdout.
    project=$1; shift
    jms launch --trust --no-auth -w "$project" "$@"
}

# ---------------------------------------------------------------- tier A --
tier_a() {
    echo "== tier A: base image and launch contracts =="
    jms build --base

    if [ "$runtime" = container ]; then
        container run --rm --entrypoint /bin/sh jmscontainers-base:latest -c \
            'command -v bwrap >/dev/null'
        return 0
    fi

    # --- Linux launch-contract assertions (each keyed to a §9 table row) ---
    proj="$work/tier-a"
    mkdir -p "$proj/.jmscontainer"
    printf 'FROM jmscontainers-base:latest\n' > "$proj/.jmscontainer/Containerfile"

    # Ownership (default): host ownership of /work writes; UID 1000 inside.
    launch_out "$proj" --bin /bin/sh -- -c 'touch /work/probe-default; id -u'
    [ -f "$proj/probe-default" ] || fail "default launch did not write /work"
    owner=$(stat -c %u "$proj/probe-default")
    [ "$owner" = "$(id -u)" ] || fail "default /work write owned by $owner, not invoking user"
    uid_inside=$(launch_out "$proj" --bin /bin/sh -- -c 'id -u' | tr -d '[:space:]')
    [ "$uid_inside" = 1000 ] || fail "default in-container uid is $uid_inside, not 1000"

    # Ownership (--root): UID 0 inside; host ownership still the invoking user.
    launch_out "$proj" --root --bin /bin/sh -- -c 'touch /work/probe-root'
    owner=$(stat -c %u "$proj/probe-root")
    [ "$owner" = "$(id -u)" ] || fail "--root /work write owned by $owner, not invoking user"
    uid_inside=$(launch_out "$proj" --root --bin /bin/sh -- -c 'id -u' | tr -d '[:space:]')
    [ "$uid_inside" = 0 ] || fail "--root in-container uid is $uid_inside, not 0"

    # Sudo: passwordless for isolation under keep-id.
    launch_out "$proj" --bin /bin/sh -- -c 'sudo -n true' || fail "sudo -n failed as isolation"

    # Hostname: --hostname container agrees inside.
    hostname_inside=$(launch_out "$proj" --bin /bin/sh -- -c 'echo "$HOSTNAME"' | tr -d '[:space:]')
    [ "$hostname_inside" = container ] || fail "in-container hostname is $hostname_inside"

    # Exit propagation: jms launch exits with the container's status.
    status=0
    launch_out "$proj" --bin /bin/sh -- -c 'exit 7' || status=$?
    [ "$status" = 7 ] || fail "exit 7 propagated as $status"

    # SIGTERM: an interrupted launch leaves no container (verified by the
    # sweep) and the named container is gone immediately after.  The probe
    # entrypoint installs a TERM handler: container PID 1 ignores unhandled
    # TERM by kernel rule, and the contract under test is jms's cleanup of a
    # well-behaved entrypoint (the default bash exits on TERM), not signal
    # delivery to handler-less PID 1.
    name="jms-itest-sigterm-$$"
    # Invoke the binary directly (not the jms() wrapper function): $! must be
    # the process that exec's `podman run`, so the TERM reaches the runtime.
    "$root/bin/jms" launch --trust --no-auth -w "$proj" -n "$name" --bin /bin/sh -- \
        -c 'trap "exit 0" TERM; sleep 60 & wait' &
    launch_pid=$!
    sleep 5
    kill -TERM "$launch_pid" 2>/dev/null || true
    wait "$launch_pid" 2>/dev/null || true
    sleep 3
    if podman container exists "$name" 2>/dev/null; then
        fail "SIGTERM left container $name behind"
    fi

    # Time zone: the container renders dates in the host's zone, not UTC.  The
    # offset comparison is vacuous on a UTC host, so a host that states a zone
    # at all must also see a nonempty TZ inside.  --bin bypasses the login
    # profile deliberately: what is under test is the inherited environment.
    host_offset=$(date +%z)
    offset_inside=$(launch_out "$proj" --bin /bin/sh -- -c 'date +%z' | tr -d '[:space:]')
    [ "$offset_inside" = "$host_offset" ] \
        || fail "in-container UTC offset is $offset_inside, host is $host_offset"
    if [ -L /etc/localtime ]; then
        tz_inside=$(launch_out "$proj" --bin /bin/sh -- -c 'printf %s "$TZ"' | tr -d '[:space:]')
        [ -n "$tz_inside" ] || fail "host states a zone but TZ did not reach the container"
    fi

    # Read-only shell state: writing to the shell-state target fails.
    if launch_out "$proj" --bin /bin/sh -- -c 'touch "$HOME/.config/jms-shell/x"' 2>/dev/null; then
        fail "shell-state mount was writable"
    fi

    # Ambient-config conflicts: the explicit --userns flag beats PODMAN_USERNS
    # and containers.conf in both directions (R7.4).
    uid_inside=$(PODMAN_USERNS=host launch_out "$proj" --bin /bin/sh -- -c 'id -u' | tr -d '[:space:]')
    [ "$uid_inside" = 1000 ] || fail "PODMAN_USERNS=host overrode the explicit keep-id mapping"
    uid_inside=$(PODMAN_USERNS=keep-id launch_out "$proj" --root --bin /bin/sh -- -c 'id -u' | tr -d '[:space:]')
    [ "$uid_inside" = 0 ] || fail "PODMAN_USERNS=keep-id overrode the explicit --userns=host"
    conf="$work/containers.conf"
    printf '[containers]\nuserns = "host"\n' > "$conf"
    uid_inside=$(CONTAINERS_CONF="$conf" launch_out "$proj" --bin /bin/sh -- -c 'id -u' | tr -d '[:space:]')
    [ "$uid_inside" = 1000 ] || fail "containers.conf userns overrode the explicit flag"

    # Bwrap probes (R7.14): the nested user namespace works; the full
    # sandbox fails on the masked /proc; jms never passes unmask.
    launch_out "$proj" --bin /bin/sh -- -c \
        'bwrap --unshare-user --dev-bind / / /bin/true' \
        || fail "bwrap --unshare-user failed inside the container"
    if launch_out "$proj" --bin /bin/sh -- -c \
        'bwrap --unshare-pid --dev-bind / / --proc /proc /bin/true' 2>/dev/null; then
        fail "bwrap fresh-/proc mount unexpectedly succeeded (masking changed?)"
    fi

    # Failed-run cleanup: a mid-run failure still cleans and sweeps (the
    # trap-driven sweep at exit proves no leak).
    status=0
    launch_out "$proj" --bin /bin/sh -- -c 'touch /work/probe-fail; exit 3' || status=$?
    [ "$status" = 3 ] || fail "deliberate failing run exited $status"

    # FROM resolution (R3.7/MIR-041): under egress denial, a present base
    # resolves locally with the production --pull=missing argv; an absent
    # base fails non-interactively with the conditional missing-base hint.
    install_egress_denial
    rm -f "$proj/probe-default" "$proj/probe-root" "$proj/probe-fail"
    jms clean --images -w "$proj" >/dev/null 2>&1 || true
    jms build --trust --no-auth --no-cache -w "$proj" \
        || fail "project build from the local base contacted a registry or failed"
    jms clean --images -w "$proj" >/dev/null
    podman image rm --ignore localhost/jmscontainers-base:latest >/dev/null
    status=0
    jms build --trust --no-auth --no-cache -w "$proj" </dev/null \
        2> "$work/missing-base.err" || status=$?
    [ "$status" -ne 0 ] || fail "build with the base absent unexpectedly succeeded"
    grep -q "run \`jms build\` in the base directory first" "$work/missing-base.err" \
        || fail "missing-base failure lacked the conditional hint"
    remove_egress_denial
    jms build --base    # restore (cached layers make this fast)
    jms clean --images -w "$proj" >/dev/null 2>&1 || true
    echo "== tier A passed =="
}

# ---------------------------------------------------------------- tier B --
tier_b() {
    echo "== tier B: example images =="
    for example in odin data-science clean-slate go rust; do
        # Definitions inside the checkout live under a protected integrity
        # root; copy each fixture to an independent project root first.
        cp -R "$root/examples/$example" "$work/$example"
        jms build --trust --no-auth -w "$work/$example"
        jms inspect -w "$work/$example"
        jms launch --trust --no-auth --bin /bin/true -w "$work/$example"
        jms clean --images --dry-run -w "$work/$example"
        jms clean --images -w "$work/$example"
    done

    # A COPY source outside .jmscontainer/ must fail with the v2 context rule.
    cp -R "$root/examples/clean-slate" "$work/escape"
    printf '%s\n' 'COPY ../escape.txt /tmp/escape' >> "$work/escape/.jmscontainer/Containerfile"
    if jms build --trust --no-auth -w "$work/escape" 2>"$work/escape.err"; then
        fail "COPY outside the project definition unexpectedly succeeded"
    fi
    grep -q "jmscontainer/ only" "$work/escape.err" \
        || fail "build failure did not explain the v2 context rule"
    jms clean --images -w "$work/escape"

    # Manifest env and auth-mount assertions (R7.9/R7.12).
    proj="$work/tier-b-manifest"
    mkdir -p "$proj/.jmscontainer"
    printf 'FROM jmscontainers-base:latest\n' > "$proj/.jmscontainer/Containerfile"
    printf '[env]\nJMS_ITEST = "parity"\n' > "$proj/.jmscontainer/jmscontainer.toml"
    value=$(jms launch --trust --no-auth -w "$proj" --bin /bin/sh -- -c 'echo "$JMS_ITEST"' \
            | tr -d '[:space:]')
    [ "$value" = parity ] || fail "manifest env var not visible inside the container"
    # A pinned zone replaces the inherited one, and reaches the runtime once.
    printf '[env]\nJMS_ITEST = "parity"\nTZ = "Asia/Tokyo"\n' > "$proj/.jmscontainer/jmscontainer.toml"
    value=$(jms launch --trust --no-auth -w "$proj" --bin /bin/sh -- -c 'date +%z' \
            | tr -d '[:space:]')
    [ "$value" = "+0900" ] || fail "manifest TZ pin did not win: offset inside is $value"
    probe="itest-auth-probe-$$"
    jms launch --trust --auth -w "$proj" --bin /bin/sh -- \
        -c 'echo "$CLAUDE_CONFIG_DIR" > "$HOME/.claude/'"$probe"'"'
    agent_probe="$HOME/.local/share/jmscontainers/agents/claude/$probe"
    [ -f "$agent_probe" ] || fail "auth launch did not write the mounted agent state"
    owner=$(stat -c %u "$agent_probe" 2>/dev/null || stat -f %u "$agent_probe")
    [ "$owner" = "$(id -u)" ] || fail "agent-state write owned by $owner, not invoking user"
    grep -q "/.claude" "$agent_probe" || fail "CLAUDE_CONFIG_DIR not visible inside"
    rm -f "$agent_probe"
    jms clean --images -w "$proj"

    if [ "$runtime" = podman ]; then
        # Survivor-set graph run (R5.4, MIR-042/047): a manual alias outside
        # the reserved namespace and an unselected dangling image survive a
        # jms cleanup; the untag never cascades.
        proj="$work/tier-b-survivors"
        mkdir -p "$proj/.jmscontainer"
        printf 'FROM jmscontainers-base:latest\nLABEL jms.itest=survivor\n' \
            > "$proj/.jmscontainer/Containerfile"
        jms build --trust --no-auth -w "$proj"
        built=$(podman images --filter label=jms.itest=survivor --format '{{.ID}}' | head -n 1)
        [ -n "$built" ] || fail "survivor-graph build produced no image"
        podman tag "$built" itest-survivor-alias:keep
        printf 'd' > "$work/dangle-a"; tar -C "$work" -cf "$work/dangle-a.tar" dangle-a
        printf 'e' > "$work/dangle-b"; tar -C "$work" -cf "$work/dangle-b.tar" dangle-b
        podman import --quiet "$work/dangle-a.tar" itest-dangle:latest >/dev/null
        dangling=$(podman images --format '{{.ID}} {{.Repository}}' | awk '$2=="localhost/itest-dangle" {print $1}')
        podman import --quiet "$work/dangle-b.tar" itest-dangle:latest >/dev/null
        jms clean --images -w "$proj"
        podman image exists itest-survivor-alias:keep \
            || fail "manual alias outside the reserved namespace was removed"
        podman image exists "$built" || fail "aliased image identity was deleted, not untagged"
        podman image exists "$dangling" || fail "unselected dangling image was pruned"
        podman image rm --ignore itest-survivor-alias:keep itest-dangle:latest "$dangling" >/dev/null

        # Clean-store standalone external base (R3.7, tier B, no denial):
        # the fully qualified FROM fetches on a store without it.
        podman image rm --ignore registry.fedoraproject.org/fedora:latest >/dev/null
        cp -R "$root/examples/clean-slate" "$work/clean-store"
        jms build --trust --no-auth -w "$work/clean-store" \
            || fail "standalone project failed to fetch its fully qualified base"

        # Standalone image user ABI (R3.9): numeric runtime selection,
        # account metadata, home ownership, sudo, and keep-id host ownership
        # must all describe the same identity.
        launch_out "$work/clean-store" --bin /bin/sh -- -c '
            test "$(id -u)" = 1000 &&
            test "$(id -g)" = 1000 &&
            test "$(id -un)" = isolation &&
            test "$(id -u isolation)" = 1000 &&
            test "$(id -g isolation)" = 1000 &&
            test "$(getent passwd isolation | cut -d: -f6)" = /home/isolation &&
            test "$(getent passwd isolation | cut -d: -f7)" = /bin/bash &&
            test -d /home/isolation &&
            test -w /home/isolation &&
            test "$(stat -c %u:%g /home/isolation)" = 1000:1000 &&
            sudo -n true &&
            touch /work/standalone-abi-probe
        ' || fail "standalone image does not satisfy the isolation user ABI"
        owner=$(stat -c %u:%g "$work/clean-store/standalone-abi-probe")
        expected_owner="$(id -u):$(id -g)"
        [ "$owner" = "$expected_owner" ] \
            || fail "standalone /work write owned by $owner, not invoking user $expected_owner"
        jms clean --images -w "$work/clean-store"
    elif [ "$runtime" = container ]; then
        # Survivor-set graph run (R5.4, MIR-042/047), apple/container half.
        # This run *determines* the engine's delete-by-ref cascade behavior:
        # a manual alias outside the reserved namespace and the unselected
        # base image must survive a jms cleanup. A cascade discovered here is
        # a qualification failure to resolve before release, not a silently
        # accepted behavior (MIR-042). The Podman branch's dangling-image
        # case has no apple equivalent: the apple normalizer excludes
        # ref-less records from image facts by design (§5).
        proj="$work/tier-b-survivors"
        mkdir -p "$proj/.jmscontainer"
        printf 'FROM jmscontainers-base:latest\nLABEL jms.itest=survivor\n' \
            > "$proj/.jmscontainer/Containerfile"
        jms build --trust --no-auth -w "$proj"
        built=$(container image list --format json | python3 -c '
import json, sys
for record in json.load(sys.stdin):
    variants = record.get("variants") or [{}]
    config = (variants[0].get("config") or {}).get("config") or {}
    if (config.get("Labels") or {}).get("jms.itest") == "survivor":
        print(record["id"] + " " + record["configuration"]["name"])
        break
')
        [ -n "$built" ] || fail "survivor-graph build produced no labeled image"
        built_id=${built%% *}
        built_ref=${built#* }
        container image tag "$built_ref" itest-survivor-alias:keep
        jms clean --images -w "$proj"
        survivors=$(container image list --format json | python3 -c '
import json, sys
for record in json.load(sys.stdin):
    if record["id"] == sys.argv[1]:
        name = (record.get("configuration") or {}).get("name")
        if name:
            print(name)
' "$built_id")
        case "$survivors" in
            *itest-survivor-alias:keep*) ;;
            *) fail "delete-by-ref cascaded: the manual alias outside the reserved namespace did not survive (MIR-042)" ;;
        esac
        case "$survivors" in
            *jmscontainers-*) fail "a jms-owned survivor ref was not removed by the cleanup" ;;
        esac
        container image inspect jmscontainers-base:latest >/dev/null \
            || fail "unselected base image was removed"
        container image delete itest-survivor-alias:keep >/dev/null
    fi
    echo "== tier B passed =="
}

case "$tier" in
    a)   tier_a ;;
    b)   tier_b ;;
    all) tier_a; tier_b ;;
esac
echo "integration tier(s) '$tier' passed on $runtime"
