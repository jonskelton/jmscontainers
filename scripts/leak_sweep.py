#!/usr/bin/env python3
"""Integration leak sweep (multi-runtime spec §9).

Usage: leak_sweep.py {container|podman} WORK

Asserts no container holds a mount whose source is WORK or lies under it.
Three mutually exclusive outcomes:

  exit 0 -- clean
  exit 1 -- leak found: every leaking container id and offending source named
  exit 2 -- sweep failure: a diagnostic distinct from the leak message

A sweep that cannot complete fails closed and is never conflated with "leak
found", so schema drift in a future engine shows up as its own signal.
Parsing is strict: a malformed record is never skipped, because a skipped
record could hide a leak.
"""
import json
import subprocess
import sys


class SweepFailure(Exception):
    pass


def run(argv):
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def parse_json(data, context):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SweepFailure(context + " returned invalid JSON")


def leaking_sources(work, sources):
    prefix = work + "/"
    return [source for source in sources if source == work or source.startswith(prefix)]


def hex64(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def podman_sweep(work, runner=run):
    """Two steps: `ps` for ids, `inspect` per id for mount sources -- the
    5.4.2 `ps` JSON carries mount targets only."""
    code, out, err = runner(["podman", "ps", "--all", "--format", "json"])
    if code:
        raise SweepFailure("podman ps failed: " + err.decode("utf-8", "replace").strip())
    records = parse_json(out, "podman ps")
    if not isinstance(records, list):
        raise SweepFailure("podman ps did not return a JSON array")
    identifiers = []
    for record in records:
        if not isinstance(record, dict) or not hex64(record.get("Id")):
            raise SweepFailure("podman ps returned a malformed container record")
        identifiers.append(record["Id"])
    leaks = []
    for identifier in identifiers:
        code, out, err = runner(["podman", "inspect", "--type", "container",
                                 "--format", "json", identifier])
        if code:
            # The single tolerated race: a --rm container may vanish between
            # ps and inspect.  Classified by existence recheck, never by
            # stderr matching (MIR-043 rule shape, applied by MIR-056).
            exists_code, _, _ = runner(["podman", "container", "exists", identifier])
            if exists_code == 1:
                continue        # gone: holds no mounts, not a leak
            raise SweepFailure(
                "podman inspect failed for %s and `container exists` exited %d"
                % (identifier, exists_code))
        payload = parse_json(out, "podman inspect")
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise SweepFailure("podman inspect did not return a single-record array")
        mounts = payload[0].get("Mounts")
        if not isinstance(mounts, list):
            raise SweepFailure("podman inspect returned a malformed Mounts field")
        sources = []
        for mount in mounts:
            # Every entry is evaluated regardless of Type -- a leak is a leak
            # however it was mounted.
            if (not isinstance(mount, dict) or not isinstance(mount.get("Source"), str)
                    or not isinstance(mount.get("Destination"), str)):
                raise SweepFailure("podman inspect returned a malformed mount entry")
            sources.append(mount["Source"])
        bad = leaking_sources(work, sources)
        if bad:
            leaks.append((identifier, bad))
    return leaks


def apple_sweep(work, runner=run):
    """Single pass: `container list` embeds configuration.mounts[].source."""
    code, out, err = runner(["container", "list", "--all", "--format", "json"])
    if code:
        raise SweepFailure("container list failed: " + err.decode("utf-8", "replace").strip())
    records = parse_json(out, "container list")
    if not isinstance(records, list):
        raise SweepFailure("container list did not return a JSON array")
    leaks = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise SweepFailure("container list returned a malformed container record")
        configuration = record.get("configuration")
        if not isinstance(configuration, dict):
            raise SweepFailure("container list returned a malformed container record")
        mounts = configuration.get("mounts")
        if mounts is None:
            mounts = []
        if not isinstance(mounts, list):
            raise SweepFailure("container list returned a malformed mounts field")
        sources = []
        for mount in mounts:
            if not isinstance(mount, dict) or not isinstance(mount.get("source"), str):
                raise SweepFailure("container list returned a malformed mount entry")
            sources.append(mount["source"])
        bad = leaking_sources(work, sources)
        if bad:
            leaks.append((record["id"], bad))
    return leaks


def sweep(backend, work, runner=run):
    if backend == "podman":
        return podman_sweep(work, runner)
    if backend == "container":
        return apple_sweep(work, runner)
    raise SweepFailure("unknown backend: " + backend)


def main(argv):
    if len(argv) != 2 or argv[1].startswith("-") or not argv[1]:
        print("usage: leak_sweep.py {container|podman} WORK", file=sys.stderr)
        return 2
    backend, work = argv
    try:
        leaks = sweep(backend, work)
    except SweepFailure as failure:
        print("leak sweep failed: " + str(failure), file=sys.stderr)
        return 2
    if leaks:
        for identifier, sources in leaks:
            print("leaked container %s: mount source(s) %s"
                  % (identifier, ", ".join(sources)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
