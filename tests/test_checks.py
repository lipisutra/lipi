"""test_checks.py — проверки проекта из ключа checks (P1, ADR-008).

Чекер запускает команды, которые проект объявил в ``lipi.json``: без
оболочки, из корня проекта, первый элемент ``run`` со слэшем — путь от корня,
без слэша — команда из PATH. ``mode: quick`` — при каждой проверке,
``mode: audit`` — только с ``--audit``; ``timeout`` — предел времени в
секундах. Ненулевой код возврата, превышение времени или ненайденная команда —
ошибка P1 с именем проверки и последними 20 строками вывода; в
``--format github`` — аннотация без файла. В базовую линию P1 попадает как
обычная ошибка (subject — имя проверки).

Запуск: python3 -m unittest discover -s tests -p "test_checks.py" -v
"""
import json
import os
import sys
import unittest
from pathlib import Path

from tests import support
from tests.support import Case, check, check_json, found, set_config

PY = [sys.executable]


def python(*code):
    """Команда текущего интерпретатора: одинаково работает на любой ОС."""
    return PY + list(code)


def fail_with(text="", code=1):
    """Команда Python, печатающая text и завершающаяся кодом code."""
    program = "import sys"
    if text:
        program += "; sys.stdout.write(%r)" % text
    program += "; sys.exit(%d)" % code
    return python("-c", program)


def add_checks(root, *checks):
    """Записывает ключ checks в lipi.json проекта."""
    set_config(root, checks=list(checks))


def root_script(root, name="phpstan"):
    """Исполняемая команда в vendor/bin — путь от корня проекта.

    Успешна, только если рабочий каталог — корень проекта (виден lipi.json).
    На POSIX — sh-скрипт, на Windows — .cmd: чекер запускает файл по пути, а
    не через интерпретатор.
    """
    if os.name == "nt":
        rel = "vendor/bin/%s.cmd" % name
        support.w(root / rel,
                  "@echo off\r\n"
                  "if exist lipi.json (exit /b 0)\r\n"
                  "echo нет lipi.json\r\n"
                  "exit /b 3\r\n")
        return rel
    rel = "vendor/bin/%s" % name
    path = root / rel
    support.w(path, "#!/bin/sh\n"
                    "[ -f lipi.json ] || { echo \"нет lipi.json\"; exit 3; }\n"
                    "exit 0\n")
    path.chmod(0o755)
    return rel


def path_tool(directory, name="lipi-test-tool"):
    """Команда в каталоге PATH — обёртка, запускающая текущий Python.

    Возвращает каталог, который надо добавить в PATH.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        support.w(directory / (name + ".cmd"),
                  '@echo off\r\n"%s" %%*\r\n' % sys.executable)
    else:
        path = directory / name
        support.w(path, '#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        path.chmod(0o755)
    return directory


def with_path(directory):
    """Окружение с каталогом directory в начале PATH."""
    env = os.environ.copy()
    key = "PATH" if "PATH" in env else "Path"
    env[key] = str(directory) + os.pathsep + env.get(key, "")
    return env


def run_check(root, env, *args):
    """Чекер установленного lipi по проекту с окружением env (для PATH)."""
    return support.run(support.PY + [str(support.CHECK), "--root", str(root)]
                       + list(args), cwd=str(root), env=env)


class ProjectChecks(Case):
    """P1: успех, ненулевой код, таймаут, режимы, путь от корня, PATH."""

    def test_success_is_silent(self):
        """Успешная команда: P1 молчит, код возврата 0."""
        root = self.project()
        add_checks(root, {"name": "api", "run": python("-c", "pass")})
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "P1"), out)

    def test_nonzero_return_is_p1(self):
        """Ненулевой код возврата: P1, имя проверки, конец вывода, текстовый формат."""
        root = self.project()
        add_checks(root, {"name": "api",
                          "run": fail_with("первая строка\nпоследняя строка\n", 3)})
        code, out = check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        line = next(ln for ln in out.split("\n") if support.localized('[error P1]', "[ошибка P1]") in ln)
        self.assertTrue(line.startswith(support.localized('[error P1] check "api": exit code 3: ', "[ошибка P1] проверка «api»: код возврата 3: ")),
                        line)
        self.assertIn("первая строка", line)
        self.assertIn("последняя строка", out)

    def test_non_ascii_output_under_cp1252_parent(self):
        """Команда-скрипт Python печатает не-ASCII при PYTHONIOENCODING=cp1252
        у родителя (Windows-консоль): чекер задаёт дочерней UTF-8, и команда
        доходит до своего кода возврата, а не падает на UnicodeEncodeError."""
        root = self.project()
        add_checks(root, {"name": "api", "run": fail_with("хвост проверки\n", 3)})
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        code, out = run_check(root, env)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn(support.localized('exit code 3', "код возврата 3"), out)
        self.assertIn("хвост проверки", out)

    def test_json_finding_without_file(self):
        """JSON: P1 без файла и строки, subject — имя проверки."""
        root = self.project()
        add_checks(root, {"name": "api", "run": fail_with("сломано\n", 2)})
        code, data = check_json(root)
        self.assertEqual(code, 1)
        self.assertEqual(len(data["errors"]), 1, data)
        err = data["errors"][0]
        self.assertEqual(err["code"], "P1")
        self.assertEqual(err["file"], "")
        self.assertEqual(err["line"], 0)
        self.assertEqual(err["subject"], "api")
        self.assertIn('check "api": exit code 2', err["message"])
        self.assertIn("сломано", err["message"])

    def test_tail_is_last_20_lines(self):
        """В сообщение попадают последние 20 строк вывода, предыдущие — нет."""
        root = self.project()
        program = ";".join(["print('tail-%02d')" % i for i in range(1, 26)]
                           + ["raise SystemExit(1)"])
        add_checks(root, {"name": "long", "run": python("-c", program)})
        code, out = check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn("tail-25", out)
        self.assertIn("tail-06", out)
        self.assertNotIn("tail-05", out)

    def test_timeout_is_p1(self):
        """Превышение timeout: P1 с таймаутом и именем проверки."""
        root = self.project()
        add_checks(root, {"name": "slow",
                          "run": python("-c", "import time; time.sleep(10)"),
                          "timeout": 1})
        code, out = check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn(support.localized('check "slow": timed out after 1 s', "проверка «slow»: таймаут 1 с"), out)

    def test_audit_mode_only_in_audit(self):
        """mode audit: в быстрой проверке не запускается, с --audit — запускается."""
        root = self.project()
        add_checks(root, {"name": "deep", "run": fail_with("глубоко\n", 1),
                          "mode": "audit"})
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "P1"), out)
        code, out = check(root, "--audit")
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn(support.localized('"deep"', "«deep»"), out)

    def test_quick_mode_runs_in_audit_too(self):
        """mode quick (по умолчанию) запускается и в аудите."""
        root = self.project()
        add_checks(root, {"name": "fast", "run": fail_with(code=1)})
        code, out = check(root, "--audit")
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn(support.localized('"fast"', "«fast»"), out)

    def test_run_from_project_root_by_path(self):
        """run со слэшем — путь от корня проекта; cwd команды — корень."""
        root = self.project()
        add_checks(root, {"name": "phpstan",
                          "run": [root_script(root), "analyse-docs"]})
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "P1"), out)

    def test_missing_command_is_p1(self):
        """Нет файла по пути от корня: P1 «команда не найдена»."""
        root = self.project()
        add_checks(root, {"name": "gone", "run": ["vendor/bin/nope", "check"]})
        code, out = check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(found(out, "P1"), out)
        self.assertIn(support.localized('check "gone": command not found: vendor/bin/nope', "проверка «gone»: команда не найдена: vendor/bin/nope"), out)

    def test_command_from_path(self):
        """run без слэша: команда ищется в PATH (на Windows — и .cmd)."""
        root = self.project()
        tool = path_tool(root / "tools")
        add_checks(root, {"name": "which", "run": ["lipi-test-tool", "-c", "pass"]})
        code, out = run_check(root, with_path(tool))
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "P1"), out)


class ProjectChecksSchema(Case):
    """C1: неверный ключ checks — код 2 с подсказкой, команды не запускаются."""

    BAD = (
        ("api", ('key "checks": expected a list, got string', "ключ «checks»: ожидается список, а не строка")),
        (["api"], ('item 1: expected an object, got string', "элемент 1: ожидается объект, а не строка")),
        ([{"run": ["x"]}], ('item 1: missing key "name"', "элемент 1: нет ключа «name»")),
        ([{"name": "api"}], ('item 1: missing key "run"', "элемент 1: нет ключа «run»")),
        ([{"name": 1, "run": ["x"]}], ('"name": expected a string, got integer', "«name»: ожидается строка, а не целое")),
        ([{"name": " ", "run": ["x"]}], ('empty check name', "пустое имя проверки")),
        ([{"name": "api", "run": []}], ('"run": empty list', "«run»: пустой список")),
        ([{"name": "api", "run": ["x", 1]}],
         ('item 2: expected a string, got 1', "элемент 2: ожидается строка, а не 1")),
        ([{"name": "api", "run": ["x"], "mod": "quick"}],
         ('unknown key "mod", did you mean "mode"?', "неизвестный ключ «mod», имелось в виду «mode»?")),
        ([{"name": "api", "run": ["x"], "mode": "fast"}],
         ('"mode": expected quick or audit, got "fast"', "«mode»: ожидается quick или audit, а не «fast»")),
        ([{"name": "api", "run": ["x"], "mode": 1}],
         ('"mode": expected quick or audit, got 1', "«mode»: ожидается quick или audit, а не 1")),
        ([{"name": "api", "run": ["x"], "timeout": 0}],
         ('"timeout": expected a positive integer (seconds), got 0', "«timeout»: ожидается положительное целое (секунды), а не 0")),
        ([{"name": "api", "run": ["x"], "timeout": "300"}],
         ('"timeout": expected a positive integer (seconds), got "300"', "«timeout»: ожидается положительное целое (секунды), а не «300»")),
    )

    def test_bad_checks_stop_with_2(self):
        """Неверный ключ/тип/значение checks — C1, код 2, подсказка."""
        for checks, expected in self.BAD:
            with self.subTest(checks=checks):
                root = self.project()
                set_config(root, checks=checks)
                code, out = check(root)
                self.assertEqual(code, 2, out)
                self.assertTrue(found(out, "C1"), out)
                self.assertIn(support.localized(*expected), out)

    def test_valid_checks_pass_schema(self):
        """Полный объект проверки с mode и timeout — C1 молчит."""
        root = self.project()
        add_checks(root, {"name": "api", "run": python("-c", "pass"),
                          "mode": "audit", "timeout": 300})
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "C1"), out)


class ProjectChecksOutput(Case):
    """Вывод P1: github без file и базовая линия по имени проверки."""

    def test_github_annotation_without_file(self):
        """--format github: ::error без file, title=P1."""
        root = self.project()
        add_checks(root, {"name": "api", "run": fail_with("упало\n", 1)})
        code, out = check(root, "--format", "github")
        self.assertEqual(code, 1, out)
        line = next(ln for ln in out.split("\n") if "title=P1" in ln)
        self.assertTrue(line.startswith("::error title=P1::"), line)
        self.assertNotIn("file=", line)
        self.assertIn(support.localized('"api"', "«api»"), line)

    def test_baseline_covers_p1(self):
        """Ошибка P1 в линии: проверка 0, subject — имя проверки."""
        root = self.project()
        add_checks(root, {"name": "api", "run": fail_with("упало\n", 1)})
        self.assertEqual(check(root)[0], 1)
        code, out = check(root, "baseline")
        self.assertEqual(code, 0, out)
        entries = json.loads((root / support.BASE_REL).read_text(encoding="utf-8"))["entries"]
        self.assertEqual(entries,
                         [{"code": "P1", "file": "", "subject": "api", "count": 1}])

        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(found(out, "P1"), out)
        self.assertIn(support.localized('in the baseline: 1', "в базовой линии 1"), out)

        add_checks(root, {"name": "api", "run": python("-c", "pass")})
        code, out = check(root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('fixed: 1', "исправлено 1"), out)


if __name__ == "__main__":
    unittest.main()
