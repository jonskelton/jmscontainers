#!/bin/bash
# Podman 4.9.x qualification pass (Ubuntu 24.04, rootless) for
# docs/multi-runtime-implementation.md — MIR-006/007/008/009/011/013/017.
# Runs as an unprivileged user on any rootless-Podman Linux host; writes
# fixtures + results to $QUAL_OUT (default /out). Needs: podman, python3,
# network access to pull fedora:latest.
set -uo pipefail

OUT=${QUAL_OUT:-/out}
RESULTS=$OUT/results.txt
: > "$RESULTS"
FAILURES=0

pass() { echo "PASS: $*" | tee -a "$RESULTS"; }
fail() { echo "FAIL: $*" | tee -a "$RESULTS"; FAILURES=$((FAILURES+1)); }
note() { echo "NOTE: $*" | tee -a "$RESULTS"; }

export XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p "$XDG_RUNTIME_DIR"

# Nested-container accommodations (engine plumbing only — never touches
# userns/security settings under test).
mkdir -p ~/.config/containers
cat > ~/.config/containers/containers.conf <<'EOF'
[engine]
cgroup_manager = "cgroupfs"
events_logger = "file"
EOF

podman --version | tee "$OUT/versions.txt"
podman version >> "$OUT/versions.txt" 2>&1 || true

PODVER=$(podman --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)

sanitize() {  # sanitize <raw.json> <out.json>
  python3 - "$1" "$2" <<'PYEOF'
import json, socket, sys
raw, out = sys.argv[1], sys.argv[2]
host = socket.gethostname()
def scrub(v):
    if isinstance(v, str):
        return (v.replace("quser", "user").replace(host, "testhost"))
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items()}
    return v
with open(raw) as f:
    data = json.load(f)
with open(out, "w") as f:
    json.dump(scrub(data), f, indent=2, sort_keys=True)
    f.write("\n")
PYEOF
}

############################################################
note "=== MIR-008: podman info fixture + field checks ==="
if podman info --format json > /tmp/info.raw.json 2>/tmp/info.err; then
  pass "MIR-008 podman info --format json succeeds"
  sanitize /tmp/info.raw.json "$OUT/podman-$PODVER-info.json"
  python3 - /tmp/info.raw.json <<'PYEOF' | tee -a "$RESULTS"
import json, sys
d = json.load(open(sys.argv[1]))
checks = [
    ("host.serviceIsRemote is False", d["host"]["serviceIsRemote"] is False),
    ("host.security.rootless is True", d["host"]["security"]["rootless"] is True),
    ("host.idMappings.uidmap present", bool(d["host"]["idMappings"]["uidmap"])),
    ("host.idMappings.gidmap present", bool(d["host"]["idMappings"]["gidmap"])),
    ("host.ociRuntime.name present", bool(d["host"]["ociRuntime"]["name"])),
    ("host.networkBackend present", bool(d["host"].get("networkBackend"))),
    ("store.graphDriverName present", bool(d["store"]["graphDriverName"])),
]
for name, ok in checks:
    print(("PASS: MIR-008 " if ok else "FAIL: MIR-008 ") + name)
PYEOF
  grep -c '^FAIL' "$RESULTS" >/dev/null && FAILURES=$(grep -c '^FAIL' "$RESULTS" || true)
else
  fail "MIR-008 podman info failed: $(cat /tmp/info.err)"
fi

############################################################
note "=== Build base + project images (Section 3 shape) ==="
mkdir -p ~/build/base ~/build/proj ~/work
cat > ~/build/base/Containerfile <<'EOF'
FROM registry.fedoraproject.org/fedora:latest
RUN groupadd -g 1000 isolation && \
    useradd -m -s /bin/bash -u 1000 -g 1000 isolation && \
    dnf -y install bubblewrap && dnf clean all
EOF
cat > ~/build/proj/Containerfile <<'EOF'
FROM jmscontainers-base:latest
RUN touch /projmarker
EOF

if podman build --tag jmscontainers-base:latest ~/build/base > /tmp/build-base.log 2>&1; then
  pass "base image build (fully-qualified FROM) succeeds"
else
  fail "base image build failed"; tail -20 /tmp/build-base.log | tee -a "$RESULTS"
fi

if podman build --pull=never --label jms.project=testpid \
     --tag jmscontainers-testpid:latest ~/build/proj > /tmp/build-proj.log 2>&1; then
  pass "MIR-011 project build: short-name FROM + --pull=never, base present"
else
  fail "MIR-011 project build failed"; tail -20 /tmp/build-proj.log | tee -a "$RESULTS"
fi

# Create a dangling image: rebuild same tag with different content.
echo "RUN touch /projmarker2" >> ~/build/proj/Containerfile
podman build --pull=never --label jms.project=testpid \
  --tag jmscontainers-testpid:latest ~/build/proj > /dev/null 2>&1 \
  && pass "rebuild created dangling predecessor image" \
  || fail "rebuild for dangling-image coverage failed"

############################################################
note "=== MIR-006: podman images fixture + shape checks ==="
if podman images --all --format json > /tmp/images.raw.json 2>/tmp/images.err; then
  sanitize /tmp/images.raw.json "$OUT/podman-$PODVER-images.json"
  python3 - /tmp/images.raw.json <<'PYEOF' | tee -a "$RESULTS"
import json, sys
recs = json.load(open(sys.argv[1]))
def p(name, ok): print(("PASS: MIR-006 " if ok else "FAIL: MIR-006 ") + name)
p("records present", bool(recs))
p("uppercase Id on all records", all("Id" in r for r in recs))
p("Created is integer on all records", all(isinstance(r.get("Created"), int) for r in recs))
p("CreatedAt string present", all(isinstance(r.get("CreatedAt", ""), str) for r in recs))
named = [r for r in recs if r.get("Names")]
p("Names is array where present", all(isinstance(r["Names"], list) for r in named))
lab = [r for r in recs if (r.get("Names") and any("testpid" in n for n in r["Names"]))]
p("labelled project image found", bool(lab))
p("top-level Labels map with jms.project",
  bool(lab) and all((r.get("Labels") or {}).get("jms.project") == "testpid" for r in lab))
dang = [r for r in recs if not r.get("Names")]
print(f"NOTE: MIR-006 dangling records: {len(dang)}; "
      f"Names value on dangling: {[r.get('Names') for r in dang]!r}; "
      f"RepoTags on dangling: {[r.get('RepoTags') for r in dang]!r}")
PYEOF
else
  fail "MIR-006 podman images --format json failed: $(cat /tmp/images.err)"
fi

############################################################
note "=== MIR-009: explicit --userns matrix ==="
IMG=jmscontainers-testpid:latest
COMMON=(--rm --network=none --security-opt label=disable)
KEEPID=--userns=keep-id:uid=1000,gid=1000

run_expect() {  # run_expect <label> <expected-substring> <podman-args...>
  local label=$1 want=$2; shift 2
  local out
  out=$(podman "$@" 2>&1)
  if [[ "$out" == *"$want"* ]]; then
    pass "MIR-009 $label -> $want"
  else
    fail "MIR-009 $label: wanted '$want', got: $out"
  fi
}

run_expect "userns=host id" "uid=0(root) gid=0(root)" \
  run "${COMMON[@]}" --userns=host "$IMG" id
run_expect "keep-id --user isolation id" "uid=1000(isolation) gid=1000(isolation)" \
  run "${COMMON[@]}" "$KEEPID" --user isolation "$IMG" id
run_expect "--user isolation under host mode resolves" "uid=1000(isolation)" \
  run "${COMMON[@]}" --userns=host --user isolation "$IMG" id

# /work ownership on the host, both variants.
rm -f ~/work/f-keepid ~/work/f-root
podman run "${COMMON[@]}" "$KEEPID" --user isolation \
  --mount type=bind,source="$HOME/work",target=/work "$IMG" touch /work/f-keepid
[[ $(stat -c %U ~/work/f-keepid 2>/dev/null) == quser ]] \
  && pass "MIR-009 /work write under keep-id owned by invoking user" \
  || fail "MIR-009 /work ownership under keep-id: $(stat -c %U:%G ~/work/f-keepid 2>&1)"
podman run "${COMMON[@]}" --userns=host \
  --mount type=bind,source="$HOME/work",target=/work "$IMG" touch /work/f-root
[[ $(stat -c %U ~/work/f-root 2>/dev/null) == quser ]] \
  && pass "MIR-009 /work write under host mode (--root shape) owned by invoking user" \
  || fail "MIR-009 /work ownership under host mode: $(stat -c %U:%G ~/work/f-root 2>&1)"

# isolation under host mode cannot write /work (recorded negative from 5.4.2).
if podman run "${COMMON[@]}" --userns=host --user isolation \
     --mount type=bind,source="$HOME/work",target=/work "$IMG" touch /work/f-iso-host 2>/dev/null; then
  fail "MIR-009 isolation under host mode unexpectedly wrote /work"
else
  pass "MIR-009 isolation under host mode cannot write /work (matches 5.4.2 note)"
fi

# Conflicting PODMAN_USERNS loses to the explicit flag, both directions.
out=$(PODMAN_USERNS=keep-id podman run "${COMMON[@]}" --userns=host "$IMG" id 2>&1)
[[ "$out" == *"uid=0(root)"* ]] \
  && pass "MIR-009 PODMAN_USERNS=keep-id loses to --userns=host" \
  || fail "MIR-009 PODMAN_USERNS=keep-id vs host: $out"
out=$(PODMAN_USERNS=host podman run "${COMMON[@]}" "$KEEPID" --user isolation "$IMG" id 2>&1)
[[ "$out" == *"uid=1000(isolation)"* ]] \
  && pass "MIR-009 PODMAN_USERNS=host loses to --userns=keep-id:uid=1000" \
  || fail "MIR-009 PODMAN_USERNS=host vs keep-id: $out"

# Conflicting containers.conf loses to the explicit flag, both directions,
# with a no-flag control proving the conf value does take effect.
CONF_KEEPID=/tmp/conf-keepid.conf; CONF_HOST=/tmp/conf-host.conf
printf '[containers]\nuserns = "keep-id"\n' > "$CONF_KEEPID"
printf '[containers]\nuserns = "host"\n' > "$CONF_HOST"
out=$(CONTAINERS_CONF_OVERRIDE=$CONF_KEEPID podman run "${COMMON[@]}" --userns=host "$IMG" id 2>&1)
[[ "$out" == *"uid=0(root)"* ]] \
  && pass "MIR-009 containers.conf userns=keep-id loses to --userns=host" \
  || fail "MIR-009 conf keep-id vs host flag: $out"
out=$(CONTAINERS_CONF_OVERRIDE=$CONF_HOST podman run "${COMMON[@]}" "$KEEPID" --user isolation "$IMG" id 2>&1)
[[ "$out" == *"uid=1000(isolation)"* ]] \
  && pass "MIR-009 containers.conf userns=host loses to --userns=keep-id:uid=1000" \
  || fail "MIR-009 conf host vs keep-id flag: $out"
out=$(CONTAINERS_CONF_OVERRIDE=$CONF_KEEPID podman run "${COMMON[@]}" "$IMG" id 2>&1)
[[ "$out" == *"uid=$(id -u)("* ]] \
  && pass "MIR-009 control: conf userns=keep-id takes effect with no flag (uid=$(id -u))" \
  || fail "MIR-009 control run: $out"

############################################################
note "=== MIR-013: label=disable accepted (non-SELinux half) ==="
podman run --rm --network=none --security-opt label=disable "$IMG" true \
  && pass "MIR-013 --security-opt label=disable accepted as no-op" \
  || fail "MIR-013 --security-opt label=disable rejected"

############################################################
note "=== MIR-007: podman ps fixture + inspect mount sources ==="
podman rm -f qrun qexit >/dev/null 2>&1
podman run -d --name qrun --label jms.extra=onctr --network=none \
  --security-opt label=disable "$KEEPID" --user isolation \
  --mount type=bind,source="$HOME/work",target=/work "$IMG" sleep 600 >/dev/null \
  && pass "MIR-007 running labelled container started" \
  || fail "MIR-007 could not start running container"
podman run --name qexit --network=none --security-opt label=disable "$IMG" true \
  && pass "MIR-007 exited container created" \
  || fail "MIR-007 exited container failed"
# Auto-removed coverage: --rm container must not appear in ps --all.
podman run --rm --name qauto --network=none --security-opt label=disable "$IMG" true

if podman ps --all --format json > /tmp/ps.raw.json 2>/tmp/ps.err; then
  sanitize /tmp/ps.raw.json "$OUT/podman-$PODVER-ps.json"
  python3 - /tmp/ps.raw.json <<'PYEOF' | tee -a "$RESULTS"
import json, sys
recs = json.load(open(sys.argv[1]))
def p(name, ok): print(("PASS: MIR-007 " if ok else "FAIL: MIR-007 ") + name)
by = {}
for r in recs:
    for n in r.get("Names") or []:
        by[n] = r
p("running + exited containers present", "qrun" in by and "qexit" in by)
p("auto-removed container absent from ps --all", "qauto" not in by)
p("Id is full 64-char", all(len(r.get("Id","")) == 64 for r in recs))
qrun = by.get("qrun", {})
p("top-level Labels map", isinstance(qrun.get("Labels"), dict))
p("image label inherited onto container Labels",
  (qrun.get("Labels") or {}).get("jms.project") == "testpid")
p("container-only label present", (qrun.get("Labels") or {}).get("jms.extra") == "onctr")
m = qrun.get("Mounts")
print(f"NOTE: MIR-007 ps Mounts shape on this version: {m!r}")
srcful = isinstance(m, list) and any(isinstance(x, dict) and x.get("Source") for x in (m or []))
print("NOTE: MIR-007 ps Mounts carries sources: " + str(bool(srcful)))
PYEOF
else
  fail "MIR-007 podman ps --all --format json failed: $(cat /tmp/ps.err)"
fi

podman inspect qrun --format json > /tmp/inspect.raw.json 2>/dev/null
python3 - /tmp/inspect.raw.json "$HOME/work" <<'PYEOF' | tee -a "$RESULTS"
import json, sys
recs = json.load(open(sys.argv[1])); want_src = sys.argv[2]
m = recs[0].get("Mounts", [])
ok = any(x.get("Source") == want_src and x.get("Destination") == "/work" for x in m)
print(("PASS: " if ok else "FAIL: ")
      + "MIR-007 podman inspect .Mounts exposes bind source+destination (leak-sweep contract)")
PYEOF
sanitize /tmp/inspect.raw.json "$OUT/podman-$PODVER-inspect-mounts.json"

############################################################
note "=== MIR-017: nested bwrap reproduction (NESTED-PODMAN CAVEAT) ==="
BWRAP_FLAGS=("${COMMON[@]}" "$KEEPID" --user isolation)
out=$(podman run "${BWRAP_FLAGS[@]}" "$IMG" \
      bwrap --unshare-user --ro-bind / / id 2>&1)
[[ "$out" == *"uid="* ]] \
  && pass "MIR-017 bwrap --unshare-user works under default security settings" \
  || note "MIR-017 bwrap --unshare-user result (nested caveat): $out"
out=$(podman run "${BWRAP_FLAGS[@]}" "$IMG" \
      bwrap --unshare-all --ro-bind / / --proc /proc --dev /dev true 2>&1)
if [[ "$out" == *"Can't mount proc"* ]]; then
  pass "MIR-017 full bwrap sandbox fails on masked /proc (matches 5.4.2 repro)"
else
  note "MIR-017 full bwrap under default settings gave: ${out:-<success>}"
fi
out=$(podman run "${BWRAP_FLAGS[@]}" --security-opt unmask=ALL "$IMG" \
      bwrap --unshare-all --ro-bind / / --proc /proc --dev /dev true 2>&1)
[[ -z "$out" ]] \
  && pass "MIR-017 unmask=ALL makes full bwrap sandbox succeed (matches 5.4.2 repro)" \
  || note "MIR-017 full bwrap with unmask=ALL gave: $out"

############################################################
note "=== MIR-011: short-name matrix under three registries.conf variants ==="
REG1=/tmp/reg-none.conf; REG2=/tmp/reg-permissive.conf; REG3=/tmp/reg-enforcing.conf
printf 'unqualified-search-registries = []\n' > "$REG1"
printf 'unqualified-search-registries = ["docker.io"]\nshort-name-mode = "permissive"\n' > "$REG2"
printf 'unqualified-search-registries = ["docker.io"]\nshort-name-mode = "enforcing"\n' > "$REG3"

for v in none permissive enforcing; do
  case $v in none) conf=$REG1;; permissive) conf=$REG2;; enforcing) conf=$REG3;; esac
  if CONTAINERS_REGISTRIES_CONF=$conf timeout 120 podman build --pull=never --network=none \
       --tag qshort-$v:latest ~/build/proj > /tmp/short-$v.log 2>&1 < /dev/null; then
    pass "MIR-011 [$v] build succeeds offline with base present"
  else
    fail "MIR-011 [$v] build with base present failed"; tail -5 /tmp/short-$v.log | tee -a "$RESULTS"
  fi
done

# Absent-base half: remove every image that references the base.
podman rm -f qrun qexit >/dev/null 2>&1
podman rmi -f qshort-none:latest qshort-permissive:latest qshort-enforcing:latest \
  jmscontainers-testpid:latest jmscontainers-base:latest >/dev/null 2>&1
podman image prune -f >/dev/null 2>&1

for v in none permissive enforcing; do
  case $v in none) conf=$REG1;; permissive) conf=$REG2;; enforcing) conf=$REG3;; esac
  CONTAINERS_REGISTRIES_CONF=$conf timeout 60 podman build --pull=never --network=none \
    --tag qabsent-$v:latest ~/build/proj > /tmp/absent-$v.log 2>&1 < /dev/null
  rc=$?
  if [[ $rc -eq 125 ]] && grep -qi 'image not known' /tmp/absent-$v.log; then
    pass "MIR-011 [$v] base absent: fast non-interactive failure, exit 125, 'image not known'"
  else
    fail "MIR-011 [$v] base absent: rc=$rc, log tail:"; tail -5 /tmp/absent-$v.log | tee -a "$RESULTS"
  fi
done

############################################################
FAILCOUNT=$(grep -c '^FAIL' "$RESULTS" || true)
note "=== DONE: $(grep -c '^PASS' "$RESULTS" || true) passes, $FAILCOUNT failures ==="
cp /tmp/*.log "$OUT/" 2>/dev/null
exit 0
