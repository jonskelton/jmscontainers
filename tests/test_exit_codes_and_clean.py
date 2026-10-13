"""Exit-code consistency (C-07) and the `clean` confirmation path (C-10)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


def load_source(name, path):
    # Same loader as tests/test_jms.py; a distinct module name keeps this
    # file's patches off the module test_jms.py holds.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(name, loader)
    )
    sys.modules[name] = module
    loader.exec_module(module)
    return module


JMS = load_source("jms_exit_codes", pathlib.Path(__file__).parents[1] / "bin" / "jms")
PID = "0" * 64


class TTYIO(io.StringIO):
    def __init__(self, tty, value=""):
        super().__init__(value)
        self.tty = tty

    def isatty(self):
        return self.tty

    def fileno(self):
        return 0  # consent_input restores blocking mode; set_blocking is stubbed


class FakeBackend(JMS.PodmanBackend):
    """Just enough of a backend for cmd_clean: selection facts and removals."""

    def __init__(self, containers=(), images=()):
        self.containers = list(containers)
        self.images = list(images)
        self.removed = []

    def ps(self):
        return [{"id": ident, "labels": {"jms.project": PID, "jms.container": "launch"}}
                for ident in self.containers]

    def image_facts(self):
        return [("id-" + ref, [ref], None,
                 {} if ref == JMS.BASE else {"jms.project": PID})
                for ref in self.images]

    def stop_container(self, ident):
        self.removed.append(("stop", ident))
        return JMS.RemovalResult("removed")

    def remove_container(self, ident):
        self.removed.append(("rm", ident))
        return JMS.RemovalResult("removed")

    def remove_image(self, ref):
        self.removed.append(("rmi", ref))
        return JMS.RemovalResult("removed")


@contextlib.contextmanager
def sandbox():
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "home"
        (home / "git").mkdir(parents=True)
        checkout = pathlib.Path(tmp) / "checkout"
        checkout.mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ("JMS_TRUST_FINGERPRINT", "JMS_PROJECT_ROOTS")}
        env["HOME"] = str(home)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(JMS, "checkout_root",
                               lambda: JMS.canon(os.fsencode(checkout))):
            yield home


def run_main(argv, *, stdin_tty=False, stderr_tty=False, answer=""):
    """Run main() with argv; return (exit code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), TTYIO(stderr_tty)
    with mock.patch.object(sys, "argv", ["jms", *argv]), \
         mock.patch.object(sys, "stdin", TTYIO(stdin_tty, answer)), \
         mock.patch.object(JMS.os, "set_blocking", lambda *a: None), \
         contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = JMS.main() or 0  # main() returns None on success
    return code, stdout.getvalue(), stderr.getvalue()


class ExitCodeConsistencyTests(unittest.TestCase):
    def test_missing_definition_is_a_usage_error_in_trust_and_clean(self):
        # Same condition, same code: docs/cli.md files a missing definition
        # under usage errors, and `clean` already exited 2 for it.
        with sandbox() as home:
            plain = home / "git" / "plain"
            plain.mkdir()
            code, _, err = run_main(["trust", str(plain)])
            self.assertEqual(code, 2)
            self.assertIn("error: no project container definition found", err)
            with mock.patch.object(JMS, "_RUNTIME", FakeBackend()), \
                 mock.patch.object(os, "getcwd", return_value=str(plain)):
                code, _, err = run_main(["clean"])
            self.assertEqual(code, 2)
            self.assertIn("error: no project container definition found", err)

    def test_keyboard_interrupt_anywhere_exits_130(self):
        def interrupted(args):
            raise KeyboardInterrupt
        with sandbox(), mock.patch.object(JMS, "cmd_inspect", interrupted):
            code, out, err = run_main(["inspect"])
        self.assertEqual((code, out, err), (130, "", ""))


class CleanConfirmationTests(unittest.TestCase):
    def clean(self, argv, backend, **kwargs):
        with sandbox(), mock.patch.object(JMS, "_RUNTIME", backend), \
             mock.patch.object(JMS, "runtime_ready", lambda: None):
            return run_main(["clean", *argv], **kwargs)

    def test_terminal_decline_removes_nothing_and_exits_1(self):
        backend = FakeBackend(containers=["jms-demo-1"], images=[JMS.BASE])
        code, out, err = self.clean(["--all", "--images"], backend,
                                    stdin_tty=True, stderr_tty=True, answer="\n")
        self.assertEqual(code, 1)
        self.assertEqual(backend.removed, [])
        self.assertIn('- container "jms-demo-1"', err)
        self.assertIn("- image " + JMS.quote(JMS.BASE), err)
        self.assertIn("rebuilds it from scratch", err)
        self.assertIn("Remove these? [y/N] ", err)
        self.assertIn("error: clean declined; nothing was removed", err)
        self.assertEqual(out, "")

    def test_terminal_eof_is_the_default_no(self):
        backend = FakeBackend(containers=["jms-demo-1"])
        code, _, _ = self.clean(["--all"], backend, stdin_tty=True, stderr_tty=True)
        self.assertEqual(code, 1)
        self.assertEqual(backend.removed, [])

    def test_terminal_yes_proceeds(self):
        backend = FakeBackend(containers=["jms-demo-1"])
        code, out, _ = self.clean(["--all"], backend,
                                  stdin_tty=True, stderr_tty=True, answer="y\n")
        self.assertEqual(code, 0)
        self.assertEqual(backend.removed, [("stop", "jms-demo-1"), ("rm", "jms-demo-1")])
        self.assertIn('removed container "jms-demo-1"', out)

    def test_yes_flag_skips_the_question(self):
        for flag in ("--yes", "-y"):
            backend = FakeBackend(containers=["jms-demo-1"])
            with mock.patch.object(JMS, "consent_input", self.fail):
                code, _, _ = self.clean(["--all", flag], backend,
                                        stdin_tty=True, stderr_tty=True)
            self.assertEqual(code, 0)
            self.assertIn(("rm", "jms-demo-1"), backend.removed)

    def test_off_a_terminal_clean_proceeds_without_asking(self):
        # Compatible with 2.0: scripts and pipes never see a prompt.
        for stdin_tty, stderr_tty in ((False, False), (True, False), (False, True)):
            backend = FakeBackend(containers=["jms-demo-1"])
            with mock.patch.object(JMS, "consent_input", self.fail):
                code, _, _ = self.clean(["--all"], backend,
                                        stdin_tty=stdin_tty, stderr_tty=stderr_tty)
            self.assertEqual(code, 0)
            self.assertIn(("rm", "jms-demo-1"), backend.removed)

    def test_dry_run_never_asks(self):
        backend = FakeBackend(containers=["jms-demo-1"])
        with mock.patch.object(JMS, "consent_input", self.fail):
            code, out, _ = self.clean(["--all", "--dry-run"], backend,
                                      stdin_tty=True, stderr_tty=True)
        self.assertEqual(code, 0)
        self.assertEqual(backend.removed, [])
        self.assertIn("would remove container", out)

    def test_empty_selection_says_so_on_stderr(self):
        for extra in ([], ["--dry-run"]):
            backend = FakeBackend()
            with mock.patch.object(JMS, "consent_input", self.fail):
                code, out, err = self.clean(["--all", *extra], backend,
                                            stdin_tty=True, stderr_tty=True)
            self.assertEqual((code, out, err), (0, "", "nothing to remove\n"))


if __name__ == "__main__":
    unittest.main()
