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
             mock.patch.object(JMS.subprocess, "Popen", absent):
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


def heading_anchors(path):
    """GitHub-style anchors for every Markdown heading in path."""
    anchors = set()
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            text = line.lstrip("#").strip().lower()
            anchors.add("".join(c for c in text if c.isalnum() or c in " -_").replace(" ", "-"))
    return anchors


class LifecycleDocsTests(unittest.TestCase):
    def test_uninstall_message_points_at_an_existing_section(self):
        # OPS-13: `make uninstall` names what it leaves and where to read more.
        makefile = (ROOT / "Makefile").read_text()
        uninstall = makefile.split("\nuninstall:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("README.md#uninstalling", uninstall)
        self.assertIn("uninstalling", heading_anchors(ROOT / "README.md"))

    def test_uninstall_section_names_every_state_root(self):
        # OPS-13: the recipe must cover each directory bin/jms writes.
        section = (ROOT / "README.md").read_text().split("### Uninstalling", 1)[1]
        for state in ("~/.config/jmscontainers", "~/.local/share/jmscontainers",
                      "jms clean --all --images"):
            self.assertIn(state, section)
        home = pathlib.Path("/h")
        with mock.patch.object(JMS, "home_path", lambda: b"/h"):
            self.assertEqual(JMS.store_directory(), home / ".config" / "jmscontainers")
            self.assertEqual(JMS.agent_state_root().parent, home / ".local" / "share" / "jmscontainers")
            self.assertEqual(JMS.shell_state_root().parent, home / ".local" / "share" / "jmscontainers")

    def test_disk_usage_links_resolve(self):
        # OPS-06, OPS-08: README links into both platform guides.
        readme = (ROOT / "README.md").read_text()
        for guide in ("linux.md", "macos.md"):
            self.assertIn("docs/" + guide + "#disk-usage", readme)
            self.assertIn("disk-usage", heading_anchors(ROOT / "docs" / guide))

    def test_docker_is_ruled_out_in_readme_and_runtime_docs(self):
        # ADOPT-04, OPS-14.
        for path in ("README.md", "docs/linux.md", "docs/macos.md", "docs/cli.md"):
            self.assertRegex((ROOT / path).read_text(), r"Docker( Desktop)? is not\s+(a\s+)?supported",
                             path)

    def test_first_base_build_cost_is_stated(self):
        # ADOPT-06.
        self.assertIn("roughly 3 GB", (ROOT / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
