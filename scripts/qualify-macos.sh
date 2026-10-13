#!/bin/sh
# macOS release qualification for jms 2.1 (docs/qualification-2.1.0-macos.md).
#
# Runs the repository gate, both live integration tiers under script(1) so
# tier B's credential prompt has a terminal, and the 2.1 spot checks that no
# tier covers. Every step's output lands in one evidence directory; the
# summary at the end is what goes back to the release commit.
#
# Usage: scripts/qualify-macos.sh [EVIDENCE_DIR]
# Run it in the foreground in Terminal.app or an ssh session with a tty.
set -u

root=$(cd "$(dirname "$0")/.." && pwd)
evidence=${1:-$HOME/jms-qual-$(date +%Y%m%d-%H%M%S)}
jms="$root/bin/jms"
summary="$evidence/SUMMARY.txt"
failed=0

mkdir -p "$evidence"
: > "$summary"

note() { printf '%s\n' "$*" | tee -a "$summary"; }
result() {  # result NAME STATUS [DETAIL]
    note "$(printf '%-28s %s %s' "$1" "$2" "${3:-}")"
    [ "$2" = FAIL ] && failed=1
    return 0
}

case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) ;;
    *) echo "qualify-macos: needs an Apple Silicon Mac" >&2; exit 2 ;;
esac
if ! [ -t 0 ] || ! [ -t 2 ]; then
    echo "qualify-macos: run on a terminal (tier B prompts)" >&2
    exit 2
fi

echo "evidence: $evidence"

# ------------------------------------------------------------ environment --
{
    echo "date: $(date)"; echo "tz: $(date +%Z)"
    echo "commit: $(git -C "$root" log --oneline -1)"
    echo "worktree changes:"; git -C "$root" status --short
    sw_vers; uname -srm; python3 --version
    container --version; container system status
    shellcheck --version 2>/dev/null | sed -n 2p
} > "$evidence/environment.txt" 2>&1
note "== jms macOS qualification =="
note "commit: $(git -C "$root" log --oneline -1)"
note "macOS: $(sw_vers -productVersion) ($(sw_vers -buildVersion))"
note "runtime: $(container --version 2>&1 | head -1)"
if [ -n "$(git -C "$root" status --short)" ]; then
    result "clean worktree" FAIL "uncommitted changes; see environment.txt"
else
    result "clean worktree" PASS
fi

# ---------------------------------------------------------- unit + tiers --
if (cd "$root" && make test) > "$evidence/make-test.log" 2>&1; then
    result "make test" PASS "$(grep -E '^Ran ' "$evidence/make-test.log")"
else
    result "make test" FAIL "see make-test.log"
fi

echo
echo ">>> integration tiers A and B: answer y at the credential prompt <<<"
echo
(cd "$root" && script -q "$evidence/integration.log" scripts/integration.sh all)
if grep -q "integration tier(s) 'all' passed on container" "$evidence/integration.log"; then
    result "integration all" PASS
else
    result "integration all" FAIL "see integration.log"
fi

# ---------------------------------------------------------- spot checks ----
# OPS-10: a cold start must not hide a first-run prompt.  jms now bounds
# `container system start` (3 x JMS_RUNTIME_TIMEOUT, 180 s by default).
container system stop > "$evidence/cold-start.log" 2>&1
started=$(date +%s)
if "$jms" build --base >> "$evidence/cold-start.log" 2>&1 < /dev/null; then
    result "cold start (OPS-10)" PASS "$(( $(date +%s) - started ))s"
else
    result "cold start (OPS-10)" FAIL "$(( $(date +%s) - started ))s; see cold-start.log"
fi

# 2.1 build labels on a real apple/container image.
container image inspect jmscontainers-base:latest > "$evidence/base-inspect.json" 2>&1
labels=$(grep -o '"jms\.\(version\|commit\)" *: *"[^"]*"' "$evidence/base-inspect.json" | tr '\n' ' ')
case "$labels" in
    *jms.version*jms.commit*|*jms.commit*jms.version*) result "build labels" PASS "$labels" ;;
    *) result "build labels" FAIL "jms.version/jms.commit missing; see base-inspect.json" ;;
esac

# docs/macos.md marks these two as unverified; record what is true.
container image --help > "$evidence/image-help.txt" 2>&1
if grep -qi prune "$evidence/image-help.txt"; then
    result "image prune exists" OBSERVED "yes"
else
    result "image prune exists" OBSERVED "no"
fi

project=$(mktemp -d /tmp/jms-qual.XXXXXX)
mkdir -p "$project/.jmscontainer"
printf 'FROM jmscontainers-base:latest\nRUN sleep 120\n' > "$project/.jmscontainer/Containerfile.slow"
printf 'FROM jmscontainers-base:latest\nLABEL jms.itest=qual\n' > "$project/.jmscontainer/Containerfile"

# Build first without the dead proxy, so only the launch sees it.
"$jms" build --trust --no-auth -w "$project" < /dev/null > "$evidence/proxy-build.log" 2>&1
HTTPS_PROXY=http://127.0.0.1:9 "$jms" launch --trust --no-auth -w "$project" \
    --bin /bin/sh -- -c 'env | grep -i proxy || echo "no proxy variables"' \
    < /dev/null > "$evidence/proxy.txt" 2>&1
if grep -q '127.0.0.1:9' "$evidence/proxy.txt"; then
    result "proxy forwarded" OBSERVED "yes (HTTPS_PROXY reached the container)"
else
    result "proxy forwarded" OBSERVED "no; see proxy.txt"
fi

# OPS-02: SIGTERM to jms reaches the runtime build; nothing is left running.
mv "$project/.jmscontainer/Containerfile.slow" "$project/.jmscontainer/Containerfile"
"$jms" build --trust --no-auth -w "$project" < /dev/null > "$evidence/sigterm.log" 2>&1 &
pid=$!
waited=0
while ! pgrep -f 'container build' > /dev/null && [ "$waited" -lt 120 ]; do
    sleep 1; waited=$((waited + 1))
done
sleep 5
kill -TERM "$pid"
wait "$pid"
status=$?
sleep 5
if [ "$status" -eq 143 ] && ! pgrep -fl 'container build' >> "$evidence/sigterm.log"; then
    result "SIGTERM forwarding" PASS "exit 143, no build left"
else
    result "SIGTERM forwarding" FAIL "exit $status; see sigterm.log"
fi

"$jms" clean --yes --images -w "$project" > /dev/null 2>&1 < /dev/null
rm -rf "$project"

# ------------------------------------------------------------------ done --
note ""
note "Still by hand (docs/qualification-2.1.0-macos.md, 'Terminal checks'):"
note "  consent layout, clean prompt, zsh completion"
note "evidence: $evidence"
if [ "$failed" -eq 0 ]; then
    note "RESULT: automated checks passed"
else
    note "RESULT: FAILED"
fi
exit "$failed"
