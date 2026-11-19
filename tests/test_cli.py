"""test_cli.py — команда lipi, вывод чекера (text/json/github) и версия (V1).

V1 живёт здесь, а не в test_init.py: он проверяет пару «чекер ↔ версия
развёртывания», а не развёртывание. CLI-тесты вызывают src/lipi/cli.py подпроцессом.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support
from tests.support import (LIPI, Case, check, check_json, cli, found,
                           header_set, set_config, sub)

src = str(support.SRC.parent)
if src not in sys.path:
    sys.path.insert(0, src)
from lipi.checker.report import gh_lines
from lipi.checker.state import version_mismatch
from lipi import cli as cli_module

VERSION = support.VERSION


class TestWindowsEncoding(Case):
    """На Windows stdout по умолчанию в кодировке консоли (cp1252).

    PYTHONIOENCODING=cp1252 воспроизводит это на любой ОС: русские сообщения
    чекера и init не должны ронять печать.
    """

    def test_checker_errors_print_under_cp1252(self):
        root = self.project()
        support.w(root / "docs" / "guide.md", "# X\n\n[a](nope.md)\n")
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        code, out = support.run(
            support.PY + [str(support.CHECK), "--root", str(root)],
            cwd=str(root), env=env)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "D1"), out)

    def test_init_prints_under_cp1252(self):
        tmp = Path(tempfile.mkdtemp(prefix="lipi-cp1252-"))
        try:
            p = tmp / "p"
            p.mkdir()
            env = dict(os.environ, PYTHONIOENCODING="cp1252")
            code, out = support.run(support.PY + [str(support.INIT), str(p)], env=env)
            self.assertEqual(code, 0, out)
            self.assertTrue((p / "lipi.json").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# @trace docs/ru/codes.md#v1,ADR-010
class TestV1(Case):
    """V1: версия установленного lipi против версии проекта из lock-файла.

    Совместимость — по первой цифре (ADR-010). Источник версии проекта —
    `.agents/lipi/lipi.lock`.
    Нет lock-файла — V1 молчит. Установленный lipi — версия чекера.
    """

    def test_v1_versions_match(self):
        """Одна и та же версия — V1 молчит."""
        root = self.project()
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "V1"), out)

    def test_v1_project_on_previous_major(self):
        """Для старшей установки V1 указывает тег линии проекта и своё руководство."""
        major = int(VERSION.split(".")[0])
        for deployed_major in (major, major + 1):
            with self.subTest(deployed_major=deployed_major):
                installed = "%d.1.0" % (major + 2)
                level, message = version_mismatch(installed, "%d.1.2" % deployed_major)
                self.assertEqual(level, "E")
                self.assertIn(support.localized('Read CHANGELOG.md and run lipi init', 'прочитайте CHANGELOG.md и примените lipi init'), message)
                self.assertIn(
                    support.localized("pipx install --suffix @%d git+https://github.com/lipisutra/lipi@v%d, then lipi@%d check",
                                      "pipx install --suffix @%d git+https://github.com/lipisutra/lipi@v%d, затем lipi@%d check") % (deployed_major, deployed_major, deployed_major),
                    message)
                self.assertIn(
                    "https://github.com/lipisutra/lipi/blob/v%s/SETUP.md#install" % installed,
                    message)

    def test_v1_installed_older_same_major(self):
        """Установленный lipi старше проекта в пределах одной первой цифры — предупреждение."""
        major = int(VERSION.split(".")[0])
        root = self.project()
        sub(root / support.LOCK_REL, '"%s"' % VERSION, '"%d.99.0"' % major)
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertTrue(found(out, "V1"), out)
        self.assertIn(support.localized('upgrade lipi: pipx upgrade lipi', 'обновите lipi: pipx upgrade lipi'), out)
        self.assertNotIn(support.localized('the project uses', 'проект на'), out)
        code, out = check(root, "--strict")
        self.assertEqual(code, 1, out)          # --strict делает его ошибкой

    def test_v1_installed_older_other_major(self):
        """Разные первые цифры дают ошибку, если установленный lipi старше."""
        root = self.project()
        major = int(VERSION.split(".")[0])
        support.set_lock_version(root, "%d.0.0" % (major + 1))
        code, out = check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "V1"), out)
        self.assertIn(support.localized('upgrade lipi: pipx upgrade lipi', 'обновите lipi: pipx upgrade lipi'), out)

    def test_v1_installed_newer_same_major(self):
        """Установленный lipi новее проекта в пределах одной цифры — совместимо."""
        major = int(VERSION.split(".")[0])
        self.assertIsNone(version_mismatch("%d.1.0" % major, "%d.0.1" % major))

    def test_v1_without_lock(self):
        """Нет lock-файла — V1 молчит."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "V1"), out)

    def test_v1_version_key_belongs_to_lock(self):
        """Ключ «lipi» вне lock-файла даёт C1."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        set_config(root, lipi=VERSION)
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('unknown key "lipi"', 'неизвестный ключ «lipi»'), out)
        self.assertFalse(found(out, "V1"), out)


# @trace docs/ru/codes.md#c1
class TestConfig(Case):
    """C1 — настройки по схеме: неизвестный ключ, неверный тип и значение.

    Ошибка настроек означает, что проверке нельзя доверять: чекер печатает
    все C1 и завершается с кодом 2, не запуская остальных проверок.
    """

    def test_unknown_key_stops_with_2(self):
        root = self.project()
        set_config(root, anchor="docs")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(found(out, "C1"), out)
        self.assertIn(support.localized('unknown key "anchor"', 'неизвестный ключ «anchor»'), out)
        # «anchor» не похож ни на один ключ: подсказки difflib нет
        self.assertNotIn(support.localized('did you mean', 'имелось в виду'), out)

    def test_unknown_key_suggests_closest(self):
        root = self.project()
        set_config(root, doc=".")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('unknown key "doc", did you mean "docs"?', 'неизвестный ключ «doc», имелось в виду «docs»?'), out)

    def test_wrong_type_limits(self):
        root = self.project()
        set_config(root, limits="много")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(found(out, "C1"), out)
        self.assertIn(support.localized('key "limits": expected an object, got string', 'ключ «limits»: ожидается объект, а не строка'), out)

    def test_wrong_type_skip_dirs(self):
        root = self.project()
        set_config(root, skip_dirs="generated")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('key "skip_dirs": expected a list of strings, got string', 'ключ «skip_dirs»: ожидается список строк, а не строка'), out)

    def test_invalid_entry_regex_is_c1(self):
        root = self.project()
        set_config(root, entry=["["])
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(found(out, "C1"), out)
        self.assertIn(support.localized('key "entry": item 1: invalid regular expression', 'ключ «entry»: элемент 1: неверное регулярное выражение'), out)
        self.assertNotIn("Traceback", out)

    def test_negative_limit(self):
        root = self.project()
        set_config(root, limits={"docs_lines": -1})
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('"docs_lines": expected a nonnegative integer, got -1', '«docs_lines»: ожидается неотрицательное целое, а не -1'), out)

    def test_string_limit(self):
        root = self.project()
        set_config(root, limits={"docs_lines": "много"})
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('"docs_lines": expected a nonnegative integer, got "много"', '«docs_lines»: ожидается неотрицательное целое, а не «много»'), out)

    def test_bad_lock_lipi_type(self):
        root = self.project()
        support.w(root / support.LOCK_REL, "{\"lipi\": 123}")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn("lipi.lock", out)
        self.assertIn(support.localized('key "lipi": expected a string, got integer', 'ключ «lipi»: ожидается строка, а не целое'), out)

    def test_bad_lock_list(self):
        root = self.project()
        support.w(root / support.LOCK_REL, "[]")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('.agents/lipi/lipi.lock: [error C1] expected an object, got list', '.agents/lipi/lipi.lock: [ошибка C1] ожидается объект, а не список'), out)

    def test_bad_baseline_schema(self):
        root = self.project()
        support.w(root / support.BASE_REL,
                  "{\"schema\": 2, \"entries\": []}")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('"schema": expected 1, got 2', '«schema»: ожидается 1, а не 2'), out)

    def test_bad_baseline_entries(self):
        root = self.project()
        support.w(root / support.BASE_REL,
                  "{\"schema\": 1, \"entries\": {}}")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('"entries": expected a list, got object', '«entries»: ожидается список, а не объект'), out)

    def test_no_lock_no_baseline_not_an_error(self):
        root = self.project()
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "C1"), out)

    def test_all_documented_keys_valid(self):
        root = self.project()
        set_config(root, docs="docs", description=None, workflow="workflow",
                   limits={"docs_lines": 320, "docs_bytes": 24576,
                           "workflow_lines": 600, "masterplan_lines": 150},
                   release_notes="releases.md",
                   stale_days={"active": 30, "review": 14, "issue": 60},
                   entry=["^if __name__"], skip_dirs=["generated"],
                   layers={"src/api/*": "api", "tests/*": "tests"},
                   tests=["check_*.py"], slice_budget=1)
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "C1"), out)

    def test_slice_settings_invalid(self):
        root = self.project()
        original = (root / "lipi.json").read_text(encoding="utf-8")
        cases = {
            "layers": [[], "src", {"": "api"}, {"src/*": " "}, {"src/*": 1}],
            "tests": ["test_*", [1], [""]],
            "slice_budget": [True, False, 0, -1, 1.5, "60", None],
        }
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    support.w(root / "lipi.json", original)
                    set_config(root, **{key: value})
                    code, out = check(root)
                    self.assertEqual(code, 2, out)
                    self.assertTrue(found(out, "C1"), out)
                    self.assertIn(support.localized('key "%s"', 'ключ «%s»') % key, out)

    def test_slice_settings_defaults_and_replacement(self):
        from lipi.checker.config import load_config
        root = self.project()
        defaults = load_config(root, None)
        self.assertEqual(defaults["slice_budget"], 60)
        self.assertEqual(defaults["layers"], {})
        self.assertEqual(defaults["tests"],
                         ["test_*", "*_test.*", "*.test.*", "*.spec.*", "*Test.*"])
        set_config(root, tests=[], layers={"z/*": "last", "a/*": "first"})
        cfg = load_config(root, None)
        self.assertEqual(cfg["tests"], [])
        self.assertEqual(list(cfg["layers"]), ["z/*", "a/*"])

    def test_release_notes_wrong_type(self):
        """release_notes не строка и не null: ошибка C1."""
        root = self.project()
        set_config(root, release_notes=1)
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(found(out, "C1"), out)
        self.assertIn(support.localized('key "release_notes": expected a string, got integer', 'ключ «release_notes»: ожидается строка, а не целое'), out)

    def test_release_notes_empty(self):
        """Пустой путь release_notes — ошибка C1."""
        root = self.project()
        set_config(root, release_notes="")
        code, out = check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(found(out, "C1"), out)
        self.assertIn(support.localized('key "release_notes": empty value', 'ключ «release_notes»: пустое значение'), out)
        self.assertIn(support.localized('expected a path to a documentation page', 'ожидается путь страницы описания'), out)

    def test_valid_lock_and_baseline(self):
        root = self.project()
        support.w(root / support.BASE_REL,
                  json.dumps({"schema": 1, "entries": [
                      {"code": "D1", "file": "docs/guide.md", "subject": "net.md",
                       "count": 2}]}, ensure_ascii=False))
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "C1"), out)

    def test_c1_as_json(self):
        root = self.project()
        set_config(root, anchor="docs")
        code, data = check_json(root)
        self.assertEqual(code, 2)
        self.assertIsNotNone(data)
        self.assertIsInstance(data["version"], str)
        errs = data["errors"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["code"], "C1")
        self.assertEqual(errs[0]["file"], "lipi.json")
        self.assertEqual(errs[0]["line"], 0)
        self.assertIn('unknown key "anchor"', errs[0]["message"])


# @trace docs/ru/commands.md#output
class TestOutputFormats(Case):
    """Форматы вывода: text (по умолчанию), json и github; коды возврата.

    text не меняется: «путь: [ошибка КОД] …». JSON — один объект со схемой 1
    (описан в README); github — аннотации GitHub Actions. Коды возврата:
    0 — чисто, 1 — новые ошибки (или предупреждения при --strict), 2 —
    неверный запуск или C1.
    """

    def test_json_shape(self):
        """JSON чистого проекта: schema, version, списки находок, baseline, summary."""
        root = self.project()
        code, data = check_json(root)
        self.assertEqual(code, 0)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["version"], VERSION)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["baseline"], {"known": 0, "fixed": 0})
        self.assertEqual(set(data["summary"]),
                         {"pages", "docs", "tags", "errors", "warnings"})
        self.assertNotIn("structure", data)

    def test_audit_ignore_trace_count_is_information(self):
        root = self.project()
        marker = "lipi: ignore-trace"
        support.w(root / "src/examples.py",
                  '# ' + support.TAG + ' missing.md#x ' + marker + '\n'
                  '# ' + marker + ' ' + marker + '\n')
        support.w(root / "tests/fixtures/ignored.py", '# ' + marker + '\n')
        set_config(root, skip_dirs=["tests/fixtures"])
        # Документация и исключённые файлы не входят в счётчик кода.
        with (root / "docs/guide.md").open("a") as page:
            page.write('\n`' + marker + '`\n')
        code, data = check_json(root, "--audit", "--strict")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["summary"]["ignored_trace_lines"], 2)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["baseline"], {"known": 0, "fixed": 0})
        for fmt in ("text", "github"):
            code, out = check(root, "--audit", "--strict", "--format", fmt)
            self.assertEqual(code, 0, out)
            self.assertIn(support.localized('lines with ', 'строк с ') + marker + ": 2", out)
            self.assertNotIn("::warning", out)
        code, data = check_json(root)
        self.assertEqual(code, 0, data)
        self.assertNotIn("ignored_trace_lines", data["summary"])
        (root / "src/examples.py").unlink()
        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["summary"]["ignored_trace_lines"], 0)

    def test_json_finding_shape(self):
        """Находка в JSON: code, file, line, subject, message; предупреждения — в warnings."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. [a](nope.md)")
        code, data = check_json(root)
        self.assertEqual(code, 1)
        err = data["errors"][0]
        self.assertEqual(set(err), {"code", "file", "line", "subject", "message"})
        self.assertEqual(err["code"], "D1")
        self.assertEqual(err["file"], "docs/guide.md")
        self.assertEqual(err["subject"], "nope.md")
        self.assertIn('file that does not exist', err["message"])
        self.assertEqual(data["summary"]["errors"], 1)

        warned = self.project()
        support.sub(warned / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n## Наибольшая\n")
        code, data = check_json(warned)
        self.assertEqual(code, 0)
        self.assertEqual(data["errors"], [])
        self.assertTrue(any(w["code"] == "D2" for w in data["warnings"]), data)
        self.assertEqual(data["summary"]["warnings"], 1)

    def test_json_structure(self):
        """--format json --structure: граф в прежней форме плюс schema объекта."""
        root = self.project()
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        self.assertEqual(data["schema"], 1)
        self.assertIn("nodes", data["structure"])
        self.assertIn("edges", data["structure"])

    def test_format_equals_form(self):
        """--format=json — та же форма, что и --format json."""
        root = self.project()
        code, out = support.check(root, "--format=json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["schema"], 1)

    def test_github_annotations(self):
        """github: ::error с file, line и title; предупреждение — ::warning."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. [a](nope.md)")
        code, out = support.check(root, "--format", "github")
        self.assertEqual(code, 1, out)
        line = next(ln for ln in out.split("\n") if "title=D1" in ln)
        self.assertTrue(line.startswith("::error file=docs/guide.md,line=5,title=D1::"),
                        line)
        self.assertIn(support.localized('file that does not exist', 'несуществующий файл'), line)

        warned = self.project()
        support.sub(warned / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n## Наибольшая\n")
        code, out = support.check(warned, "--format", "github")
        self.assertEqual(code, 0, out)
        self.assertTrue(any(ln.startswith("::warning file=") and "title=D2" in ln
                            for ln in out.split("\n")), out)

    def test_github_zero_line_has_no_line(self):
        """github: предупреждение без номера строки — без параметра line."""
        root = self.project()
        major = int(VERSION.split(".")[0])
        support.sub(root / support.LOCK_REL, '"%s"' % VERSION,
                    '"%d.99.0"' % major)
        code, out = support.check(root, "--format", "github")
        self.assertEqual(code, 0, out)
        line = next(ln for ln in out.split("\n") if "title=V1" in ln)
        self.assertTrue(line.startswith("::warning file=.agents/lipi/lipi.lock,title=V1::"),
                        line)

    def test_github_without_file(self):
        """github: находка без файла — без параметра file (и без line при 0)."""
        self.assertEqual(gh_lines([("", 0, "E", "P1", "нет файла", "")]),
                         ["::error title=P1::нет файла"])
        self.assertEqual(gh_lines([("", 0, "W", "P1", "нет файла", "")]),
                         ["::warning title=P1::нет файла"])

    def test_return_codes(self):
        """0 — чисто; 1 — ошибка и предупреждение при --strict; 2 — C1."""
        root = self.project()
        self.assertEqual(support.check(root)[0], 0)
        broken = self.project()
        support.w(broken / "docs" / "guide.md", "# X\n\n[a](nope.md)\n")
        self.assertEqual(support.check(broken)[0], 1)
        warned = self.project()
        support.sub(warned / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n## Наибольшая\n")
        self.assertEqual(support.check(warned)[0], 0)
        self.assertEqual(support.check(warned, "--strict")[0], 1)
        bad = self.project()
        set_config(bad, anchor="docs")
        for fmt in ("text", "json", "github"):
            self.assertEqual(support.check(bad, "--format", fmt)[0], 2)

    def test_json_flag_rejected(self):
        """Удалённый --json отвергается с кодом 2 и подсказкой; то же после new."""
        root = self.project()
        for args in (("--json",), ("--format", "json", "--json"),
                     ("new", "pln", "План", "--json")):
            code, out = support.check(root, *args)
            self.assertEqual(code, 2, out)
            self.assertIn("--format json", out)

    def test_github_c1(self):
        """C1 в github — обычная аннотация ::error с файлом настроек."""
        root = self.project()
        set_config(root, anchor="docs")
        code, out = support.check(root, "--format", "github")
        self.assertEqual(code, 2, out)
        self.assertTrue(any(ln.startswith("::error file=lipi.json,title=C1::")
                            for ln in out.split("\n")), out)

    def test_bad_format_rejected(self):
        """Неизвестный формат — код 2, до new и после new."""
        root = self.project()
        for args in (("--format", "xml"), ("new", "pln", "План", "--format", "xml")):
            code, out = support.check(root, *args)
            self.assertEqual(code, 2, out)
            self.assertIn("--format", out)


# @trace docs/ru/commands.md#help
class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-cli-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_help(self):
        code, out = cli(self.tmp, "help")
        self.assertEqual(code, 0)
        for word in ("check", "init", "new", "selftest", "version",
                     "--dry-run", "--enforce"):
            self.assertIn(word, out)
        self.assertNotIn("lipi update", out)
        self.assertNotIn("--update-internal", out)

    def test_update_is_unknown(self):
        for args in (("update",), ("update", str(self.tmp), "--dry-run")):
            with self.subTest(args=args):
                code, out = cli(self.tmp, *args)
                self.assertEqual(code, 2, out)
                self.assertIn(support.localized('unknown command: update', 'неизвестная команда: update'), out)
                self.assertEqual(list(self.tmp.iterdir()), [])

    # @trace docs/ru/commands.md#slice
    def test_slice_help(self):
        code, out = cli(self.tmp, "help", "slice")
        self.assertEqual(code, 0, out)
        for flag in ("--format", "--full", "--depth", "--layer", "--only"):
            self.assertIn(flag, out)

    def test_slice_bad_arguments(self):
        for args in ((), ("x", "--depth", "4"), ("x", "--depth", "1"),
                     ("x", "--only", "unknown"), ("x", "--only", ""),
                     ("x", "--format", "github")):
            with self.subTest(args=args):
                code, out = cli(self.tmp, "slice", *args)
                self.assertEqual(code, 2, out)

    def test_slice_c1_before_loading_project(self):
        for config in ('{"slice_budget": true}', '{"layers": []}',
                       '{"entry": ["["]}', '{broken'):
            support.w(self.tmp / "lipi.json", config)
            code, out = cli(self.tmp, "slice", "x", "--format", "json")
            self.assertEqual(code, 2, out)
            self.assertNotIn("Traceback", out)
            self.assertEqual(json.loads(out)["errors"][0]["code"], "C1")

    # @trace docs/ru/commands.md#output
    def test_unknown_command(self):
        code, out = cli(self.tmp, "wat")
        self.assertEqual(code, 2)
        self.assertIn(support.localized('unknown command', 'неизвестная команда'), out)

    # @trace docs/ru/commands.md#version
    def test_lipi_version_prints(self):
        code, out = cli(self.tmp, "version")
        self.assertEqual(code, 0)
        self.assertIn("lipi ", out)
        code, out = cli(self.tmp, "version", "--path")
        self.assertEqual(code, 0)
        self.assertIn("lipi ", out)
        self.assertTrue(out.strip().endswith("check.py"), out)

    # @trace docs/ru/commands.md#guide
    def test_guide_prints_setup(self):
        code, out = cli(self.tmp, "guide")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), (LIPI / "SETUP.md").read_text(encoding="utf-8").strip())

    def test_packaged_doc_preserves_nested_path(self):
        for name in ("docs/en/commands.md", "docs/ru/commands.md"):
            with self.subTest(page=name):
                self.assertEqual(cli_module.packaged_doc(name), LIPI / name)
                shared = self.tmp / "share" / "lipi" / name
                support.w(shared, "# Commands\n")
                with patch.object(cli_module, "REPO", self.tmp / "missing-repo"), \
                        patch.object(cli_module.sysconfig, "get_path", return_value=str(self.tmp)):
                    self.assertEqual(cli_module.packaged_doc(name), shared)

    def test_guide_missing_setup_links_to_installed_version(self):
        with patch.object(cli_module, "setup_text", return_value=None), \
                patch.object(sys, "argv", ["lipi", "guide"]), \
                patch("builtins.print") as output:
            self.assertEqual(cli_module.main(), 1)
        output.assert_called_once_with(
            support.localized("For setup instructions, see SETUP.md in the lipi repository: ",
                              "Инструкция по развёртыванию — SETUP.md репозитория lipi: ") +
            "https://github.com/lipisutra/lipi/blob/v%s/SETUP.md" % VERSION)

    # @trace docs/ru/commands.md#update,docs/ru/commands.md#check
    def test_init_and_check_in_cwd(self):
        p = self.tmp / "p"
        p.mkdir()
        code, out = cli(p, "init")
        self.assertEqual(code, 0, out)
        self.assertTrue((p / "lipi.json").is_file())
        code, out = cli(p, "check")
        self.assertEqual(code, 0, out)

    # @trace docs/ru/commands.md#check,ADR-010
    def test_check_runs_package_checker_with_external_copy_present(self):
        """Скрипт check.py в проекте не влияет на lipi check."""
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        support.w(p / support.CHECK_REL,
                  "import sys\nprint('пользовательский чекер в проекте')\nsys.exit(0)\n")
        code, out = cli(p, "check", "--version")
        self.assertEqual(code, 0, out)
        self.assertIn("lipi %s" % VERSION, out)
        self.assertNotIn("пользовательский чекер в проекте", out)

    def test_commands_never_run_project_checker_copy(self):
        """check, audit, index, baseline и new запускают чекер пакета."""
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        marker = self.tmp / "copy-ran"
        support.w(p / support.CHECK_REL,
                  "import sys\nopen(%r, 'w').close()\nprint('копия в проекте')\n"
                  "sys.exit(0)\n" % str(marker))
        for args in (("check",), ("audit",), ("index",), ("baseline",),
                     ("new", "pln", "План без копии")):
            _, out = cli(p, *args)
            self.assertNotIn("копия в проекте", out, args)
            self.assertFalse(marker.exists(), args)
        self.assertTrue(any((p / "workflow" / "plan").glob("[0-9][0-9][0-9][0-9]/pln-001-*")))

    # @trace docs/ru/commands.md#new
    def test_new_via_cli(self):
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        code, out = cli(p, "new", "pln", "План через команду")
        self.assertEqual(code, 0, out)
        self.assertTrue(any((p / "workflow" / "plan").glob("[0-9][0-9][0-9][0-9]/pln-001-*")))

    def test_new_never_writes_through_ignored_symlink(self):
        year = str(datetime.date.today().year)
        for nested in (False, True):
            for place in ("year", "file", "feedback", "adr"):
                with self.subTest(nested=nested, place=place):
                    repo = self.tmp / (place + ("-nested" if nested else "-root"))
                    project = repo / "project" if nested else repo
                    project.mkdir(parents=True)
                    support.git_init(repo)
                    code, out = cli(project, "init")
                    self.assertEqual(code, 0, out)
                    relative = (".agents/lipi-feedback" if place == "feedback" else
                                "workflow/adr" if place == "adr" else
                                "workflow/issue/" + year +
                                ("/iss-001-example.md" if place == "file" else ""))
                    support.w(project / ".gitignore", "/" + relative + "\n")
                    if place == "feedback":
                        set_config(project, workflow=None)
                    support.commit(repo, "initial")
                    peer = self.tmp / (repo.name + "-peer")
                    peer.mkdir()
                    sentinel = peer / "data.md"
                    support.w(sentinel, "unchanged\n")
                    link = project / relative
                    link.parent.mkdir(parents=True, exist_ok=True)
                    if link.is_dir():
                        shutil.rmtree(link)
                    link.symlink_to(sentinel if place == "file" else peer,
                                    target_is_directory=place != "file")
                    args = (["new", "adr", "Example"] if place == "adr" else
                            ["new", "iss", "Example", "bug"])
                    if place == "feedback":
                        args.append("lipi")
                    code, out = cli(project, *args)
                    self.assertEqual(code, 2, out)
                    self.assertIn(support.localized('symbolic link', 'символическая ссылка'), out)
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
                    self.assertEqual(list(peer.iterdir()), [sentinel])
                    self.assertTrue(link.is_symlink())

    def test_new_issue_hints_section(self):
        """`lipi new iss` печатает, какой раздел заполнить."""
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        code, out = cli(p, "new", "iss", "Что сломалось", "bug")
        self.assertEqual(code, 0, out)
        self.assertIn("Observation", out)
        self.assertIn(support.localized('fill in', 'заполните'), out)

    def test_new_plan_filename_omits_only_an_explicit_plan_label(self):
        root = self.tmp / "project"
        root.mkdir()
        code, out = cli(root, "init")
        self.assertEqual(code, 0, out)
        cases = [
            ("pln", "Plan: Agent guide", "agent-guide"),
            ("pln", "План: Agent guide", "agent-guide"),
            ("pln", "Plan comparison", "plan-comparison"),
            ("pln", "План работ", "plan-rabot"),
            ("pln", "Compare Plan: A", "compare-plan-a"),
            ("iss", "Plan: Agent guide", "plan-agent-guide"),
        ]
        for kind, title, expected in cases:
            with self.subTest(kind=kind, title=title):
                code, out = cli(root, "new", kind, title, "--format", "json")
                self.assertEqual(code, 0, out)
                doc = json.loads(out)
                path = root / doc["path"]
                self.assertEqual(path.name, f"{doc['id'].lower()}-{expected}.md")
                self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], "# " + title)

    def test_new_plan_hints_sections(self):
        """`lipi new pln` печатает оба обязательных раздела с пометкой о статусах."""
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        code, out = cli(p, "new", "pln", "План")
        self.assertEqual(code, 0, out)
        self.assertIn("Purpose", out)
        self.assertIn("Completion criteria", out)
        self.assertIn("in progress", out)
        self.assertIn("pending acceptance", out)

    def test_new_json_stays_pure(self):
        """new --format json: stdout остаётся чистым JSON, подсказка не печатается."""
        p = self.tmp / "p"
        p.mkdir()
        cli(p, "init")
        for prefix in ("pln", "iss"):
            code, out = cli(p, "new", prefix, "Через JSON", "bug", "--format", "json")
            self.assertEqual(code, 0, out)
            data = json.loads(out)
            self.assertTrue(data["id"].startswith(prefix.upper() + "-"), out)
            self.assertNotIn(support.localized('fill in', 'заполните'), out)

    # @trace docs/ru/commands.md#selftest
    def test_selftest_runs_unittest_discover(self):
        # только один тест (-k), чтобы не запускать весь набор из набора
        code, out = cli(LIPI, "selftest", "-k", "test_lipi_version_prints")
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)


# @trace docs/ru/commands.md#index,docs/ru/codes.md#w7
class TestIndexViaCli(Case):
    def test_index_repairs_stale_index(self):
        root = self.project()
        # W8: «Что наблюдается» обязателен у замечания «в работе» — заполняем
        support.sub(support.doc(root, "iss"), "## Observation",
                    "## Observation\n\nЗамечание взято в работу.")
        header_set(root, "iss", {"Status": "in progress"})
        # под CI локальная пересборка выключена: W7 видна, а lipi index чинит
        code, out = check(root, env={"CI": "1"})
        self.assertTrue(found(out, "W7"))
        code, out = cli(root, "index")
        self.assertEqual(code, 0, out)
        code, out = check(root, env={"CI": "1"})
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "W7"))


if __name__ == "__main__":
    unittest.main()
