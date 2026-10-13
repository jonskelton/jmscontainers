"""Runtime robustness: query timeouts, signal forwarding, JMS_DEBUG tracing,
trust-store durability, the per-project build lock and build provenance
labels (2.1 audit themes C-06 and C-08).

Hermetic: no container runtime is ever invoked.  Where a real child process
is needed (timeouts, signals), the backend's executable is a throwaway
Python stub in a temporary directory.
"""
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import types
import unittest
from unittest import mock


def load_source(name, path):
    # Same loader as tests/test_jms.py: bin/jms has no .py suffix.  A private
    # module name keeps this copy from replacing test_jms's `jms` module.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(name, loader)
    )
    sys.modules[name] = module
    loader.exec_module(module)
    return module


JMS = load_source("jms_runtime_robustness",
                  pathlib.Path(__file__).parents[1] / "bin" / "jms")


def setUpModule():
    JMS._RUNTIME = JMS.PodmanBackend()


def tearDownModule():
    JMS._RUNTIME = None


@contextlib.contextmanager
def sandbox():
    """Scratch HOME and checkout; no ambient JMS_* variables."""
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "home"
        home.mkdir()
        checkout = pathlib.Path(tmp) / "checkout"
        checkout.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("JMS_")}
        env["HOME"] = str(home)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(JMS, "checkout_root",
                               lambda: JMS.canon(os.fsencode(checkout))):
            yield home


def result(returncode=0, stdout=b"", stderr=b""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Recorder:
    """A runtime_run stand-in that records argv and the timeout it was given."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("timeout"), kwargs.get("replace", False)))
        for prefix, response in self.responses.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return response
        return result(stdout=b"[]")

    def timeout_of(self, *prefix):
        return [timeout for argv, timeout, _ in self.calls if tuple(argv[:len(prefix)]) == prefix]


class StubBackend(JMS.PodmanBackend):
    """PodmanBackend whose executable is a test-owned stub script."""

    def __init__(self, exe):
        self.exe = exe


@contextlib.contextmanager
def stub_runtime(body):
    """Install a Python stub as the runtime executable; yields (exe, tmpdir)."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "stub-runtime")
        with open(exe, "w") as handle:
            handle.write("#!" + sys.executable + "\n" + textwrap.dedent(body))
        os.chmod(exe, 0o700)
        with mock.patch.object(JMS, "_RUNTIME", StubBackend(exe)):
            yield exe, tmp


def wait_for(path, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for " + path)
        time.sleep(0.01)


@contextlib.contextmanager
def preserved_signal_handlers():
    saved = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)
        JMS._TERMINATING = None
        JMS._CHILD = None


class QueryTimeoutTests(unittest.TestCase):
    """OPS-01: readiness and query calls are bounded; build and run are not."""

    def test_default_and_override(self):
        with sandbox():
            self.assertEqual(JMS.query_timeout(), JMS.DEFAULT_RUNTIME_TIMEOUT)
            with mock.patch.dict(os.environ, {"JMS_RUNTIME_TIMEOUT": "7"}):
                self.assertEqual(JMS.query_timeout(), 7)
            with mock.patch.dict(os.environ, {"JMS_RUNTIME_TIMEOUT": ""}):
                self.assertEqual(JMS.query_timeout(), JMS.DEFAULT_RUNTIME_TIMEOUT)

    def test_invalid_override_is_a_usage_error(self):
        with sandbox():
            for value in ("0", "-1", "1.5", "ten", " 5", "05", "1000000"):
                with self.subTest(value=value), \
                     mock.patch.dict(os.environ, {"JMS_RUNTIME_TIMEOUT": value}):
                    with self.assertRaisesRegex(JMS.UsageError, "JMS_RUNTIME_TIMEOUT"):
                        JMS.query_timeout()

    def test_podman_queries_are_bounded(self):
        info = json.loads((pathlib.Path(__file__).parent / "fixtures"
                           / "podman-5.4.2-info.json").read_text())
        recorder = Recorder({
            ("podman", "--version"): result(stdout=b"podman version 5.4.2\n"),
            ("podman", "info"): result(stdout=json.dumps(info).encode()),
            ("podman", "image", "inspect"): result(
                stdout=json.dumps([{"Id": "a" * 64, "Labels": None}]).encode()),
        })
        with sandbox(), mock.patch.dict(os.environ, {"JMS_RUNTIME_TIMEOUT": "9"}), \
             mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
             mock.patch.object(JMS, "runtime_run", recorder):
            JMS.runtime_ready()
            JMS.image_exists("x:1")
            JMS.resolve_image("x:1")
            JMS.image_facts()
            JMS.container_records()
        for prefix in (("podman", "--version"), ("podman", "info"),
                       ("podman", "image", "exists"), ("podman", "image", "inspect"),
                       ("podman", "images"), ("podman", "ps")):
            with self.subTest(prefix=prefix):
                timeouts = recorder.timeout_of(*prefix)
                self.assertTrue(timeouts)
                self.assertEqual(set(timeouts), {9})

    def test_container_queries_are_bounded_and_start_gets_longer(self):
        status = iter([result(1), result(0)])
        recorder = Recorder({
            ("container", "--version"): result(stdout=b"container CLI version 1.5.0\n"),
            ("container", "image", "inspect"): result(1, b"", b"Error: image not found: x:1"),
        })

        def runner(argv, **kwargs):
            if argv[1:3] == ["system", "status"]:
                recorder.calls.append((list(argv), kwargs.get("timeout"), False))
                return next(status)
            return recorder(argv, **kwargs)

        with sandbox(), mock.patch.dict(os.environ, {"JMS_RUNTIME_TIMEOUT": "4"}), \
             mock.patch.object(JMS, "_RUNTIME", JMS.ContainerBackend()), \
             mock.patch.object(JMS, "runtime_run", runner), \
             contextlib.redirect_stdout(io.StringIO()):
            JMS.runtime_ready()
            JMS.resolve_image("x:1")
            JMS.image_facts()
            JMS.container_records()
        self.assertEqual(recorder.timeout_of("container", "system", "status"), [4, 4])
        self.assertEqual(recorder.timeout_of("container", "system", "start"),
                         [4 * JMS.SYSTEM_START_TIMEOUT_FACTOR])
        for prefix in (("container", "--version"), ("container", "image", "inspect"),
                       ("container", "image", "list"), ("container", "list")):
            with self.subTest(prefix=prefix):
                self.assertEqual(recorder.timeout_of(*prefix), [4])

    def test_build_removals_and_run_stay_unbounded(self):
        recorder = Recorder()
        with sandbox(), mock.patch.object(JMS, "_RUNTIME", JMS.PodmanBackend()), \
             mock.patch.object(JMS, "runtime_run", recorder), quiet():
            JMS.run_build("/spec", "t:1", JMS.parse_cli(["build"]), project=True)
            JMS.stop_container("c" * 64)
            JMS.remove_container("c" * 64)
            JMS.remove_image("t:1")
        self.assertEqual([timeout for _, timeout, _ in recorder.calls], [None] * 4)

    def test_hung_query_is_killed_with_a_named_error(self):
        body = """
            import time
            time.sleep(60)
        """
        with sandbox(), stub_runtime(body) as (exe, _):
            started = time.monotonic()
            with self.assertRaises(JMS.JMSException) as caught:
                JMS.runtime_run([exe, "info"], timeout=1)
            self.assertLess(time.monotonic() - started, 30)
        message = str(caught.exception)
        self.assertNotIsInstance(caught.exception, JMS.UsageError)
        self.assertIn("timed out after 1s", message)
        self.assertIn("info", message)
        self.assertIn("JMS_RUNTIME_TIMEOUT", message)
        self.assertIsNone(JMS._CHILD)

    def test_completed_query_keeps_the_result_shape(self):
        body = """
            import sys
            sys.stdout.write("out")
            sys.stderr.write("err")
            sys.exit(3)
        """
        with sandbox(), stub_runtime(body) as (exe, _):
            proc = JMS.runtime_run([exe, "x"], check=False, timeout=30)
            self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (3, b"out", b"err"))
            with self.assertRaisesRegex(JMS.JMSException, 'command failed: .* -- "err"'):
                JMS.runtime_run([exe, "x"], timeout=30)


def quiet():
    return contextlib.redirect_stderr(io.StringIO())


class SignalForwardingTests(unittest.TestCase):
    """OPS-02: SIGTERM/SIGHUP reach the runtime child; jms waits for it."""

    CHILD = """
        import os, signal, sys, time
        marker = sys.argv[1]
        def on_signal(signum, frame):
            with open(marker + ".got", "w") as handle:
                handle.write(str(signum))
            sys.exit(128 + signum)
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGHUP, on_signal)
        open(marker + ".ready", "w").close()
        time.sleep(60)
        sys.exit(0)
    """

    def forward(self, signum):
        with sandbox(), preserved_signal_handlers(), \
             stub_runtime(self.CHILD) as (exe, tmp):
            JMS.install_signal_forwarding()
            marker = os.path.join(tmp, "child")

            def send():
                wait_for(marker + ".ready")
                os.kill(os.getpid(), signum)

            sender = threading.Thread(target=send)
            sender.start()
            try:
                with self.assertRaises(JMS.Terminated) as caught:
                    JMS.runtime_run([exe, marker], capture=False, stdin=subprocess.DEVNULL)
            finally:
                sender.join()
            with open(marker + ".got") as handle:
                self.assertEqual(handle.read(), str(int(signum)))
        return caught.exception

    def test_sigterm_is_forwarded_and_awaited(self):
        exc = self.forward(signal.SIGTERM)
        self.assertEqual(exc.exit_code, 128 + signal.SIGTERM)

    def test_sighup_is_forwarded_and_awaited(self):
        exc = self.forward(signal.SIGHUP)
        self.assertEqual(exc.exit_code, 128 + signal.SIGHUP)

    def test_terminated_is_not_swallowed_as_a_jms_error(self):
        # run_build and friends catch JMSException; a termination must pass.
        self.assertFalse(issubclass(JMS.Terminated, Exception))

    def test_signal_without_a_child_terminates_at_once(self):
        with preserved_signal_handlers():
            with self.assertRaises(JMS.Terminated) as caught:
                JMS.forward_termination(signal.SIGTERM)
        self.assertEqual(caught.exception.exit_code, 143)

    def test_main_reports_termination_and_exit_status(self):
        def terminated(argv=None):
            raise JMS.Terminated(signal.SIGHUP)
        stderr = io.StringIO()
        with preserved_signal_handlers(), mock.patch.object(JMS, "parse_cli", terminated), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(JMS.main(), 129)
            self.assertIs(signal.getsignal(signal.SIGTERM), JMS.forward_termination)
            self.assertIs(signal.getsignal(signal.SIGHUP), JMS.forward_termination)
        self.assertEqual(stderr.getvalue(), "error: terminated by SIGHUP\n")


class DebugTraceTests(unittest.TestCase):
    """OPS-04: JMS_DEBUG=1 traces each runtime argv and its exit status."""

    BODY = """
        import sys
        sys.exit(3)
    """

    def run_stub(self, debug_value):
        stderr = io.StringIO()
        with sandbox(), stub_runtime(self.BODY) as (exe, _), \
             contextlib.redirect_stderr(stderr):
            if debug_value is not None:
                os.environ["JMS_DEBUG"] = debug_value
            JMS.runtime_run([exe, "image", "ls"], check=False, timeout=30)
        return exe, stderr.getvalue()

    def test_debug_traces_argv_and_exit(self):
        exe, err = self.run_stub("1")
        lines = err.splitlines()
        self.assertEqual(lines[0], "jms-debug: run: %s \"image\" \"ls\" (timeout 30s)"
                         % JMS.quote(exe))
        self.assertRegex(lines[1], r"^jms-debug: exit 3 \([0-9]+\.[0-9]{2}s\)$")
        self.assertEqual(len(lines), 2)

    def test_debug_is_off_by_default_and_for_zero(self):
        for value in (None, "", "0"):
            with self.subTest(value=value):
                self.assertEqual(self.run_stub(value)[1], "")

    def test_debug_traces_the_exec(self):
        class Execed(Exception):
            pass

        def execvp(path, argv):
            raise Execed(argv)

        stderr = io.StringIO()
        with sandbox(), stub_runtime("import sys; sys.exit(0)\n") as (exe, _), \
             mock.patch.dict(os.environ, {"JMS_DEBUG": "1"}), \
             mock.patch.object(os, "execvp", execvp), contextlib.redirect_stderr(stderr):
            with self.assertRaises(Execed):
                JMS.runtime_run([exe, "run", "--rm", "img"], replace=True)
        self.assertEqual(stderr.getvalue(),
                         'jms-debug: exec: %s "run" "--rm" "img"\n' % JMS.quote(exe))


class TrustStoreDurabilityTests(unittest.TestCase):
    """OPS-11: the store's data and its rename are fsynced."""

    def test_update_store_fsyncs_file_before_rename_then_directory(self):
        events = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            kind = "dir" if _is_dir_fd(fd) else "file"
            events.append("fsync-" + kind)
            return real_fsync(fd)

        def replace(src, dst):
            events.append("replace")
            return real_replace(src, dst)

        with sandbox() as home, mock.patch.object(os, "fsync", fsync), \
             mock.patch.object(os, "replace", replace):
            JMS.update_store(lambda store: True)
            stored = json.loads((home / ".config" / "jmscontainers" / "store.json").read_text())
        self.assertEqual(stored, {"schema": 2, "projects": {}})
        self.assertEqual(events, ["fsync-file", "replace", "fsync-dir"])

    def test_failed_fsync_leaves_no_temporary_file(self):
        def broken(fd):
            raise OSError(5, "I/O error")

        with sandbox() as home, mock.patch.object(os, "fsync", broken):
            with self.assertRaises(OSError):
                JMS.update_store(lambda store: True)
            directory = home / ".config" / "jmscontainers"
            self.assertFalse(list(directory.glob("store.json.tmp-*")))
            self.assertFalse((directory / "store.json").exists())


def _is_dir_fd(fd):
    import stat
    return stat.S_ISDIR(os.fstat(fd).st_mode)


if __name__ == "__main__":
    unittest.main()
