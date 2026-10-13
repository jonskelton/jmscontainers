"""Runtime-boundary and lifecycle guidance (audit themes C-09, C-11)."""

import importlib.machinery
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).parents[1]


def load_source(name, path):
    # Same loader as tests/test_jms.py: bin/jms has no .py suffix.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = module
    loader.exec_module(module)
    return module


JMS = load_source("jms_lifecycle", ROOT / "bin" / "jms")


class MissingRuntimeHintTests(unittest.TestCase):
    def missing_cli_message(self, backend):
        def absent(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")
        with mock.patch.object(JMS, "_RUNTIME", backend), \
             mock.patch.object(JMS.subprocess, "run", absent):
            with self.assertRaises(JMS.JMSException) as caught:
                JMS.runtime_run([backend.exe, "--version"])
        return str(caught.exception)

    def test_podman_hint_is_distro_neutral_before_naming_apt(self):
        # ADOPT-14: a Fedora or Arch user must not be told to run apt as the
        # only remedy; the Debian command stays, labelled, after the
        # distro-neutral instruction.
        message = self.missing_cli_message(JMS.PodmanBackend())
        self.assertTrue(message.startswith("podman CLI not found; install Podman 5.4 or newer "
                                           "with your distribution's package manager"), message)
        neutral, _, debian = message.partition("on Debian")
        self.assertNotIn("apt", neutral)
        self.assertIn("sudo apt install podman uidmap passt", debian)

    def test_container_hint_is_unchanged(self):
        message = self.missing_cli_message(JMS.ContainerBackend())
        self.assertEqual(message, "container CLI not found; install it with: brew install container")


if __name__ == "__main__":
    unittest.main()
