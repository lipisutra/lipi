"""test_release.py — версия, CHANGELOG, lock и уровни кодов.

Проверяет согласованность выпуска:

- версия в `src/lipi/__init__.py` (`__version__`), верхний заголовок версии в
  `CHANGELOG.md` и `"lipi"` в `.agents/lipi/lipi.lock` самого lipi совпадают;
- после первого выпуска каждая запись сначала предлагает обновить программу,
  затем говорит, требуется ли применить `lipi init`;
- истории шаблонов `locale/<language>/templates/history/` в пакете нет: по ADR-009
  `lipi init` заменяет файлы lipi целиком, старые шаблоны ему не нужны
  (З24). Каталог не виден ни на дереве, ни через `importlib.resources`;
- дисциплина выпусков (З7, ADR-010): таблица уровней `CODE_LEVELS` в чекере
  сравнивается с таблицей на теге `v<первая цифра>.0.0`. Новый код с уровнем
  `error` или повышение уровня с `warning` до `error` внутри одной первой
  цифры — ошибка теста. ADR-022 допускает в линии 1.x ошибку T5 для явной роли.
  Смена первой цифры разрешает
  повышения: они попадают в сам тег, и сравнение с ним их не ловит.
  До первого тега новой линии сравнения уровней пропускаются; версия,
  CHANGELOG и lock проверяются независимо. Для 1.x эталон — тег v1.0.0.

Запуск: python3 -m unittest discover -s tests -p "test_release.py" -v
"""
import importlib.resources
import json
import re
import subprocess
import sys
import unittest
from unittest import mock

from tests import support

LOCALE = support.SRC / "locale"
LOCK = support.LIPI / ".agents" / "lipi" / "lipi.lock"
CHANGELOG = support.LIPI / "CHANGELOG.md"
FIRST_RELEASE = "1.0.0"
REPORT = "src/lipi/checker/report.py"

HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+) —", re.M)
TABLE_RE = re.compile(r"^CODE_LEVELS = \{(.*?)^\}", re.M | re.S)
PAIR_RE = re.compile(r'"([A-Z][0-9])": "(error|warning)"')


def version():
    """Версия lipi из `src/lipi/__init__.py`."""
    return support.VERSION


def changelog_versions():
    """Версии из заголовков `## X.Y.Z — дата` в порядке файла."""
    return HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))


def check_upgrade_instructions(text):
    """Два обязательных шага каждой записи после первого выпуска."""
    entries = re.split(HEADING_RE, text)
    for release, body in zip(entries[1::2], entries[2::2]):
        if release == FIRST_RELEASE:
            continue
        section = re.search(
            r"^### Upgrading your project(?: for " + re.escape(release)
            + r")?\s*\n(.*?)(?=^### |\Z)", body, re.M | re.S)
        assert section, "%s: нет раздела «Upgrading your project»" % release
        lines = [line.strip() for line in section.group(1).splitlines() if line.strip()]
        commands = ("pipx upgrade lipi",
                    "pipx install --force git+https://github.com/lipisutra/lipi@v" + release)
        assert lines and lines[0] in (
            "1. Upgrade Lipi with `%s`." % command for command in commands
        ), "%s: первый шаг должен обновлять установленную программу" % release
        assert len(lines) > 1 and lines[1] in (
            "2. The rules and templates are unchanged. You can skip `lipi init`.",
            "2. The rules and templates have changed. Run `lipi init`.",
        ), "%s: второй шаг должен согласовать изменения правил и шаблонов с lipi init" % release


def parse_levels(text):
    """Таблица CODE_LEVELS из текста чекера: код → уровень."""
    m = TABLE_RE.search(text)
    assert m, "в чекере нет таблицы CODE_LEVELS"
    return dict(PAIR_RE.findall(m.group(1)))


def levels_of_checker():
    return parse_levels((support.LIPI / REPORT).read_text(encoding="utf-8"))


def tagged_file(tag, path):
    proc = subprocess.run(
        ["git", "-C", str(support.LIPI), "show", "%s:%s" % (tag, path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout.decode("utf-8")


def tagged_levels(tag):
    """Эталон читает только тег lipi; ошибки чтения не скрываются."""
    exists = subprocess.run(
        ["git", "-C", str(support.LIPI), "show-ref", "--verify", "--quiet",
         "refs/tags/%s" % tag],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if exists.returncode == 1:
        raise unittest.SkipTest("тега %s ещё нет — сравнение уровней пропущено" % tag)
    exists.check_returncode()
    project = re.search(r"^[ \t]*\[project\][ \t]*$(.*?)(?=^[ \t]*\[|\Z)",
                        tagged_file(tag, "pyproject.toml"), re.M | re.S)
    assert project, "%s: в pyproject.toml нет раздела [project]" % tag
    name = re.search(r"""^[ \t]*name[ \t]*=[ \t]*["']([^"'\n]+)["']""",
                     project[1], re.M)
    assert name, "%s: в [project] не указано имя пакета" % tag
    if name[1] != "lipi":
        raise unittest.SkipTest("тег %s относится к другому пакету" % tag)
    return parse_levels(tagged_file(tag, REPORT))


def reference_levels():
    """Таблица уровней на первом теге текущей мажорной линии."""
    major = version().split(".")[0]
    tag = "v%s.0.0" % major
    return tagged_levels(tag), tag


class TestVersionConsistency(unittest.TestCase):
    """Версия одна и та же в коде, CHANGELOG и lock-файле lipi."""

    def test_version_matches_changelog(self):
        """Верхний заголовок CHANGELOG.md — версия из __init__.py."""
        versions = changelog_versions()
        self.assertTrue(versions, "в CHANGELOG.md нет заголовков версий")
        self.assertEqual(versions[0], version())

    def test_version_matches_lock(self):
        """Версия в .agents/lipi/lipi.lock — та же, что в __init__.py."""
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(lock.get("lipi"), version())


class TestUpgradeInstructions(unittest.TestCase):
    """Установка программы предшествует решению об обновлении файлов проекта."""

    INSTALL = "1. Upgrade Lipi with `pipx upgrade lipi`."
    UNCHANGED = "2. The rules and templates are unchanged. You can skip `lipi init`."
    CHANGED = "2. The rules and templates have changed. Run `lipi init`."

    def entry(self, steps, release="1.1.0"):
        return ("## %s — 2026-01-01\n\n### Upgrading your project for %s\n\n%s\n"
                % (release, release, "\n".join(steps)))

    def test_changelog_upgrade_instructions(self):
        check_upgrade_instructions(CHANGELOG.read_text(encoding="utf-8"))

    def test_supported_install_commands_and_decisions(self):
        for release in ("1.1.0", "1.10.0"):
            for command in (self.INSTALL,
                            "1. Upgrade Lipi with `pipx install --force "
                            "git+https://github.com/lipisutra/lipi@v%s`." % release):
                for decision in (self.UNCHANGED, self.CHANGED):
                    with self.subTest(release=release, command=command, decision=decision):
                        check_upgrade_instructions(self.entry((command, decision), release))

    def test_missing_install_or_update_first_fails(self):
        for steps in ((self.UNCHANGED,),
                      ("1. Run `lipi init`.", self.INSTALL, self.CHANGED),
                      (self.INSTALL.replace("pipx upgrade lipi", "pipx install --force "
                       "git+https://github.com/lipisutra/lipi@v1.0.0"), self.UNCHANGED)):
            with self.subTest(steps=steps), self.assertRaisesRegex(AssertionError, "первый шаг"):
                check_upgrade_instructions(self.entry(steps))

    def test_missing_or_contradictory_decision_fails(self):
        for decision in ("", "2. Run `lipi init`.",
                         self.UNCHANGED.replace("are unchanged", "have changed"),
                         self.CHANGED.replace("have changed", "are unchanged")):
            with self.subTest(decision=decision), self.assertRaisesRegex(AssertionError, "второй шаг"):
                check_upgrade_instructions(self.entry((self.INSTALL, decision)))

    def test_upgrade_section_requires_english_heading_and_steps(self):
        valid = self.entry((self.INSTALL, self.CHANGED))
        for expected, old in (
            ("Upgrading your project", "Проекту при обновлении"),
            (self.INSTALL, "1. Обновите программу: `pipx upgrade lipi`."),
            (self.CHANGED, "2. Правила и шаблоны изменились — выполните `lipi init`."),
        ):
            with self.subTest(old=old), self.assertRaises(AssertionError):
                check_upgrade_instructions(valid.replace(expected, old))

    def test_only_first_release_may_omit_upgrade_instructions(self):
        first = "## 1.0.0 — First release\n\nRelease notes.\n"
        valid = self.entry((self.INSTALL, self.UNCHANGED), "1.2.0")
        check_upgrade_instructions(first)
        check_upgrade_instructions(valid + first)
        for release in ("1.0.1", "1.1.0"):
            with self.subTest(release=release), self.assertRaises(AssertionError):
                check_upgrade_instructions(valid + self.entry((), release) + first)
        with self.assertRaisesRegex(AssertionError, "нет раздела"):
            check_upgrade_instructions("## 1.0.1 — 2026-01-01\nRelease notes.\n")


class TestNoTemplateHistory(unittest.TestCase):
    """Истории шаблонов в пакете нет — init она не нужна."""

    def test_no_history_directory(self):
        """Каталога locale/<language>/templates/history/ нет."""
        for language in LOCALE.iterdir():
            self.assertFalse((language / "templates" / "history").exists())

    def test_package_resources_have_no_history(self):
        """importlib.resources в пакете lipi не видит templates/history."""
        src = str(support.LIPI / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        package = importlib.import_module("lipi")
        self.assertTrue(str(package.__file__).startswith(src),
                        "пакет загружен не из src: %s" % package.__file__)
        for language in ("en", "ru"):
            templates = importlib.resources.files(package).joinpath("locale", language, "templates")
            self.assertTrue(templates.is_dir())
            self.assertFalse(templates.joinpath("history").is_dir())


# @trace ADR-010
class TestLevelsDiscipline(unittest.TestCase):
    """Дисциплина выпусков (ADR-010): уровни кодов против тега линии."""

    def test_new_codes_follow_major_line_defaults(self):
        """T5 проверяет явный атрибут роли. Остальные новые коды начинают с warning."""
        current = levels_of_checker()
        reference, where = reference_levels()
        for code, level in sorted(current.items()):
            if code not in reference:
                expected = "error" if (where, code) == ("v1.0.0", "T5") else "warning"
                self.assertEqual(level, expected,
                                 "новый код %s в линии %s: ожидается %s" %
                                 (code, where, expected))

    def test_no_promotion_inside_major(self):
        """Повышение уровня warning → error внутри первой цифры запрещено."""
        current = levels_of_checker()
        reference, where = reference_levels()
        for code, level in sorted(current.items()):
            if reference.get(code) == "warning" and level == "error":
                self.fail("код %s повышен с warning до error внутри первой "
                          "цифры (%s): повышение уровня — только при смене "
                          "первой цифры" % (code, where))


class TestTaggedLevels(unittest.TestCase):
    """Отсутствие тега не должно скрывать повреждённый эталон выпуска."""

    @mock.patch(__name__ + ".subprocess.run")
    def test_absent_tag_skips_comparison(self, run):
        run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaises(unittest.SkipTest):
            tagged_levels("v1.0.0")

    @mock.patch(__name__ + ".subprocess.run")
    def test_tag_of_another_project_skips_comparison(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0),
                           subprocess.CompletedProcess([], 0, stdout=b'[project]\nname = "example"\n')]
        with self.assertRaises(unittest.SkipTest):
            tagged_levels("v1.0.0")

    @mock.patch(__name__ + ".subprocess.run")
    def test_existing_tag_without_file_fails(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0),
                           subprocess.CompletedProcess([], 0, stdout=b'[project]\nname = "lipi"\n'),
                           subprocess.CalledProcessError(128, ["git", "show"])]
        with self.assertRaises(subprocess.CalledProcessError):
            tagged_levels("v1.0.0")

    @mock.patch(__name__ + ".subprocess.run")
    def test_existing_tag_without_table_fails(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0),
                           subprocess.CompletedProcess([], 0, stdout=b'[project]\nname = "lipi"\n'),
                           subprocess.CompletedProcess([], 0, stdout=b"no table")]
        with self.assertRaisesRegex(AssertionError, "CODE_LEVELS"):
            tagged_levels("v1.0.0")

    @mock.patch(__name__ + ".subprocess.run")
    def test_existing_tag_without_package_name_fails(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout=b'[project]\n[tool.example]\nname = "other"\n'),
        ]
        with self.assertRaisesRegex(AssertionError, "не указано имя пакета"):
            tagged_levels("v1.0.0")


if __name__ == "__main__":
    unittest.main()
