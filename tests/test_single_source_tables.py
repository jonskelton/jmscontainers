"""Single-source tables (C-13): each security table is written once and every
site derives from it, so extending a table cannot silently miss a site."""
import hashlib
import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


def load_source(name, path):
    # As tests/test_jms.py: bin/jms has no .py suffix for spec_from_file_location.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = module  # dataclasses resolve string annotations through it
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


def plan(**overrides):
    fields = dict(name="jms-demo-cafe0123", user="isolation", tty=False, workdir="/work",
                  entrypoint="/bin/bash", image="img:1",
                  labels=(("jms.project", "p" * 64), ("jms.container", "launch")),
                  env=(("CLAUDE_CONFIG_DIR", HOME + "/.claude"), ("FOO", "bar")),
                  mounts=(("/tmp/proj", "/work", False),
                          ("/tmp/shell", HOME + "/.config/jms-shell", True),
                          ("/tmp/agents/claude", HOME + "/.claude", False)),
                  command=("-l",), network=False)
    fields.update(overrides)
    return JMS.LaunchPlan(**fields)


BACKENDS = ((JMS.ContainerBackend(), "source="), (JMS.PodmanBackend(), "type=bind,source="))


class SharedLaunchArgvTests(unittest.TestCase):
    """MAINT-03: both backends build run argv through one shared helper."""

    def pairs(self, argv, flag):
        return [argv[index + 1] for index, value in enumerate(argv) if value == flag]

    def test_both_backends_emit_the_shared_security_flags(self):
        for backend, prefix in BACKENDS:
            for user in ("isolation", "root"):
                argv = backend.run_argv(plan(user=user))
                with self.subTest(backend=backend.name, user=user):
                    self.assertEqual(argv[:4], [backend.exe, "run", "--rm", "--interactive"])
                    self.assertNotIn("--tty", argv)
                    self.assertEqual(self.pairs(argv, "--label"),
                                     ["jms.project=" + "p" * 64, "jms.container=launch"])
                    self.assertEqual(self.pairs(argv, "--env"),
                                     ["CLAUDE_CONFIG_DIR=" + HOME + "/.claude", "FOO=bar"])
                    self.assertEqual(self.pairs(argv, "--mount"), [
                        prefix + "/tmp/proj,target=/work",
                        prefix + "/tmp/shell,target=" + HOME + "/.config/jms-shell,readonly",
                        prefix + "/tmp/agents/claude,target=" + HOME + "/.claude"])
                    self.assertEqual(argv[-4:], ["--network", "none", "img:1", "-l"])
                    self.assertEqual(argv[argv.index("--entrypoint") + 1], "/bin/bash")
                    self.assertEqual(argv[argv.index("--workdir") + 1], "/work")

    def test_both_backends_refuse_ambiguous_mount_targets(self):
        for backend, _ in BACKENDS:
            for target in ("/opt/a,b", "/opt/a=b", "/opt/a\nb"):
                with self.subTest(backend=backend.name, target=target), \
                     self.assertRaises(JMS.JMSException):
                    backend.mount_argument("/tmp/a", target)

    def test_roster_config_variables_precede_the_project_mount_on_both_backends(self):
        with with_extra_agent():
            env = tuple(JMS.agent_config_env(HOME)) + (("FOO", "bar"),)
            for backend, _ in BACKENDS:
                argv = backend.run_argv(plan(env=env))
                first_mount = argv.index("--mount")
                self.assertEqual([value for index, value in enumerate(argv[:first_mount])
                                  if argv[index - 1] == "--env"],
                                 ["CLAUDE_CONFIG_DIR=" + HOME + "/.claude",
                                  "NEWAGENT_HOME=" + HOME + "/.newagent/state"])
                self.assertGreater(argv.index("FOO=bar"), first_mount)


class TrustRecordTests(unittest.TestCase):
    """MAINT-08: one constructor writes the trust record valid_store() reads."""

    def store_with(self, record):
        return {"schema": 2, "projects": {hashlib.sha256(b"/home/u/git/p").hexdigest(): record}}

    def test_constructed_records_are_exactly_what_the_validator_accepts(self):
        for tf, auth in (("a" * 64, True), ("a" * 64, False), (JMS.BASE_CREDENTIAL_TF, False)):
            record = JMS.make_trust_record(b"/home/u/git/p", tf, auth)
            self.assertEqual(set(record), JMS.TRUST_RECORD_FIELDS)
            self.assertEqual(record["grants"], {"build_run": True, "auth": auth})
            self.assertEqual((record["root"], record["tf"], record["jms_version"]),
                             ("/home/u/git/p", tf, JMS.__version__))
            self.assertTrue(JMS.valid_store(self.store_with(record)))
            for field in JMS.TRUST_RECORD_FIELDS:
                partial = {key: value for key, value in record.items() if key != field}
                self.assertFalse(JMS.valid_store(self.store_with(partial)), field)

    def test_the_base_answer_writer_stores_the_constructed_record(self):
        written = []
        def capture(change):
            store = {"schema": 2, "projects": {}}
            change(store)
            written.extend(store["projects"].values())
        with mock.patch.object(JMS, "update_store", capture), \
             mock.patch.object(JMS, "make_trust_record", return_value={"sentinel": True}):
            JMS.record_base_answer(b"/home/u/git/p", True)
        self.assertEqual(written, [{"sentinel": True}])


if __name__ == "__main__":
    unittest.main()
