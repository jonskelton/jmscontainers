import contextlib
import datetime
import importlib.machinery
import hashlib
import io
import json
import os
import pathlib
import pty
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock


JMS = importlib.machinery.SourceFileLoader(
    "jms", str(pathlib.Path(__file__).parents[1] / "bin" / "jms")
).load_module()

# Golden trust fingerprints for the fixed trees built by golden_tree() and a
# single default Containerfile.  A change here is a breaking consent change.
GOLDEN_TREE_TF = "0941c3a1ee51b32eeace1fb270552a32cb8c694e2e6c3801087effc2c287742d"
GOLDEN_SINGLE_TF = "d0004b6bc950679f0de2eedf06f9bec5c9f02442b46109af80ef1915acd5f7c7"
DEFAULT_CONTAINERFILE = b"FROM jmscontainers-base:latest\n"
# Launch inherits the host's zone, so every sandboxed test pins one: the suite
# must produce the same argv on a developer's machine and on a UTC CI runner.
# The real resolution is exercised by TimezoneTests against fake zoneinfo trees.
SANDBOX_ZONE = "America/Los_Angeles"


def setUpModule():
    # Install the backend by assigning the cache (seam #3): the suite must be
    # platform-independent, never exercising select_runtime() implicitly.
    JMS._RUNTIME = JMS.ContainerBackend()


def tearDownModule():
    JMS._RUNTIME = None


@contextlib.contextmanager
def sandbox():
    """Isolated HOME, a sandboxed checkout, and no ambient pins.

    checkout_root() is patched so no sandboxed test can ever read from or
    write to the real checkout.  `git/` here is an ordinary directory with no
    special meaning to jms -- it is only where make_project() puts things.
    """
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "home"
        (home / "git").mkdir(parents=True)
        checkout = pathlib.Path(tmp) / "checkout"
        checkout.mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ("JMS_TRUST_FINGERPRINT", "JMS_RUNTIME_ACCEPT",
                              "JMS_PROJECT_ROOTS")}
        env["HOME"] = str(home)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(JMS, "checkout_root",
                               lambda: JMS.canon(os.fsencode(checkout))), \
             mock.patch.object(JMS, "host_timezone", lambda: SANDBOX_ZONE):
            yield home


def make_project(home, name="demo", containerfile=DEFAULT_CONTAINERFILE, manifest=None):
    root = home / "git" / name
    spec = root / ".jmscontainer"
    spec.mkdir(parents=True)
    # Discovery spans the enclosing checkout, so a project fixture is one.
    (root / ".git").mkdir()
    (spec / "Containerfile").write_bytes(containerfile)
    if manifest is not None:
        (spec / "jmscontainer.toml").write_bytes(manifest)
    return root


def golden_tree(spec):
    (spec / "data" / "empty").mkdir(parents=True)
    (spec / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
    (spec / "tool.sh").write_bytes(b"#!/bin/sh\n")
    (spec / "tool.sh").chmod(0o755)
    (spec / "data" / "blob.bin").write_bytes(bytes(range(256)))
    os.symlink("Containerfile", spec / "link")


def fingerprint_of(root):
    return JMS.trust_fingerprint(JMS.spec_entries(os.fsencode(root / ".jmscontainer")))


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name, "rb") as handle:
        return json.load(handle)


def forbid(*args, **kwargs):
    raise AssertionError("forbidden call reached: " + repr(args[:1]))


def fake_hex_id(name):
    return hashlib.sha256(name.encode()).hexdigest()


def image_record(ref, created="2026-01-01T00:00:00Z", labels=None):
    """Normalized fake-image state; FakeRuntime renders it per backend."""
    return {"created": created, "labels": dict(labels or {})}


class FakeRuntime:
    """Canned runtime subprocess seam driven by the argv prefix.

    Internal state is backend-neutral (image_record() specs keyed by ref,
    containers as {"id", "labels"} dicts); payloads are rendered in each
    engine's real JSON schema so the strict normalizers parse them.
    """

    def __init__(self, images=None, containers=None, build_error=None, stop_error=False,
                 backend="container"):
        self.calls = []
        self.images = dict(images or {})
        self.containers = list(containers or [])
        self.deleted = []
        self.build_error = build_error
        self.build_count = 0
        self.stop_error = stop_error
        self.backend = backend

    def result(self, returncode=0, stdout=b"", stderr=b""):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def payload(self, value):
        return self.result(stdout=json.dumps(value).encode())

    def apple_images_payload(self):
        records = []
        for ref, spec in self.images.items():
            digest = fake_hex_id(ref)
            records.append({"id": digest,
                            "configuration": {"name": ref, "creationDate": spec["created"],
                                              "descriptor": {"digest": "sha256:" + digest}},
                            "variants": [{"config": {"config": {"Labels": dict(spec["labels"])}}}]})
        return records

    def podman_images_payload(self):
        records = []
        for ref, spec in self.images.items():
            epoch = int(datetime.datetime.fromisoformat(spec["created"]).timestamp())
            records.append({"Id": fake_hex_id(ref), "Names": [ref], "Created": epoch,
                            "Labels": dict(spec["labels"]) or None})
        return records

    def parse_build(self, argv, label_flag):
        self.build_count += 1
        if self.build_error is not None:
            raise JMS.JMSException(self.build_error)
        tag = argv[argv.index("--tag") + 1]
        labels = {}
        for index, value in enumerate(argv):
            if value == label_flag:
                key, _, label_value = argv[index + 1].partition("=")
                labels[key] = label_value
        created = "2026-01-01T00:00:%02dZ" % (self.build_count % 60)
        self.images[tag] = image_record(tag, created=created, labels=labels)
        return self.result()

    def __call__(self, argv, capture=True, check=True, stdin=None,
                 stdout=None, stderr=None, replace=False):
        self.calls.append({"argv": list(argv), "replace": replace})
        if argv[0] != self.backend:
            raise AssertionError("fake %s runtime saw argv[0]=%s" % (self.backend, argv[0]))
        if self.backend == "podman":
            return self.podman_call(argv, check)
        return self.apple_call(argv, check)

    def apple_call(self, argv, check):
        if argv[:2] == ["container", "--version"]:
            return self.result(stdout=b"container CLI version 1.2.0 (build: release)\n")
        if argv[:3] == ["container", "system", "status"]:
            return self.result()
        if argv[:3] == ["container", "image", "inspect"]:
            ref = argv[3]
            if ref in self.images:
                return self.payload(self.apple_images_payload())
            return self.result(returncode=1, stderr=("Error: image not found: " + ref).encode())
        if argv[:3] == ["container", "image", "list"]:
            return self.payload(self.apple_images_payload())
        if argv[:3] == ["container", "image", "delete"]:
            self.deleted.append(argv[3])
            self.images.pop(argv[3], None)
            return self.result()
        if argv[:2] == ["container", "build"]:
            return self.parse_build(argv, "-l")
        if argv[:2] == ["container", "list"]:
            return self.payload([{"id": c["id"], "configuration": {"labels": dict(c["labels"])}}
                                 for c in self.containers])
        if argv[:2] == ["container", "stop"] and self.stop_error:
            if check:
                raise JMS.JMSException("command failed: container stop " + argv[2])
            return self.result(returncode=1, stderr=b"Error: container is not running")
        return self.result()

    def podman_call(self, argv, check):
        if argv[:2] == ["podman", "--version"]:
            return self.result(stdout=b"podman version 5.4.2\n")
        if argv[:2] == ["podman", "info"]:
            return self.payload(load_fixture("podman-5.4.2-info.json"))
        if argv[:3] == ["podman", "image", "exists"]:
            return self.result(returncode=0 if argv[3] in self.images else 1)
        if argv[:2] == ["podman", "images"]:
            return self.payload(self.podman_images_payload())
        if argv[:3] == ["podman", "image", "rm"]:
            self.deleted.append(argv[-1])
            self.images.pop(argv[-1], None)
            return self.result()
        if argv[:2] == ["podman", "build"]:
            return self.parse_build(argv, "--label")
        if argv[:2] == ["podman", "ps"]:
            return self.payload([{"Id": c["id"], "Labels": dict(c["labels"]) or None}
                                 for c in self.containers])
        if argv[:2] == ["podman", "stop"] and self.stop_error:
            return self.result(returncode=1, stderr=b"some containers could not be stopped")
        return self.result()


@contextlib.contextmanager
def fake_runtime(backend="container", **kwargs):
    runtime = FakeRuntime(backend=backend, **kwargs)
    backend_cls = JMS.ContainerBackend if backend == "container" else JMS.PodmanBackend
    with mock.patch.object(JMS, "_RUNTIME", backend_cls()), \
         mock.patch.object(JMS, "runtime_run", runtime):
        yield runtime


def quiet():
    return contextlib.redirect_stderr(io.StringIO())


class TTYIO(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class FingerprintTests(unittest.TestCase):
    def test_golden_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = pathlib.Path(tmp) / ".jmscontainer"
            golden_tree(spec)
            entries = JMS.spec_entries(os.fsencode(spec))
            self.assertEqual(JMS.trust_fingerprint(entries), GOLDEN_TREE_TF)
            self.assertEqual(
                [(entry[0], entry[1], entry[2]) for entry in entries],
                [(b"f", b"Containerfile", b"-"), (b"d", b"data", b"-"),
                 (b"f", b"data/blob.bin", b"-"), (b"d", b"data/empty", b"-"),
                 (b"l", b"link", b"-"), (b"f", b"tool.sh", b"x")])
        with tempfile.TemporaryDirectory() as tmp:
            spec = pathlib.Path(tmp) / ".jmscontainer"
            spec.mkdir()
            (spec / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            self.assertEqual(JMS.trust_fingerprint(JMS.spec_entries(os.fsencode(spec))),
                             GOLDEN_SINGLE_TF)

    def test_fingerprint_is_reproducible_and_creation_order_insensitive(self):
        digests = []
        for order in (("a.txt", "b.txt", "z"), ("z", "b.txt", "a.txt")):
            with tempfile.TemporaryDirectory() as tmp:
                spec = pathlib.Path(tmp) / ".jmscontainer"
                spec.mkdir()
                for name in order:
                    if name == "z":
                        (spec / name).mkdir()
                    else:
                        (spec / name).write_bytes(name.encode())
                digests.append(JMS.trust_fingerprint(JMS.spec_entries(os.fsencode(spec))))
        self.assertEqual(digests[0], digests[1])

    def test_fingerprint_sensitivity_matrix(self):
        def tf_after(change):
            with tempfile.TemporaryDirectory() as tmp:
                spec = pathlib.Path(tmp) / ".jmscontainer"
                golden_tree(spec)
                change(spec)
                return JMS.trust_fingerprint(JMS.spec_entries(os.fsencode(spec)))
        cases = {
            "content": lambda spec: (spec / "Containerfile").write_bytes(b"FROM other\n"),
            "exec-bit": lambda spec: (spec / "Containerfile").chmod(0o755),
            "exec-removed": lambda spec: (spec / "tool.sh").chmod(0o644),
            "symlink-target": lambda spec: (os.unlink(spec / "link"),
                                            os.symlink("tool.sh", spec / "link")),
            "rename": lambda spec: os.rename(spec / "tool.sh", spec / "tool2.sh"),
            "new-empty-dir": lambda spec: (spec / "data" / "more").mkdir(),
            "file-to-symlink": lambda spec: (os.unlink(spec / "tool.sh"),
                                             os.symlink("Containerfile", spec / "tool.sh")),
        }
        for name, change in cases.items():
            with self.subTest(change=name):
                self.assertNotEqual(tf_after(change), GOLDEN_TREE_TF)

    def test_unsupported_file_types_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = pathlib.Path(tmp) / ".jmscontainer"
            spec.mkdir()
            (spec / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            os.mkfifo(spec / "pipe")
            with self.assertRaisesRegex(JMS.JMSException, "unsupported file type"):
                JMS.spec_entries(os.fsencode(spec))

    def test_symlinked_directories_are_hashed_as_symlinks_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = pathlib.Path(tmp) / "outside"
            outside.mkdir()
            (outside / "secret").write_bytes(b"credential")
            spec = pathlib.Path(tmp) / ".jmscontainer"
            spec.mkdir()
            (spec / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            os.symlink(outside, spec / "dirlink")
            entries = JMS.spec_entries(os.fsencode(spec))
            kinds = {entry[1]: entry[0] for entry in entries}
            self.assertEqual(kinds[b"dirlink"], b"l")
            self.assertNotIn(b"dirlink/secret", kinds)


class TrustStoreTests(unittest.TestCase):
    def test_round_trip_and_disk_format(self):
        with sandbox() as home:
            record = {"root": str(home / "git" / "demo"), "tf": "a" * 64,
                      "grants": {"build_run": True, "auth": False},
                      "granted_at": "2026-01-01T00:00:00Z", "jms_version": JMS.__version__}
            pid = hashlib.sha256(record["root"].encode()).hexdigest()
            def add(store):
                store["projects"][pid] = record
                return True
            JMS.update_store(add)
            raw = (home / ".config" / "jmscontainers" / "store.json").read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw)["schema"], 2)
            self.assertEqual(JMS.read_store()["projects"], {pid: record})

    def test_missing_store_reads_empty_without_writing(self):
        with sandbox() as home:
            self.assertEqual(JMS.read_store(), {"schema": 2, "projects": {}})
            self.assertFalse((home / ".config").exists())

    def test_read_only_change_does_not_write(self):
        with sandbox() as home:
            JMS.update_store(lambda store: False)
            self.assertFalse((home / ".config" / "jmscontainers" / "store.json").exists())

    def test_malformed_and_newer_stores_fail_closed(self):
        cases = (
            (b"{not json", "invalid JSON", True),
            (b"[]\n", "wrong schema", True),
            (b'{"schema": 2, "projects": {"zz": {}}}\n', "wrong schema", True),
            (b'{"schema": 3, "projects": {}}\n', "newer jms", False),
        )
        for raw, message, expects_reset_hint in cases:
            with self.subTest(raw=raw), sandbox() as home:
                directory = home / ".config" / "jmscontainers"
                directory.mkdir(parents=True)
                (directory / "store.json").write_bytes(raw)
                with self.assertRaisesRegex(JMS.JMSException, message) as caught:
                    JMS.read_store()
                self.assertEqual("reset all approvals" in str(caught.exception),
                                 expects_reset_hint)

    def test_record_field_validation(self):
        root = "/tmp/project"
        pid = hashlib.sha256(root.encode()).hexdigest()
        good = {"root": root, "tf": "a" * 64, "grants": {"build_run": True, "auth": False},
                "granted_at": "2026-01-01T00:00:00Z", "jms_version": "1.0.0"}
        mutations = {
            "wrong-pid": ("0" * 64, good),
            "bad-tf": (pid, dict(good, tf="xyz")),
            "extra-key": (pid, dict(good, categories={})),
            "build-run-false": (pid, dict(good, grants={"build_run": False, "auth": False})),
            "bad-date": (pid, dict(good, granted_at="yesterday")),
        }
        for name, (key, record) in mutations.items():
            with self.subTest(mutation=name):
                self.assertFalse(JMS.valid_store({"schema": 2, "projects": {key: record}}))
        self.assertTrue(JMS.valid_store({"schema": 2, "projects": {pid: good}}))

    def test_concurrent_mutations_serialize_under_flock(self):
        with sandbox() as home:
            barrier = threading.Barrier(2)
            def add(index):
                root = str(home / "git" / ("p%d" % index))
                pid = hashlib.sha256(root.encode()).hexdigest()
                def change(store):
                    time.sleep(0.05)
                    store["projects"][pid] = {
                        "root": root, "tf": "a" * 64,
                        "grants": {"build_run": True, "auth": False},
                        "granted_at": "2026-01-01T00:00:00Z", "jms_version": "1.0.0"}
                    return True
                barrier.wait(timeout=5)
                JMS.update_store(change)
            threads = [threading.Thread(target=add, args=(index,)) for index in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(len(JMS.read_store()["projects"]), 2)

    def test_failed_write_leaves_no_temp_files(self):
        with sandbox() as home:
            def boom(store):
                store["projects"] = {"bad": object()}
                return True
            with self.assertRaises(TypeError):
                JMS.update_store(boom)
            directory = home / ".config" / "jmscontainers"
            leftovers = [name for name in os.listdir(directory) if name.startswith("store.json.tmp")]
            self.assertEqual(leftovers, [])


class ManifestTests(unittest.TestCase):
    def test_defaults_and_full_manifest(self):
        self.assertEqual(JMS.parse_manifest(None), JMS.default_config())
        with sandbox() as home:
            cache = home / "cache"
            cache.mkdir()
            config = JMS.parse_manifest(
                b'name = "demo"\n[env]\nFOO = "bar"\n[run]\nentry = ["/bin/zsh"]\n'
                b'mount_auth = false\n[[mounts]]\nsource = "~/cache"\n'
                b'target = "/home/isolation/.cache/demo"\n')
            self.assertEqual(config["name"], "demo")
            self.assertEqual(config["env"], {"FOO": "bar"})
            self.assertEqual(config["entry"], ["/bin/zsh"])
            self.assertFalse(config["mount_auth"])
            self.assertEqual(config["mounts"],
                             [{"source": JMS.canon(os.fsencode(cache)),
                               "target": "/home/isolation/.cache/demo", "readonly": True}])

    def test_invalid_fields_are_reported_together(self):
        with self.assertRaisesRegex(JMS.JMSException, "invalid jmscontainer.toml fields"):
            JMS.parse_manifest(b'nonsense = 1\n[env]\n"BAD KEY" = "x"\n')

    def test_newer_schema_is_rejected(self):
        with self.assertRaisesRegex(JMS.JMSException, "newer than this jms"):
            JMS.parse_manifest(b"schema = 2\n")

    def test_mount_target_grammar_and_reserved_targets(self):
        home = "/home/isolation"
        for target in (home + "/.cache/x", "/opt/data", "/mnt/x", "/srv/x"):
            self.assertTrue(JMS.valid_target(target, home), target)
        for target in ("relative", "//x", home + "/", "/etc/passwd", home + "/..", "/opt/a,b"):
            self.assertFalse(JMS.valid_target(target, home), target)
        for target in ("/work", "/work/sub", home + "/.claude", home + "/.claude/sub",
                       home + "/.local/share/opencode", home, home + "/.config/opencode",
                       home + "/.config/jms-shell", home + "/.config/jms-shell/bashrc"):
            self.assertTrue(JMS.target_overlaps_reserved(target, home), target)
        self.assertFalse(JMS.target_overlaps_reserved(home + "/.cache", home))

    def test_overlapping_mount_targets_are_rejected(self):
        with sandbox() as home:
            (home / "cache").mkdir()
            manifest = (b'[[mounts]]\nsource = "~/cache"\ntarget = "/opt/data"\n'
                        b'[[mounts]]\nsource = "~/cache"\ntarget = "/opt/data/inner"\n')
            with self.assertRaisesRegex(JMS.JMSException, "mounts targets overlap"):
                JMS.parse_manifest(manifest)

    def test_mount_source_expansion(self):
        with sandbox() as home:
            (home / "cache").mkdir()
            with mock.patch.dict(os.environ, {"XDG_THING": str(home / "cache")}):
                for expression in ("~/cache", "$HOME/cache", "${XDG_THING}"):
                    self.assertEqual(JMS.expand_mount_source(expression),
                                     JMS.canon(os.fsencode(home / "cache")), expression)
            for expression in ("relative/path", "$UNSET_VARIABLE_XYZ/x", "~user/x"):
                with self.assertRaises(JMS.JMSException):
                    JMS.expand_mount_source(expression)


class PreserveHostPathTests(unittest.TestCase):
    """run.preserve_host_path: the project mount keeps its host path.

    The manifest chooses only whether to preserve the path, never what the
    path is, so the adversarial surface is a hostile *checkout location*
    combined with the key -- not a hostile target string.
    """
    HOME = "/home/isolation"

    def preserved(self, **overrides):
        return dict(JMS.default_config(), preserve_host_path=True, **overrides)

    def test_manifest_accepts_the_boolean_and_rejects_anything_else(self):
        self.assertFalse(JMS.parse_manifest(None)["preserve_host_path"])
        self.assertTrue(JMS.parse_manifest(b"[run]\npreserve_host_path = true\n")["preserve_host_path"])
        self.assertFalse(JMS.parse_manifest(b"[run]\npreserve_host_path = false\n")["preserve_host_path"])
        for raw in (b'[run]\npreserve_host_path = "yes"\n', b"[run]\npreserve_host_path = 1\n"):
            with self.assertRaisesRegex(JMS.JMSException, "run.preserve_host_path"):
                JMS.parse_manifest(raw)

    def test_default_never_consults_the_host_path(self):
        """Off, even a checkout at /etc must still resolve to "/work"."""
        for root in (b"/etc/project", b"/", b"/usr/local/src"):
            self.assertEqual(JMS.project_mount_target(root, JMS.default_config(), self.HOME), "/work")

    def test_ordinary_checkout_is_preserved_verbatim(self):
        for root in (b"/home/jskelton/git/finance", b"/opt/project", b"/srv/x", b"/tmp/scratch/p"):
            self.assertEqual(JMS.project_mount_target(root, self.preserved(), self.HOME),
                             os.fsdecode(root))

    def test_critical_container_paths_are_refused(self):
        for path in ("/", "/etc", "/usr", "/usr/local/src", "/dev/shm/p", "/proc/x", "/var/tmp/p"):
            self.assertTrue(JMS.shadows_critical_path(path), path)
        for path in ("/home/x/p", "/opt/p", "/srv/p", "/tmp/p", "/mnt/p", "/work"):
            self.assertFalse(JMS.shadows_critical_path(path), path)
        for root in (b"/etc/project", b"/usr/local/src/p", b"/proc/p", b"/"):
            with self.assertRaisesRegex(JMS.JMSException, "container system state"):
                JMS.project_mount_target(root, self.preserved(), self.HOME)

    def test_a_checkout_that_would_swallow_a_reserved_mount_is_refused(self):
        """/home shadows the agent-state mounts; .claude collides outright."""
        for root in (b"/home", b"/home/isolation", b"/home/isolation/.claude/p", b"/work", b"/work/p"):
            with self.assertRaisesRegex(JMS.JMSException, "reserved mount target"):
                JMS.project_mount_target(root, self.preserved(), self.HOME)

    def test_a_relative_or_denormalized_root_is_refused(self):
        """Unreachable through canon(), but a relative target matches no prefix guard."""
        for root in (b"relative/path", b"/opt/./project", b"/opt/project/", b"/opt/../etc"):
            with self.assertRaisesRegex(JMS.JMSException, "absolute, normalized"):
                JMS.project_mount_target(root, self.preserved(), self.HOME)

    def test_root_user_home_is_refused_under_its_own_effective_home(self):
        """--root moves the home to /root, which is also critical: refused twice over."""
        with self.assertRaises(JMS.JMSException):
            JMS.project_mount_target(b"/root/git/p", self.preserved(), "/root")

    def plan_for(self, root, config, root_user=False):
        args = types.SimpleNamespace(container_name=None, bin=None, root=root_user,
                                     auth=False, extra=[])
        data = {"root": root, "pid": "a" * 64, "config": config}
        with mock.patch.object(JMS, "ensure_shell_state_directory"), \
             mock.patch.object(JMS, "ensure_agent_state_directory"):
            return JMS.launch_plan(root, data, args, "img", False)

    def test_manifest_mount_inside_the_preserved_project_is_refused(self):
        """"/work" is reserved so it covers the default mount; a host path is not."""
        config = self.preserved(mounts=[{"source": b"/tmp", "target": "/opt/project/inner",
                                         "readonly": True}])
        with self.assertRaisesRegex(JMS.JMSException, "overlaps the project mount"):
            self.plan_for(b"/opt/project", config)

    def test_manifest_mount_containing_the_preserved_project_is_refused(self):
        config = self.preserved(mounts=[{"source": b"/tmp", "target": "/opt/project",
                                         "readonly": True}])
        with self.assertRaisesRegex(JMS.JMSException, "overlaps the project mount"):
            self.plan_for(b"/opt/project/deep", config)

    def test_a_disjoint_manifest_mount_still_launches(self):
        config = self.preserved(mounts=[{"source": b"/tmp", "target": "/opt/other",
                                         "readonly": True}])
        plan = self.plan_for(b"/opt/project", config)
        self.assertEqual(plan.workdir, "/opt/project")
        self.assertEqual(plan.mounts[0], (b"/opt/project", "/opt/project", False))

    def test_the_same_overlap_is_allowed_when_the_key_is_off(self):
        """Off, the project sits at /work, so /opt/project/inner no longer collides."""
        config = dict(JMS.default_config(),
                      mounts=[{"source": b"/tmp", "target": "/opt/project/inner",
                               "readonly": True}])
        plan = self.plan_for(b"/opt/project", config)
        self.assertEqual(plan.workdir, "/work")


class DiscoveryTests(unittest.TestCase):
    def test_discovery_ceiling_nested_and_invalid_marker_matrix(self):
        with sandbox() as home:
            git = home / "git"
            outer = git / "outer"; inner = outer / "inner"; leaf = inner / "leaf"
            leaf.mkdir(parents=True)
            (outer / ".git").mkdir()
            for project in (outer, inner):
                marker = project / ".jmscontainer"; marker.mkdir()
                (marker / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            root, marker = JMS.discover(JMS.canon(os.fsencode(leaf)))
            self.assertEqual(root, JMS.canon(os.fsencode(inner)))
            self.assertEqual(marker, JMS.canon(os.fsencode(inner)) + b"/.jmscontainer")
            for path in (inner / ".jmscontainer" / "Containerfile", inner / ".jmscontainer"):
                if path.is_dir():
                    os.rmdir(path)
                else:
                    os.unlink(path)
            (inner / ".jmscontainer").write_text("wrong type")
            with self.assertRaisesRegex(JMS.JMSException, "must be a directory"):
                JMS.discover(JMS.canon(os.fsencode(leaf)))

    def test_discovery_stops_at_the_checkout_root(self):
        """A definition above the checkout is invisible from inside it."""
        with sandbox() as home:
            git = home / "git"
            outer = git / "outer"; leaf = outer / "leaf"
            leaf.mkdir(parents=True)
            (outer / ".git").mkdir()
            above = git / ".jmscontainer"; above.mkdir()
            (above / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            self.assertEqual(JMS.discover(JMS.canon(os.fsencode(leaf))), (None, None))
            marker = outer / ".jmscontainer"; marker.mkdir()
            (marker / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            root, _ = JMS.discover(JMS.canon(os.fsencode(leaf)))
            self.assertEqual(root, JMS.canon(os.fsencode(outer)))

    def test_discovery_outside_a_checkout_considers_only_the_workdir(self):
        with sandbox() as home:
            loose = home / "loose"; leaf = loose / "leaf"
            leaf.mkdir(parents=True)
            marker = loose / ".jmscontainer"; marker.mkdir()
            (marker / "Containerfile").write_bytes(DEFAULT_CONTAINERFILE)
            self.assertEqual(JMS.discover(JMS.canon(os.fsencode(leaf))), (None, None))
            root, _ = JMS.discover(JMS.canon(os.fsencode(loose)))
            self.assertEqual(root, JMS.canon(os.fsencode(loose)))

    def test_git_managed_home_is_not_a_checkout_root(self):
        """One dotfiles repository must not make every directory one project."""
        with sandbox() as home:
            (home / ".git").mkdir()
            project = home / "git" / "demo"
            project.mkdir(parents=True)
            workdir = JMS.canon(os.fsencode(project))
            self.assertIsNone(JMS.vcs_root(workdir))
            self.assertEqual(JMS.ceiling_for(workdir), JMS.parent(workdir))
            self.assertIsNotNone(JMS.implicit_workdir_refusal(workdir))

    def test_workdir_operand_grammar(self):
        with sandbox() as home:
            project = home / "git" / "demo"
            (project / "sub").mkdir(parents=True)
            canonical = JMS.canon(os.fsencode(project))
            with mock.patch.object(os, "getcwd", return_value=str(home / "git")):
                for operand in ("demo", "./demo", "demo/sub/..", str(project)):
                    with self.subTest(operand=operand):
                        self.assertEqual(JMS.resolve_operand(operand), (canonical, True))
                self.assertEqual(JMS.resolve_operand("."),
                                 (JMS.canon(os.fsencode(home / "git")), True))
                self.assertEqual(JMS.resolve_operand(None),
                                 (JMS.canon(os.fsencode(home / "git")), False))
            with mock.patch.object(os, "getcwd", return_value=str(project / "sub")):
                self.assertEqual(JMS.resolve_operand(".."), (canonical, True))
            with mock.patch.object(os, "getcwd", return_value=str(home)):
                with self.assertRaisesRegex(JMS.UsageError, "non-empty path"):
                    JMS.resolve_operand("")
                with self.assertRaisesRegex(JMS.UsageError, "workdir does not exist"):
                    JMS.resolve_operand("nope")
                with self.assertRaisesRegex(JMS.UsageError, "workdir is not a directory"):
                    (home / "file").write_text("x")
                    JMS.resolve_operand("file")

    def test_unresolved_symlink_workdirs_are_usage_errors(self):
        with sandbox() as home:
            work = home / "work"
            roots = home / "roots"
            work.mkdir()
            (roots / "dangling").mkdir(parents=True)
            os.symlink("missing", work / "dangling")
            os.symlink("loop-b", work / "loop-a")
            os.symlink("loop-a", work / "loop-b")
            with mock.patch.dict(os.environ, {"JMS_PROJECT_ROOTS": str(roots)}), \
                 mock.patch.object(os, "getcwd", return_value=str(work)):
                for operand in ("dangling", "loop-a"):
                    with self.subTest(operand=operand):
                        with self.assertRaisesRegex(
                                JMS.UsageError, "workdir does not exist") as caught:
                            JMS.resolve_operand(operand)
                        self.assertEqual(caught.exception.exit_code, 2)

    def test_bare_name_prefers_the_cwd_over_the_search_path(self):
        """The shorthand may never silently pick a different real directory."""
        with sandbox() as home:
            local = home / "work" / "demo"; local.mkdir(parents=True)
            shared = home / "git" / "demo"; shared.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"JMS_PROJECT_ROOTS": str(home / "git")}), \
                 mock.patch.object(os, "getcwd", return_value=str(home / "work")):
                self.assertEqual(JMS.resolve_operand("demo")[0],
                                 JMS.canon(os.fsencode(local)))

    def test_search_path_resolves_a_name_absent_from_the_cwd(self):
        with sandbox() as home:
            shared = home / "git" / "demo"; shared.mkdir(parents=True)
            empty = home / "work"; empty.mkdir()
            with mock.patch.dict(os.environ, {"JMS_PROJECT_ROOTS": "~/git"}), \
                 mock.patch.object(os, "getcwd", return_value=str(empty)):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    resolved, _ = JMS.resolve_operand("demo")
                self.assertEqual(resolved, JMS.canon(os.fsencode(shared)))
                self.assertIn("JMS_PROJECT_ROOTS", stderr.getvalue())

    def test_search_path_is_off_by_default_and_rejects_relative_entries(self):
        with sandbox() as home:
            (home / "git" / "demo").mkdir(parents=True)
            with mock.patch.object(os, "getcwd", return_value=str(home / "work")):
                (home / "work").mkdir()
                with self.assertRaisesRegex(JMS.UsageError, "workdir does not exist"):
                    JMS.resolve_operand("demo")
            with mock.patch.dict(os.environ, {"JMS_PROJECT_ROOTS": "git"}):
                with self.assertRaisesRegex(JMS.UsageError, "must be absolute paths"):
                    JMS.project_roots()

    def test_project_data_computes_identity(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            self.assertEqual(data["tf"], GOLDEN_SINGLE_TF)
            self.assertEqual(data["pid"], hashlib.sha256(data["root"]).hexdigest())
            self.assertEqual(data["tag_prefix"], "jmscontainers-demo-" + data["pid"][:8])
            self.assertIsNone(JMS.project_data(JMS.canon(os.fsencode(home / "git"))))

    def test_manifest_mount_over_protected_source_is_rejected(self):
        with sandbox() as home:
            config_dir = home / ".config" / "jmscontainers"
            config_dir.mkdir(parents=True)
            manifest = ('[[mounts]]\nsource = "%s"\ntarget = "/opt/steal"\n' % config_dir).encode()
            root = make_project(home, manifest=manifest)
            with self.assertRaisesRegex(JMS.JMSException, "protected jms host directory"):
                JMS.project_data(JMS.canon(os.fsencode(root)))

    def test_reserved_root_covers_repo_trust_store_and_data_dir(self):
        with sandbox() as home:
            repo = JMS.checkout_root()
            self.assertTrue(JMS.reserved_root(repo))
            self.assertTrue(JMS.reserved_root(repo + b"/bin"))
            config = home / ".config" / "jmscontainers"
            config.mkdir(parents=True)
            self.assertTrue(JMS.reserved_root(JMS.canon(os.fsencode(config))))
            agents = home / ".local" / "share" / "jmscontainers" / "agents"
            agents.mkdir(parents=True)
            self.assertTrue(JMS.reserved_root(JMS.canon(os.fsencode(agents))))
            self.assertTrue(JMS.reserved_root(JMS.canon(os.fsencode(agents.parent))))
            self.assertFalse(JMS.reserved_root(JMS.canon(os.fsencode(home / "git"))))


class ConsentTests(unittest.TestCase):
    def approve(self, root, tf, argv, action="build", config=None, answers=(), tty=True):
        args = JMS.parse_cli(argv)
        replies = list(answers)
        self.questions = []
        def reply(question):
            self.questions.append(question)
            return replies.pop(0)
        with mock.patch.object(JMS, "consent_input", side_effect=reply), \
             mock.patch.object(sys, "stdin", TTYIO(tty)), \
             mock.patch.object(sys, "stderr", TTYIO(tty)):
            return JMS.approve(root, tf, args, action=action, config=config)

    def test_consent_read_survives_a_leaked_nonblocking_terminal(self):
        # An attached `container run --interactive` exits with O_NONBLOCK
        # left on the shared terminal description; the consent read must not
        # turn that leak into an instant default-No EOF.
        master, slave = pty.openpty()
        try:
            os.set_blocking(slave, False)
            os.write(master, b"y\n")
            reader = os.fdopen(slave, "r", closefd=False)
            with mock.patch.object(sys, "stdin", reader), \
                 mock.patch.object(sys, "stderr", TTYIO(True)):
                self.assertEqual(JMS.consent_input("Allow? "), "y")
            self.assertTrue(os.get_blocking(slave))
        finally:
            os.close(master)
            os.close(slave)

    def test_trust_flag_is_one_shot_and_never_writes(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            result = self.approve(root, "a" * 64, ["build", "--trust"], tty=False)
            self.assertEqual(result, (True, False))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_env_pin_grants_on_match_and_fails_on_mismatch(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            with mock.patch.dict(os.environ, {"JMS_TRUST_FINGERPRINT": "a" * 64}):
                self.assertEqual(self.approve(root, "a" * 64, ["build"], tty=False),
                                 (True, False))
                with self.assertRaisesRegex(JMS.TrustError, "JMS_TRUST_FINGERPRINT"):
                    self.approve(root, "b" * 64, ["build"], tty=False)

    def test_trust_auth_combination_is_not_a_non_interactive_credential_bypass(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            with self.assertRaisesRegex(JMS.TrustError, "prompting is unavailable"):
                self.approve(root, "a" * 64, ["launch", "--trust", "--auth"],
                             action="launch", tty=False)
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_trust_auth_asks_the_credential_question_on_a_tty(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            self.assertEqual(self.approve(root, "a" * 64, ["launch", "--trust", "--auth"],
                                          action="launch", answers=["y"]), (True, True))
            self.assertEqual(self.approve(root, "a" * 64, ["launch", "--trust", "--auth"],
                                          action="launch", answers=[""]), (True, False))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_trust_auth_escalation_leaves_a_stored_grant_unchanged(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            pid = hashlib.sha256(root).hexdigest()
            self.approve(root, "a" * 64, ["build"], answers=["y", ""])
            granted_at = JMS.read_store()["projects"][pid]["granted_at"]
            self.assertEqual(self.approve(root, "a" * 64, ["launch", "--trust", "--auth"],
                                          action="launch", answers=["y"]), (True, True))
            record = JMS.read_store()["projects"][pid]
            self.assertEqual(record["grants"], {"build_run": True, "auth": False})
            self.assertEqual(record["granted_at"], granted_at)

    def test_env_pin_with_auth_grants_credentials_one_shot(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            with mock.patch.dict(os.environ, {"JMS_TRUST_FINGERPRINT": "a" * 64}):
                self.assertEqual(self.approve(root, "a" * 64, ["launch", "--auth"],
                                              action="launch", tty=False), (True, True))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_fingerprint_pin_records_durable_trust_non_interactively(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            tf = "c" * 64
            result = self.approve(root, tf, ["trust", "--fingerprint", tf, "--auth"],
                                  action="trust", tty=False)
            self.assertEqual(result, (True, True))
            pid = hashlib.sha256(root).hexdigest()
            record = JMS.read_store()["projects"][pid]
            self.assertEqual(record["tf"], tf)
            self.assertEqual(record["grants"], {"build_run": True, "auth": True})
            self.assertEqual(record["root"], root.decode())
            with self.assertRaisesRegex(JMS.TrustError, "--fingerprint does not match"):
                self.approve(root, "d" * 64, ["trust", "--fingerprint", tf], action="trust")

    def test_prompting_unavailable_fails_closed(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            with self.assertRaisesRegex(JMS.TrustError, "prompting is unavailable") as caught:
                self.approve(root, "a" * 64, ["build"], tty=False)
            self.assertEqual(caught.exception.exit_code, 3)

    def test_interactive_grant_and_decline_matrix(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            pid = hashlib.sha256(root).hexdigest()
            self.assertEqual(self.approve(root, "a" * 64, ["build"], answers=["y", "y"]),
                             (True, True))
            self.assertEqual(JMS.read_store()["projects"][pid]["grants"],
                             {"build_run": True, "auth": True})
            with self.assertRaisesRegex(JMS.TrustError, "declined"):
                self.approve(root, "b" * 64, ["build"], answers=["n"])
            self.assertEqual(self.approve(root, "b" * 64, ["build"], answers=["y", ""]),
                             (True, False))
            self.assertEqual(JMS.read_store()["projects"][pid]["grants"],
                             {"build_run": True, "auth": False})

    def test_stored_grant_is_reused_without_prompting(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            self.approve(root, "a" * 64, ["build"], answers=["y", "y"])
            self.assertEqual(self.approve(root, "a" * 64, ["build"], tty=False), (True, True))
            self.assertEqual(self.approve(root, "a" * 64, ["build", "--no-auth"], tty=False),
                             (True, False))

    def test_fingerprint_change_requires_fresh_consent_for_both_grants(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            pid = hashlib.sha256(root).hexdigest()
            self.approve(root, "a" * 64, ["build"], answers=["y", "y"])
            with self.assertRaisesRegex(JMS.TrustError, "prompting is unavailable"):
                self.approve(root, "b" * 64, ["build"], tty=False)
            self.assertEqual(self.approve(root, "b" * 64, ["build"], answers=["y", ""]),
                             (True, False))
            self.assertEqual(JMS.read_store()["projects"][pid]["grants"]["auth"], False)

    def test_trust_action_replaces_decisions_even_when_stored(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            self.approve(root, "a" * 64, ["build"], answers=["y", "y"])
            self.assertEqual(self.approve(root, "a" * 64, ["trust"], action="trust",
                                          answers=["y", ""]), (True, False))

    def test_credential_question_names_agent_state_and_credentials(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            self.approve(root, "a" * 64, ["build"], answers=["y", "y"])
            self.assertEqual(len(self.questions), 2)
            self.assertIn("persistent agent state", self.questions[1])
            self.assertIn("credentials", self.questions[1])

    def test_auth_escalation_prompts_and_records(self):
        with sandbox() as home:
            root = JMS.canon(os.fsencode(make_project(home)))
            pid = hashlib.sha256(root).hexdigest()
            self.approve(root, "a" * 64, ["build"], answers=["y", ""])
            result = self.approve(root, "a" * 64, ["launch", "--auth"], action="launch",
                                  answers=["y"])
            self.assertEqual(result, (True, True))
            self.assertEqual(JMS.read_store()["projects"][pid]["grants"]["auth"], True)


class CliSurfaceTests(unittest.TestCase):
    def reject(self, argv):
        with quiet(), self.assertRaises(SystemExit) as caught:
            JMS.parse_cli(argv)
        self.assertEqual(caught.exception.code, 2)

    def test_launch_preserves_the_double_dash_tail(self):
        args = JMS.parse_cli(["launch", "demo", "--", "echo", "--not-a-flag"])
        self.assertEqual(args.extra, ["echo", "--not-a-flag"])
        self.assertEqual(args.name, "demo")
        args = JMS.parse_cli(["launch"])
        self.assertEqual(args.extra, [])

    def test_flag_combination_errors(self):
        with sandbox():
            cases = (
                (JMS.cmd_build, ["build", "--base", "-w", "/tmp"], "--base cannot be combined"),
                (JMS.cmd_build, ["build", "--pull"], "--pull is valid only with --base"),
                (JMS.cmd_launch, ["launch", "--auth", "--no-auth"], "cannot be combined"),
                (JMS.cmd_launch, ["launch", "demo", "-w", "/tmp"], "cannot be combined"),
                (JMS.cmd_inspect, ["inspect", "demo", "-w", "/tmp"], "cannot be combined"),
                (JMS.cmd_clean, ["clean", "--all", "-w", "/tmp"], "cannot be combined"),
                (JMS.cmd_trust, ["trust", "list", "--purge-images"], "--purge-images is valid only"),
                (JMS.cmd_trust, ["trust", "list", "--auth"], "valid only when approving"),
            )
            for function, argv, message in cases:
                with self.subTest(argv=argv):
                    with self.assertRaisesRegex(JMS.UsageError, message):
                        function(JMS.parse_cli(argv))

    def test_launch_rejects_empty_runtime_arguments_before_discovery(self):
        for argv, message in ((["launch", "-b", ""], "binary must be nonempty"),
                              (["launch", "-n", ""], "container name must be nonempty")):
            with self.subTest(argv=argv), mock.patch.object(JMS, "resolve_operand") as resolve:
                with self.assertRaisesRegex(JMS.UsageError, message):
                    JMS.cmd_launch(JMS.parse_cli(argv))
                resolve.assert_not_called()

    def test_version_is_reported(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit):
            JMS.parse_cli(["--version"])
        self.assertEqual(stdout.getvalue().strip(), "1.1.0")


class BuildTests(unittest.TestCase):
    BACKEND = "container"
    EXE = "container"
    PULL_FLAG = "--pull"

    def build_args(self, *extra):
        return JMS.parse_cli(["build", *extra])

    def fake(self, **kwargs):
        return fake_runtime(backend=self.BACKEND, **kwargs)

    def test_project_build_uses_spec_as_context_with_identity_labels(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            with self.fake() as runtime, contextlib.redirect_stdout(io.StringIO()):
                tag, built = JMS.build_project(data, self.build_args("--trust"))
            self.assertTrue(built)
            self.assertEqual(tag, data["tag_prefix"] + ":" + data["tf"][:12])
            build = next(call["argv"] for call in runtime.calls if call["argv"][:2] == [self.EXE, "build"])
            spec_text = os.fsdecode(data["spec"])
            self.assertEqual(build[-1], spec_text)
            self.assertIn("--file", build)
            self.assertEqual(build[build.index("--file") + 1], spec_text + "/Containerfile")
            self.assertIn("jms.project=" + data["pid"], build)
            self.assertIn("jms.fingerprint=" + data["tf"], build)
            self.assertNotIn("--no-cache", build)
            # No pull refresh: project builds never re-pull (podman's explicit
            # --pull=missing is the no-refresh spelling on that backend).
            self.assertNotIn(self.PULL_FLAG, build)

    def test_fingerprint_reuse_and_no_cache_rebuild(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            with self.fake(images={tag: image_record(tag)}) as runtime, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(JMS.build_project(data, self.build_args()), (tag, False))
                self.assertEqual(runtime.build_count, 0)
                self.assertEqual(JMS.build_project(data, self.build_args("--no-cache")),
                                 (tag, True))
                build = next(call["argv"] for call in runtime.calls
                             if call["argv"][:2] == [self.EXE, "build"])
                self.assertIn("--no-cache", build)

    def test_pull_without_base_is_rejected_with_the_update_recipe(self):
        with sandbox() as home:
            make_project(home)
            with self.fake() as runtime:
                with self.assertRaisesRegex(JMS.UsageError,
                                            "jms build --base --pull --no-cache") as caught:
                    JMS.cmd_build(self.build_args("--pull"))
            self.assertIn("local-only", str(caught.exception))
            self.assertEqual(runtime.calls, [])

    def test_definition_change_between_consent_and_build_fails_closed(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            (root / ".jmscontainer" / "Containerfile").write_bytes(b"FROM sneaky\n")
            with self.fake() as runtime:
                with self.assertRaisesRegex(JMS.JMSException, "changed during consent"):
                    JMS.build_project(data, self.build_args())
                self.assertEqual(runtime.build_count, 0)

    def test_project_build_failure_names_the_context_rule(self):
        with sandbox() as home:
            root = make_project(home, containerfile=b"FROM x\nCOPY ../src /src\n")
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            stderr = io.StringIO()
            with self.fake(build_error="command failed: container build"), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(JMS.JMSException, "command failed"):
                    JMS.build_project(data, self.build_args())
            self.assertIn(".jmscontainer/ only", stderr.getvalue())

    def test_base_build_failure_has_no_context_note(self):
        stderr = io.StringIO()
        with self.fake(build_error="command failed"), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(stderr):
            with self.assertRaises(JMS.JMSException):
                JMS.build_base(self.build_args("--base"))
        self.assertNotIn(".jmscontainer", stderr.getvalue())

    def test_base_build_uses_the_repo_as_context(self):
        with self.fake() as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.build_base(self.build_args("--base", "--pull", "--no-cache"))
        build = runtime.calls[-1]["argv"]
        repo = os.fsdecode(JMS.canon(os.fsencode(pathlib.Path(JMS.__file__).resolve().parent.parent)))
        self.assertEqual(build[build.index("--tag") + 1], JMS.BASE)
        self.assertEqual(build[build.index("--file") + 1], repo + "/Containerfile")
        self.assertEqual(build[-1], repo)
        self.assertIn("--no-cache", build)
        self.assertIn(self.PULL_FLAG, build)

    def test_cmd_build_without_project_builds_base(self):
        with sandbox() as home:
            (home / "git" / "plain").mkdir()
            with self.fake() as runtime, contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_build(JMS.parse_cli(["build", "-w", str(home / "git" / "plain")]))
            build = next(call["argv"] for call in runtime.calls if call["argv"][:2] == [self.EXE, "build"])
            self.assertEqual(build[build.index("--tag") + 1], JMS.BASE)

    def test_newest_two_images_are_kept_per_project(self):
        pid = "f" * 64
        def owned(ref, minute):
            return image_record(ref, created="2026-01-01T00:%02d:00Z" % minute,
                                labels={"jms.project": pid, "jms.fingerprint": "a" * 64})
        images = {
            "p:1": owned("p:1", 1), "p:2": owned("p:2", 2),
            "p:3": owned("p:3", 3), "p:4": owned("p:4", 4),
            # An inherited/copied label without the jms tag prefix is not
            # proof of ownership and must never be evicted.
            "squatter:1": owned("squatter:1", 0),
            "other:1": image_record("other:1", labels={"jms.project": "0" * 64}),
            "plain:1": image_record("plain:1"),
        }
        with self.fake(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=2)
        self.assertEqual(sorted(runtime.deleted), ["p:1", "p:2"])

    def test_protected_tag_survives_an_equal_timestamp_tie(self):
        pid = "f" * 64
        # Runtime creation times are whole seconds, so a build landing in the
        # same second as an earlier one ties and falls back to digest order.
        # The protected tag is deliberately the one whose digest sorts last:
        # the case that untagged the caller's own image before `protect`.
        refs = sorted(["p:1", "p:2", "p:3"], key=fake_hex_id)
        current = refs[-1]
        images = {ref: image_record(ref, created="2026-01-01T00:00:00Z",
                                    labels={"jms.project": pid}) for ref in refs}
        with self.fake(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=2, protect=current)
        self.assertNotIn(current, runtime.deleted)
        self.assertEqual(len(runtime.deleted), 1)

    def test_protection_consumes_a_retention_slot(self):
        pid = "f" * 64
        def owned(ref, minute):
            return image_record(ref, created="2026-01-01T00:%02d:00Z" % minute,
                                labels={"jms.project": pid})
        images = {"p:old": owned("p:old", 1), "p:mid": owned("p:mid", 2),
                  "p:new": owned("p:new", 3)}
        with self.fake(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=2, protect="p:old")
        # Still two survivors, not three: protection reorders retention, it
        # does not widen it.
        self.assertEqual(runtime.deleted, ["p:mid"])

    def test_build_never_untags_the_image_it_returns(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            # Two earlier builds of this project sharing the second the new
            # build lands in (the fake stamps build #1 at 00:00:01Z).
            stale = {}
            for suffix in ("a" * 12, "b" * 12):
                ref = data["tag_prefix"] + ":" + suffix
                stale[ref] = image_record(ref, created="2026-01-01T00:00:01Z",
                                          labels={"jms.project": data["pid"]})
            with self.fake(images=stale) as runtime, contextlib.redirect_stdout(io.StringIO()):
                tag, built = JMS.build_project(data, self.build_args("--trust"))
        self.assertTrue(built)
        self.assertNotIn(tag, runtime.deleted)

    def test_trust_revoke_purge_removes_every_project_image(self):
        pid = "f" * 64
        images = {"p:1": image_record("p:1", labels={"jms.project": pid}),
                  "squatter:1": image_record("squatter:1", labels={"jms.project": pid})}
        with self.fake(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=0)
        self.assertEqual(runtime.deleted, ["p:1"])


class BuildTestsPodman(BuildTests):
    BACKEND = "podman"
    EXE = "podman"
    PULL_FLAG = "--pull=always"


class RuntimeGateTests(unittest.TestCase):
    def probe(self, version_line, returncode=0):
        def fake(argv, **kwargs):
            if argv[:2] == ["container", "--version"]:
                return types.SimpleNamespace(returncode=returncode, stdout=version_line, stderr=b"")
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(JMS, "runtime_run", fake):
            JMS.runtime_ready()

    def test_version_gate(self):
        self.probe(b"container CLI version 1.2.0 (build: release, commit: x)\n")
        with self.assertRaisesRegex(JMS.JMSException, "too old"):
            self.probe(b"container CLI version 1.1.9\n")
        with self.assertRaisesRegex(JMS.JMSException, "newer than the newest runtime"):
            self.probe(b"container CLI version 1.3.0\n")
        with self.assertRaisesRegex(JMS.JMSException, "cannot parse"):
            self.probe(b"something else\n")
        with self.assertRaisesRegex(JMS.JMSException, "cannot parse"):
            self.probe(b"container CLI version 1.2.0\n", returncode=1)

    def test_runtime_accept_pin_admits_one_exact_newer_version(self):
        newer = b"container CLI version 1.3.0\n"
        with mock.patch.dict(os.environ, {"JMS_RUNTIME_ACCEPT": "1.3.0"}):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.probe(newer)
            self.assertIn("not qualified", stderr.getvalue())
            self.assertIn("JMS_RUNTIME_ACCEPT", stderr.getvalue())
        with mock.patch.dict(os.environ, {"JMS_RUNTIME_ACCEPT": "1.4.0"}):
            with self.assertRaisesRegex(JMS.JMSException, "newer than the newest runtime"):
                self.probe(newer)
        with mock.patch.dict(os.environ, {"JMS_RUNTIME_ACCEPT": "1.1.9"}):
            with self.assertRaisesRegex(JMS.JMSException, "too old"):
                self.probe(b"container CLI version 1.1.9\n")
        with self.assertRaisesRegex(JMS.JMSException, "JMS_RUNTIME_ACCEPT=1.3.0"):
            self.probe(newer)

    def test_runtime_json_rejects_invalid_payloads(self):
        with fake_runtime() as runtime:
            runtime.images = {}
            self.assertEqual(JMS.image_facts(), [])
        def fake(argv, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout=b"not json", stderr=b"")
        with mock.patch.object(JMS, "runtime_run", fake):
            with self.assertRaisesRegex(JMS.JMSException, "invalid JSON"):
                JMS.runtime_json(["container", "image", "list", "--format", "json"])

    def test_image_exists_distinguishes_absence_from_failure(self):
        def fake(stderr_line):
            def run(argv, **kwargs):
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=stderr_line)
            return run
        with mock.patch.object(JMS, "runtime_run", fake(b"Error: image not found: x:1\n")):
            self.assertFalse(JMS.image_exists("x:1"))
        with mock.patch.object(JMS, "runtime_run", fake(b"Error: connection refused\n")):
            with self.assertRaisesRegex(JMS.JMSException, "image inspect failed"):
                JMS.image_exists("x:1")


class LaunchTests(unittest.TestCase):
    BACKEND = "container"
    EXE = "container"
    USER_ISOLATION = "isolation"
    USER_ROOT = "root"
    MOUNT = "source="

    def launch_argv(self, home, argv, images=None, containers=None, trusted_auth=False):
        """Run cmd_launch against the fake runtime; return the exec argv."""
        with fake_runtime(backend=self.BACKEND, images=dict(images or {})) as runtime, \
             mock.patch.object(JMS, "ensure_agent_state_directory"), \
             contextlib.redirect_stdout(io.StringIO()), quiet():
            JMS.cmd_launch(JMS.parse_cli(argv))
        replaced = [call for call in runtime.calls if call["replace"]]
        self.assertEqual(len(replaced), 1)
        return replaced[0]["argv"]

    def test_project_launch_argv_shape(self):
        with sandbox() as home:
            manifest = (b'[env]\nFOO = "bar"\n')
            root = make_project(home, manifest=manifest)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(
                home, ["launch", "--trust", "--no-auth", "-w", str(root), "--", "-c", "true"],
                images={tag: image_record(tag)})
            self.assertEqual(argv[:4], [self.EXE, "run", "--rm", "--interactive"])
            self.assertEqual(argv[argv.index("--user") + 1], self.USER_ISOLATION)
            self.assertEqual(argv[argv.index("--workdir") + 1], "/work")
            self.assertEqual(argv[argv.index("--entrypoint") + 1], "/bin/bash")
            self.assertIn("FOO=bar", argv)
            self.assertIn("jms.project=" + data["pid"], argv)
            root_text = os.fsdecode(JMS.canon(os.fsencode(root)))
            self.assertIn(self.MOUNT + root_text + ",target=/work", argv)
            self.assertIn(tag, argv)
            self.assertEqual(argv[-2:], ["-c", "true"])
            self.assertNotIn("/.claude", " ".join(argv[argv.index("--mount"):]))
            self.assertNotIn("CLAUDE_CONFIG_DIR=/home/isolation/.claude", argv)

    def test_root_flag_switches_user_and_home(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "--trust", "--no-auth", "--root",
                                           "-b", "/bin/sh", "-w", str(root)],
                                    images={tag: image_record(tag)})
            self.assertEqual(argv[argv.index("--user") + 1], self.USER_ROOT)
            self.assertEqual(argv[argv.index("--entrypoint") + 1], "/bin/sh")
            self.assertNotIn("CLAUDE_CONFIG_DIR=/root/.claude", argv)

    def test_auth_grant_mounts_credential_directories(self):
        with sandbox() as home:
            root = make_project(home)
            canonical = JMS.canon(os.fsencode(root))
            data = JMS.project_data(canonical)
            pid = hashlib.sha256(canonical).hexdigest()
            def add(store):
                store["projects"][pid] = {
                    "root": canonical.decode(), "tf": data["tf"],
                    "grants": {"build_run": True, "auth": True},
                    "granted_at": "2026-01-01T00:00:00Z", "jms_version": JMS.__version__}
                return True
            JMS.update_store(add)
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "-w", str(root)],
                                    images={tag: image_record(tag)})
            mounts = " ".join(argv)
            agents = str(JMS.agent_state_root())
            self.assertIn(self.MOUNT + agents + "/claude,target=/home/isolation/.claude", mounts)
            self.assertIn("target=/home/isolation/.codex", mounts)
            self.assertIn("target=/home/isolation/.local/share/opencode", mounts)
            self.assertIn("target=/home/isolation/.config/opencode", mounts)
            self.assertIn("CLAUDE_CONFIG_DIR=/home/isolation/.claude", argv)

    def test_launch_without_project_uses_the_shared_base(self):
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            argv = self.launch_argv(home, ["launch", "--no-auth", "-w", str(plain)],
                                    images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn(JMS.BASE, argv)
            self.assertEqual(argv[argv.index("--workdir") + 1], "/work")

    def test_shell_config_mounts_read_only_for_both_users(self):
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            shell = str(JMS.shell_state_root())
            argv = self.launch_argv(home, ["launch", "--no-auth", "-w", str(plain)],
                                    images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn(self.MOUNT + shell + ",target=/home/isolation/.config/jms-shell,readonly",
                          argv)
            self.assertTrue(JMS.shell_state_root().is_dir())
            argv = self.launch_argv(home, ["launch", "--no-auth", "--root", "-w", str(plain)],
                                    images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn(self.MOUNT + shell + ",target=/root/.config/jms-shell,readonly", argv)

    def test_shell_config_symlink_source_is_rejected_before_the_runtime(self):
        with sandbox() as home:
            data = home / ".local" / "share" / "jmscontainers"
            data.mkdir(parents=True)
            (data / "shell").symlink_to(home)
            plain = home / "git" / "plain"
            plain.mkdir()
            with self.assertRaisesRegex(JMS.JMSException, "shell config source must be a directory"):
                JMS.cmd_launch(JMS.parse_cli(["launch", "--no-auth", "-w", str(plain)]))

    def test_launch_rejects_protected_workdir(self):
        with sandbox() as home:
            config = home / ".config" / "jmscontainers"
            config.mkdir(parents=True)
            with self.assertRaisesRegex(JMS.JMSException, "protected jms host directory"):
                JMS.cmd_launch(JMS.parse_cli(["launch", "-w", str(config)]))

    def test_launch_defaulted_to_cwd_inside_checkout_is_rejected(self):
        with sandbox():
            checkout = os.fsdecode(JMS.checkout_root())
            with mock.patch.object(os, "getcwd", return_value=checkout):
                with self.assertRaisesRegex(JMS.JMSException, "protected jms host directory"):
                    JMS.cmd_launch(JMS.parse_cli(["launch"]))

    def test_launch_outside_a_checkout_requires_an_explicit_workdir(self):
        with sandbox() as home:
            outside = home / "elsewhere"
            outside.mkdir()
            with mock.patch.object(os, "getcwd", return_value=str(outside)):
                with self.assertRaisesRegex(JMS.UsageError, "not inside a checkout"):
                    JMS.cmd_launch(JMS.parse_cli(["launch"]))

    def test_launch_refuses_home_even_when_home_is_a_repository(self):
        with sandbox() as home:
            (home / ".git").mkdir()
            canonical = JMS.canon(os.fsencode(home))
            self.assertIsNone(JMS.vcs_root(canonical))
            self.assertIsNotNone(JMS.implicit_workdir_refusal(canonical))
            with mock.patch.object(os, "getcwd", return_value=str(home)):
                with self.assertRaises(JMS.JMSException):
                    JMS.cmd_launch(JMS.parse_cli(["launch"]))

    def test_launch_defaults_to_a_checkout_cwd_wherever_it_lives(self):
        """An implicit launch works outside ~/git; the checkout is the signal."""
        with sandbox() as home:
            anywhere = home / "elsewhere" / "proj"
            anywhere.mkdir(parents=True)
            (anywhere / ".git").mkdir()
            canonical = JMS.canon(os.fsencode(anywhere))
            self.assertIsNone(JMS.implicit_workdir_refusal(canonical))
            with mock.patch.object(os, "getcwd", return_value=str(anywhere)):
                argv = self.launch_argv(home, ["launch", "--no-auth"],
                                        images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn(self.MOUNT + os.fsdecode(canonical) + ",target=/work",
                          " ".join(argv))

    def test_preserve_host_path_mounts_the_project_at_its_own_path(self):
        with sandbox() as home:
            root = make_project(home, manifest=b"[run]\npreserve_host_path = true\n")
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "--trust", "--no-auth", "-w", str(root)],
                                    images={tag: image_record(tag)})
            root_text = os.fsdecode(JMS.canon(os.fsencode(root)))
            self.assertEqual(argv[argv.index("--workdir") + 1], root_text)
            self.assertIn(self.MOUNT + root_text + ",target=" + root_text, argv)
            self.assertNotIn("/work", " ".join(argv))

    def test_preserve_host_path_keeps_the_inner_workdir_suffix(self):
        with sandbox() as home:
            root = make_project(home, manifest=b"[run]\npreserve_host_path = true\n")
            inner = root / "sub" / "deeper"
            inner.mkdir(parents=True)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "--trust", "--no-auth", "-w", str(inner)],
                                    images={tag: image_record(tag)})
            root_text = os.fsdecode(JMS.canon(os.fsencode(root)))
            self.assertEqual(argv[argv.index("--workdir") + 1], root_text + "/sub/deeper")

    def test_default_project_mount_is_unchanged_without_the_key(self):
        """The opt-in is the only thing that moves the mount; absence is "/work"."""
        with sandbox() as home:
            root = make_project(home, manifest=b"[run]\npreserve_host_path = false\n")
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "--trust", "--no-auth", "-w", str(root)],
                                    images={tag: image_record(tag)})
            self.assertEqual(argv[argv.index("--workdir") + 1], "/work")
            root_text = os.fsdecode(JMS.canon(os.fsencode(root)))
            self.assertIn(self.MOUNT + root_text + ",target=/work", argv)


    def test_launch_inherits_the_host_timezone(self):
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            argv = self.launch_argv(home, ["launch", "--no-auth", "-w", str(plain)],
                                    images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn("TZ=" + SANDBOX_ZONE, argv)

    def test_manifest_timezone_replaces_the_inherited_one(self):
        """A pinned zone is emitted once: no reliance on the runtime's last-wins."""
        with sandbox() as home:
            root = make_project(home, manifest=b'[env]\nTZ = "Europe/Berlin"\n')
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            argv = self.launch_argv(home, ["launch", "--trust", "--no-auth", "-w", str(root)],
                                    images={tag: image_record(tag)})
            self.assertEqual([value for value in argv if value.startswith("TZ=")],
                             ["TZ=Europe/Berlin"])

    def test_launch_omits_tz_when_the_host_states_no_zone(self):
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            with mock.patch.object(JMS, "host_timezone", lambda: None):
                argv = self.launch_argv(home, ["launch", "--no-auth", "-w", str(plain)],
                                        images={JMS.BASE: image_record(JMS.BASE)})
            self.assertFalse([value for value in argv if value.startswith("TZ=")])


class LaunchTestsPodman(LaunchTests):
    BACKEND = "podman"
    EXE = "podman"
    USER_ISOLATION = "1000:1000"
    USER_ROOT = "0:0"
    MOUNT = "type=bind,source="


class TimezoneTests(unittest.TestCase):
    """Host-zone resolution: every source, and nothing that is not a real zone."""

    @contextlib.contextmanager
    def zoneinfo(self, *names, prefix=""):
        """A fake zoneinfo tree, its roots tuple, and a directory to link from."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / prefix if prefix else pathlib.Path(tmp)
            for name in names:
                zone = root / name
                zone.parent.mkdir(parents=True, exist_ok=True)
                zone.write_bytes(b"TZif2")
            root.mkdir(parents=True, exist_ok=True)
            yield pathlib.Path(tmp), (str(root) + "/",)

    def resolve(self, roots, tmp, tz=None, link=None, timezone_file=None):
        env = {} if tz is None else {"TZ": tz}
        localtime = str(tmp / "localtime")
        if link is not None:
            os.symlink(link, localtime)
        stamp = str(tmp / "timezone")
        if timezone_file is not None:
            pathlib.Path(stamp).write_text(timezone_file, encoding="utf-8")
        with mock.patch.dict(os.environ, env, clear=True):
            return JMS.host_timezone(roots=roots, localtime=localtime, timezone_file=stamp)

    def test_tz_environment_wins_over_the_symlink(self):
        with self.zoneinfo("America/Los_Angeles", "Europe/Berlin") as (tmp, roots):
            self.assertEqual(
                self.resolve(roots, tmp, tz="America/Los_Angeles",
                             link=roots[0] + "Europe/Berlin"),
                "America/Los_Angeles")

    def test_posix_leading_colon_is_stripped(self):
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertEqual(self.resolve(roots, tmp, tz=":America/Los_Angeles"),
                             "America/Los_Angeles")

    def test_posix_rule_string_falls_through_to_the_symlink(self):
        """TZ="PST8PDT,M3.2.0,M11.1.0" names a rule, not a zone file."""
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertEqual(
                self.resolve(roots, tmp, tz="PST8PDT,M3.2.0,M11.1.0",
                             link=roots[0] + "America/Los_Angeles"),
                "America/Los_Angeles")

    def test_absolute_symlink_resolves(self):
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertEqual(self.resolve(roots, tmp, link=roots[0] + "America/Los_Angeles"),
                             "America/Los_Angeles")

    def test_relative_symlink_resolves(self):
        """Debian links /etc/localtime relatively; the target is not absolute."""
        with self.zoneinfo("America/Los_Angeles", prefix="usr/share") as (tmp, roots):
            self.assertEqual(self.resolve(roots, tmp, link="usr/share/America/Los_Angeles"),
                             "America/Los_Angeles")

    def test_macos_zoneinfo_root_is_stripped(self):
        with self.zoneinfo("America/Los_Angeles",
                           prefix="private/var/db/timezone/zoneinfo") as (tmp, roots):
            self.assertEqual(self.resolve(roots, tmp, link=roots[0] + "America/Los_Angeles"),
                             "America/Los_Angeles")

    def test_shipped_roots_cover_both_macos_forms(self):
        """/var is a symlink to /private/var, so a resolved target takes either form."""
        for root in ("/var/db/timezone/zoneinfo/", "/private/var/db/timezone/zoneinfo/",
                     "/usr/share/zoneinfo/"):
            self.assertIn(root, JMS.ZONEINFO_ROOTS)

    def test_etc_timezone_is_the_last_resort(self):
        with self.zoneinfo("Europe/Berlin") as (tmp, roots):
            self.assertEqual(self.resolve(roots, tmp, timezone_file="Europe/Berlin\n"),
                             "Europe/Berlin")

    def test_a_host_stating_no_zone_yields_none(self):
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertIsNone(self.resolve(roots, tmp))

    def test_a_name_absent_from_the_tree_is_refused(self):
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertIsNone(self.resolve(roots, tmp, tz="Mars/Olympus"))

    def test_traversal_and_injection_attempts_are_refused(self):
        """TZ is host input that becomes runtime argv; the grammar is the gate."""
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            for hostile in ("../../etc/passwd", "/etc/passwd", "America/../../etc/passwd",
                            "America/Los_Angeles ", "America Los_Angeles",
                            "America/Los_Angeles\nFOO=bar", "-x", ""):
                self.assertIsNone(self.resolve(roots, tmp, tz=hostile), hostile)

    def test_a_directory_is_not_a_zone(self):
        with self.zoneinfo("America/Los_Angeles") as (tmp, roots):
            self.assertIsNone(self.resolve(roots, tmp, tz="America"))


class TrustCommandTests(unittest.TestCase):
    def run_trust(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), quiet():
            JMS.cmd_trust(JMS.parse_cli(argv))
        return stdout.getvalue()

    def seed(self, home, name="demo"):
        root = make_project(home, name=name)
        canonical = JMS.canon(os.fsencode(root))
        tf = fingerprint_of(root)
        self.run_trust(["trust", str(root), "--fingerprint", tf])
        return root, canonical, tf

    def test_trust_list_revoke_and_prune_lifecycle(self):
        with sandbox() as home:
            root, canonical, _ = self.seed(home)
            pid = hashlib.sha256(canonical).hexdigest()
            listing = self.run_trust(["trust", "list"])
            self.assertIn(pid[:12], listing)
            self.assertIn("present", listing)
            self.assertIn("auth=no", listing)
            output = self.run_trust(["trust", "revoke", str(root)])
            self.assertIn("revoked trust for", output)
            self.assertEqual(JMS.read_store()["projects"], {})
            with self.assertRaisesRegex(JMS.JMSException, "no trust record"):
                self.run_trust(["trust", "revoke", str(root)])

    def test_prune_removes_only_missing_roots(self):
        with sandbox() as home:
            keep_root, _, _ = self.seed(home, "keep")
            gone_root, gone_canonical, _ = self.seed(home, "gone")
            import shutil
            shutil.rmtree(gone_root)
            output = self.run_trust(["trust", "prune"])
            self.assertIn("pruned trust record", output)
            projects = JMS.read_store()["projects"]
            self.assertEqual(len(projects), 1)
            self.assertNotIn(hashlib.sha256(gone_canonical).hexdigest(), projects)

    def test_revoke_purge_images_removes_project_images(self):
        with sandbox() as home:
            root, canonical, _ = self.seed(home)
            pid = hashlib.sha256(canonical).hexdigest()
            mine = JMS.tag_prefix_for(canonical, pid) + ":aaaaaaaaaaaa"
            images = {mine: image_record(mine, labels={"jms.project": pid}),
                      "squatter:1": image_record("squatter:1", labels={"jms.project": pid})}
            with fake_runtime(images=images) as runtime:
                self.run_trust(["trust", "revoke", str(root), "--purge-images"])
            self.assertEqual(runtime.deleted, [mine])

    def test_trust_requires_a_project_definition(self):
        with sandbox() as home:
            (home / "git" / "plain").mkdir()
            with self.assertRaisesRegex(JMS.JMSException, "no project container definition"):
                self.run_trust(["trust", str(home / "git" / "plain")])


class InspectTests(unittest.TestCase):
    def inspect(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), quiet():
            JMS.cmd_inspect(JMS.parse_cli(argv))
        return dict(line.split(": ", 1) for line in stdout.getvalue().splitlines())

    def test_project_report_fields(self):
        with sandbox() as home:
            root = make_project(home)
            report = self.inspect(["inspect", "-w", str(root)])
            self.assertEqual(report["trust_fingerprint"], GOLDEN_SINGLE_TF)
            self.assertEqual(report["trust_source"], "none")
            self.assertEqual(report["build_run_grant"], "required")
            self.assertEqual(report["trust_store"], "readable")
            self.assertTrue(report["target_image"].startswith("jmscontainers-demo-"))
            self.assertTrue(report["target_image"].endswith(GOLDEN_SINGLE_TF[:12]))

    def test_trust_source_states(self):
        with sandbox() as home:
            root = make_project(home)
            canonical = JMS.canon(os.fsencode(root))
            tf = fingerprint_of(root)
            with quiet(), contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
            self.assertEqual(self.inspect(["inspect", "-w", str(root)])["trust_source"],
                             "trust store")
            (root / ".jmscontainer" / "Containerfile").write_bytes(b"FROM changed\n")
            report = self.inspect(["inspect", "-w", str(root)])
            self.assertEqual(report["trust_source"], "stale trust-store record")
            self.assertEqual(report["build_run_grant"], "required")
            new_tf = fingerprint_of(root)
            with mock.patch.dict(os.environ, {"JMS_TRUST_FINGERPRINT": new_tf}):
                report = self.inspect(["inspect", "-w", str(root)])
            self.assertEqual(report["trust_source"], "JMS_TRUST_FINGERPRINT (one-shot)")
            self.assertEqual(report["build_run_grant"], "held")
            with mock.patch.dict(os.environ, {"JMS_TRUST_FINGERPRINT": "0" * 64}):
                report = self.inspect(["inspect", "-w", str(root)])
            self.assertEqual(report["trust_source"], "JMS_TRUST_FINGERPRINT mismatch")

    def test_non_project_report(self):
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            report = self.inspect(["inspect", "-w", str(plain)])
            self.assertEqual(report["spec"], "shared base")
            self.assertEqual(report["target_image"], JMS.BASE)
            self.assertNotIn("trust_fingerprint", report)


class InitTests(unittest.TestCase):
    def test_init_scaffolds_a_project(self):
        with sandbox() as home:
            workdir = home / "git" / "fresh"
            workdir.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_init(JMS.parse_cli(["init", "-w", str(workdir)]))
            containerfile = (workdir / ".jmscontainer" / "Containerfile").read_text()
            self.assertIn("FROM " + JMS.BASE, containerfile)
            self.assertFalse((workdir / ".jmscontainer" / "jmscontainer.toml").exists())
            with self.assertRaisesRegex(JMS.JMSException, "already exists"):
                JMS.cmd_init(JMS.parse_cli(["init", "-w", str(workdir)]))

    def test_init_rolls_back_on_failure(self):
        with sandbox() as home:
            workdir = home / "git" / "fresh"
            workdir.mkdir()
            real_open = os.open
            def flaky(path, flags, mode=0o777, *args, **kwargs):
                if os.fsdecode(path).endswith("jmscontainer.toml"):
                    raise PermissionError(13, "denied")
                return real_open(path, flags, mode, *args, **kwargs)
            with mock.patch.object(JMS.os, "open", flaky):
                with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                    JMS.cmd_init(JMS.parse_cli(["init", "-w", str(workdir), "--with-manifest"]))
            self.assertFalse((workdir / ".jmscontainer").exists())

    def test_init_refuses_home_and_protected_roots(self):
        with sandbox() as home:
            with self.assertRaisesRegex(JMS.JMSException, r"at \$HOME"):
                JMS.cmd_init(JMS.parse_cli(["init", "-w", str(home)]))
            # An ordinary directory of checkouts is no longer special-cased.
            with contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_init(JMS.parse_cli(["init", "-w", str(home / "git")]))
            self.assertTrue((home / "git" / ".jmscontainer" / "Containerfile").is_file())


class CleanTests(unittest.TestCase):
    BACKEND = "container"
    EXE = "container"
    STOP_PREFIX = ("container", "stop")
    REMOVE_PREFIX = ("container", "delete")
    IMAGE_PREFIX = ("container", "image")

    def clean(self, argv, images=None, containers=None, stop_error=False):
        with fake_runtime(backend=self.BACKEND, images=dict(images or {}),
                          containers=list(containers or []),
                          stop_error=stop_error) as runtime:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                JMS.cmd_clean(JMS.parse_cli(argv))
            return runtime, stdout.getvalue()

    def cid(self, name):
        # Podman container ids are 64-hex; apple/container ids are names.
        return name if self.BACKEND == "container" else fake_hex_id(name)

    def container_record(self, ident, labels=None, *, launch=None):
        labels = dict(labels or {})
        # jms-launched fixtures carry the provenance marker the predicate
        # requires (§5); pass launch=False for manual-container cases.
        if launch is None:
            launch = "jms.project" in labels
        if launch:
            labels.setdefault("jms.container", "launch")
        return {"id": self.cid(ident), "labels": labels}

    def prefixed(self, call, prefix):
        return tuple(call["argv"][:len(prefix)]) == prefix

    def test_project_scope_selects_only_matching_containers_and_images(self):
        with sandbox() as home:
            root = make_project(home)
            canonical = JMS.canon(os.fsencode(root))
            pid = hashlib.sha256(canonical).hexdigest()
            mine = JMS.tag_prefix_for(canonical, pid) + ":aaaaaaaaaaaa"
            containers = [
                self.container_record("jms-demo-1", {"jms.project": pid}),
                self.container_record("jms-other-1", {"jms.project": "0" * 64}),
                self.container_record("unrelated"),
            ]
            images = {
                mine: image_record(mine, labels={"jms.project": pid}),
                "squatter:1": image_record("squatter:1", labels={"jms.project": pid}),
                "other:1": image_record("other:1", labels={"jms.project": "0" * 64}),
                JMS.BASE: image_record(JMS.BASE),
            }
            runtime, output = self.clean(["clean", "--images", "-w", str(root)],
                                         images=images, containers=containers)
            self.assertIn("removed container \"" + self.cid("jms-demo-1") + "\"", output)
            self.assertNotIn(self.cid("jms-other-1"), output)
            self.assertEqual(runtime.deleted, [mine])
            stopped = [call["argv"][-1] for call in runtime.calls
                       if self.prefixed(call, self.STOP_PREFIX)]
            self.assertEqual(stopped, [self.cid("jms-demo-1")])

    def test_all_scope_includes_base_and_labelled_containers(self):
        with sandbox():
            containers = [
                self.container_record("labelled", {"jms.project": "0" * 64}),
                self.container_record("unrelated"),
            ]
            images = {
                "jmscontainers-mine-00000000:1": image_record(
                    "jmscontainers-mine-00000000:1", labels={"jms.project": "0" * 64}),
                "squatter:1": image_record("squatter:1", labels={"jms.project": "0" * 64}),
                JMS.BASE: image_record(JMS.BASE),
                "foreign:1": image_record("foreign:1"),
            }
            runtime, output = self.clean(["clean", "--all", "--images"],
                                         images=images, containers=containers)
            self.assertIn(self.cid("labelled"), output)
            self.assertNotIn(self.cid("unrelated"), output)
            self.assertEqual(sorted(runtime.deleted),
                             [JMS.BASE, "jmscontainers-mine-00000000:1"])
            self.assertFalse(any(call["argv"][2:3] == ["prune"] for call in runtime.calls
                                 if self.prefixed(call, self.IMAGE_PREFIX)))

    def test_all_scope_ignores_unlabelled_containers_named_like_jms(self):
        with sandbox():
            containers = [self.container_record("jms-production-db"),
                          self.container_record("jms-demo-1", {"jms.project": "0" * 64})]
            runtime, output = self.clean(["clean", "--all"], containers=containers)
            self.assertNotIn(self.cid("jms-production-db"), output)
            self.assertIn("removed container \"" + self.cid("jms-demo-1") + "\"", output)
            touched = [call["argv"][-1] for call in runtime.calls
                       if self.prefixed(call, self.STOP_PREFIX)
                       or self.prefixed(call, self.REMOVE_PREFIX)]
            self.assertNotIn(self.cid("jms-production-db"), touched)

    def test_cleanup_provenance_predicate(self):
        # R5.8: ownership requires jms.project AND jms.container=launch;
        # inherited-marker, manual, and marker-absent containers are never
        # selected, and dry-run selects the same ids as real cleanup.
        with sandbox():
            pid = "0" * 64
            containers = [
                self.container_record("jms-launched", {"jms.project": pid}),
                # Manual container from a jms image: inherits the neutral
                # build marker, never the launch value.
                self.container_record("manual-from-jms-image",
                                      {"jms.project": pid, "jms.container": "image"},
                                      launch=False),
                # Malicious preseed cannot exist on a jms build (the build
                # stamp overrides it), but a manual --label can spell it; it
                # still lacks nothing here -- it IS selected only with both.
                self.container_record("marker-absent", {"jms.project": pid}, launch=False),
                self.container_record("unrelated-jms-name", launch=False),
            ]
            runtime, dry = self.clean(["clean", "--all", "--dry-run"], containers=containers)
            runtime, real = self.clean(["clean", "--all"], containers=containers)
            for output in (dry, real):
                self.assertIn(self.cid("jms-launched"), output)
                self.assertNotIn(self.cid("manual-from-jms-image"), output)
                self.assertNotIn(self.cid("marker-absent"), output)
                self.assertNotIn(self.cid("unrelated-jms-name"), output)

    def test_all_scope_without_images_performs_no_image_operations(self):
        with sandbox():
            containers = [self.container_record("jms-demo-1", {"jms.project": "0" * 64})]
            images = {JMS.BASE: image_record(JMS.BASE),
                      "foreign:1": image_record("foreign:1")}
            runtime, output = self.clean(["clean", "--all"], images=images,
                                         containers=containers)
            self.assertIn("removed container \"" + self.cid("jms-demo-1") + "\"", output)
            self.assertEqual(runtime.deleted, [])
            self.assertFalse(any(self.prefixed(call, self.IMAGE_PREFIX)
                                 for call in runtime.calls))

    def test_stop_failure_does_not_abort_deletion(self):
        with sandbox():
            containers = [self.container_record("jms-demo-1", {"jms.project": "0" * 64}),
                          self.container_record("jms-demo-2", {"jms.project": "0" * 64})]
            runtime, output = self.clean(["clean", "--all"], containers=containers,
                                         stop_error=True)
            self.assertIn("removed container \"" + self.cid("jms-demo-1") + "\"", output)
            self.assertIn("removed container \"" + self.cid("jms-demo-2") + "\"", output)
            deleted = [call["argv"][-1] for call in runtime.calls
                       if self.prefixed(call, self.REMOVE_PREFIX)]
            self.assertEqual(deleted, [self.cid("jms-demo-1"), self.cid("jms-demo-2")])

    def test_dry_run_reports_without_mutating(self):
        with sandbox():
            containers = [self.container_record("jms-demo-1", {"jms.project": "0" * 64})]
            images = {JMS.BASE: image_record(JMS.BASE)}
            runtime, output = self.clean(["clean", "--all", "--images", "--dry-run"],
                                         images=images, containers=containers)
            self.assertIn("would remove container", output)
            self.assertIn("would remove image", output)
            self.assertNotIn("prune", output)
            self.assertEqual(runtime.deleted, [])
            self.assertFalse(any(self.prefixed(call, self.STOP_PREFIX)
                                 for call in runtime.calls))

    def test_clean_without_project_requires_explicit_scope(self):
        with sandbox() as home:
            outside = home / "elsewhere"
            outside.mkdir()
            with mock.patch.object(os, "getcwd", return_value=str(outside)):
                with fake_runtime(backend=self.BACKEND):
                    with self.assertRaisesRegex(JMS.UsageError, "pass --workdir or --all"):
                        JMS.cmd_clean(JMS.parse_cli(["clean"]))

    def test_invalid_clean_scope_is_rejected_before_runtime_startup(self):
        with sandbox() as home, mock.patch.object(JMS, "runtime_ready") as ready:
            with self.assertRaisesRegex(JMS.UsageError, "workdir does not exist"):
                JMS.cmd_clean(JMS.parse_cli(["clean", "-w", str(home / "missing")]))
            ready.assert_not_called()


class CleanTestsPodman(CleanTests):
    BACKEND = "podman"
    EXE = "podman"
    STOP_PREFIX = ("podman", "stop")
    REMOVE_PREFIX = ("podman", "rm")
    IMAGE_PREFIX = ("podman", "image")


class TerminalSafetyTests(unittest.TestCase):
    def test_quote_escapes_hostile_bytes(self):
        self.assertEqual(JMS.quote(b"plain"), '"plain"')
        self.assertEqual(JMS.quote(b"\x1b[31mred"), '"\\x1b[31mred"')
        self.assertEqual(JMS.quote(b'say "hi"\\'), '"say \\"hi\\"\\\\"')
        self.assertEqual(JMS.terminal_safe_text("tab\there\x07"), "tab\\x09here\\x07")

    def test_error_paths_render_terminal_safe_output(self):
        with mock.patch.object(sys, "argv", ["jms", "build", "-w", "rel/\x1bpath"]):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = JMS.main()
            self.assertEqual(code, 2)
            self.assertNotIn("\x1b", stderr.getvalue())

    def test_runtime_arguments_reject_nul_and_invalid_utf8(self):
        with self.assertRaisesRegex(JMS.JMSException, "NUL"):
            JMS.runtime_argument("a\0b")
        with self.assertRaisesRegex(JMS.JMSException, "valid UTF-8"):
            JMS.runtime_argument(b"\xff\xfe")
        with self.assertRaisesRegex(JMS.JMSException, "mount grammar"):
            JMS.runtime_path("/tmp/a,b")

    def test_mount_argument_serialization(self):
        self.assertEqual(JMS.mount_argument("/tmp/x", "/work"), "source=/tmp/x,target=/work")
        self.assertEqual(JMS.mount_argument("/tmp/x", "/opt/y", readonly=True),
                         "source=/tmp/x,target=/opt/y,readonly")
        with self.assertRaises(JMS.JMSException):
            JMS.mount_argument("/tmp/a=b", "/work")


PROJECT_PID = "p" * 64
GOLDEN_LABELS = (("jms.project", PROJECT_PID), ("jms.container", "launch"))


def golden_plan(**overrides):
    fields = dict(name="jms-demo-cafe0123", user="isolation", tty=False,
                  workdir="/work", entrypoint="/bin/bash", image="img:1",
                  labels=GOLDEN_LABELS, env=(),
                  mounts=(("/tmp/proj", "/work", False),
                          ("/tmp/shell", "/home/isolation/.config/jms-shell", True)),
                  command=("-l",))
    fields.update(overrides)
    return JMS.LaunchPlan(**fields)


class LaunchArgvGoldenTests(unittest.TestCase):
    """R7.1/R7.7/R7.8/R7.9/R7.14: exact launch argv per backend, same plans."""

    def test_default_launch_argv_golden(self):
        plan = golden_plan()
        self.assertEqual(JMS.ContainerBackend().run_argv(plan), [
            "container", "run", "--rm", "--interactive",
            "--name", "jms-demo-cafe0123", "--user", "isolation",
            "--workdir", "/work", "--entrypoint", "/bin/bash",
            "--label", "jms.project=" + PROJECT_PID,
            "--label", "jms.container=launch",
            "--mount", "source=/tmp/proj,target=/work",
            "--mount", "source=/tmp/shell,target=/home/isolation/.config/jms-shell,readonly",
            "img:1", "-l"])
        self.assertEqual(JMS.PodmanBackend().run_argv(plan), [
            "podman", "run", "--rm", "--interactive",
            "--name", "jms-demo-cafe0123", "--user", "1000:1000",
            "--workdir", "/work", "--entrypoint", "/bin/bash",
            "--label", "jms.project=" + PROJECT_PID,
            "--label", "jms.container=launch",
            "--hostname", "container", "--security-opt", "label=disable",
            "--userns=keep-id:uid=1000,gid=1000",
            "--mount", "type=bind,source=/tmp/proj,target=/work",
            "--mount", "type=bind,source=/tmp/shell,target=/home/isolation/.config/jms-shell,readonly",
            "img:1", "-l"])

    def test_root_launch_argv_golden(self):
        plan = golden_plan(user="root", tty=True,
                           mounts=(("/tmp/proj", "/work", False),
                                   ("/tmp/shell", "/root/.config/jms-shell", True)))
        apple = JMS.ContainerBackend().run_argv(plan)
        podman = JMS.PodmanBackend().run_argv(plan)
        self.assertEqual(apple[4], "--tty")
        self.assertEqual(apple[apple.index("--user") + 1], "root")
        self.assertEqual(podman[podman.index("--user") + 1], "0:0")
        self.assertIn("--userns=host", podman)
        self.assertNotIn("--userns=keep-id:uid=1000,gid=1000", podman)

    def test_auth_and_manifest_launch_argv_golden(self):
        plan = golden_plan(
            env=(("CLAUDE_CONFIG_DIR", "/home/isolation/.claude"), ("FOO", "bar")),
            mounts=(("/tmp/proj", "/work", False),
                    ("/tmp/cache", "/home/isolation/.cache/example", True),
                    ("/tmp/shell", "/home/isolation/.config/jms-shell", True),
                    ("/tmp/agents/claude", "/home/isolation/.claude", False)))
        for backend, mount_prefix in ((JMS.ContainerBackend(), "source="),
                                      (JMS.PodmanBackend(), "type=bind,source=")):
            argv = backend.run_argv(plan)
            # CLAUDE_CONFIG_DIR precedes the /work mount; manifest env follows it.
            env_positions = [index for index, value in enumerate(argv) if value == "--env"]
            self.assertEqual(argv[env_positions[0] + 1], "CLAUDE_CONFIG_DIR=/home/isolation/.claude")
            self.assertEqual(argv[env_positions[1] + 1], "FOO=bar")
            mount_positions = [index for index, value in enumerate(argv) if value == "--mount"]
            self.assertLess(env_positions[0], mount_positions[0])
            self.assertLess(mount_positions[0], env_positions[1])
            self.assertEqual(argv[mount_positions[0] + 1], mount_prefix + "/tmp/proj,target=/work")
            self.assertEqual(argv[mount_positions[-1] + 1],
                             mount_prefix + "/tmp/agents/claude,target=/home/isolation/.claude")

    def test_no_unmask_in_any_argv(self):
        for plan in (golden_plan(), golden_plan(user="root")):
            for backend in (JMS.ContainerBackend(), JMS.PodmanBackend()):
                argv = backend.run_argv(plan)
                self.assertFalse(any("unmask" in value for value in argv))
                security = [argv[index + 1] for index, value in enumerate(argv)
                            if value == "--security-opt"]
                self.assertIn(security, ([], ["label=disable"]))

    def test_launch_plan_rejects_unknown_user_mode(self):
        with self.assertRaises(AssertionError):
            golden_plan(user="admin")


class BuildArgvGoldenTests(unittest.TestCase):
    """R6.1: exact build argv per backend."""

    LABELS = {"jms.project": PROJECT_PID, "jms.fingerprint": "a" * 64,
              "jms.container": "image"}

    def test_build_argv_golden(self):
        apple, podman = JMS.ContainerBackend(), JMS.PodmanBackend()
        self.assertEqual(
            apple.build_argv("/spec", "t:1", self.LABELS, no_cache=False, pull=False, project=True),
            ["container", "build", "--tag", "t:1", "--file", "/spec/Containerfile",
             "-l", "jms.project=" + PROJECT_PID, "-l", "jms.fingerprint=" + "a" * 64,
             "-l", "jms.container=image", "/spec"])
        self.assertEqual(
            podman.build_argv("/spec", "t:1", self.LABELS, no_cache=False, pull=False, project=True),
            ["podman", "build", "--tag", "t:1", "--file", "/spec/Containerfile",
             "--label", "jms.project=" + PROJECT_PID, "--label", "jms.fingerprint=" + "a" * 64,
             "--label", "jms.container=image", "--pull=missing", "/spec"])
        self.assertEqual(
            apple.build_argv("/repo", JMS.BASE, {}, no_cache=True, pull=True, project=False),
            ["container", "build", "--tag", JMS.BASE, "--file", "/repo/Containerfile",
             "--no-cache", "--pull", "/repo"])
        self.assertEqual(
            podman.build_argv("/repo", JMS.BASE, {}, no_cache=True, pull=True, project=False),
            ["podman", "build", "--tag", JMS.BASE, "--file", "/repo/Containerfile",
             "--no-cache", "--pull=always", "/repo"])
        # Base build without --pull: no pull flag on either backend.
        self.assertNotIn("--pull", apple.build_argv("/repo", JMS.BASE, {}, no_cache=False, pull=False, project=False))
        self.assertFalse([value for value in podman.build_argv("/repo", JMS.BASE, {}, no_cache=False, pull=False, project=False)
                          if value.startswith("--pull")])

    def test_builds_stamp_the_neutral_provenance_label(self):
        # run_build owns the shared label assembly; the stamp overrides any
        # caller-supplied value (R5.8's build half).
        with fake_runtime() as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.build_base(JMS.parse_cli(["build", "--base"]))
        build = runtime.calls[-1]["argv"]
        self.assertIn("jms.container=image", build)


class SelectionTests(unittest.TestCase):
    """MIR-039/R4.5: platform selection is side-effect-free and precedes consent."""

    def select(self, platform, euid=1000):
        with mock.patch.object(sys, "platform", platform), \
             mock.patch.object(os, "geteuid", lambda: euid), \
             mock.patch.object(subprocess, "run", forbid), \
             mock.patch.object(os, "uname", forbid):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                backend = JMS.select_runtime()
            self.assertEqual(stderr.getvalue(), "")
            return backend

    def test_platform_defaults(self):
        self.assertIsInstance(self.select("darwin"), JMS.ContainerBackend)
        self.assertIsInstance(self.select("linux"), JMS.PodmanBackend)

    def test_unsupported_platform_is_refused(self):
        for platform in ("win32", "freebsd14", "aix"):
            with self.assertRaisesRegex(JMS.UsageError, "unsupported platform"):
                self.select(platform)

    def test_root_on_linux_is_refused(self):
        with self.assertRaisesRegex(JMS.UsageError, "rootless podman only"):
            self.select("linux", euid=0)

    def test_linux_scope_is_qualification_not_gate(self):
        # Debian amd64, another distro, arm64: jms performs no distribution
        # or architecture detection, so every local rootless Linux host
        # selects PodmanBackend identically, silently (MIR-039).  The forbid
        # patches on subprocess.run and os.uname prove no detection call.
        for euid in (1000, 12345, 65534):
            self.assertIsInstance(self.select("linux", euid=euid), JMS.PodmanBackend)

    def test_selection_failure_precedes_consent_and_store_writes(self):
        with sandbox() as home:
            root = make_project(home)
            with mock.patch.object(JMS, "_RUNTIME", None), \
                 mock.patch.object(sys, "platform", "win32"), \
                 mock.patch.object(JMS, "consent_input", forbid), \
                 mock.patch.object(JMS, "runtime_run", forbid):
                with self.assertRaisesRegex(JMS.UsageError, "unsupported platform"):
                    JMS.cmd_build(JMS.parse_cli(["build", "-w", str(root)]))
                with self.assertRaisesRegex(JMS.UsageError, "unsupported platform"):
                    JMS.cmd_launch(JMS.parse_cli(["launch", "-w", str(root)]))
                with self.assertRaisesRegex(JMS.UsageError, "unsupported platform"):
                    JMS.cmd_clean(JMS.parse_cli(["clean", "--all"]))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_revoke_purge_selection_failure_leaves_the_store_untouched(self):
        with sandbox() as home:
            root = make_project(home)
            tf = fingerprint_of(root)
            with contextlib.redirect_stdout(io.StringIO()), quiet():
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
            self.assertEqual(len(JMS.read_store()["projects"]), 1)
            with mock.patch.object(JMS, "_RUNTIME", None), \
                 mock.patch.object(sys, "platform", "win32"), \
                 mock.patch.object(JMS, "runtime_run", forbid):
                with self.assertRaisesRegex(JMS.UsageError, "unsupported platform"):
                    JMS.cmd_trust(JMS.parse_cli(["trust", "revoke", str(root), "--purge-images"]))
            self.assertEqual(len(JMS.read_store()["projects"]), 1)


class LazinessTests(unittest.TestCase):
    """MIR-051/§2: pure commands never select a runtime or start a process."""

    @contextlib.contextmanager
    def no_runtime(self):
        with mock.patch.object(JMS, "_RUNTIME", None), \
             mock.patch.object(JMS, "runtime", forbid), \
             mock.patch.object(JMS, "select_runtime", forbid), \
             mock.patch.object(JMS, "runtime_run", forbid):
            yield

    def test_version_never_selects_a_runtime(self):
        with self.no_runtime(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                JMS.parse_cli(["--version"])
            self.assertEqual(caught.exception.code, 0)

    def test_pure_commands_run_with_no_runtime(self):
        with sandbox() as home:
            root = make_project(home)
            tf = fingerprint_of(root)
            with self.no_runtime(), contextlib.redirect_stdout(io.StringIO()), quiet():
                JMS.cmd_inspect(JMS.parse_cli(["inspect", "-w", str(root)]))
                JMS.cmd_init(JMS.parse_cli(["init", "-w", str(home / "git")]))
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
                JMS.cmd_trust(JMS.parse_cli(["trust", "list"]))
                JMS.cmd_trust(JMS.parse_cli(["trust", "revoke", str(root)]))
                JMS.cmd_trust(JMS.parse_cli(["trust", "prune"]))


class OrderingAndCanonTests(unittest.TestCase):
    """R4.5/R4.6: consent precedes readiness; canon's coreutils diagnostic."""

    def test_consent_precedes_runtime_readiness(self):
        with sandbox() as home:
            root = make_project(home)
            order = []
            def approve(*args, **kwargs):
                order.append("approve")
                raise JMS.TrustError("declined")
            with mock.patch.object(JMS, "approve", approve), \
                 mock.patch.object(JMS, "runtime_ready",
                                   lambda: order.append("ready")):
                with self.assertRaises(JMS.TrustError):
                    JMS.cmd_build(JMS.parse_cli(["build", "-w", str(root)]))
            # A declined consent never contacts the runtime.
            self.assertEqual(order, ["approve"])
            order.clear()
            def approve_ok(*args, **kwargs):
                order.append("approve")
                return True, False
            with mock.patch.object(JMS, "approve", approve_ok), \
                 mock.patch.object(JMS, "runtime_ready",
                                   side_effect=lambda: order.append("ready")), \
                 mock.patch.object(JMS, "build_project", lambda *a: ("t:1", False)), \
                 contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_build(JMS.parse_cli(["build", "-w", str(root)]))
            self.assertEqual(order, ["approve", "ready"])

    def test_grant_survives_a_readiness_failure(self):
        with sandbox() as home:
            root = make_project(home)
            tf = fingerprint_of(root)
            with contextlib.redirect_stdout(io.StringIO()), quiet():
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
            with mock.patch.object(JMS, "runtime_ready",
                                   side_effect=JMS.JMSException("engine down")):
                with self.assertRaisesRegex(JMS.JMSException, "engine down"):
                    JMS.cmd_build(JMS.parse_cli(["build", "-w", str(root)]))
            # The grant records consent to a definition, not runtime state.
            self.assertEqual(len(JMS.read_store()["projects"]), 1)

    def test_canon_missing_realpath_diagnostic(self):
        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        with mock.patch.object(subprocess, "run", missing):
            with self.assertRaisesRegex(JMS.JMSException,
                                        "cannot canonicalize paths") as caught:
                JMS.canon(b"/somewhere")
        self.assertIn("coreutils", str(caught.exception))
        self.assertNotIsInstance(caught.exception, JMS.UsageError)


class PodmanReadinessTests(unittest.TestCase):
    """R4.3/R4.4/R4.7: version floor and full podman-info validation."""

    def info(self, mutate=None):
        payload = load_fixture("podman-5.4.2-info.json")
        if mutate is not None:
            mutate(payload)
        return payload

    def ensure(self, payload):
        def fake(argv, **kwargs):
            self.assertEqual(argv[:2], ["podman", "info"])
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode(), stderr=b"")
        with mock.patch.object(JMS, "runtime_run", fake):
            JMS.PodmanBackend().ensure_started()

    def maps(self, payload):
        return payload["host"]["idMappings"]

    def test_healthy_engine_passes(self):
        self.ensure(self.info())

    def test_remote_service_is_refused(self):
        with self.assertRaisesRegex(JMS.JMSException, "remote podman service"):
            self.ensure(self.info(lambda p: p["host"].update(serviceIsRemote=True)))

    def test_rootful_engine_is_refused(self):
        with self.assertRaisesRegex(JMS.JMSException, "not running rootless"):
            self.ensure(self.info(lambda p: p["host"]["security"].update(rootless=False)))

    def test_podman_readiness_matrix(self):
        # Coverage boundary, per map independently: through 65535 passes,
        # through 65534 fails with the subordinate-ID hint (R4.4).
        singleton = lambda size: [{"container_id": 0, "host_id": 1000, "size": 1},
                                  {"container_id": 1, "host_id": 100000, "size": size}]
        self.ensure(self.info(lambda p: self.maps(p).update(uidmap=singleton(65535))))
        for key in ("uidmap", "gidmap"):
            with self.assertRaisesRegex(JMS.JMSException, key + r"[\s\S]*/etc/subuid"):
                self.ensure(self.info(lambda p: self.maps(p).update({key: singleton(65534)})))
        # A gap below 65536 fails even when the total size is sufficient.
        gapped = [{"container_id": 0, "host_id": 1000, "size": 1},
                  {"container_id": 2, "host_id": 100000, "size": 65536}]
        with self.assertRaisesRegex(JMS.JMSException, "does not cover"):
            self.ensure(self.info(lambda p: self.maps(p).update(uidmap=gapped)))
        # Overlapping entries are harmless union semantics.
        overlapping = [{"container_id": 0, "host_id": 1000, "size": 40000},
                       {"container_id": 30000, "host_id": 200000, "size": 35536}]
        self.ensure(self.info(lambda p: self.maps(p).update(uidmap=overlapping)))

    def test_malformed_id_maps_fail_distinctly(self):
        # Structurally malformed entries abort as malformed engine output,
        # never as the undersized-range hint.
        malformed = ([{"container_id": 0, "host_id": 1000, "size": True}],
                     [{"container_id": "0", "host_id": 1000, "size": 65536}],
                     [{"container_id": -1, "host_id": 1000, "size": 65536}],
                     [{"container_id": 0, "host_id": 1000, "size": 0}],
                     ["entry"], "not a list")
        for uidmap in malformed:
            with self.assertRaisesRegex(JMS.JMSException, "malformed uidmap") as caught:
                self.ensure(self.info(lambda p: self.maps(p).update(uidmap=uidmap)))
            self.assertNotIn("/etc/subuid", str(caught.exception))

    def test_missing_graph_driver_is_refused(self):
        with self.assertRaisesRegex(JMS.JMSException, "no storage graph driver"):
            self.ensure(self.info(lambda p: p["store"].pop("graphDriverName")))

    def test_malformed_info_shape_is_refused(self):
        for payload in ([], "text", {"host": {}}, {"store": {}}, {"host": [], "store": {}}):
            with self.assertRaises(JMS.JMSException):
                self.ensure(payload)

    def test_podman_version_floor(self):
        backend = JMS.PodmanBackend()
        self.assertEqual(backend.parse_version("podman version 5.4.2"), (5, 4, 2))
        self.assertEqual(backend.parse_version("podman version 5.4.2-dev"), (5, 4, 2))
        self.assertEqual(backend.parse_version("podman version 5.4.2+ds1"), (5, 4, 2))
        self.assertIsNone(backend.parse_version("podman version 5.4"))
        self.assertIsNone(backend.parse_version("podman version 5.4.2.1"))
        self.assertIsNone(backend.parse_version("container CLI version 1.2.0"))
        with self.assertRaisesRegex(JMS.JMSException, "too old"):
            backend.validate_version((5, 3, 9), "podman version 5.3.9")
        # No ceiling: nothing at or above the floor is ever refused.  Within
        # the qualified major that acceptance is silent.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            backend.validate_version((5, 4, 0), "podman version 5.4.0")
            backend.validate_version((5, 9, 9), "podman version 5.9.9")
        self.assertEqual(stderr.getvalue(), "")
        # A newer major is accepted too, but never silently.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            backend.validate_version((6, 0, 0), "podman version 6.0.0")
        warning = stderr.getvalue()
        self.assertIn("podman 6.0.0 is newer", warning)
        self.assertIn("5.4.2", warning)         # the qualified version, from code
        self.assertIn("proceeding unqualified", warning)
        # JMS_RUNTIME_ACCEPT is meaningful only for apple/container: it
        # neither suppresses this warning nor is required to proceed.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with mock.patch.dict(os.environ, {"JMS_RUNTIME_ACCEPT": "6.0.0"}):
                backend.validate_version((6, 0, 0), "podman version 6.0.0")
        self.assertEqual(stderr.getvalue(), warning)

    def test_podman_runtime_ready_end_to_end(self):
        info_payload = json.dumps(self.info()).encode()
        def fake(argv, **kwargs):
            if argv[:2] == ["podman", "--version"]:
                return types.SimpleNamespace(returncode=0, stdout=b"podman version 5.4.2\n", stderr=b"")
            if argv[:2] == ["podman", "info"]:
                return types.SimpleNamespace(returncode=0, stdout=info_payload, stderr=b"")
            raise AssertionError("unexpected argv: " + repr(argv))
        with mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
             mock.patch.object(JMS, "runtime_run", fake):
            JMS.runtime_ready()
        def bad_utf8(argv, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout=b"\xff\xfe", stderr=b"")
        with mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
             mock.patch.object(JMS, "runtime_run", bad_utf8):
            with self.assertRaisesRegex(JMS.JMSException, "invalid UTF-8"):
                JMS.runtime_ready()

    def test_podman_diagnostics_match_debian_contract(self):
        # R4.7: the CLI-missing hint is the one full qualified apt command,
        # and the ID-map hint names the uidmap package and both files.
        apt_command = ("sudo apt install podman uidmap passt dbus-user-session "
                       "fuse-overlayfs coreutils")
        self.assertEqual(JMS.PodmanBackend.install_hint,
                         "install the qualified package set: " + apt_command)
        readme = (pathlib.Path(JMS.__file__).parents[1] / "README.md").read_text()
        self.assertIn(apt_command, readme)          # verbatim agreement (R4.7)
        self.assertIn("/etc/subuid", readme)
        self.assertIn("adduser", readme)
        singleton = [{"container_id": 0, "host_id": 1000, "size": 1}]
        with self.assertRaises(JMS.JMSException) as caught:
            self.ensure(self.info(lambda p: self.maps(p).update(uidmap=singleton)))
        message = str(caught.exception)
        for expected in ("uidmap package", "/etc/subuid", "/etc/subgid", "adduser"):
            self.assertIn(expected, message)

    def test_podman_image_exists_tristate(self):
        def fake(code, stderr=b""):
            def run(argv, **kwargs):
                self.assertEqual(argv[:3], ["podman", "image", "exists"])
                return types.SimpleNamespace(returncode=code, stdout=b"", stderr=stderr)
            return run
        backend = JMS.PodmanBackend()
        with mock.patch.object(JMS, "runtime_run", fake(0)):
            self.assertTrue(backend.image_exists("x:1"))
        with mock.patch.object(JMS, "runtime_run", fake(1)):
            self.assertFalse(backend.image_exists("x:1"))
        with mock.patch.object(JMS, "runtime_run", fake(125, b"storage corrupt")):
            with self.assertRaisesRegex(JMS.JMSException, "image exists failed"):
                backend.image_exists("x:1")


class MountGrammarTests(unittest.TestCase):
    """R7.6: per-backend grammar, identical rejection behavior and error text."""

    def test_mount_grammar_per_backend(self):
        apple, podman = JMS.ContainerBackend(), JMS.PodmanBackend()
        self.assertEqual(apple.mount_argument("/tmp/x", "/work"), "source=/tmp/x,target=/work")
        self.assertEqual(podman.mount_argument("/tmp/x", "/work"), "type=bind,source=/tmp/x,target=/work")
        self.assertEqual(apple.mount_argument("/tmp/x", "/opt/y", readonly=True),
                         "source=/tmp/x,target=/opt/y,readonly")
        self.assertEqual(podman.mount_argument("/tmp/x", "/opt/y", readonly=True),
                         "type=bind,source=/tmp/x,target=/opt/y,readonly")

    def test_mount_rejections_identical_across_backends(self):
        cases = [(b"/tmp/a,b", "/work"), (b"/tmp/a=b", "/work"),
                 (b"/tmp/a\0b", "/work"), (b"/tmp/\xff\xfe", "/work"),
                 (b"/tmp/x", "/work,x"), (b"/tmp/x", "/work=x")]
        for source, target in cases:
            messages = []
            for backend in (JMS.ContainerBackend(), JMS.PodmanBackend()):
                with self.assertRaises(JMS.JMSException) as caught:
                    backend.mount_argument(source, target)
                messages.append(str(caught.exception))
            self.assertEqual(messages[0], messages[1])


class IsolationUidPinTests(unittest.TestCase):
    """R3.1: runtime constants and repository image definitions agree."""

    def test_isolation_identity_constants_match_containerfiles(self):
        root = pathlib.Path(JMS.__file__).parents[1]
        base = (root / "Containerfile").read_text()
        standalone = (
            root / "examples" / "clean-slate" / ".jmscontainer" / "Containerfile"
        ).read_text()
        uid = JMS.ISOLATION_UID
        gid = JMS.ISOLATION_GID
        self.assertEqual(uid, 1000)
        self.assertEqual(gid, 1000)
        self.assertIn("groupadd -g %d isolation" % gid, base)
        self.assertIn("useradd -m -s /bin/bash -u %d -g %d isolation" % (uid, gid), base)
        self.assertIn("groupadd --gid %d isolation" % gid, standalone)
        self.assertIn("--uid %d --gid %d isolation" % (uid, gid), standalone)


class SupportVocabularyTests(unittest.TestCase):
    """MIR-039 / RC-002: the public support documents share one
    classification for configurations outside the qualified matrix."""

    PUBLIC_DOCS = ("README.md", "SECURITY.md", "docs/cli.md", "CHANGELOG.md")

    def test_selinux_classification_is_unqualified_but_allowed(self):
        root = pathlib.Path(JMS.__file__).parents[1]
        for name in self.PUBLIC_DOCS:
            text = (root / name).read_text()
            self.assertIn("unqualified but allowed", text,
                          "%s lost the MIR-039 support vocabulary" % name)
            # Blocks are paragraphs or single top-level bullets, so the
            # SELinux bullet is judged apart from its list neighbors.
            for block in re.split(r"\n\n|\n(?=- )", text):
                if "SELinux-enforcing" not in block:
                    continue
                self.assertNotIn(
                    "unsupported", block,
                    "%s classifies SELinux-enforcing hosts as unsupported; "
                    "MIR-039 says unqualified but allowed" % name)


class MissingBaseHintTests(unittest.TestCase):
    """R3.7 (unit half): conditional wording, keyed to observed absence."""

    def test_missing_base_hint_wording(self):
        self.assertEqual(JMS.MISSING_BASE_NOTE,
                         "note: the shared base image jmscontainers-base:latest is not "
                         "present; if this project builds from it, run `jms build` in "
                         "the base directory first")

    def build_failure_stderr(self, images):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            stderr = io.StringIO()
            with fake_runtime(images=images, build_error="command failed: build"), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(stderr):
                with self.assertRaises(JMS.JMSException):
                    JMS.build_project(data, JMS.parse_cli(["build"]))
            return stderr.getvalue()

    def test_hint_appended_after_context_note_when_base_absent(self):
        output = self.build_failure_stderr(images={})
        self.assertIn(JMS.CONTEXT_NOTE, output)
        self.assertIn(JMS.MISSING_BASE_NOTE, output)
        self.assertLess(output.index(JMS.CONTEXT_NOTE), output.index(JMS.MISSING_BASE_NOTE))

    def test_no_hint_when_base_is_present(self):
        output = self.build_failure_stderr(images={JMS.BASE: image_record(JMS.BASE)})
        self.assertIn(JMS.CONTEXT_NOTE, output)
        self.assertNotIn(JMS.MISSING_BASE_NOTE, output)


SWEEP = importlib.machinery.SourceFileLoader(
    "leak_sweep", str(pathlib.Path(__file__).parents[1] / "scripts" / "leak_sweep.py")
).load_module()

EPOCH_2026 = int(datetime.datetime.fromisoformat("2026-01-01T00:00:00Z").timestamp())


def proc_result(returncode=0, stdout=b"", stderr=b""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class RemovalClassificationTests(unittest.TestCase):
    """R5.9: normalized RemovalResult outcomes on both backends."""

    def test_podman_removal_argv_and_success(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append(argv)
            return proc_result()
        with mock.patch.object(JMS, "runtime_run", runner):
            backend = JMS.PodmanBackend()
            self.assertEqual(backend.stop_container("c" * 64).outcome, "removed")
            self.assertEqual(backend.remove_container("c" * 64).outcome, "removed")
            self.assertEqual(backend.remove_image("localhost/x:1").outcome, "removed")
        self.assertEqual(seen, [
            ["podman", "stop", "--ignore", "c" * 64],
            ["podman", "rm", "--ignore", "--force", "c" * 64],
            ["podman", "image", "rm", "--ignore", "--no-prune", "localhost/x:1"]])

    def test_podman_failure_detail_chain(self):
        def runner_for(returncode, stdout=b"", stderr=b""):
            return lambda argv, **kwargs: proc_result(returncode, stdout, stderr)
        backend = JMS.PodmanBackend()
        with mock.patch.object(JMS, "runtime_run", runner_for(125, stderr=b"boom")):
            result = backend.remove_image("x:1")
            self.assertEqual((result.outcome, result.detail), ("failed", '"boom"'))
        with mock.patch.object(JMS, "runtime_run", runner_for(125, stdout=b"only stdout")):
            self.assertEqual(backend.stop_container("c" * 64).detail, '"only stdout"')
        with mock.patch.object(JMS, "runtime_run", runner_for(125)):
            self.assertEqual(backend.remove_container("c" * 64).detail,
                             "no diagnostic output (exit 125)")

    def apple_runner(self, *, op_rc=1, op_stderr=b"engine says no", ps_payload=None,
                     image_present=True):
        def runner(argv, **kwargs):
            if argv[:2] in (["container", "stop"], ["container", "delete"]) \
                    or argv[:3] == ["container", "image", "delete"]:
                return proc_result(op_rc, stderr=op_stderr)
            if argv[:2] == ["container", "list"]:
                return proc_result(stdout=json.dumps(ps_payload or []).encode())
            if argv[:3] == ["container", "image", "inspect"]:
                if image_present:
                    return proc_result()
                return proc_result(1, stderr=b"Error: image not found: " + argv[3].encode())
            raise AssertionError("unexpected argv: " + repr(argv))
        return runner

    def test_apple_absence_classifies_removed_on_all_three_operations(self):
        backend = JMS.ContainerBackend()
        with mock.patch.object(JMS, "runtime_run", self.apple_runner(ps_payload=[])):
            # Absent-stop case (MIR-052): the ps() recheck proves absence.
            self.assertEqual(backend.stop_container("gone").outcome, "removed")
            self.assertEqual(backend.remove_container("gone").outcome, "removed")
        with mock.patch.object(JMS, "runtime_run", self.apple_runner(image_present=False)):
            self.assertEqual(backend.remove_image("x:1").outcome, "removed")

    def test_apple_present_resource_stays_failed(self):
        backend = JMS.ContainerBackend()
        present = [{"id": "still-here", "configuration": {"labels": {}}}]
        with mock.patch.object(JMS, "runtime_run", self.apple_runner(ps_payload=present)):
            result = backend.remove_container("still-here")
            self.assertEqual((result.outcome, result.detail), ("failed", '"engine says no"'))
            stop = backend.stop_container("still-here")
            self.assertEqual(stop.outcome, "failed")

    def test_apple_recheck_failure_never_raises(self):
        backend = JMS.ContainerBackend()
        def broken_recheck(argv, **kwargs):
            if argv[:2] == ["container", "delete"]:
                return proc_result(1, stderr=b"original failure")
            if argv[:2] == ["container", "list"]:
                return proc_result(stdout=b"not json")     # normalizer aborts
            raise AssertionError("unexpected argv: " + repr(argv))
        with mock.patch.object(JMS, "runtime_run", broken_recheck):
            result = backend.remove_container("x")
        self.assertEqual(result.outcome, "failed")
        self.assertIn('"original failure"', result.detail)
        self.assertIn("; recheck failed: ", result.detail)

    def test_apple_empty_output_failure_uses_fixed_detail(self):
        backend = JMS.ContainerBackend()
        present = [{"id": "x", "configuration": {"labels": {}}}]
        with mock.patch.object(JMS, "runtime_run",
                               self.apple_runner(op_stderr=b"", ps_payload=present)):
            self.assertEqual(backend.remove_container("x").detail,
                             "no diagnostic output (exit 1)")


class ImageFactTests(unittest.TestCase):
    """R5.2/R5.3/R5.10 and R3.5: normalizers, accumulator, local_name."""

    def apple_facts(self, records):
        runner = lambda argv, **kwargs: proc_result(stdout=json.dumps(records).encode())
        with mock.patch.object(JMS, "runtime_run", runner):
            return JMS.ContainerBackend().image_facts()

    def podman_facts(self, records):
        runner = lambda argv, **kwargs: proc_result(stdout=json.dumps(records).encode())
        with mock.patch.object(JMS, "runtime_run", runner):
            return JMS.PodmanBackend().image_facts()

    def apple_rec(self, ident, name, created="2026-01-01T00:00:00Z", labels=None):
        record = {"id": ident,
                  "configuration": {"creationDate": created,
                                    "descriptor": {"digest": "sha256:" + ident}}}
        if name is not None:
            record["configuration"]["name"] = name
        record["variants"] = [{"config": {"config": {"Labels": labels}}}]
        return record

    def podman_rec(self, ident, names, created=EPOCH_2026, labels=None):
        return {"Id": ident, "Names": names, "Created": created, "Labels": labels}

    def test_image_fact_accumulator(self):
        ident, other = "a" * 64, "b" * 64
        # apple: reordered duplicates, repeated refs, and mixed dangling/named
        # records yield the identical single fact.
        records = [self.apple_rec(ident, "x:2"), self.apple_rec(ident, "x:1"),
                   self.apple_rec(ident, "x:1"), self.apple_rec(ident, None)]
        for ordering in (records, records[::-1]):
            self.assertEqual(self.apple_facts(ordering),
                             [(ident, ("x:1", "x:2"), EPOCH_2026, {})])
        # Conflicting created and conflicting/missing-vs-present labels abort.
        with self.assertRaisesRegex(JMS.JMSException, "conflicting records"):
            self.apple_facts([self.apple_rec(ident, "x:1"),
                              self.apple_rec(ident, "x:2", created="2026-01-01T00:00:01Z")])
        with self.assertRaisesRegex(JMS.JMSException, "conflicting records"):
            self.apple_facts([self.apple_rec(ident, "x:1", labels={"jms.project": "x"}),
                              self.apple_rec(ident, "x:2", labels={})])
        with self.assertRaisesRegex(JMS.JMSException, "conflicting records"):
            self.apple_facts([self.apple_rec(ident, "x:1", labels={"jms.project": "x"}),
                              self.apple_rec(ident, "x:2")])
        # id must equal the descriptor digest.
        broken = self.apple_rec(ident, "x:1")
        broken["configuration"]["descriptor"]["digest"] = "sha256:" + other
        with self.assertRaisesRegex(JMS.JMSException, "descriptor digest"):
            self.apple_facts([broken])
        # podman: byte-identical per-tag duplicates collapse (fixture-pinned
        # 5.4.2 reality); any disagreement aborts.
        dup = self.podman_rec(ident, ["localhost/x:1", "localhost/x:2"])
        self.assertEqual(self.podman_facts([dup, dict(dup)]),
                         [(ident, ("localhost/x:1", "localhost/x:2"), EPOCH_2026, {})])
        with self.assertRaisesRegex(JMS.JMSException, "conflicting records"):
            self.podman_facts([dup, self.podman_rec(ident, ["localhost/x:1"])])
        with self.assertRaisesRegex(JMS.JMSException, "conflicting records"):
            self.podman_facts([dup, dict(dup, Created=EPOCH_2026 + 1)])
        # Output sorted by id on both backends.
        two = [self.podman_rec(other, ["b:1"]), self.podman_rec(ident, ["a:1"])]
        self.assertEqual([fact[0] for fact in self.podman_facts(two)], [ident, other])

    def test_shared_validation_rejections(self):
        ident = "a" * 64
        bad_podman = [
            self.podman_rec("A" * 64, ["x:1"]),                    # uppercase id
            self.podman_rec("a" * 63, ["x:1"]),                    # short id
            self.podman_rec(ident, "x:1"),                         # names not a list
            self.podman_rec(ident, ["x:1"], created=True),         # bool created
            self.podman_rec(ident, ["x:1"], created=-1),
            self.podman_rec(ident, ["x:1"], created=JMS.MAX_EPOCH + 1),
            self.podman_rec(ident, ["x:1"], created="2026"),
            self.podman_rec(ident, ["x:1"], labels="not a map"),
            self.podman_rec(ident, ["x:1"], labels={"": "v"}),     # empty key
            self.podman_rec(ident, ["x:1"], labels={"k": 7}),      # non-str value
            self.podman_rec(ident, ["x:1"], labels={"k\0": "v"}),  # NUL key
            self.podman_rec(ident, ["x\0:1"]),                     # NUL ref
        ]
        for record in bad_podman:
            with self.assertRaises(JMS.JMSException):
                self.podman_facts([record])
        bad_apple = [
            self.apple_rec(ident, "x:1", created="2026-01-01T00:00:00"),  # naive
            self.apple_rec(ident, "x:1", created="not a date"),
            self.apple_rec(ident, "x:1", created=1767225600),             # non-str
            self.apple_rec(ident, "x:1", labels={"k": None}),
        ]
        for record in bad_apple:
            with self.assertRaises(JMS.JMSException):
                self.apple_facts([record])

    def test_null_and_none_name_normalization(self):
        # MIR-053: null/absent labels become {}; dangling and <none> names drop.
        ident, named = "a" * 64, "b" * 64
        facts = self.podman_facts([
            self.podman_rec(ident, None),                          # dangling: skipped
            self.podman_rec(named, ["<none>", "x:1"], labels=None)])
        self.assertEqual(facts, [(named, ("x:1",), EPOCH_2026, {})])
        record = self.podman_rec(named, ["x:1"])
        del record["Labels"]
        self.assertEqual(self.podman_facts([record])[0][3], {})

    def test_created_is_epoch_seconds_on_both_backends(self):
        # R5.3: one internal type; ordering never compares backend-local shapes.
        apple = self.apple_facts([self.apple_rec("a" * 64, "x:1",
                                                 created="2026-01-01T00:00:00+00:00")])
        podman = self.podman_facts([self.podman_rec("a" * 64, ["x:1"])])
        self.assertEqual(apple[0][2], podman[0][2])
        self.assertIsInstance(apple[0][2], int)

    def test_local_name_per_backend(self):
        apple, podman = JMS.ContainerBackend(), JMS.PodmanBackend()
        self.assertEqual(apple.local_name("docker.io/library/x:1"), "x:1")
        self.assertEqual(apple.local_name("localhost/x:1"), "localhost/x:1")
        self.assertEqual(podman.local_name("localhost/x:1"), "x:1")
        # MIR-047: podman strips exactly localhost/ -- a registry-qualified
        # manual alias stays outside the reserved namespace.
        self.assertEqual(podman.local_name("docker.io/library/jmscontainers-a-b:1"),
                         "docker.io/library/jmscontainers-a-b:1")

    def test_podman_image_facts_normalizer(self):
        # R5.2 over the checked-in capture.
        records = load_fixture("podman-5.4.2-images.json")
        runner = lambda argv, **kwargs: proc_result(stdout=json.dumps(records).encode())
        with mock.patch.object(JMS, "runtime_run", runner):
            facts = JMS.PodmanBackend().image_facts()
        by_ref = {ref: fact for fact in facts for ref in fact[1]}
        labelled = by_ref["localhost/jmsfix-labelled:latest"]
        self.assertIn("localhost/jmsfix-labelled:alias", labelled[1])
        self.assertEqual(labelled[3].get("jms.container"), "image")
        self.assertEqual(by_ref["localhost/jmsfix-unlabeled:latest"][3], {})
        self.assertTrue(all(fact[1] for fact in facts))            # dangling dropped
        self.assertEqual([fact[0] for fact in facts], sorted(fact[0] for fact in facts))

    def test_podman_ps_normalizer(self):
        # R5.5 over the checked-in capture.
        records = load_fixture("podman-5.4.2-ps.json")
        runner = lambda argv, **kwargs: proc_result(stdout=json.dumps(records).encode())
        with mock.patch.object(JMS, "runtime_run", runner):
            parsed = JMS.PodmanBackend().ps()
        markers = sorted(fact["labels"].get("jms.container", "absent") for fact in parsed)
        self.assertEqual(markers, ["absent", "image", "launch"])
        for fact in parsed:
            self.assertRegex(fact["id"], r"^[0-9a-f]{64}$")
        for bad in ([{"Id": "short"}], [{"Id": "a" * 64, "Labels": "x"}], ["record"], "text"):
            with mock.patch.object(JMS, "runtime_run",
                                   lambda argv, **kwargs: proc_result(stdout=json.dumps(bad).encode())):
                with self.assertRaises(JMS.JMSException):
                    JMS.PodmanBackend().ps()


class CleanupPartialFailureTests(unittest.TestCase):
    """R5.7: schedule/execute split with per-call-site policy (MIR-048)."""

    def test_background_gc_warns_on_enumeration_failure(self):
        runner = lambda argv, **kwargs: proc_result(stdout=b"not json")
        stderr = io.StringIO()
        with mock.patch.object(JMS, "_RUNTIME", JMS.ContainerBackend()), \
             mock.patch.object(JMS, "runtime_run", runner), \
             contextlib.redirect_stderr(stderr):
            JMS.gc_project_images("f" * 64, "p", keep=0)   # must not raise
        self.assertIn("warning: image cleanup skipped", stderr.getvalue())

    def test_background_gc_warns_on_removal_failure_and_continues(self):
        pid = "f" * 64
        payload = [
            {"Id": "a" * 64, "Names": ["p:old2"], "Created": 2, "Labels": {"jms.project": pid}},
            {"Id": "b" * 64, "Names": ["p:old1"], "Created": 1, "Labels": {"jms.project": pid}},
        ]
        removed = []
        def runner(argv, **kwargs):
            if argv[:2] == ["podman", "images"]:
                return proc_result(stdout=json.dumps(payload).encode())
            if argv[:3] == ["podman", "image", "rm"]:
                removed.append(argv[-1])
                if argv[-1] == "p:old2":
                    return proc_result(1, stderr=b"in use")
                return proc_result()
            raise AssertionError("unexpected argv: " + repr(argv))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
             mock.patch.object(JMS, "runtime_run", runner), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            JMS.gc_project_images(pid, "p", keep=0)        # must not raise
        self.assertEqual(removed, ["p:old2", "p:old1"])    # attempt-all ordering
        self.assertIn("warning: could not remove image \"p:old2\"", stderr.getvalue())
        self.assertIn("removed image \"p:old1\"", stdout.getvalue())

    def test_clean_aggregates_failures_and_exits_1(self):
        with sandbox():
            container_id = "c" * 64
            payload = [{"Id": container_id,
                        "Labels": {"jms.project": "0" * 64, "jms.container": "launch"}}]
            def runner(argv, **kwargs):
                if argv[:2] == ["podman", "--version"]:
                    return proc_result(stdout=b"podman version 5.4.2\n")
                if argv[:2] == ["podman", "info"]:
                    return proc_result(stdout=json.dumps(load_fixture("podman-5.4.2-info.json")).encode())
                if argv[:2] == ["podman", "ps"]:
                    return proc_result(stdout=json.dumps(payload).encode())
                if argv[:2] == ["podman", "stop"]:
                    return proc_result()
                if argv[:2] == ["podman", "rm"]:
                    return proc_result(2, stderr=b"cannot remove")
                raise AssertionError("unexpected argv: " + repr(argv))
            stderr = io.StringIO()
            with mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
                 mock.patch.object(JMS, "runtime_run", runner), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(JMS.JMSException, "cleanup failed") as caught:
                    JMS.cmd_clean(JMS.parse_cli(["clean", "--all"]))
            self.assertEqual(caught.exception.exit_code, 1)
            self.assertIn("failed to remove container", stderr.getvalue())
            self.assertIn('"cannot remove"', stderr.getvalue())

    def test_revoke_purge_stays_durable_through_every_failure(self):
        with sandbox() as home:
            root = make_project(home)
            tf = fingerprint_of(root)
            with contextlib.redirect_stdout(io.StringIO()), quiet():
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
            # Readiness failure after revocation: the split message, and the
            # record is already gone.
            with mock.patch.object(JMS, "runtime_ready",
                                   side_effect=JMS.JMSException("engine down")):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(JMS.JMSException,
                                                "trust was revoked, but image purge failed"):
                        JMS.cmd_trust(JMS.parse_cli(["trust", "revoke", str(root),
                                                     "--purge-images"]))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_revoke_purge_aggregates_removal_failures(self):
        with sandbox() as home:
            root = make_project(home)
            canonical = JMS.canon(os.fsencode(root))
            pid = hashlib.sha256(canonical).hexdigest()
            tf = fingerprint_of(root)
            mine = JMS.tag_prefix_for(canonical, pid) + ":aaaaaaaaaaaa"
            with contextlib.redirect_stdout(io.StringIO()), quiet():
                JMS.cmd_trust(JMS.parse_cli(["trust", str(root), "--fingerprint", tf]))
            payload = [{"Id": "a" * 64, "Names": [mine], "Created": 1,
                        "Labels": {"jms.project": pid}}]
            def runner(argv, **kwargs):
                if argv[:2] == ["podman", "--version"]:
                    return proc_result(stdout=b"podman version 5.4.2\n")
                if argv[:2] == ["podman", "info"]:
                    return proc_result(stdout=json.dumps(load_fixture("podman-5.4.2-info.json")).encode())
                if argv[:2] == ["podman", "images"]:
                    return proc_result(stdout=json.dumps(payload).encode())
                if argv[:3] == ["podman", "image", "rm"]:
                    return proc_result(1, stderr=b"in use by a container")
                raise AssertionError("unexpected argv: " + repr(argv))
            with mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
                 mock.patch.object(JMS, "runtime_run", runner), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(JMS.JMSException,
                                            "trust was revoked, but image purge failed"):
                    JMS.cmd_trust(JMS.parse_cli(["trust", "revoke", str(root),
                                                 "--purge-images"]))
            self.assertEqual(JMS.read_store()["projects"], {})

    def test_second_clean_invocation_converges(self):
        with sandbox():
            containers = [{"id": "jms-demo-1",
                           "labels": {"jms.project": "0" * 64, "jms.container": "launch"}}]
            with fake_runtime(containers=containers) as runtime:
                with contextlib.redirect_stdout(io.StringIO()):
                    JMS.cmd_clean(JMS.parse_cli(["clean", "--all"]))
                runtime.containers = []      # removed out-of-band / by first run
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    JMS.cmd_clean(JMS.parse_cli(["clean", "--all"]))
            self.assertNotIn("removed container", stdout.getvalue())


class SeamTests(unittest.TestCase):
    """§2 prohibitions: every backend execution crosses module runtime_run."""

    def test_backend_operations_only_reach_processes_via_runtime_run(self):
        calls = []
        def recorder(argv, **kwargs):
            calls.append(list(argv))
            return proc_result(stdout=b"[]")
        with mock.patch.object(subprocess, "run", forbid), \
             mock.patch.object(os, "execvp", forbid):
            for backend in (JMS.ContainerBackend(), JMS.PodmanBackend()):
                with mock.patch.object(JMS, "_RUNTIME", backend), \
                     mock.patch.object(JMS, "runtime_run", recorder):
                    JMS.image_facts()
                    JMS.container_records()
                    JMS.stop_container("c" * 64)
                    JMS.remove_container("c" * 64)
                    JMS.remove_image("x:1")
        self.assertTrue(all(argv[0] in ("container", "podman") for argv in calls))
        self.assertGreaterEqual(len(calls), 10)

    # The complete protocol surface (§2): five class attributes plus the
    # Class A and Class B method tables, and nothing else.
    PROTOCOL_SURFACE = frozenset({
        "name", "exe", "install_hint", "version_min", "version_max",
        "version_argv", "parse_version", "local_name", "mount_argument",
        "build_argv", "run_argv",
        "validate_version", "ensure_started", "image_exists", "image_facts",
        "ps", "stop_container", "remove_container", "remove_image",
    })

    def test_no_backend_exposes_an_image_inspection_operation(self):
        # R3.2 (conformance half): the public surface of each backend is
        # exactly the protocol -- in particular, no verify_image_abi and no
        # operation that reads an image's filesystem exists on any backend.
        for backend in (JMS.ContainerBackend(), JMS.PodmanBackend()):
            public = {attr for attr in dir(backend) if not attr.startswith("_")}
            self.assertEqual(public, set(self.PROTOCOL_SURFACE))

    def test_commands_never_branch_on_the_backend_identity(self):
        # §2 prohibition: no command function reads runtime().name,
        # isinstance-checks a backend, or branches on sys.platform for
        # runtime behavior.  sys.platform may appear only inside
        # select_runtime(); backend classes are never isinstance-checked.
        source = pathlib.Path(JMS.__file__).read_text()
        self.assertNotIn("runtime().name", source)
        self.assertNotIn("isinstance(backend", source)
        for match in re.finditer(r"[^\n]*sys\.platform[^\n]*", source):
            line_start = source.rfind("\ndef ", 0, match.start())
            head = source[line_start + 1:source.index("\n", line_start + 1)]
            self.assertEqual(head, "def select_runtime():",
                             "sys.platform outside select_runtime(): " + match.group(0))


class LeakSweepTests(unittest.TestCase):
    """R7.13: sweep snippet over the checked-in fixtures; three outcomes."""

    WORK = "/home/user/jms-fixture-work"

    def podman_runner(self, ps_payload, inspect_map, exists_codes=None):
        def runner(argv):
            if argv[:2] == ["podman", "ps"]:
                return 0, json.dumps(ps_payload).encode(), b""
            if argv[:2] == ["podman", "inspect"]:
                ident = argv[-1]
                entry = inspect_map.get(ident)
                if entry is None:
                    return 125, b"", b"no such container"
                return 0, json.dumps(entry).encode(), b""
            if argv[:3] == ["podman", "container", "exists"]:
                return (exists_codes or {}).get(argv[-1], 0), b"", b""
            raise AssertionError("unexpected argv: " + repr(argv))
        return runner

    def fixture_state(self):
        ps_payload = load_fixture("podman-5.4.2-ps.json")
        inspect_record = load_fixture("podman-5.4.2-inspect.json")
        running = inspect_record[0]["Id"]
        empty = [dict(inspect_record[0], Mounts=[])]
        inspect_map = {record["Id"]: ([dict(inspect_record[0], Id=record["Id"])]
                                      if record["Id"] == running else
                                      [dict(empty[0], Id=record["Id"])])
                       for record in ps_payload}
        return ps_payload, inspect_map, running

    def test_clean_and_leak_outcomes(self):
        ps_payload, inspect_map, running = self.fixture_state()
        runner = self.podman_runner(ps_payload, inspect_map)
        self.assertEqual(SWEEP.podman_sweep("/somewhere/else", runner), [])
        leaks = SWEEP.podman_sweep(self.WORK, runner)
        self.assertEqual(leaks, [(running, [self.WORK])])
        # Prefix semantics: exact match and children leak, siblings do not.
        self.assertTrue(SWEEP.leaking_sources("/w", ["/w"]))
        self.assertTrue(SWEEP.leaking_sources("/w", ["/w/sub"]))
        self.assertFalse(SWEEP.leaking_sources("/w", ["/w2", "/x/w"]))

    def test_vanished_container_recheck_outcomes(self):
        # All three `container exists` recheck outcomes (MIR-056).
        ps_payload, inspect_map, running = self.fixture_state()
        gone = ps_payload[0]["Id"]
        del inspect_map[gone]
        runner = self.podman_runner(ps_payload, inspect_map, exists_codes={gone: 1})
        self.assertIsInstance(SWEEP.podman_sweep("/somewhere/else", runner), list)
        for code in (0, 125):
            runner = self.podman_runner(ps_payload, inspect_map, exists_codes={gone: code})
            with self.assertRaisesRegex(SWEEP.SweepFailure, "container exists"):
                SWEEP.podman_sweep("/somewhere/else", runner)

    def test_malformed_output_is_sweep_failure_never_leak(self):
        bad_ps = self.podman_runner([{"Id": "short"}], {})
        with self.assertRaises(SWEEP.SweepFailure):
            SWEEP.podman_sweep(self.WORK, bad_ps)
        ps_payload, inspect_map, running = self.fixture_state()
        inspect_map[running] = [dict(inspect_map[running][0], Mounts="not a list")]
        with self.assertRaises(SWEEP.SweepFailure):
            SWEEP.podman_sweep(self.WORK, self.podman_runner(ps_payload, inspect_map))
        broken = self.podman_runner("not a list", {})
        with self.assertRaises(SWEEP.SweepFailure):
            SWEEP.podman_sweep(self.WORK, broken)

    def test_apple_sweep_single_pass(self):
        records = [{"id": "leaky", "configuration": {"mounts": [{"source": self.WORK + "/sub"}]}},
                   {"id": "fine", "configuration": {"mounts": [{"source": "/elsewhere"}]}}]
        runner = lambda argv: (0, json.dumps(records).encode(), b"")
        self.assertEqual(SWEEP.apple_sweep(self.WORK, runner),
                         [("leaky", [self.WORK + "/sub"])])
        with self.assertRaises(SWEEP.SweepFailure):
            SWEEP.apple_sweep(self.WORK, lambda argv: (0, b"not json", b""))
        with self.assertRaises(SWEEP.SweepFailure):
            SWEEP.apple_sweep(self.WORK, lambda argv: (
                0, json.dumps([{"id": "x", "configuration": {"mounts": [{"source": 7}]}}]).encode(), b""))

    def test_main_usage_and_unknown_backend(self):
        with quiet():
            self.assertEqual(SWEEP.main([]), 2)
            self.assertEqual(SWEEP.main(["docker", "/w", "extra"]), 2)


if __name__ == "__main__":
    unittest.main()
