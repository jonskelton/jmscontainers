"""Single-source tables (C-13): each security table is written once and every
site derives from it, so extending a table cannot silently miss a site."""
import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest import mock


def load_source(name, path):
    # As tests/test_jms.py: bin/jms has no .py suffix for spec_from_file_location.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


# A private copy under its own name, so monkeypatching the roster here can
# never leak into the module object tests/test_jms.py patches.
JMS = load_source("jms_single_source", pathlib.Path(__file__).parents[1] / "bin" / "jms")
HOME = "/home/isolation"
EXTRA = JMS.AgentState("newagent", ".newagent/state", "newagent", config_env="NEWAGENT_HOME")


def with_extra_agent():
    return mock.patch.object(JMS, "AGENT_ROSTER", JMS.AGENT_ROSTER + (EXTRA,))


class AgentRosterTests(unittest.TestCase):
    """MAINT-05: the agent roster is the only place an agent is named."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def manifest_mount(self, target):
        (self.home / "cache").mkdir(exist_ok=True)
        return ('[[mounts]]\nsource = "~/cache"\ntarget = "%s"\n' % target).encode()

    def test_every_site_derives_from_the_current_roster(self):
        reserved = JMS.reserved_mount_targets(HOME)
        mounts = dict((target, source) for source, target in JMS.agent_state_mounts())
        credentials = JMS.credential_sources()
        for entry in JMS.AGENT_ROSTER:
            target = HOME + "/" + entry.target
            self.assertIn(entry.leaf, JMS.AGENT_STATE_LEAVES)
            self.assertIn(target, reserved)
            self.assertEqual(mounts[target], JMS.agent_state_root() / entry.leaf)
            self.assertIn(JMS.canon_lenient(os.fsencode(self.home) + b"/" + entry.target.encode()),
                          credentials)
            self.assertIn(entry.agent, JMS.credential_question(JMS.default_config()))
        self.assertEqual(JMS.agent_config_env(HOME), [("CLAUDE_CONFIG_DIR", HOME + "/.claude")])

    def test_consent_text_lists_each_agent_once_in_roster_order(self):
        # Byte-for-byte the text every earlier release showed.
        self.assertEqual(JMS.agent_names_text(), "claude, codex, opencode, pi")
        self.assertEqual(JMS.agent_names_text("and"), "claude, codex, opencode, and pi")

    def test_a_new_roster_entry_reserves_its_mount_target(self):
        target = HOME + "/.newagent/state"
        for candidate in (target, target + "/auth.json", HOME + "/.newagent"):
            JMS.parse_manifest(self.manifest_mount(candidate))  # accepted before the entry exists
            with with_extra_agent():
                self.assertTrue(JMS.target_overlaps_reserved(candidate, HOME), candidate)
                self.assertTrue(JMS.target_overlaps_reserved(candidate.replace(HOME, "/root"), "/root"))
                with self.assertRaisesRegex(JMS.JMSException, r"mounts\[0\]\.target"):
                    JMS.parse_manifest(self.manifest_mount(candidate))

    def test_a_new_roster_entry_reaches_every_other_site(self):
        with with_extra_agent():
            self.assertIn((JMS.agent_state_root() / "newagent", HOME + "/.newagent/state"),
                          JMS.agent_state_mounts())
            self.assertIn((JMS.agent_state_root() / "newagent", "/root/.newagent/state"),
                          JMS.agent_state_mounts("root"))
            self.assertIn(JMS.canon_lenient(os.fsencode(self.home) + b"/.newagent/state"),
                          JMS.credential_sources())
            self.assertIn("opencode, pi, and newagent -- with read-write access",
                          JMS.credential_question(JMS.default_config()))
            self.assertEqual(JMS.agent_config_env(HOME),
                             [("CLAUDE_CONFIG_DIR", HOME + "/.claude"),
                              ("NEWAGENT_HOME", HOME + "/.newagent/state")])


if __name__ == "__main__":
    unittest.main()
