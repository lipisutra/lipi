"""test_doctor.py — команда lipi doctor: диагностика развёртывания.

Каждый тест получает копию чистого проекта (init + git + pre-commit от
lipi при `"enforce": true`) и портит в ней ровно один пункт: версию
lock-файла, pre-commit, указатель. Проверяется сторона «проблема» и соседняя
сторона «ок»; чистый проект — код 0, версии установленного lipi и проекта
рядом, ни одного пункта про копию чекера (ADR-010: копии в проекте нет).
"""
import contextlib
import io
import itertools
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support
from tests.support import localized

sys.path.insert(0, str(support.SRC.parent))
from lipi import doctor as doctor_module

VERSION = support.VERSION
ITEM_NAMES = ("Python:", "lipi:", "lipi.json:", localized('lock file:', "lock-файл:"),
              "pre-commit:", localized('layout:', "раскладка:"), localized('headers:', "шапки:"), localized('index:', "указатель:"), localized('baseline:', "базовая линия:"))


def snapshot(root):
    """Пути файлов проекта без .git: doctor не должен ничего создавать."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.relative_to(root).parts[0] != ".git")


class DoctorTest(unittest.TestCase):
    _counter = itertools.count()

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lipi-doctor-"))
        cls.base = cls.tmp / "base"
        cls.base.mkdir()
        support.git_init(cls.base)
        code, out = support.init(cls.base)
        if code != 0:
            raise AssertionError("init не прошёл: %s" % out)
        # Хук ставит сам lipi по ключу enforce (ADR-011), копии чекера в
        # проекте нет (ADR-010), а doctor проверяет, что хук на месте.
        support.set_config(cls.base, enforce=True)
        code, out = support.init(cls.base)
        if code != 0:
            raise AssertionError("повторный init не прошёл: %s" % out)
        code, out = support.doctor(cls.base)
        if code != 0:
            raise AssertionError("чистый проект не чист: %s" % out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self):
        root = self.tmp / ("p-%d" % next(type(self)._counter))
        shutil.copytree(self.base, root)
        return root

    def doctor(self, root):
        code, out = support.doctor(root)
        self.assertNotIn("Traceback", out, out)
        return code, out

    def assert_ok(self, out, name):
        line = next((s for s in out.splitlines() if s.startswith(name)), None)
        self.assertIsNotNone(line, "нет строки %s в:\n%s" % (name, out))
        self.assertTrue(line.endswith(localized('— OK', "— ок")), line)

    def test_clean_project(self):
        """Чистый проект: код 0, все семь пунктов «ок», версии рядом."""
        code, out = self.doctor(self.project())
        self.assertEqual(code, 0, out)
        self.assertNotIn(localized('[problem]', "[проблема]"), out)
        self.assertNotIn(localized('checker copy', "копия чекера"), out)
        for name in ITEM_NAMES:
            self.assert_ok(out, name)
        self.assertEqual(out.count(localized('— OK', "— ок")), len(ITEM_NAMES), out)
        self.assertIn(localized('Python: %s — OK', "Python: %s — ок") % sys.version.split()[0], out)
        self.assertIn(localized('lipi: %s — OK', "lipi: %s — ок") % VERSION, out)
        self.assertIn(localized('lock file: found, project %s (lipi %s) — OK', "lock-файл: есть, проект %s (lipi %s) — ок") % (VERSION, VERSION), out)
        self.assertIn(localized('pre-commit: found, lipi check --staged — OK', "pre-commit: есть, lipi check --staged — ок"), out)
        self.assertIn(localized('baseline: found, entries: 0, errors: 0 — OK', "базовая линия: есть, записей 0, ошибок 0 — ок"), out)
        self.assertIn(localized('No problems found', "итого: проблем нет"), out)

    def test_no_project(self):
        """Каталог без lipi.json: проект не найден, что запустить, код 1."""
        root = self.tmp / "empty"
        root.mkdir()
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('project: lipi not found', "проект: lipi не найден"), out)
        self.assertIn(localized('[problem]', "[проблема]"), out)
        self.assertIn("lipi init", out)
        # проверки проекта не запускаются: нечего проверять
        self.assertNotIn(localized('lock file', "lock-файл"), out)
        self.assertNotIn(localized('index', "указатель"), out)

    def test_no_lock(self):
        root = self.project()
        (root / support.LOCK_REL).unlink()
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('lock file: missing — [problem]', "lock-файл: нет — [проблема]"), out)
        self.assertIn("lipi init", out)

    def test_lock_previous_major(self):
        """Проект младшей линии: диагностика указывает CHANGELOG и init."""
        root = self.project()
        major = int(VERSION.split(".")[0])
        report, output = doctor_module.Report(), io.StringIO()
        with patch.object(doctor_module, "VERSION", "%d.0.0" % (major + 1)):
            with contextlib.redirect_stdout(output):
                doctor_module.check_lock(root, report)
        self.assertEqual(report.problems, 1, output.getvalue())
        self.assertIn(localized('the project uses %d.x. Read CHANGELOG.md and run lipi init', "проект на %d.x — прочитайте CHANGELOG.md и примените lipi init")
                      % major, output.getvalue())

    def test_invalid_lock_requires_repair(self):
        """init не исправляет повреждённый lock: сначала нужно восстановление."""
        for contents in ("{broken", "{}"):
            with self.subTest(contents=contents):
                root = self.project()
                support.w(root / support.LOCK_REL, contents)
                code, out = self.doctor(root)
                self.assertEqual(code, 1, out)
                self.assertIn(localized('Restore the lock file, then run lipi init', "восстановите lock-файл, затем запустите lipi init"), out)

    def test_lock_newer_major(self):
        """Проект на новой первой цифре: pipx upgrade lipi."""
        root = self.project()
        newer = "%d.0.0" % (int(VERSION.split(".")[0]) + 1)
        support.set_lock_version(root, newer)
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('lock file: found, project %s (lipi %s) — [problem]', "lock-файл: есть, проект %s (lipi %s) — [проблема]") % (newer, VERSION), out)
        self.assertIn(localized('upgrade lipi: pipx upgrade lipi', "обновите lipi: pipx upgrade lipi"), out)

    def test_lock_newer_same_major(self):
        """Проект новее в пределах первой цифры: обновить lipi (предупреждение)."""
        root = self.project()
        major, minor, _ = map(int, VERSION.split("."))
        support.set_lock_version(root, "%d.%d.0" % (major, minor + 1))
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('upgrade lipi: pipx upgrade lipi', "обновите lipi: pipx upgrade lipi"), out)

    def test_no_hook_enforce(self):
        """enforce: true и хука нет: lipi init его поставит."""
        root = self.project()
        (root / ".git" / "hooks" / "pre-commit").unlink()
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('pre-commit: missing — [problem]', "pre-commit: нет — [проблема]"), out)
        self.assertIn(localized('Run lipi init', "запустите lipi init"), out)

    def test_no_hook_soft(self):
        """enforce: false и хука нет — не проблема."""
        root = self.project()
        support.set_config(root, enforce=False)
        (root / ".git" / "hooks" / "pre-commit").unlink()
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('pre-commit: missing (enforce: false) — OK', "pre-commit: нет (enforce: false) — ок"), out)

    def test_own_hook_soft(self):
        """enforce выключен, а хук lipi остался: lipi init его уберёт."""
        root = self.project()
        support.set_config(root, enforce=False)
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('pre-commit: found, lipi check --staged — [problem]', "pre-commit: есть, lipi check --staged — [проблема]"), out)
        self.assertIn(localized('Run lipi init to remove the hook', "lipi init уберёт этот хук"), out)

    def test_unmarked_lipi_invocation_is_foreign_when_enforced(self):
        """Даже вызов lipi в хуке без метки считается пользовательским."""
        root = self.project()
        support.w(root / ".git" / "hooks" / "pre-commit",
                  "#!/bin/sh\nexec lipi check --staged\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('pre-commit: found, project hook (missing lipi marker) — [problem]', "pre-commit: есть, чужой хук (без метки lipi) — [проблема]"), out)
        self.assertIn(localized('To install the lipi hook', "lipi его не трогает"), out)

    def test_unmarked_lipi_invocation_is_foreign_in_soft_mode(self):
        """Хук с вызовом lipi без метки сохраняется при enforce: false."""
        root = self.project()
        support.set_config(root, enforce=False)
        support.w(root / ".git" / "hooks" / "pre-commit",
                  "#!/bin/sh\nexec lipi check --staged\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('pre-commit: found, project hook (missing lipi marker). lipi leaves it in place. — OK', "pre-commit: есть, чужой хук (без метки lipi) — lipi его не трогает — ок"), out)

    def test_foreign_hook_enforce(self):
        """Чужой хук при enforce: true: lipi его не трогает."""
        root = self.project()
        support.w(root / ".git" / "hooks" / "pre-commit", "#!/bin/sh\nexit 0\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('pre-commit: found, project hook (missing lipi marker) — [problem]', "pre-commit: есть, чужой хук (без метки lipi) — [проблема]"), out)
        self.assertIn(localized('To install the lipi hook', "lipi его не трогает"), out)

    def test_foreign_hook_soft(self):
        """Чужой хук при enforce: false — не проблема."""
        root = self.project()
        support.set_config(root, enforce=False)
        support.w(root / ".git" / "hooks" / "pre-commit", "#!/bin/sh\nexit 0\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('pre-commit: found, project hook (missing lipi marker). lipi leaves it in place. — OK', "pre-commit: есть, чужой хук (без метки lipi) — lipi его не трогает — ок"), out)

    def test_stale_index(self):
        """Устаревший указатель — проблема; после lipi index — чистый проект."""
        root = self.project()
        # без рабочих документов W7 не проверяется: заводим план
        code, out = support.check(root, "new", "pln", "План")
        self.assertEqual(code, 0, out)
        index = root / "workflow" / "INDEX.md"
        support.w(index, index.read_text(encoding="utf-8") + "\nручная правка\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn(localized('index: stale — [problem]', "указатель: устарел — [проблема]"), out)
        self.assertIn("lipi index", out)
        code, out = support.reindex(root)
        self.assertEqual(code, 0, out)
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('index: current — OK', "указатель: актуален — ок"), out)

    def test_reports_flat_document_and_invalid_header(self):
        root = self.project()
        support.w(root / "workflow" / "plan" / "pln-001-flat.md",
                  "# План\n\n- Created: неверная\n- Status: new\n")
        before = snapshot(root)
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn("W10]", out)
        self.assertIn("W3]", out)
        self.assertIn("workflow/plan/pln-001-flat.md", out)
        self.assertEqual(snapshot(root), before)

    def test_reports_wrong_year_and_missing_closed_date(self):
        root = self.project()
        support.w(root / "workflow" / "plan" / "2025" / "pln-001-done.md",
                  "# План\n\n- Created: 2024-01-01\n"
                  "- Updated: 2025-01-01\n- Status: completed\n"
                  "- Result: готово\n")
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertIn("W11]", out)
        self.assertIn("W4]", out)
        self.assertIn("Closed", out)
        self.assertIn("pln-001-done.md", out)

    def test_baseline_size(self):
        """Базовая линия есть: печатаются записи и суммарное число ошибок."""
        root = self.project()
        support.w(root / support.BASE_REL, json.dumps(
            {"schema": 1, "entries": [
                {"code": "D1", "file": "docs/guide.md", "subject": "net.md", "count": 2},
                {"code": "W6", "file": "docs/README.md", "subject": "gone.md", "count": 1},
            ]}, ensure_ascii=False))
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertNotIn(localized('[problem]', "[проблема]"), out)
        self.assertIn(localized('baseline: found, entries: 2, errors: 3 — OK', "базовая линия: есть, записей 2, ошибок 3 — ок"), out)

    def test_creates_nothing(self):
        """Проблемное состояние: doctor только читает, файлы не меняются."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        before = snapshot(root)
        code, out = self.doctor(root)
        self.assertEqual(code, 1, out)
        self.assertEqual(snapshot(root), before)

    def test_prints_under_cp1252(self):
        """Windows: doctor печатает в UTF-8 даже при кодировке консоли cp1252."""
        root = self.project()
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        code, out = support.run(support.PY + [str(support.DOCTOR)],
                                cwd=str(root), env=env)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('baseline: found, entries: 0, errors: 0 — OK', "базовая линия: есть, записей 0, ошибок 0 — ок"), out)

    def test_no_baseline(self):
        """Базовая линия удалена: doctor печатает «нет» без проблемы."""
        root = self.project()
        (root / support.BASE_REL).unlink()
        code, out = self.doctor(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('baseline: missing — OK', "базовая линия: нет — ок"), out)

    def test_cli(self):
        """lipi doctor — команда lipi, она есть в справке."""
        root = self.project()
        code, out = support.cli(root, "doctor")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('— OK', "— ок"), out)
        code, out = support.cli(self.tmp, "help")
        self.assertEqual(code, 0, out)
        self.assertIn("lipi doctor", out)


if __name__ == "__main__":
    unittest.main()
