import argparse
import contextlib
import importlib.machinery
import importlib.util
import pathlib
import io
import re
import shutil
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]


def load_source(name, path):
    # Same loader as test_jms.py, under a separate module name so the two
    # suites never share (or replace) one module object.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(name, loader)
    )
    sys.modules[name] = module
    loader.exec_module(module)
    return module


JMS = load_source("jms_help_under_test", ROOT / "bin" / "jms")


def subcommands(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


class ParityTests(unittest.TestCase):
    """Every subcommand and flag the parser accepts is completed and documented.

    CONTRIBUTING asks for same-commit updates to docs/cli.md and the
    completions; this walk is what actually holds that line.
    """

    def surface(self):
        top = JMS.parser()
        yield "top", [o for a in top._actions for o in a.option_strings
                      if not isinstance(a, argparse._HelpAction)]
        for name, sub in subcommands(top).items():
            yield name, [name] + [o for a in sub._actions for o in a.option_strings
                                  if not isinstance(a, argparse._HelpAction)]

    def test_every_option_is_completed_and_documented(self):
        targets = ("completions/jms.bash", "completions/_jms", "docs/cli.md")
        texts = {path: (ROOT / path).read_text() for path in targets}
        for command, words in self.surface():
            for word in words:
                for path, text in texts.items():
                    with self.subTest(command=command, word=word, file=path):
                        self.assertRegex(text, r"(?<![\w-])" + re.escape(word) + r"(?![\w-])")


def help_text(*argv):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.suppress(SystemExit):
        JMS.parse_cli([*argv, "--help"])
    return stdout.getvalue()


class HelpTests(unittest.TestCase):
    def test_top_level_help_names_agents_terms_environment_and_exit_codes(self):
        text = help_text()
        for needle in ("AI coding agents", "definition", "fingerprint", "JMS_PROJECT_ROOTS",
                       "JMS_TRUST_FINGERPRINT", "exit status", "jms launch -b yolo-claude -- ",
                       "docs/cli.md"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_launch_help_separates_the_project_path_from_the_container_name(self):
        text = help_text("launch")
        self.assertIn("[-n NAME]", text)
        self.assertIn("[PATH]", text)
        self.assertNotIn("[name]", text)
        self.assertIn("Everything after --", text)

    def test_every_workdir_option_shows_a_path_metavar(self):
        for command in ("build", "launch", "inspect", "init", "clean"):
            with self.subTest(command=command):
                # Python < 3.13 repeats the metavar: "-w PATH, --workdir PATH".
                self.assertRegex(help_text(command), r"-w( PATH)?, --workdir PATH")
                self.assertIn("JMS_PROJECT_ROOTS", help_text(command))


    def test_a_mistyped_option_reports_the_subcommand_usage_and_a_suggestion(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            JMS.parse_cli(["launch", "--git-writeable"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("usage: jms launch", stderr.getvalue())
        self.assertIn("did you mean --git-writable?", stderr.getvalue())

    def test_a_stray_operand_gets_no_suggestion(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            JMS.parse_cli(["build", "somewhere"])
        self.assertIn("usage: jms build", stderr.getvalue())
        self.assertIn("unrecognized arguments: somewhere\n", stderr.getvalue())


BASH = shutil.which("bash")
# Stand-ins for the bash-completion helpers, so the test needs only bash:
# _filedir marks where directories would be offered.
BASH_STUBS = r"""
_init_completion() {
    words=("${COMP_WORDS[@]}"); cword=$COMP_CWORD
    cur=${words[cword]}; prev=${words[cword-1]}
}
_filedir() { COMPREPLY+=("<dirs>"); }
"""


@unittest.skipUnless(BASH, "bash is not installed")
class BashCompletionTests(unittest.TestCase):
    def complete(self, line):
        words = line.split(" ")
        script = (BASH_STUBS + 'source "$1"; shift; COMP_WORDS=("$@"); '
                  'COMP_CWORD=$(( $# - 1 )); _jms_completion; printf "%s\\n" "${COMPREPLY[@]}"')
        result = subprocess.run([BASH, "--norc", "--noprofile", "-c", script, "bash",
                                 str(ROOT / "completions" / "jms.bash"), *words],
                                capture_output=True, text=True, check=True)
        return set(result.stdout.split())

    def test_completion_follows_the_argument_position(self):
        launch = {"-w", "--workdir", "--trust", "--auth", "--no-auth", "--no-cache",
                  "--no-network", "--git-writable", "-r", "--root", "-b", "--bin", "-n", "--name"}
        cases = {
            "jms --v": {"--version"},
            "jms build ": {"-w", "--workdir", "--base", "--trust", "--no-auth", "--no-cache", "--pull"},
            "jms init ": {"-w", "--workdir", "--with-manifest"},
            "jms launch -w ": {"<dirs>"},
            "jms launch -b ": set(),
            "jms launch -n x ": launch | {"<dirs>"},
            "jms launch . ": launch,
            "jms launch -w . ": launch,
            "jms launch -- ": set(),
            "jms launch -b yolo-claude -- --c": set(),
            "jms trust ": {"list", "revoke", "prune", "--fingerprint", "--auth", "--no-auth", "<dirs>"},
            "jms trust list ": set(),
            "jms trust revoke ": {"--purge-images", "<dirs>"},
            "jms trust revoke . ": {"--purge-images"},
            "jms trust . ": {"--fingerprint", "--auth", "--no-auth"},
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(self.complete(line), expected)

if __name__ == "__main__":
    unittest.main()
