"""PLN-001. Personal language selection, resource fallback, and the JSON contract."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support
from lipi import i18n


class LanguageResources(unittest.TestCase):
    def test_directory_defines_language_and_fallback_by_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "locale"
            shutil.copytree(i18n.LOCALE / "en", root / "en")
            extra = root / "xy"
            extra.mkdir()
            with patch.object(i18n, "LOCALE", root):
                self.assertIn("xy", i18n.available_languages())
                for kind, key, translated in (("messages", "cli.help", "XY help"),
                                              ("terms", "slice", {"term": "XY", "definition": "XY slice"})):
                    source = json.loads((root / "en" / (kind + ".json")).read_text(encoding="utf-8"))[key]
                    support.w(extra / (kind + ".json"), json.dumps({
                        key: {"text": translated, "source_sha256": i18n.fingerprint(source)}
                    }))
                sample = Path("seed/common/AGENTS.md")
                managed = Path("lipi/common/README.md")
                support.w(extra / "templates" / sample, "XY instructions")
                support.w(extra / "templates" / managed, "XY managed rules")
                support.w(extra / "template-hashes.json", json.dumps({
                    sample.as_posix(): i18n.fingerprint(i18n.template_path(sample, "en").read_text(encoding="utf-8")),
                    managed.as_posix(): "0" * 64,
                }))
                self.assertEqual(i18n.tr("cli.help", "xy"), "XY help")
                self.assertEqual(i18n.term("slice", "xy")["term"], "XY")
                self.assertEqual(i18n.template_path(sample, "xy").read_text(encoding="utf-8"), "XY instructions")
                self.assertEqual(i18n.template_path(managed, "xy"), i18n.template_path(managed, "en"))

                report = i18n.translation_report("xy")
                self.assertFalse(report["stale"])
                for kind, key, read in (("messages", "cli.unknown", i18n.tr),
                                        ("terms", "baseline", i18n.term),
                                        ("templates", "seed/package/docs/README.md", i18n.template_path)):
                    self.assertIn(kind + "/" + key, report["missing"])
                    self.assertEqual(read(key, "xy"), read(key, "en"))
                self.assertFalse(any(key.startswith("templates/lipi/") for key in report["missing"]))

            # The translator edits the English sources while the old digests are still present.
            for kind, key in (("messages", "cli.help"), ("terms", "slice")):
                path = root / "en" / (kind + ".json")
                data = json.loads(path.read_text(encoding="utf-8"))
                if kind == "terms":
                    data[key]["definition"] += " Further detail."
                else:
                    data[key] += "!"
                support.w(path, json.dumps(data))
            support.w(root / "en/templates" / sample, "Revised instructions")
            with patch.object(i18n, "LOCALE", root):
                self.assertEqual(set(i18n.translation_report("xy")["stale"]),
                                 {"messages/cli.help", "terms/slice", "templates/" + sample.as_posix()})

    def test_translation_inventory(self):
        for language in i18n.available_languages():
            if language != "en":
                print(language, json.dumps(i18n.translation_report(language), ensure_ascii=False))


class InterfaceLanguage(unittest.TestCase):
    def test_personal_selection_and_machine_output_on_the_same_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            home = Path(directory) / "home"
            root.mkdir()
            home.mkdir()
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))

            def run(*args):
                return support.run(support.PY + [str(support.CLI)] + list(args), cwd=root, env=env)

            self.assertEqual(run("lang"), (0, "en\n"))
            self.assertEqual(run("init")[0], 0)
            readme = root / "docs/README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\n[Пример](нет.md)\n", encoding="utf-8")
            self.assertEqual(run("new", "iss", "Новый вопрос", "question")[0], 0)
            def capture():
                outputs = {}
                for args in (("check", "--structure"), ("audit",), ("map",),
                             ("slice", "ISS-001"), ("slice", "нет.md"),
                             ("review", "docs/README.md#absent", "--at", "missing.py")):
                    status, text = run(*args, "--format=json")
                    outputs[args] = (status, json.loads(text))
                return outputs
            en_status, en_text = run("check")
            english = capture()
            self.assertEqual(english[("check", "--structure")][1]["errors"][0]["subject"], "нет.md")
            self.assertEqual(run("lang", "ru"), (0, "ru\n"))
            ru_status, ru_text = run("check")
            self.assertEqual((en_status, ru_status), (1, 1))
            self.assertIn("[error D1]", en_text)
            self.assertIn("[ошибка D1]", ru_text)
            self.assertEqual(capture(), english)
            code, message = run("lang", "../no")
            self.assertEqual(code, 2)
            self.assertIn("en, ru", message)
            self.assertEqual(run("lang"), (0, "ru\n"))
