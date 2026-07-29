#!/bin/sh
# Real-runtime integration tier. This intentionally does not run in PR CI.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
command -v container >/dev/null 2>&1 || {
    echo "integration requires apple/container (brew install container)" >&2
    exit 1
}

mkdir -p "$HOME/.cache/odin" "$HOME/.cache/pip" \
    "$HOME/.cache/go-build" "$HOME/go/pkg/mod" "$HOME/.cargo/registry"
work=$(mktemp -d)
cleanup() {
    for project in "$work"/*; do
        [ -d "$project" ] || continue
        "$root/bin/jms" clean --images -w "$project" >/dev/null 2>&1 || true
    done
    rm -rf "$work"
}
trap cleanup EXIT HUP INT TERM

"$root/bin/jms" build --base
container run --rm --entrypoint /bin/sh jmscontainers-base:latest -c \
    'command -v bwrap >/dev/null'

for example in odin data-science clean-slate go rust; do
    # Definitions inside the checkout live under a protected integrity root;
    # copy each fixture to an independent project root before exercising it.
    cp -R "$root/examples/$example" "$work/$example"
    "$root/bin/jms" build --trust --no-auth -w "$work/$example"
    "$root/bin/jms" inspect -w "$work/$example"
    "$root/bin/jms" launch --trust --no-auth --bin /bin/true -w "$work/$example"
    "$root/bin/jms" clean --images --dry-run -w "$work/$example"
    "$root/bin/jms" clean --images -w "$work/$example"
done

# A COPY source outside .jmscontainer/ must fail with the v2 context rule.
cp -R "$root/examples/clean-slate" "$work/escape"
printf '%s\n' 'COPY ../escape.txt /tmp/escape' >> "$work/escape/.jmscontainer/Containerfile"
if "$root/bin/jms" build --trust --no-auth -w "$work/escape" 2>"$work/escape.err"; then
    echo "COPY outside the project definition unexpectedly succeeded" >&2
    exit 1
fi
grep -q "jmscontainer/ only" "$work/escape.err" || {
    echo "build failure did not explain the v2 context rule" >&2
    exit 1
}
"$root/bin/jms" clean --images -w "$work/escape"

if container list --all --format json | python3 -c '
import json, sys
work = sys.argv[1]
for record in json.load(sys.stdin):
    configuration = record.get("configuration", {})
    for mount in configuration.get("mounts", []):
        source = mount.get("source")
        if isinstance(source, str) and (source == work or source.startswith(work + "/")):
            raise SystemExit(0)
raise SystemExit(1)
' "$work"; then
    echo "integration left a test container behind under $work" >&2
    exit 1
fi
