"""Published connection examples match real installed-style CLI responses."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support


class RepositoryExamples(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lipi-repo-examples-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def example_project(self, language):
        self.root = self.base / language / "project"
        self.root.mkdir(parents=True)

    def configure(self, root, **settings):
        support.w(root / "lipi.json", json.dumps(dict(docs="docs", workflow=None, **settings)))

    def mark(self, root, path, target, preface=""):
        support.w(root / path, preface + "# %s %s\ndef request():\n    return 1\n" % (support.TAG, target))

    def commit(self, *roots):
        for root in roots:
            support.git_init(root)
            code, output = support.commit(root, "synthetic example", date="2026-11-17T09:00:00+00:00")
            self.assertEqual(code, 0, output)

    def command(self, *args, language=None):
        env = None
        if language is not None:
            env = support.language_env(self.base / ("profile-" + language), language)
        return support.run(support.PY + [str(support.CLI), *args], cwd=self.root, env=env)

    def response(self, *args, language=None):
        code, output = self.command(*args, "--format", "json", language=language)
        self.assertEqual(code, 0, output)
        return json.loads(output)

    @staticmethod
    def section(language, page):
        description = (support.LIPI / "docs" / language / page).read_text(encoding="utf-8")
        return description.split('<a id="repos"></a>', 1)[1]

    @staticmethod
    def blocks(text, kind):
        return re.findall(rf"```{kind}\n(.*?)\n```", text, re.S)

    def normalized(self, result, expected):
        heads = {}
        for actual, reference in zip(result["checks"]["repos"], expected["checks"]["repos"]):
            if reference["head"] is not None:
                self.assertRegex(actual["head"], r"^[0-9a-f]{40}$")
                heads[actual["head"][:7]] = reference["head"][:7]
                actual["head"] = reference["head"]
        return heads

    def assert_text(self, expected, heads, *args, language):
        code, text = self.command(*args, language=language)
        self.assertEqual(code, 0, text)
        for actual, reference in heads.items():
            text = text.replace(actual, reference)
        self.assertEqual([line.rstrip() for line in text.strip().splitlines()],
                         [line.rstrip() for line in expected.splitlines()])

    def assert_external_slice_examples(self, language):
        self.example_project(language)
        core = self.root.parent / "core"
        self.configure(self.root, layers={"src/*": "api"},
                       repos={"core": {"path": "../core", "read": ["docs"]}})
        self.configure(core)
        if language == "en":
            api = '# API\n\n## Request <a id="request"></a>\n\nA request includes an ID.\n'
        else:
            api = '# API\n\n## <a id="request"></a>Запрос\n\nЗапрос содержит идентификатор.\n'
        support.w(core / "docs/api.md", api)
        support.w(core / "local.txt", "Fixture metadata.\n")
        target = "core::docs/api.md#request"
        self.mark(self.root, "src/client.py", target, preface="# Consumer\n")
        self.commit(self.root, core)
        section = self.section(language, "slice-examples.md")
        expected, dirty_note, unavailable = map(json.loads, self.blocks(section, "json"))
        expected_text, unavailable_text = self.blocks(section, "text")
        result = self.response("slice", target, language="en")
        self.assertEqual(self.response("slice", target, language="ru"), result)
        heads = self.normalized(result, expected)
        self.assertEqual(result, expected)
        self.assert_text(expected_text, heads, "slice", target, language=language)

        support.w(core / "local.txt", "Edited fixture metadata.\n")
        dirty = self.response("slice", target, language=language)
        self.normalized(dirty, expected)
        self.assertIn(dirty_note, dirty["notes"])
        dirty["notes"].remove(dirty_note)
        expected["checks"]["repos"][1]["dirty"] = True
        expected["reproducible"] = False
        self.assertEqual(dirty, expected)

        shutil.rmtree(core)
        support.set_config(self.root, codes={"T4": "off"})
        code, output = support.commit(self.root, "disable unavailable signal", date="2026-11-17T09:01:00+00:00")
        self.assertEqual(code, 0, output)
        result = self.response("slice", target, language=language)
        heads = self.normalized(result, unavailable)
        self.assertEqual(result, unavailable)
        if language == "ru":
            unavailable_text = target + "\n" + unavailable_text
        self.assert_text(unavailable_text, heads, "slice", target, language=language)

    # @trace docs/ru/slice-examples.md#repos,docs/ru/slice.md#repos
    def test_external_slice_text_json_and_unavailable_example(self):
        for language in ("en", "ru"):
            with self.subTest(language=language):
                self.assert_external_slice_examples(language)

    def assert_map_examples(self, language, title):
        self.example_project(language)
        client = self.root.parent / "client"
        self.configure(self.root, layers={"src/*": "api"},
                       repos={"client": {"path": "../client", "read": ["code", "tests"]}})
        self.configure(client, layers={"src/*": "ui"},
                       repos={"engine": {"path": "../project", "read": ["docs"]}})
        support.w(self.root / "docs/rules.md", f'# Rules\n\n## {title} <a id="limit"></a>\n')
        self.mark(self.root, "src/main.py", "docs/rules.md#limit")
        self.mark(self.root, "tests/test_main.py", "docs/rules.md#limit")
        for path in ("src/main.py", "src/other.py", "tests/test_main.py", "tests/test_other.py"):
            self.mark(client, path, "engine::docs/rules.md#limit")
        self.commit(self.root, client)
        section = self.section(language, "map.md")
        expected, unavailable = map(json.loads, self.blocks(section, "json"))
        result = self.response("map", language="en")
        self.assertEqual(self.response("map", language="ru"), result)
        self.normalized(result, expected)
        self.assertEqual(result, expected)

        shutil.rmtree(client)
        support.set_config(self.root, codes={"T4": "off"})
        code, output = support.commit(self.root, "disable unavailable signal", date="2026-11-17T09:01:00+00:00")
        self.assertEqual(code, 0, output)
        result = self.response("map", language=language)
        self.normalized(result, unavailable)
        self.assertEqual(result, {**expected, **unavailable})

    # @trace docs/ru/map.md#repos
    def test_map_full_json_example(self):
        for language, title in (("en", "Limit"), ("ru", "Предел")):
            with self.subTest(language=language):
                self.assert_map_examples(language, title)
