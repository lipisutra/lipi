"""test_migrate.py — `lipi migrate`: перенос рабочих материалов существующего проекта.

Проверки переноса (ADR-004):
- три синтетические фикстуры раскладок существующих проектов (каталоги
  статусов current/completed/backlog, разная нумерация, ветки 011-1, журнал,
  мастер-план, отчёты, документы-папки): после `migrate --apply` и `baseline`
  проверка чиста, а без линии остаются только ошибки вне W1–W7; ссылки из
  docs/ и корневых .md переписаны и не битые;
- план без --apply ничего не меняет и печатает таблицу;
- отказы: вне git, грязное дерево, нет каталога, неверный migrate.json;
- migrate.json переопределяет тип, статус и номер;
- журнал и мастер-план уходят в history/, MIGRATION.md, итог завершённого
  плана, конфликт номера, даты из шапки и из коммитов, статусы по словам.

Фикстуры синтетические, в tempdir: чужие репозитории не трогаются (ADR-007).
"""
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.support import localized

sys.path.insert(0, str(support.LIPI / "src"))

TODAY = datetime.date.today().isoformat()
MIGRATE = support.MIGRATE
W_CODES = ("W1", "W2", "W3", "W4", "W5", "W6", "W7", "W10", "W11")


def migrate(root, *args):
    return support.run(support.PY + [str(MIGRATE)] + list(args), cwd=str(root))


def read(path):
    return Path(path).read_text(encoding="utf-8")


def status_lines(root):
    return [line for line in support.git(root, "status", "--porcelain")[1]
            .split("\n") if line.strip()]


def git_fixture(root, date="2026-03-01T10:00:00"):
    support.git_init(root)
    return support.commit(root, "fixture", date)


# --- Фикстуры раскладок существующих проектов --------------------------------

def fixture_status_dirs(root):
    """Раскладка по каталогам статусов: current/completed/backlog, журнал, отчёты."""
    assert support.init(root)[0] == 0
    w = support.w
    w(root / "workflow" / "current" / "roadmap.md",
      "# Дорожная карта\n\n- Дата создания: 2026-01-10\n- Статус: в работе\n\n"
      "## Зачем <a id=\"why\"></a>\n\nРазвитие продукта.\n")
    w(root / "workflow" / "current" / "plan-active.md",
      "# Активный план\n\n- Дата создания: 2026-01-11\n- Статус: In progress\n\n"
      "## Зачем\n\nНужно уже сейчас.\n")
    w(root / "workflow" / "completed" / "plan-done.md",
      "# Сделанный план\n\n- Дата создания: 2026-01-02\n- Статус: Done\n\n"
      "Чем кончилось — не записано.\n")
    w(root / "workflow" / "backlog" / "later.md",
      "# Позже\n\n- Дата: 2026-01-03\n\nКогда-нибудь.\n")
    w(root / "workflow" / "current" / "iss-003-bug.md",
      "# Падение на старте\n\n- Дата создания: 2026-01-05\n- Статус: открыто\n\n"
      "## Что наблюдается\n\nПроцесс падает.\n")
    w(root / "workflow" / "reports" / "2026-01.md",
      "# Отчёт за январь\n\n[дорожная карта](../current/roadmap.md)\n")
    w(root / "workflow" / "ЖУРНАЛ.md",
      "# Журнал\n\n[отчёт](reports/2026-01.md)\n")
    # ссылка из описания и корневого README в переносимые документы
    docs = root / "docs" / "README.md"
    support.sub(docs, "| --- | --- |",
                "| --- | --- |\n| Дорожная карта | "
                "[План](../workflow/current/roadmap.md#why) |")
    w(root / "README.md",
      "# Проект\n\n[дорожная карта](workflow/current/roadmap.md)\n"
      "[внешний](https://example.com/a)\n")
    git_fixture(root)


def fixture_numbers(root):
    """Другая нумерация (011 и ветка 011-1), даты из коммитов, статусы словами."""
    assert support.init(root)[0] == 0
    w = support.w
    w(root / "workflow" / "current" / "011-plan-roadmap.md",
      "# Дорожная карта\n\n- Статус: in progress\n\n## Зачем\n\nРазвитие.\n\n"
      "## Критерии завершения\n\nПлан выполнен.\n")
    w(root / "workflow" / "current" / "011-1-refactor.md",
      "# Рефакторинг\n\n- Дата создания: 2026-01-01\n")
    w(root / "workflow" / "current" / "weird.md",
      "# Непонятный статус\n\n- Статус: in review\n")
    w(root / "workflow" / "completed" / "plan-old.md",
      "# Старый план\n\n- Статус: готово\n\nЧем кончилось — забыли.\n")
    w(root / "workflow" / "backlog" / "iss-002-wish.md",
      "# Пожелание\n\n- Дата создания: 2026-01-02\n- Вид: запрос\n\n"
      "## Что наблюдается\n\nХочется удобнее.\n")
    w(root / "workflow" / "adr" / "decision.md",
      "# Решение\n\n- Статус: accepted\n")
    git_fixture(root, "2026-01-01T10:00:00")
    support.sub(root / "workflow" / "current" / "011-plan-roadmap.md",
                "## Критерии завершения", "Обновлено позже.\n\n## Критерии завершения")
    support.commit(root, "правка", "2026-02-02T12:00:00")


def fixture_correct_layout(root):
    """Раскладка уже по правилам: документы на месте, папка-документ, нет README."""
    assert support.init(root)[0] == 0
    (root / "workflow" / "README.md").unlink()
    w = support.w
    w(root / "workflow" / "plan" / "2026" / "pln-003-ok.md",
      "# Уже правильный план\n\n- Created: 2026-01-03\n"
      "- Updated: 2026-01-04\n- Status: new\n\nТекст.\n")
    w(root / "workflow" / "issue" / "2026" / "iss-004-ok.md",
      "# Уже правильное замечание\n\n- Created: 2026-01-03\n"
      "- Updated: 2026-01-04\n- Status: open\n- Kind: friction\n\n"
      "## Observation\n\nМешает.\n")
    w(root / "workflow" / "audit" / "2026" / "aud-001-tema" / "aud-001-readme.md",
      "# Аудит темы\n\n- Created: 2026-01-05\n\n## Выводы\n\nВсё.\n")
    w(root / "workflow" / "audit" / "2026" / "aud-001-tema" / "data.txt", "приложение\n")
    git_fixture(root)


class MigrateCase(unittest.TestCase):
    """Временный каталог на тест; фикстуры собираются в нём."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-migrate-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, builder, name="p"):
        root = self.tmp / name
        root.mkdir()
        builder(root)
        return root


# --- План и отказы -----------------------------------------------------------

class PlanTest(MigrateCase):
    """План без --apply: таблица, ничего не изменено, отказы при неготовности."""

    def test_plan_prints_table_and_changes_nothing(self):
        root = self.project(fixture_status_dirs)
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn("current/roadmap.md → plan/", out)
        self.assertIn(localized('Move to history/', "В history/"), out)
        self.assertIn(localized('No changes made', "ничего не изменено"), out)
        self.assertEqual(status_lines(root), [])
        self.assertTrue((root / "workflow" / "current" / "roadmap.md").is_file())
        self.assertFalse((root / "workflow" / "masterplan.md").exists()
                         and read(root / "workflow" / "masterplan.md").find(
                             localized("# Master plan", "# Мастер-план")) < 0)

    def test_ignored_documents_and_symlink_are_excluded_from_the_plan(self):
        from unittest.mock import patch
        from lipi.migrate import make_plan

        root = self.project(lambda path: support.init(path)).resolve()
        tracked = root / "workflow/current/plan.md"
        ignored_work = root / "workflow/current/local.md"
        ignored_page = root / "docs/private.md"
        escaped = root / "docs/escape.md"
        outside = self.tmp.resolve() / "outside.md"
        preserved = {
            ignored_work: "# Local work\n",
            ignored_page: "# Private\n\n[Plan](../workflow/current/plan.md)\n",
            outside: "# Outside\n\n[Plan](p/workflow/current/plan.md)\n",
        }
        support.w(tracked, "# Plan\n\n- Дата создания: 2026-01-01\n\n"
                  "[Private](../../docs/private.md) [Escape](../../docs/escape.md)\n")
        support.w(root / ".gitignore", "/docs/private.md\n/docs/escape.md\n/workflow/current/local.md\n")
        code, output = git_fixture(root)
        self.assertEqual(code, 0, output)
        for path, text in preserved.items():
            support.w(path, text)
        escaped.symlink_to(outside)
        read_text, readlink = Path.read_text, Path.readlink

        def guard_read(path, *args, **kwargs):
            self.assertNotIn(path, (*preserved, escaped))
            return read_text(path, *args, **kwargs)

        def guard_link(path):
            self.assertNotEqual(path, escaped)
            return readlink(path)

        with patch.object(Path, "read_text", guard_read), patch.object(Path, "readlink", guard_link):
            plan = make_plan(root, None, TODAY)
        self.assertEqual([doc["main"] for doc in plan["docs"]], [tracked])
        self.assertIn("[Private](../../docs/private.md) [Escape](../../docs/escape.md)",
                      plan["updates"][tracked])
        code, output = migrate(root, "--apply")
        self.assertEqual(code, 0, output)
        self.assertFalse(tracked.exists())
        self.assertTrue(escaped.is_symlink())
        for path, text in preserved.items():
            self.assertEqual(read(path), text)

    def test_document_folder_with_ignored_content_refuses_before_writing(self):
        root = self.project(lambda path: support.init(path))
        folder = root / "workflow/current/aud-001-topic"
        main = folder / "aud-001-readme.md"
        asset = folder / "private.txt"
        support.w(main, "# Audit\n\n- Дата создания: 2026-01-01\n")
        support.w(root / ".gitignore", "/workflow/current/aud-001-topic/private.txt\n")
        code, output = git_fixture(root)
        self.assertEqual(code, 0, output)
        support.w(asset, "Ignored attachment\n")
        code, output = migrate(root, "--apply")
        self.assertEqual(code, 2, output)
        self.assertIn("private.txt", output)
        self.assertTrue(main.is_file())
        self.assertEqual(read(asset), "Ignored attachment\n")
        self.assertEqual(status_lines(root), [])

    def test_printed_apply_command_with_disabled_workflow(self):
        for catalog in ("workflow", "materials", "work materials"):
            with self.subTest(catalog=catalog):
                root = self.project(lambda r: None, name=catalog)
                support.w(root / "lipi.json", '{"workflow": null}\n')
                source = root / catalog / "current" / "plan.md"
                support.w(source, "# План\n\n- Дата создания: 2026-01-01\n")
                git_fixture(root)

                code, out = support.cli(root, "migrate", "--apply")
                self.assertEqual(code, 2, out)
                self.assertIn(localized('disables workflow with null', "выключен (null)"), out)
                code, out = support.cli(root, "migrate", catalog)
                self.assertEqual(code, 0, out)
                command = out.split(localized("To apply the plan, run ", "Выполнить: "), 1)[1].strip()
                quoted_catalog = catalog
                if " " in catalog:
                    quote = '"' if os.name == "nt" else "'"
                    quoted_catalog = quote + catalog + quote
                self.assertEqual(command,
                                 "lipi migrate %s --apply" % quoted_catalog)
                self.assertEqual(status_lines(root), [])
                self.assertIsNone(json.loads(read(root / "lipi.json"))["workflow"])
                self.assertTrue(source.is_file())

                # Исполняем напечатанные аргументы через оболочку и CLI пакета.
                cli = support.PY + [str(support.CLI)]
                executable = (subprocess.list2cmdline(cli) if os.name == "nt"
                              else shlex.join(cli))
                result = subprocess.run(
                    executable + command[len("lipi"):], shell=True, cwd=root,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding="utf-8", errors="replace")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertFalse(source.exists())
                self.assertTrue((root / catalog / "plan" / "2026" / "pln-001-plan.md")
                                .is_file())
                self.assertEqual(json.loads(read(root / "lipi.json"))["workflow"],
                                 catalog)

    def test_not_git_refused(self):
        root = self.project(lambda r: support.init(r))
        support.w(root / "workflow" / "current" / "plan.md", "# План\n")
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('Git repository', "git-репозитори"), out)

    def test_dirty_tree_refused(self):
        root = self.project(fixture_status_dirs)
        support.w(root / "dirty.txt", "не закоммичено\n")
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 2, out)
        self.assertIn(localized('has changes', "не чисто"), out)
        self.assertTrue((root / "workflow" / "current" / "roadmap.md").is_file())
        self.assertEqual(read(root / "workflow" / "masterplan.md").count(
            localized("# Master plan", "# Мастер-план")), 1)

    def test_catalog_missing_refused(self):
        root = self.project(lambda r: support.init(r))
        shutil.rmtree(root / "workflow")
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('not found', "не найден"), out)

    def test_explicit_catalog_missing_refused(self):
        root = self.project(lambda r: support.init(r))
        code, out = migrate(root, "nope")
        self.assertEqual(code, 2, out)
        self.assertIn(localized('not found', "не найден"), out)


# --- Раскладка по каталогам статусов -----------------------------------------

class StatusDirsTest(MigrateCase):
    """Фикстура A: current/completed/backlog, журнал, отчёты, ссылки из docs/."""

    def apply(self):
        root = self.project(fixture_status_dirs)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        return root, out

    def test_apply_moves_and_fills_headers(self):
        root, out = self.apply()
        self.assertIn(localized('Documents moved: 5', "Перенесено документов: 5"), out)
        self.assertIn(" -> ", "\n".join(status_lines(root)))
        plan = root / "workflow" / "plan" / "2026"
        roadmap = next(plan.glob("pln-00*-roadmap.md"))
        text = read(roadmap)
        self.assertIn("- Status: in progress", text)
        self.assertIn("- Created: 2026-01-10", text)
        self.assertIn('## Purpose <a id="why"></a>\n\nРазвитие продукта.', text)
        self.assertNotIn("current/roadmap.md", text)
        done = next(plan.glob("pln-00*-plan-done.md"))
        self.assertIn("- Status: completed", read(done))
        self.assertIn(localized('- Result: Not recorded (migrated %s)', "- Result: не записан (перенесено %s)") % TODAY, read(done))
        later = next(plan.glob("pln-00*-later.md"))
        later_text = read(later)
        self.assertIn("- Status: deferred", later_text)
        self.assertIn("- Created: 2026-01-03", later_text)
        self.assertIn("- Updated: 2026-01-03", later_text)
        issue = root / "workflow" / "issue" / "2026" / "iss-003-bug.md"
        self.assertIn("- Kind: question", read(issue))
        self.assertIn("- Status: open", read(issue))
        self.assertIn("## Observation\n\nПроцесс падает.", read(issue))
        # прежние каталоги статусов убраны
        self.assertFalse((root / "workflow" / "current").exists())
        self.assertFalse((root / "workflow" / "completed").exists())
        self.assertFalse((root / "workflow" / "backlog").exists())
        self.assertFalse((root / "workflow" / "reports").exists())

    def test_journal_masterplan_and_migration_table(self):
        root, out = self.apply()
        history = root / "workflow" / "history"
        self.assertTrue((history / "ЖУРНАЛ.md").is_file())
        self.assertTrue((history / "masterplan.md").is_file())
        self.assertTrue((history / "reports" / "2026-01.md").is_file())
        # новый пустой мастер-план по шаблону
        self.assertTrue(read(root / "workflow" / "masterplan.md")
                        .startswith(localized("# Master plan", "# Мастер-план")))
        # README сохранён, ссылка на мастер-план не уехала в history
        self.assertIn("](masterplan.md)",
                      read(root / "workflow" / "README.md"))
        table = read(history / "MIGRATION.md")
        self.assertIn("`current/roadmap.md`", table)
        self.assertIn("pln-004-roadmap.md", table)
        self.assertIn("`ЖУРНАЛ.md`", table)
        self.assertIn(localized("| Old path | New path | ID |",
                                "| Старый путь | Новый путь | ID |"), table)

    def test_links_rewritten_everywhere(self):
        root, out = self.apply()
        self.assertIn(localized('Links rewritten:', "Ссылок переписано:"), out)
        docs = read(root / "docs" / "README.md")
        self.assertIn("../workflow/plan/", docs)
        self.assertIn("roadmap.md", docs)
        self.assertNotIn("current/roadmap", docs)
        self.assertIn("#why", docs)
        root_md = read(root / "README.md")
        self.assertIn("workflow/plan/", root_md)
        self.assertIn("[внешний](https://example.com/a)", root_md)
        report = read(root / "workflow" / "history" / "reports" / "2026-01.md")
        self.assertIn("../../plan/", report)
        self.assertIn("roadmap.md", report)

    def test_check_clean_with_baseline(self):
        root, _ = self.apply()
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 0, out)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('in the baseline', "в базовой линии"), out)

    def test_check_without_baseline_only_outside_w1_w7(self):
        root, _ = self.apply()
        code, out = support.check(root, "--no-baseline")
        self.assertEqual(code, 1, out)
        for code_name in W_CODES:
            self.assertFalse(support.found(out, code_name), out)
        self.assertFalse(support.found(out, "D1"), out)
        # содержимое старых документов чекер не исправляет: W8 и D5 остаются
        self.assertTrue(support.found(out, "W8"), out)

    def test_unrecognized_status_reported(self):
        root = self.project(lambda r: support.init(r))
        w = support.w
        w(root / "workflow" / "current" / "a.md", "# A\n\n- Статус: in review\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('unrecognized status', "не распознан"), out)
        self.assertIn(localized('Used new', "поставлен «new»"), out)
        self.assertIn("- Status: new", read(next(
            (root / "workflow" / "plan" / "2026").glob("pln-001-a.md"))))

    def test_already_correct_status_is_kept(self):
        root = self.project(lambda r: support.init(r))
        support.w(root / "workflow" / "current" / "a.md",
                  "# A\n\n- Статус: отменён\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("- Status: canceled", read(
            next((root / "workflow" / "plan" / "2026").glob("pln-001-a.md"))))


class YearDatesTest(MigrateCase):
    def test_migration_closure_limit_is_independent_of_local_migration_date(self):
        from lipi.migrate import MigrateError, build_plan

        root = self.project(lambda r: None)
        wf = root / "workflow"
        path = wf / "completed" / "pln-009-plan.md"
        for field in ("Дата закрытия", "Дата обновления"):
            for closed in ("2026-11-19", "2026-11-20"):
                with self.subTest(field=field, closed=closed):
                    support.w(path, "# План\n\n- Дата создания: 2024-01-01\n"
                              "- %s: %s\n- Статус: Done\n" % (field, closed))
                    with support.freeze_workflow_clock("2026-11-18T21:30:00+00:00") as clock:
                        if closed == "2026-11-19":
                            plan = build_plan(root, wf, root, {}, "2026-11-18")
                            self.assertEqual(plan["docs"][0]["closed"], closed)
                            self.assertEqual(plan["today"], "2026-11-18")
                        else:
                            with self.assertRaisesRegex(MigrateError, "W3"):
                                build_plan(root, wf, root, {}, "2026-11-18")
                    clock.now.assert_called_once_with(datetime.timezone.utc)

    def test_created_header_selects_year_before_git_date(self):
        root = self.project(lambda r: support.init(r))
        source = root / "workflow" / "current" / "pln-009-old.md"
        support.w(source, "# Старый план\n\n- Дата создания: 2024-12-31\n"
                         "- Дата обновления: 2026-02-01\n- Статус: новый\n")
        git_fixture(root)
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn("plan/2024/pln-009-old.md", out)
        self.assertIn(localized('Created = 2024-12-31 (header); year 2024', "Created = 2024-12-31 (шапка); год 2024"), out)
        self.assertEqual(status_lines(root), [])

    def test_existing_closed_date_is_preserved(self):
        root = self.project(lambda r: support.init(r))
        source = root / "workflow" / "completed" / "pln-009-old.md"
        support.w(source, "# План\n\n- Дата создания: 2024-01-01\n"
                         "- Дата обновления: 2026-01-01\n- Статус: завершён\n"
                         "- Итог: готово\n- Дата закрытия: 2025-02-03\n")
        git_fixture(root)
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Closed = 2025-02-03 (header (kept))', "Closed = 2025-02-03 (шапка (сохранена))"), out)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("- Closed: 2025-02-03", read(
            root / "workflow" / "plan" / "2024" / "pln-009-old.md"))

    def test_closed_date_uses_transition_and_survives_late_edits(self):
        root = self.project(lambda r: support.init(r))
        source = root / "workflow" / "current" / "pln-009-old.md"
        support.w(source, "# План\n\n- Дата создания: 2024-01-01\n"
                         "- Дата обновления: 2024-01-01\n- Статус: новый\n")
        git_fixture(root, "2024-01-01T10:00:00")
        support.sub(source, "- Статус: новый", "- Статус: завершён")
        support.commit(root, "закрытие", "2025-02-03T10:00:00")
        support.sub(source, "- Дата обновления: 2024-01-01",
                    "- Дата обновления: 2026-01-01")
        support.commit(root, "поздняя правка", "2026-01-01T10:00:00")
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn("Closed = 2025-02-03 (Git ", out)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        target = root / "workflow" / "plan" / "2024" / source.name
        self.assertIn("- Closed: 2025-02-03", read(target))
        support.commit(root, "перенос", "2026-02-01T10:00:00")
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Closed = 2025-02-03 (header (kept))', "Closed = 2025-02-03 (шапка (сохранена))"), out)

    def test_imported_status_uses_updated_without_guessing_git_closure(self):
        root = self.project(lambda r: support.init(r))
        source = root / "workflow" / "completed" / "plan.md"
        support.w(source, "# План\n\n- Дата создания: 2024-01-01\n"
                         "- Дата обновления: 2025-02-03\n- Статус: Done\n")
        git_fixture(root, "2026-01-01T10:00:00")
        code, out = migrate(root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized("Closed = 2025-02-03 (Updated date (source material lacked a standard header))",
                                "Closed = 2025-02-03 (Дата обновления (неоформленный исходный материал))"),
                      out)
        self.assertEqual(status_lines(root), [])

    def test_created_date_falls_back_to_migration_date_without_history(self):
        from unittest.mock import patch
        from lipi.migrate import build_plan
        root = self.project(lambda r: None)
        wf = root / "workflow"
        support.w(wf / "current" / "pln-001-plan.md", "# План\n")
        with patch("lipi.migrate.commit_dates", return_value=(None, None)):
            plan = build_plan(root, wf, root, {}, "2025-12-31")
        doc = plan["docs"][0]
        self.assertEqual(doc["created"], "2025-12-31")
        self.assertEqual(doc["created_origin"], localized('migration date', "дата переноса"))
        self.assertEqual(doc["new_main"], wf / "plan" / "2025" / "pln-001-plan.md")

    def test_invalid_closed_date_refuses_without_changes(self):
        for closed in ("2025-02-30", "2023-12-31", "9999-01-01"):
            with self.subTest(closed=closed):
                root = self.project(lambda r: support.init(r), name=closed)
                support.w(root / "workflow" / "completed" / "plan.md",
                          "# План\n\n- Дата создания: 2024-01-01\n"
                          "- Статус: завершён\n- Дата закрытия: %s\n" % closed)
                git_fixture(root)
                code, out = migrate(root, "--apply")
                self.assertEqual(code, 2, out)
                self.assertIn("W3", out)
                self.assertEqual(status_lines(root), [])


# --- Нумерация, даты, статусы по словам --------------------------------------

class NumbersTest(MigrateCase):
    """Фикстура B: номер сохраняется, ветка 011-1 получает следующий свободный."""

    def apply(self):
        root = self.project(fixture_numbers)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        return root, out

    def test_numbers_preserved_and_branch_next_free(self):
        root, out = self.apply()
        plan = root / "workflow" / "plan" / "2026"
        self.assertTrue((plan / "pln-011-plan-roadmap.md").is_file())
        self.assertTrue((plan / "pln-013-refactor.md").is_file())
        self.assertFalse((plan / "pln-011-refactor.md").exists())
        # номера уникальны: W2 чист
        code, check_out = support.check(root, "--no-baseline")
        self.assertEqual(code, 0, check_out)
        self.assertFalse(support.found(check_out, "W2"), check_out)

    def test_dates_from_git_commits(self):
        root, out = self.apply()
        plan = read(root / "workflow" / "plan" / "2026" / "pln-011-plan-roadmap.md")
        self.assertIn("- Created: 2026-01-01", plan)
        self.assertIn("- Updated: 2026-02-02", plan)
        self.assertIn(localized("taken from the file's commits", "из коммитов файла"), out)

    def test_status_words_and_types(self):
        root, out = self.apply()
        ol = root / "workflow"
        self.assertIn("- Status: completed", read(next(ol.glob("plan/2026/*-plan-old.md"))))
        self.assertIn(localized('- Result: Not recorded', "- Result: не записан"), read(next(ol.glob("plan/2026/*-plan-old.md"))))
        self.assertIn("- Status: accepted", read(next(ol.glob("adr/*-decision.md"))))
        wish = next(ol.glob("issue/2026/*-wish.md"))
        self.assertIn("- Status: open", read(wish))
        self.assertIn("- Kind: request", read(wish))
        # in review — не распознан: «новый» с пометкой
        weird = read(next(ol.glob("plan/2026/*-weird.md")))
        self.assertIn("- Status: new", weird)


class NumberConflictTest(MigrateCase):
    """Конфликт сохранённого номера: один номер занят — второй получает следующий."""

    def test_conflict_gets_next_free(self):
        root = self.project(lambda r: support.init(r))
        w = support.w
        w(root / "workflow" / "current" / "pln-005-a.md",
          "# A\n\n- Дата создания: 2026-01-01\n")
        w(root / "workflow" / "completed" / "pln-005-b.md",
          "# B\n\n- Дата создания: 2026-01-01\n- Статус: done\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('number 005 already in use. Assigned 006', "номер 005 занят — назначен 006"), out)
        plan = root / "workflow" / "plan" / "2026"
        self.assertTrue((plan / "pln-005-b.md").is_file())
        self.assertTrue((plan / "pln-006-a.md").is_file())
        code, check_out = support.check(root, "--no-baseline")
        self.assertEqual(code, 0, check_out)
        self.assertFalse(support.found(check_out, "W2"), check_out)


# --- migrate.json ------------------------------------------------------------

class OverridesTest(MigrateCase):
    """migrate.json: тип, статус и номер отдельных документов; ошибки — отказ."""

    def project_with(self, overrides, notes="# Заметки\n\n- Дата создания: 2026-01-01\n"):
        root = self.project(lambda r: support.init(r))
        w = support.w
        w(root / "workflow" / "reports" / "notes.md", notes)
        w(root / "workflow" / "current" / "plain.md",
          "# Обычный\n\n- Дата создания: 2026-01-01\n")
        (root / "workflow" / "migrate.json").write_text(
            json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
        git_fixture(root)
        return root

    def test_override_type_status_number(self):
        root = self.project_with({"files": {"reports/notes.md": {
            "type": "iss", "status": "в работе", "number": 7}}})
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        target = root / "workflow" / "issue" / "2026" / "iss-007-notes.md"
        self.assertTrue(target.is_file(), out)
        text = read(target)
        self.assertIn("- Status: in progress", text)
        # переопределение спасло документ из history/
        self.assertFalse((root / "workflow" / "history" / "reports"
                          / "notes.md").exists())

    def test_unknown_top_key_refused(self):
        root = self.project_with({"file": {}})
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('unknown key file', "неизвестный ключ «file»"), out)

    def test_unknown_type_refused(self):
        root = self.project_with({"files": {"reports/notes.md": {"type": "plan"}}})
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('unknown type plan', "неизвестный тип «plan»"), out)

    def test_unknown_status_refused(self):
        root = self.project_with({"files": {"reports/notes.md": {
            "type": "pln", "status": "завершено"}}})
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('is invalid for', "не из списка"), out)
        self.assertIn("completed", out)

    def test_unknown_field_refused(self):
        root = self.project_with({"files": {"reports/notes.md": {"kind": "баг"}}})
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('unknown key kind', "неизвестный ключ «kind»"), out)

    def test_missing_file_refused(self):
        root = self.project_with({"files": {"reports/nope.md": {"type": "pln"}}})
        code, out = migrate(root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('no such file or directory in the workflow directory', "нет в каталоге"), out)


# --- Шапка: регистр, «Дата:», отсутствие шапки --------------------------------

class HeaderFormsTest(MigrateCase):
    """Даты и статус из шапки в разном написании; шапки нет — даты из коммитов."""

    def apply(self):
        root = self.project(lambda r: support.init(r))
        w = support.w
        w(root / "workflow" / "current" / "h1case.md",
          "# В разном регистре\n\n- ДАТА СОЗДАНИЯ: 2026-01-01\n"
          "- дата обновления: 2026-01-02\n- СТАТУС: В работе\n\n"
          "## Зачем\n\nНужно.\n\n## Критерии завершения\n\nГотово.\n")
        w(root / "workflow" / "current" / "noheader.md",
          "Текст без шапки и заголовка.\n")
        w(root / "workflow" / "current" / "date-only.md",
          "# Только дата\n\n- Дата: 2026-01-07\n\nТекст.\n")
        w(root / "workflow" / "current" / "back-dates.md",
          "# Обратные даты\n\n- Дата создания: 2026-02-01\n"
          "- Дата обновления: 2026-01-01\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        return root, out

    def test_header_in_any_case(self):
        root, _ = self.apply()
        text = read(next((root / "workflow" / "plan" / "2026").glob("*-h1case.md")))
        self.assertIn("- Created: 2026-01-01", text)
        self.assertIn("- Updated: 2026-01-02", text)
        self.assertIn("- Status: in progress", text)

    def test_header_absent_dates_from_commit(self):
        root, out = self.apply()
        text = read(next((root / "workflow" / "plan" / "2026").glob("*-noheader.md")))
        self.assertIn("- Created: 2026-03-01", text)
        self.assertIn("- Updated: 2026-03-01", text)
        self.assertIn("# noheader", text)
        self.assertIn(localized("taken from the file's commits", "из коммитов файла"), out)

    def test_single_date_used_for_both(self):
        root, _ = self.apply()
        text = read(next((root / "workflow" / "plan" / "2026").glob("*-date-only.md")))
        self.assertIn("- Created: 2026-01-07", text)
        self.assertIn("- Updated: 2026-01-07", text)

    def test_update_before_created_is_leveled(self):
        root, out = self.apply()
        text = read(next((root / "workflow" / "plan" / "2026").glob("*-back-dates.md")))
        self.assertIn("- Created: 2026-02-01", text)
        self.assertIn("- Updated: 2026-02-01", text)
        self.assertIn(localized('was adjusted', "выровнена"), out)

    def test_nested_journal_name_is_normal_document(self):
        root = self.project(lambda r: support.init(r))
        support.w(root / "workflow" / "current" / "journal.md",
                  "# Не журнал\n\n- Дата создания: 2026-01-01\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(next((root / "workflow" / "plan" / "2026").glob("*-journal.md"))
                        .is_file())
        self.assertFalse((root / "workflow" / "history" / "current"
                          / "journal.md").exists())


# --- Каталоги документов, сохранение уже правильного -------------------------

class LayoutTest(MigrateCase):
    """Документ-папка, уже правильная раскладка, создание README."""

    def test_correct_layout_untouched_and_readme_created(self):
        root = self.project(fixture_correct_layout)
        good = read(root / "workflow" / "plan" / "2026" / "pln-003-ok.md")
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Already in place', "Уже на месте"), out)
        # документы на месте, папка-документ не переименована
        self.assertTrue((root / "workflow" / "plan" / "2026" / "pln-003-ok.md").is_file())
        self.assertTrue((root / "workflow" / "audit" / "2026" / "aud-001-tema"
                         / "aud-001-readme.md").is_file())
        self.assertTrue((root / "workflow" / "audit" / "2026" / "aud-001-tema"
                         / "data.txt").is_file())
        self.assertEqual(read(root / "workflow" / "plan" / "2026" / "pln-003-ok.md"), good)
        self.assertIn("- Kind: friction", read(root / "workflow" / "issue" / "2026"
                                          / "iss-004-ok.md"))
        # README из шаблона создан: на него ссылаются правила исполнителя
        self.assertTrue((root / "workflow" / "README.md").is_file())
        code, check_out = support.check(root, "--no-baseline")
        self.assertEqual(code, 0, check_out)

    def test_document_folder_from_status_dir_moves_whole(self):
        root = self.project(lambda r: support.init(r))
        w = support.w
        w(root / "workflow" / "current" / "aud-001-tema" / "aud-001-readme.md",
          "# Аудит\n\n- Дата создания: 2026-01-01\n\n## Выводы\n\nВсё.\n")
        w(root / "workflow" / "current" / "aud-001-tema" / "data.txt", "файл\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue((root / "workflow" / "audit" / "2026" / "aud-001-tema"
                         / "aud-001-readme.md").is_file())
        self.assertTrue((root / "workflow" / "audit" / "2026" / "aud-001-tema"
                         / "data.txt").is_file())
        self.assertFalse((root / "workflow" / "current").exists())

    def test_existing_result_is_kept(self):
        """Итог, уже записанный в шапке, не заменяется заглушкой."""
        root = self.project(lambda r: support.init(r))
        support.w(root / "workflow" / "completed" / "plan-done.md",
                  "# Сделанный\n\n- Дата создания: 2026-01-01\n- Статус: done\n"
                  "- Итог: сделано давно\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        text = read(next((root / "workflow" / "plan" / "2026").glob("*-plan-done.md")))
        self.assertIn("- Result: сделано давно", text)
        self.assertNotIn(localized('Not recorded', "не записан"), text)

    def test_plain_subdirectory_is_not_document_folder(self):
        root = self.project(lambda r: support.init(r))
        support.w(root / "workflow" / "current" / "sub" / "deep.md",
                  "# Вложенный\n\n- Дата создания: 2026-01-01\n")
        support.w(root / "workflow" / "current" / "sub" / "attach.txt", "x\n")
        git_fixture(root)
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue((root / "workflow" / "plan" / "2026" / "pln-001-deep.md").is_file())
        self.assertTrue((root / "workflow" / "history" / "current" / "sub"
                         / "attach.txt").is_file())
        self.assertFalse((root / "workflow" / "current").exists())

    def test_links_of_stationary_document_untouched(self):
        root = self.project(fixture_correct_layout)
        target = root / "workflow" / "plan" / "2026" / "pln-003-ok.md"
        text = read(target)
        text += ("\n[внешний](https://example.com/a) [якорь](#x) "
                 "[сосед](pln-002-other.md)\n")
        target.write_text(text, encoding="utf-8")
        support.commit(root, "ссылки", "2026-01-06T10:00:00")
        code, out = migrate(root, "--apply")
        self.assertEqual(code, 0, out)
        new = read(target)
        self.assertIn("[внешний](https://example.com/a)", new)
        self.assertIn("[якорь](#x)", new)
        self.assertIn("[сосед](pln-002-other.md)", new)


# --- Каталог и настройки -----------------------------------------------------

class CatalogConfigTest(MigrateCase):
    """Каталог из lipi.json или явный; lipi.json обновляется только при отличии."""

    def test_explicit_catalog_without_config_creates_it(self):
        root = self.project(lambda r: None)
        support.w(root / "materials" / "current" / "p.md",
                  "# План\n\n- Дата создания: 2026-01-01\n")
        support.git_init(root)
        support.commit(root)
        code, out = migrate(root, "materials", "--apply")
        self.assertEqual(code, 0, out)
        cfg = json.loads(read(root / "lipi.json"))
        self.assertEqual(cfg["workflow"], "materials")
        self.assertTrue((root / "materials" / "plan" / "2026" / "pln-001-p.md").is_file())

    def test_same_catalog_keeps_config(self):
        root = self.project(fixture_correct_layout)
        path = root / "lipi.json"
        before = path.read_bytes()
        code, out = migrate(root, "workflow", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('workflow stayed the same', "workflow не менялся"), out)
        self.assertEqual(path.read_bytes(), before)

    def test_catalog_from_other_cwd_finds_project_root(self):
        """Явный каталог: корень проекта находится по lipi.json, а не по cwd."""
        root = self.project(fixture_status_dirs)
        code, out = support.run(
            support.PY + [str(MIGRATE), str(root / "workflow"), "--apply"],
            cwd=str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertTrue(next((root / "workflow" / "plan" / "2026").glob("*-roadmap.md"))
                        .is_file())
        self.assertEqual(json.loads(read(root / "lipi.json"))["workflow"],
                         "workflow")

    def test_different_catalog_updates_config(self):
        root = self.project(lambda r: None)
        support.w(root / "lipi.json", '{"docs": "docs", "workflow": "workflow"}\n')
        support.w(root / "materials" / "current" / "p.md",
                  "# План\n\n- Дата создания: 2026-01-01\n")
        support.git_init(root)
        support.commit(root)
        code, out = migrate(root, "materials", "--apply")
        self.assertEqual(code, 0, out)
        cfg = json.loads(read(root / "lipi.json"))
        self.assertEqual(cfg["workflow"], "materials")
        self.assertEqual(cfg["docs"], "docs")


# --- Три фикстуры переноса --------------------------------------------

class ExistingProjectsTest(MigrateCase):
    """Три раскладки существующих проектов: перенос, линия, чистая проверка."""

    FIXTURES = (("статусы", fixture_status_dirs),
                ("нумерация", fixture_numbers),
                ("уже по правилам", fixture_correct_layout))

    def test_three_layouts(self):
        for name, builder in self.FIXTURES:
            with self.subTest(layout=name):
                root = self.project(builder, name="p-" + name.replace(" ", "-"))
                code, out = migrate(root, "--apply")
                self.assertEqual(code, 0, "%s: %s" % (name, out))
                code, out = support.check(root, "baseline")
                self.assertEqual(code, 0, "%s: %s" % (name, out))
                code, out = support.check(root)
                self.assertEqual(code, 0, "%s: %s" % (name, out))
                code, out = support.check(root, "--no-baseline")
                for code_name in W_CODES:
                    self.assertFalse(support.found(out, code_name),
                                     "%s: %s\n%s" % (name, code_name, out))
                self.assertFalse(support.found(out, "D1"),
                                 "%s: %s" % (name, out))


class CliTest(MigrateCase):
    """`lipi migrate` доступна из команды lipi; справка её называет."""

    def test_cli_migrate_apply(self):
        root = self.project(fixture_correct_layout)
        code, out = support.cli(root, "migrate", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Migration completed', "перенос выполнен"), out)

    def test_help_mentions_migrate(self):
        code, out = support.cli(self.tmp, "help")
        self.assertEqual(code, 0, out)
        self.assertIn("migrate", out)


if __name__ == "__main__":
    unittest.main()
