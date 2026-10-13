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


if __name__ == "__main__":
    unittest.main()
