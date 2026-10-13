"""Real executions of the two seams the rest of the suite mocks out.

test_jms.py replaces runtime_run and ensure_agent_state_directory wholesale.
These tests run both for real instead: runtime_run against a stub `podman`
shell script that is the only executable on PATH (never a real runtime), and
ensure_agent_state_directory against a temporary HOME on the real filesystem.
"""
import importlib.machinery
import importlib.util
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


def load_source(name, path):
    # Same loader as test_jms.py; a separate module name keeps this file's
    # backend selection (_RUNTIME) independent of the main suite's.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(name, loader)
    )
    sys.modules[name] = module
    loader.exec_module(module)
    return module


JMS = load_source("jms_seams", pathlib.Path(__file__).parents[1] / "bin" / "jms")

# Records its argv NUL-separated, prints fixed output on both streams, and
# exits with $JMS_STUB_EXIT.  Only shell builtins: PATH holds nothing else.
STUB_PODMAN = """#!/bin/sh
printf '%s\\0' "$@" > "$JMS_STUB_LOG"
printf 'stub stdout\\n'
printf 'stub stderr\\n' >&2
exit "${JMS_STUB_EXIT:-0}"
"""


class RuntimeRunTests(unittest.TestCase):
    """runtime_run is the sole process boundary; execute it end to end."""

    def setUp(self):
        self.addCleanup(setattr, JMS, "_RUNTIME", JMS._RUNTIME)
        JMS._RUNTIME = JMS.PodmanBackend()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.bin = os.path.join(scratch.name, "bin")
        os.mkdir(self.bin)
        self.log = os.path.join(scratch.name, "argv")
        self.environ = {"PATH": self.bin, "JMS_STUB_LOG": self.log, "JMS_STUB_EXIT": "0"}

    def install_stub(self):
        path = os.path.join(self.bin, "podman")
        with open(path, "w") as handle:
            handle.write(STUB_PODMAN)
        os.chmod(path, 0o755)

    def run_seam(self, argv, exit_code=0, **kwargs):
        self.environ["JMS_STUB_EXIT"] = str(exit_code)
        with mock.patch.dict(os.environ, self.environ):
            return JMS.runtime_run(argv, **kwargs)

    def received(self):
        with open(self.log, "rb") as handle:
            data = handle.read()
        return data.split(b"\0")[:-1]

    def assertNotInvoked(self):
        self.assertFalse(os.path.exists(self.log), "stub runtime was invoked")

    def test_argv_reaches_runtime_verbatim_and_output_is_captured(self):
        self.install_stub()
        proc = self.run_seam(["podman", "run", "--rm", "a b", "café", b"bytes-\xc3\xa9", ""])
        self.assertEqual(self.received(),
                         [b"run", b"--rm", b"a b", "café".encode(), b"bytes-\xc3\xa9", b""])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"stub stdout\n")
        self.assertEqual(proc.stderr, b"stub stderr\n")

    def test_failure_with_check_becomes_a_jms_error_naming_the_command(self):
        self.install_stub()
        with self.assertRaises(JMS.JMSException) as caught:
            self.run_seam(["podman", "image", "rm", "x:1"], exit_code=125)
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertEqual(str(caught.exception),
                         'command failed: "podman image rm x:1" -- "stub stderr\\x0a"')
        self.assertEqual(self.received(), [b"image", b"rm", b"x:1"])

    def test_failure_without_check_returns_the_exit_status(self):
        self.install_stub()
        proc = self.run_seam(["podman", "image", "exists", "x:1"], exit_code=1, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stderr, b"stub stderr\n")

    def test_explicit_stdout_is_not_captured(self):
        self.install_stub()
        with tempfile.TemporaryFile() as sink:
            proc = self.run_seam(["podman", "version"], capture=False, stdout=sink,
                                 stderr=subprocess.DEVNULL)
            sink.seek(0)
            self.assertEqual(sink.read(), b"stub stdout\n")
        self.assertIsNone(proc.stdout)
        self.assertIsNone(proc.stderr)

    def test_missing_runtime_names_the_install_hint(self):
        with self.assertRaises(JMS.JMSException) as caught:
            self.run_seam(["podman", "version"])
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertEqual(str(caught.exception),
                         "podman CLI not found; " + JMS.PodmanBackend.install_hint)

    def test_argv_for_another_executable_is_refused_before_exec(self):
        self.install_stub()
        with self.assertRaises(AssertionError):
            self.run_seam(["/bin/sh", "-c", "true"])
        with self.assertRaises(AssertionError):
            self.run_seam([])
        self.assertNotInvoked()

    def test_nul_and_invalid_utf8_arguments_never_reach_the_runtime(self):
        self.install_stub()
        for bad in ("a\0b", b"a\0b", b"\xff"):
            with self.subTest(bad=bad):
                with self.assertRaises(JMS.JMSException) as caught:
                    self.run_seam(["podman", "run", bad])
                # usage=False: a bad value this late is jms's fault, not the user's.
                self.assertEqual(caught.exception.exit_code, 1)
                self.assertNotInvoked()

    def test_replace_execs_the_runtime_in_place(self):
        self.install_stub()
        self.environ["JMS_STUB_EXIT"] = "7"
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child; exec replaces it on success
            try:
                os.environ.update(self.environ)
                with open(os.devnull, "w") as null:
                    os.dup2(null.fileno(), 1)
                    os.dup2(null.fileno(), 2)
                JMS.runtime_run(["podman", "run", "-it", "x:1"], replace=True)
            finally:
                os._exit(99)
        _, status = os.waitpid(pid, 0)
        # Exit 7 can only come from the stub: the child became podman.
        self.assertEqual(os.waitstatus_to_exitcode(status), 7)
        self.assertEqual(self.received(), [b"run", b"-it", b"x:1"])


class AgentStateDirectoryTests(unittest.TestCase):
    """ensure_agent_state_directory on a real filesystem under a temporary HOME."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = pathlib.Path(os.path.realpath(scratch.name)) / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.home / ".local" / "share" / "jmscontainers" / "agents"

    def assertPrivateDirectory(self, path):
        mode = path.lstat().st_mode
        self.assertTrue(stat.S_ISDIR(mode), path)
        self.assertEqual(stat.S_IMODE(mode), 0o700, path)

    def test_creates_private_root_and_leaf_and_is_idempotent(self):
        self.assertEqual(JMS.agent_state_root(), self.root)
        leaf = self.root / "claude"
        JMS.ensure_agent_state_directory(leaf)
        self.assertPrivateDirectory(self.root)
        self.assertPrivateDirectory(leaf)
        (leaf / "kept").write_text("x")
        JMS.ensure_agent_state_directory(leaf)
        self.assertEqual((leaf / "kept").read_text(), "x")

    def test_existing_leaf_directory_is_accepted_unchanged(self):
        leaf = self.root / "codex"
        leaf.mkdir(parents=True, mode=0o755)
        os.chmod(leaf, 0o755)
        JMS.ensure_agent_state_directory(leaf)
        self.assertEqual(stat.S_IMODE(leaf.lstat().st_mode), 0o755)

    def test_planted_symlink_to_a_directory_is_refused(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        self.root.mkdir(parents=True)
        leaf = self.root / "claude"
        leaf.symlink_to(elsewhere)
        with self.assertRaises(JMS.JMSException) as caught:
            JMS.ensure_agent_state_directory(leaf)
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertIn("not a symlink or other file", str(caught.exception))
        self.assertTrue(leaf.is_symlink())
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_dangling_symlink_is_refused_without_creating_its_target(self):
        target = self.home / "missing"
        self.root.mkdir(parents=True)
        leaf = self.root / "pi"
        leaf.symlink_to(target)
        with self.assertRaises(JMS.JMSException):
            JMS.ensure_agent_state_directory(leaf)
        self.assertFalse(os.path.lexists(target))

    def test_regular_file_is_refused(self):
        self.root.mkdir(parents=True)
        leaf = self.root / "opencode"
        leaf.write_text("not a directory")
        with self.assertRaises(JMS.JMSException):
            JMS.ensure_agent_state_directory(leaf)
        self.assertEqual(leaf.read_text(), "not a directory")


if __name__ == "__main__":
    unittest.main()
