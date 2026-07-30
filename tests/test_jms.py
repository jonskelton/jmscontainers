import contextlib
import importlib.machinery
import hashlib
import io
import json
import os
import pathlib
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
                               lambda: JMS.canon(os.fsencode(checkout))):
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


def image_record(ref, created="2026-01-01T00:00:00Z", labels=None):
    return {"configuration": {"name": ref, "creationDate": created},
            "variants": [{"config": {"config": {"Labels": labels or {}}}}]}


class FakeRuntime:
    """Canned `container` subprocess seam driven by the argv prefix."""

    def __init__(self, images=None, containers=None, build_error=None, stop_error=False):
        self.calls = []
        self.images = dict(images or {})
        self.containers = list(containers or [])
        self.deleted = []
        self.build_error = build_error
        self.build_count = 0
        self.stop_error = stop_error

    def result(self, returncode=0, stdout=b"", stderr=b""):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def __call__(self, argv, capture=True, check=True, stdin=None,
                 stdout=None, stderr=None, replace=False):
        self.calls.append({"argv": list(argv), "replace": replace})
        if argv[:2] == ["container", "--version"]:
            return self.result(stdout=b"container CLI version 1.2.0 (build: release)\n")
        if argv[:3] == ["container", "system", "status"]:
            return self.result()
        if argv[:3] == ["container", "image", "inspect"]:
            ref = argv[3]
            if ref in self.images:
                return self.result(stdout=json.dumps([self.images[ref]]).encode())
            return self.result(returncode=1, stderr=("Error: image not found: " + ref).encode())
        if argv[:3] == ["container", "image", "list"]:
            return self.result(stdout=json.dumps(list(self.images.values())).encode())
        if argv[:3] == ["container", "image", "delete"]:
            self.deleted.append(argv[3])
            self.images.pop(argv[3], None)
            return self.result()
        if argv[:2] == ["container", "build"]:
            self.build_count += 1
            if self.build_error is not None:
                raise JMS.JMSException(self.build_error)
            tag = argv[argv.index("--tag") + 1]
            labels = {}
            for index, value in enumerate(argv):
                if value == "-l":
                    key, _, label_value = argv[index + 1].partition("=")
                    labels[key] = label_value
            created = "2026-01-01T00:00:%02dZ" % (self.build_count % 60)
            self.images[tag] = image_record(tag, created=created, labels=labels)
            return self.result()
        if argv[:2] == ["container", "list"]:
            return self.result(stdout=json.dumps(self.containers).encode())
        if argv[:2] == ["container", "stop"] and self.stop_error:
            if check:
                raise JMS.JMSException("command failed: container stop " + argv[2])
            return self.result(returncode=1, stderr=b"Error: container is not running")
        return self.result()


@contextlib.contextmanager
def fake_runtime(**kwargs):
    runtime = FakeRuntime(**kwargs)
    with mock.patch.object(JMS, "runtime_run", runtime):
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
        self.assertEqual(stdout.getvalue().strip(), "1.0.0")


class BuildTests(unittest.TestCase):
    def build_args(self, *extra):
        return JMS.parse_cli(["build", *extra])

    def test_project_build_uses_spec_as_context_with_identity_labels(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            with fake_runtime() as runtime, contextlib.redirect_stdout(io.StringIO()):
                tag, built = JMS.build_project(data, self.build_args("--trust"))
            self.assertTrue(built)
            self.assertEqual(tag, data["tag_prefix"] + ":" + data["tf"][:12])
            build = next(call["argv"] for call in runtime.calls if call["argv"][:2] == ["container", "build"])
            spec_text = os.fsdecode(data["spec"])
            self.assertEqual(build[-1], spec_text)
            self.assertIn("--file", build)
            self.assertEqual(build[build.index("--file") + 1], spec_text + "/Containerfile")
            self.assertIn("jms.project=" + data["pid"], build)
            self.assertIn("jms.fingerprint=" + data["tf"], build)
            self.assertNotIn("--no-cache", build)
            self.assertNotIn("--pull", build)

    def test_fingerprint_reuse_and_no_cache_rebuild(self):
        with sandbox() as home:
            root = make_project(home)
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            tag = data["tag_prefix"] + ":" + data["tf"][:12]
            with fake_runtime(images={tag: image_record(tag)}) as runtime, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(JMS.build_project(data, self.build_args()), (tag, False))
                self.assertEqual(runtime.build_count, 0)
                self.assertEqual(JMS.build_project(data, self.build_args("--no-cache")),
                                 (tag, True))
                build = next(call["argv"] for call in runtime.calls
                             if call["argv"][:2] == ["container", "build"])
                self.assertIn("--no-cache", build)

    def test_pull_without_base_is_rejected_with_the_update_recipe(self):
        with sandbox() as home:
            make_project(home)
            with fake_runtime() as runtime:
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
            with fake_runtime() as runtime:
                with self.assertRaisesRegex(JMS.JMSException, "changed during consent"):
                    JMS.build_project(data, self.build_args())
                self.assertEqual(runtime.build_count, 0)

    def test_project_build_failure_names_the_context_rule(self):
        with sandbox() as home:
            root = make_project(home, containerfile=b"FROM x\nCOPY ../src /src\n")
            data = JMS.project_data(JMS.canon(os.fsencode(root)))
            stderr = io.StringIO()
            with fake_runtime(build_error="command failed: container build"), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(JMS.JMSException, "command failed"):
                    JMS.build_project(data, self.build_args())
            self.assertIn(".jmscontainer/ only", stderr.getvalue())

    def test_base_build_failure_has_no_context_note(self):
        stderr = io.StringIO()
        with fake_runtime(build_error="command failed"), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(stderr):
            with self.assertRaises(JMS.JMSException):
                JMS.build_base(self.build_args("--base"))
        self.assertNotIn(".jmscontainer", stderr.getvalue())

    def test_base_build_uses_the_repo_as_context(self):
        with fake_runtime() as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.build_base(self.build_args("--base", "--pull", "--no-cache"))
        build = runtime.calls[-1]["argv"]
        repo = os.fsdecode(JMS.canon(os.fsencode(pathlib.Path(JMS.__file__).resolve().parent.parent)))
        self.assertEqual(build[build.index("--tag") + 1], JMS.BASE)
        self.assertEqual(build[build.index("--file") + 1], repo + "/Containerfile")
        self.assertEqual(build[-1], repo)
        self.assertIn("--no-cache", build)
        self.assertIn("--pull", build)

    def test_cmd_build_without_project_builds_base(self):
        with sandbox() as home:
            (home / "git" / "plain").mkdir()
            with fake_runtime() as runtime, contextlib.redirect_stdout(io.StringIO()):
                JMS.cmd_build(JMS.parse_cli(["build", "-w", str(home / "git" / "plain")]))
            build = next(call["argv"] for call in runtime.calls if call["argv"][:2] == ["container", "build"])
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
        with fake_runtime(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=2)
        self.assertEqual(sorted(runtime.deleted), ["p:1", "p:2"])

    def test_trust_revoke_purge_removes_every_project_image(self):
        pid = "f" * 64
        images = {"p:1": image_record("p:1", labels={"jms.project": pid}),
                  "squatter:1": image_record("squatter:1", labels={"jms.project": pid})}
        with fake_runtime(images=images) as runtime, contextlib.redirect_stdout(io.StringIO()):
            JMS.gc_project_images(pid, "p", keep=0)
        self.assertEqual(runtime.deleted, ["p:1"])


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
            self.assertEqual(JMS.image_records(), [])
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
    def launch_argv(self, home, argv, images=None, containers=None, trusted_auth=False):
        """Run cmd_launch against the fake runtime; return the exec argv."""
        with fake_runtime(images=dict(images or {})) as runtime, \
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
            self.assertEqual(argv[:4], ["container", "run", "--rm", "--interactive"])
            self.assertEqual(argv[argv.index("--user") + 1], "isolation")
            self.assertEqual(argv[argv.index("--workdir") + 1], "/work")
            self.assertEqual(argv[argv.index("--entrypoint") + 1], "/bin/bash")
            self.assertIn("FOO=bar", argv)
            self.assertIn("jms.project=" + data["pid"], argv)
            root_text = os.fsdecode(JMS.canon(os.fsencode(root)))
            self.assertIn("source=" + root_text + ",target=/work", argv)
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
            self.assertEqual(argv[argv.index("--user") + 1], "root")
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
            self.assertIn("source=" + agents + "/claude,target=/home/isolation/.claude", mounts)
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
            self.assertIn("source=" + shell + ",target=/home/isolation/.config/jms-shell,readonly",
                          argv)
            self.assertTrue(JMS.shell_state_root().is_dir())
            argv = self.launch_argv(home, ["launch", "--no-auth", "--root", "-w", str(plain)],
                                    images={JMS.BASE: image_record(JMS.BASE)})
            self.assertIn("source=" + shell + ",target=/root/.config/jms-shell,readonly", argv)

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
            self.assertIn("source=" + os.fsdecode(canonical) + ",target=/work",
                          " ".join(argv))


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
    def clean(self, argv, images=None, containers=None, stop_error=False):
        with fake_runtime(images=dict(images or {}), containers=list(containers or []),
                          stop_error=stop_error) as runtime:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                JMS.cmd_clean(JMS.parse_cli(argv))
            return runtime, stdout.getvalue()

    def container_record(self, ident, labels=None):
        return {"id": ident, "configuration": {"labels": labels or {}}}

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
            self.assertIn("removed container \"jms-demo-1\"", output)
            self.assertNotIn("jms-other-1", output)
            self.assertEqual(runtime.deleted, [mine])
            stopped = [call["argv"][2] for call in runtime.calls if call["argv"][:2] == ["container", "stop"]]
            self.assertEqual(stopped, ["jms-demo-1"])

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
            self.assertIn("labelled", output)
            self.assertNotIn("unrelated", output)
            self.assertEqual(sorted(runtime.deleted),
                             [JMS.BASE, "jmscontainers-mine-00000000:1"])
            self.assertFalse(any(call["argv"][:3] == ["container", "image", "prune"]
                                 for call in runtime.calls))

    def test_all_scope_ignores_unlabelled_containers_named_like_jms(self):
        with sandbox():
            containers = [self.container_record("jms-production-db"),
                          self.container_record("jms-demo-1", {"jms.project": "0" * 64})]
            runtime, output = self.clean(["clean", "--all"], containers=containers)
            self.assertNotIn("jms-production-db", output)
            self.assertIn("removed container \"jms-demo-1\"", output)
            touched = [call["argv"][-1] for call in runtime.calls
                       if call["argv"][:2] in (["container", "stop"], ["container", "delete"])]
            self.assertNotIn("jms-production-db", touched)

    def test_all_scope_without_images_performs_no_image_operations(self):
        with sandbox():
            containers = [self.container_record("jms-demo-1", {"jms.project": "0" * 64})]
            images = {JMS.BASE: image_record(JMS.BASE),
                      "foreign:1": image_record("foreign:1")}
            runtime, output = self.clean(["clean", "--all"], images=images,
                                         containers=containers)
            self.assertIn("removed container \"jms-demo-1\"", output)
            self.assertEqual(runtime.deleted, [])
            self.assertFalse(any(call["argv"][:2] == ["container", "image"]
                                 for call in runtime.calls))

    def test_stop_failure_does_not_abort_deletion(self):
        with sandbox():
            containers = [self.container_record("jms-demo-1", {"jms.project": "0" * 64}),
                          self.container_record("jms-demo-2", {"jms.project": "0" * 64})]
            runtime, output = self.clean(["clean", "--all"], containers=containers,
                                         stop_error=True)
            self.assertIn("removed container \"jms-demo-1\"", output)
            self.assertIn("removed container \"jms-demo-2\"", output)
            deleted = [call["argv"][3] for call in runtime.calls
                       if call["argv"][:2] == ["container", "delete"]]
            self.assertEqual(deleted, ["jms-demo-1", "jms-demo-2"])

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
            self.assertFalse(any(call["argv"][:2] == ["container", "stop"] for call in runtime.calls))

    def test_clean_without_project_requires_explicit_scope(self):
        with sandbox() as home:
            outside = home / "elsewhere"
            outside.mkdir()
            with mock.patch.object(os, "getcwd", return_value=str(outside)):
                with fake_runtime():
                    with self.assertRaisesRegex(JMS.UsageError, "pass --workdir or --all"):
                        JMS.cmd_clean(JMS.parse_cli(["clean"]))

    def test_invalid_clean_scope_is_rejected_before_runtime_startup(self):
        with sandbox() as home, mock.patch.object(JMS, "runtime_ready") as ready:
            with self.assertRaisesRegex(JMS.UsageError, "workdir does not exist"):
                JMS.cmd_clean(JMS.parse_cli(["clean", "-w", str(home / "missing")]))
            ready.assert_not_called()


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


if __name__ == "__main__":
    unittest.main()
