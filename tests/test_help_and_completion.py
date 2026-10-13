import argparse
import importlib.machinery
import importlib.util
import pathlib
import re
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
        targets = ("completions/jms.bash", "docs/cli.md")
        texts = {path: (ROOT / path).read_text() for path in targets}
        for command, words in self.surface():
            for word in words:
                for path, text in texts.items():
                    with self.subTest(command=command, word=word, file=path):
                        self.assertRegex(text, r"(?<![\w-])" + re.escape(word) + r"(?![\w-])")


if __name__ == "__main__":
    unittest.main()
