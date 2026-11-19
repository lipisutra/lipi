"""test_app_mode.py — режим приложения: механика целиком на копиях фикстуры.

Режим приложения — это справка для пользователя в `docs/`, описание системы
для разработчика в `docs/development/` и связь между ними через `covers`.

Каждый тест работает на временной копии `tests/fixtures/app`. Копия с
историей — git-репозиторий с коммитами по датам через `tests.support`:

1. `init --type app` в пустой папке создаёт справку, описание системы и
   раздел про справку в правилах описания; `lipi check` и `--audit` — 0/0.
2. Справка связана с разделом системы `covers` полной формы
   (`docs/development/…md#якорь`), D6 чист; битый якорь D6 ловит.
3. Изменён раздел описания системы: T2 (`--staged`) напоминает только
   страницам справки, которые его указывают; после правки справки молчит.
4. `--audit`: A4 — код под меткой менялся позже раздела, который объясняет
   справка; раздел новее кода — A4 молчит.
5. `--staged --structure`: цепочка `stale` содержит страницу справки
   (`covers`) и открытую работу (`works`); без изменений цепочки нет.
6. Граф: узлы страниц справки и описания системы, ребро `covers` ведёт к
   узлу якоря. Эталон `tests/fixtures/app.structure.json` только читается.

Запуск: python3 -m unittest tests.test_app_mode -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.support import localized

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
GOLDEN = FIXTURES / "app.structure.json"
DATE = "2026-11-01T10:00:00"
LATER = "2026-11-10T10:00:00"


def run_check(root, *args):
    """Чекер репозитория по копии фикстуры: в фикстуре нет .agents/lipi/check.py."""
    return support.run(support.PY + [str(support.CHECK)] + list(args), cwd=str(root))


def check_json(root, *args):
    """run_check с --format json: (код возврата, объект или None)."""
    if "--format" not in args:
        args = ("--format", "json") + args
    code, out = run_check(root, *args)
    try:
        return code, json.loads(out)
    except ValueError:
        raise AssertionError("чекер вернул не JSON:\n" + out)


def warnings(data, code):
    return [item for item in data["warnings"] if item["code"] == code]


class AppCopy(unittest.TestCase):
    """Копия фикстуры приложения во временном каталоге."""

    def copy(self):
        tmp = Path(tempfile.mkdtemp(prefix="lipi-app-mode-"))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        root = tmp / "app"
        shutil.copytree(str(FIXTURES / "app"), str(root))
        return root

    def repo(self, date=DATE):
        """Копия фикстуры — git-репозиторий с одним коммитом по дате."""
        root = self.copy()
        support.git_init(root)
        support.commit(root, "init", date=date)
        return root

    def with_second_help(self, root):
        """Второй раздел описания системы и вторая страница справки к нему.

        Нужна, чтобы T2 проверялся с двух сторон: справка, указывающая
        изменённый раздел, и справка, указывающая соседний.
        """
        support.sub(root / "docs" / "development" / "rules.md",
                    "Скидки не суммируются.",
                    "Скидки не суммируются.\n\n"
                    "## Порядок <a id=\"order\"></a>\n\n"
                    "Сначала применяется большая скидка.")
        support.w(root / "docs" / "order.md",
                  "# Порядок\n\n<!-- covers: docs/development/rules.md#order -->\n\n"
                  "Сначала применяется большая скидка.\n")
        support.sub(root / "docs" / "README.md", "- [Скидки](discount.md)",
                    "- [Скидки](discount.md)\n- [Порядок](order.md)")


class InitAppCase(support.Case):
    """init --type app: заготовки справки и описания системы, чистая проверка."""

    base_args = ("--type", "app")
    seed_project = False

    def test_init_app_creates_help_and_system_description(self):
        """Пустая папка: справка, описание системы, раздел про справку, check 0/0."""
        root = self.project()
        help_text = (root / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn(localized('# User help', "# Справка"), help_text)
        self.assertIn("development/README.md", help_text)
        system_text = (root / "docs" / "development" / "README.md").read_text(encoding="utf-8")
        self.assertIn(localized('# System documentation', "# Описание системы"), system_text)
        for anchor in ("processes", "rules", "design"):
            self.assertIn('<a id="%s"></a>' % anchor, system_text)
        config = json.loads((root / "lipi.json").read_text(encoding="utf-8"))
        self.assertEqual(config["description"], "docs/development")
        # раздел про справку приходит из шаблона lipi, а не из заготовки
        rules = (root / ".agents" / "lipi" / "documentation.md").read_text(encoding="utf-8")
        self.assertIn('<a id="help"></a>', rules)
        self.assertIn("User help and system documentation", rules)
        self.assertIn("covers", rules)
        for args in ((), ("--audit",)):
            code, out = support.check(root, *args)
            self.assertEqual(code, 0, out)
            self.assertIn(localized('errors: 0, warnings: 0', "ошибок: 0, предупреждений: 0"), out)

    def test_init_app_help_covers_system_section(self):
        """Справка со ссылкой на раздел системы полной формы: D6 не срабатывает."""
        root = self.project()
        support.w(root / "docs" / "processes.md",
                  "# Процессы\n\n<!-- covers: docs/development/README.md#processes -->\n\n"
                  "Как идёт процесс.\n")
        support.sub(root / "docs" / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Процессы | [Процессы](processes.md) |")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D6"), out)

    def test_init_app_broken_covers_anchor(self):
        """Якорь справки на несуществующий раздел системы: ошибка D6."""
        root = self.project()
        support.w(root / "docs" / "processes.md",
                  "# Процессы\n\n<!-- covers: docs/development/README.md#no-such -->\n\n"
                  "Как идёт процесс.\n")
        support.sub(root / "docs" / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Процессы | [Процессы](processes.md) |")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)


class CoversCase(AppCopy):
    """covers полной формы в фикстуре: D6 чист, битая цель — ошибка."""

    def test_fixture_covers_full_form_is_clean(self):
        """В фикстуре справка указывает раздел системы полной формой, D6 чист."""
        root = self.copy()
        text = (root / "docs" / "discount.md").read_text(encoding="utf-8")
        self.assertIn("<!-- covers: docs/development/rules.md#max-discount -->", text)
        code, out = run_check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D6"), out)

    def test_fixture_broken_covers_is_d6(self):
        """covers ведёт на несуществующий якорь: ошибка D6."""
        root = self.copy()
        support.sub(root / "docs" / "discount.md",
                    "docs/development/rules.md#max-discount", "docs/development/rules.md#no-such")
        code, out = run_check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)


class DriftCase(AppCopy):
    """T2: изменён раздел описания системы — напоминание страницам справки."""

    def test_t2_warns_only_covering_help_page(self):
        """Указывающая справка предупреждена, соседняя — нет."""
        root = self.copy()
        self.with_second_help(root)
        support.git_init(root)
        support.commit(root, "init", date=DATE)
        support.sub(root / "docs" / "development" / "rules.md",
                    "Скидки не суммируются.",
                    "Скидки не суммируются: берётся наибольшая.")
        support.git(root, "add", "docs/development/rules.md")
        code, out = run_check(root, "--staged")
        self.assertEqual(code, 0, out)
        lines = [line for line in out.split("\n") if support.found(line, "T2")]
        self.assertTrue(any("docs/discount.md" in line for line in lines), out)
        self.assertFalse(any("docs/order.md" in line for line in lines), out)
        self.assertIn("docs/development/rules.md#max-discount", out)

    def test_t2_silent_after_help_page_updated(self):
        """Справка обновлена вместе с разделом: T2 молчит."""
        root = self.copy()
        self.with_second_help(root)
        support.git_init(root)
        support.commit(root, "init", date=DATE)
        support.sub(root / "docs" / "development" / "rules.md",
                    "Скидки не суммируются.",
                    "Скидки не суммируются: берётся наибольшая.")
        support.sub(root / "docs" / "discount.md",
                    "Вы получаете самую большую из доступных скидок.",
                    "Вы получаете самую большую из доступных скидок; "
                    "остальные не складываются.")
        support.git(root, "add", "-A")
        code, out = run_check(root, "--staged")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T2"), out)


class AuditCase(AppCopy):
    """A4: раздел, который объясняет справка, старше кода под меткой."""

    def test_a4_code_newer_than_covered_section(self):
        """Код изменён позже раздела: A4 с разделом и файлом кода."""
        root = self.repo()
        support.sub(root / "src" / "app.py", "default=0", "default=1")
        support.commit(root, "code", date=LATER)
        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0)
        found = warnings(data, "A4")
        self.assertTrue(found, data["warnings"])
        self.assertEqual(found[0]["file"], "docs/development/rules.md")
        self.assertEqual(found[0]["subject"], "docs/development/rules.md#max-discount")
        self.assertIn("src/app.py", found[0]["message"])

    def test_a4_silent_when_section_newer(self):
        """Раздел обновлён позже кода: A4 молчит."""
        root = self.repo()
        support.sub(root / "docs" / "development" / "rules.md",
                    "Скидки не суммируются.",
                    "Скидки не суммируются: берётся наибольшая.")
        support.commit(root, "description", date=LATER)
        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0)
        self.assertEqual(warnings(data, "A4"), [])


class StaleCase(AppCopy):
    """Цепочка устаревания: код под меткой, справка через covers и работа."""

    def test_stale_chain_has_help_covers_and_work(self):
        """Изменённый код: в stale страница справки через covers и работа PLN-001."""
        root = self.repo()
        support.sub(root / "src" / "app.py", "default=0", "default=1")
        support.git(root, "add", "src/app.py")
        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0)
        stale = [item for item in data["structure"]["stale"]
                 if item["anchor"] == "docs/development/rules.md#max-discount"]
        self.assertTrue(stale, data["structure"]["stale"])
        chain = stale[0]
        self.assertEqual(chain["file"], "src/app.py")
        self.assertEqual(chain["page"], "docs/development/rules.md")
        self.assertEqual(chain["covers"], ["docs/discount.md"])
        works = {item["id"]: item.get("status") for item in chain["works"]}
        self.assertEqual(works.get("PLN-001"), "in progress")

    def test_no_stale_without_changes(self):
        """Без проиндексированных изменений цепочки нет."""
        root = self.repo()
        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0)
        self.assertEqual(data["structure"]["stale"], [])


class GraphCase(AppCopy):
    """Граф структуры приложения: справка, описание системы и ребро covers."""

    def test_graph_help_and_description_nodes_covers_to_anchor(self):
        """Узлы справки и описания системы есть, covers ведёт к узлу якоря."""
        root = self.copy()
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        structure = data["structure"]
        nodes = {item["id"]: item for item in structure["nodes"]}
        for rel in ("docs/README.md", "docs/development/README.md",
                    "docs/development/rules.md", "docs/discount.md"):
            self.assertEqual(nodes.get(rel, {}).get("type"), "doc", rel)
        self.assertEqual(nodes.get("docs/development/rules.md#max-discount", {}).get("type"),
                         "anchor")
        covers = [edge for edge in structure["edges"] if edge["type"] == "covers"]
        self.assertEqual(len(covers), 1, structure["edges"])
        self.assertEqual(covers[0]["from"], "docs/discount.md")
        self.assertEqual(covers[0]["to"], "docs/development/rules.md#max-discount")
        self.assertIn(covers[0]["to"], nodes)
        # эталон фиксирует то же ребро covers -> якорь от корня проекта
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertTrue(any(edge["type"] == "covers"
                            and edge["from"] == covers[0]["from"]
                            and edge["to"] == covers[0]["to"]
                            for edge in golden["edges"]), golden["edges"])


if __name__ == "__main__":
    unittest.main()
