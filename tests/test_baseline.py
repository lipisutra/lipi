"""test_baseline.py — базовая линия (ADR-003).

Проверяет: команды `baseline` и `baseline --prune`, вывод и коды возврата
`check` с линией и с `--no-baseline`, устойчивость линии к сдвигу строк и
изменению размера страницы (D3), поле `subject` у находок, A6 в аудите и
создание линии при `lipi init` без ослабления настроек.

Запуск: python3 -m unittest discover -s tests -p "test_baseline.py" -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

BASE_NAME = support.BASE_REL


def baseline_path(root):
    return root / support.BASE_REL


def entries(root):
    return json.loads(baseline_path(root).read_text(encoding="utf-8"))["entries"]


def add_link(root, target="nope.md", tag="a"):
    """Добавляет в guide.md ссылку на target: ошибка D1 с subject = target."""
    support.sub(root / "docs" / "guide.md", "Текст.",
                "Текст. [%s](%s)" % (tag, target))


def add_long_page(root, lines=400):
    """Страница описания сверх предела строк (D3), достижимая из указателя."""
    support.w(root / "docs" / "other.md",
              "# Другое\n\n## Раздел <a id=\"other\"></a>\n\n" + "строка\n" * lines)
    support.sub(root / "docs" / "README.md",
                "| Скидки | [Скидки](guide.md#max-discount) |",
                "| Скидки | [Скидки](guide.md#max-discount) |\n"
                "| Другое | [Другое](other.md) |")


def error_with(data, code):
    return next(e for e in data["errors"] if e["code"] == code)


class TestBaselineCommands(support.Case):
    """baseline создаёт, перезаписывает и сортирует линию; предупреждения не в линии."""

    def test_baseline_creates_sorted_file(self):
        """baseline записывает ошибки по (code, file, subject) с числом повторов."""
        root = self.project()
        add_link(root, "nope.md")
        add_long_page(root)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('baseline written', "базовая линия записана"), out)
        data = json.loads(baseline_path(root).read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["entries"], [
            {"code": "D1", "file": "docs/guide.md", "subject": "nope.md", "count": 1},
            {"code": "D3", "file": "docs/other.md", "subject": "", "count": 1},
        ])
        # записи отсортированы по (code, file, subject): повторный запуск не меняет файл
        text = baseline_path(root).read_text(encoding="utf-8")
        support.check(root, "baseline")
        self.assertEqual(baseline_path(root).read_text(encoding="utf-8"), text)

    def test_baseline_rewrites_after_fix(self):
        """baseline перезаписывает линию: исправленная ошибка из неё уходит."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        self.assertEqual(len(entries(root)), 1)
        support.sub(root / "docs" / "guide.md", " [a](nope.md)", "")
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 0, out)
        self.assertEqual(entries(root), [])

    def test_warnings_not_in_baseline(self):
        """Предупреждения в линию не попадают: D2-предупреждение остаётся видимым."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n## Наибольшая\n")
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 0, out)
        self.assertEqual(entries(root), [])
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "D2"), out)
        self.assertIn(support.localized('in the baseline: 0, fixed: 0', "в базовой линии 0, исправлено 0"), out)

    def test_cli_baseline_command(self):
        """`lipi baseline` через команду lipi создаёт линию проекта."""
        root = self.project()
        add_link(root, "nope.md")
        code, out = support.cli(root, "baseline")
        self.assertEqual(code, 0, out)
        self.assertTrue(baseline_path(root).is_file())
        code, out = support.cli(root, "check")
        self.assertEqual(code, 0, out)


class TestBaselineApply(support.Case):
    """check с линией: известная ошибка не роняет, новая роняет; --no-baseline показывает всё."""

    # @trace docs/ru/commands.md#baseline,docs/ru/codes.md#v2
    def test_existing_v2_entry_cannot_cover_a_missing_rules_link(self):
        root = self.project()
        support.w(root / "AGENTS.md", "# Project instructions\n")
        add_link(root)
        debt = {"code": "D1", "file": "docs/guide.md", "subject": "nope.md", "count": 1}
        legacy = {"code": "V2", "file": "AGENTS.md", "subject": "AGENTS.md", "count": 1}
        old_entries = [debt, legacy]
        support.w(baseline_path(root), json.dumps({"schema": 1, "entries": old_entries}))

        code, data = support.check_json(root)
        self.assertEqual(code, 1, data)
        self.assertEqual([e["code"] for e in data["errors"]], ["V2"])
        self.assertEqual(data["baseline"], {"known": 1, "fixed": 0})
        self.assertEqual(entries(root), old_entries)

        support.w(root / "AGENTS.md", "[Lipi rules](.agents/lipi/README.md)\n")
        code, data = support.check_json(root)
        self.assertEqual(code, 0, data)
        self.assertEqual(entries(root), old_entries)

        support.w(root / "AGENTS.md", "# Project instructions\n")
        code, out = support.check(root, "baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertEqual(entries(root), [debt])

    def test_known_error_does_not_fail(self):
        """Известная ошибка: проверка проходит, вывод сообщает размер линии."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D1"), out)
        self.assertIn(support.localized('in the baseline: 1, fixed: 0. Run `lipi baseline --prune`.', "в базовой линии 1, исправлено 0 — `lipi baseline --prune`"), out)

    def test_new_error_fails(self):
        """Новая ошибка: код возврата 1, старая не печатается."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        add_link(root, "gone.md", tag="b")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)
        self.assertIn("gone.md", out)
        self.assertNotIn("nope.md", out)
        self.assertIn(support.localized('in the baseline: 1, fixed: 0', "в базовой линии 1, исправлено 0"), out)

    def test_new_counterpart_of_known_group_fails(self):
        """Повтор известной ошибки сверх линии — новая: два одинаковых повтора, в линии один."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        add_link(root, "nope.md", tag="b")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_line_shift_does_not_break(self):
        """Сдвиг строк выше ошибки не ломает линию: номера в неё не входят."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        page = root / "docs" / "guide.md"
        page.write_text("строка\n" * 12 + page.read_text(encoding="utf-8"), encoding="utf-8")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('in the baseline: 1', "в базовой линии 1"), out)

    def test_d3_resize_does_not_break(self):
        """Изменение размера страницы (D3) не ломает линию: в ней нет чисел."""
        root = self.project()
        add_long_page(root)
        code, out = support.check(root)
        self.assertTrue(support.found(out, "D3"), out)
        support.check(root, "baseline")
        page = root / "docs" / "other.md"
        page.write_text(page.read_text(encoding="utf-8") + "строка\n" * 100, encoding="utf-8")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D3"), out)
        self.assertIn(support.localized('in the baseline: 1', "в базовой линии 1"), out)

    def test_no_baseline_shows_all(self):
        """--no-baseline: известные ошибки снова ошибки, линии в выводе нет."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        code, out = support.check(root, "--no-baseline")
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)
        self.assertNotIn(support.localized('in the baseline', "в базовой линии"), out)

    def test_no_baseline_file_no_summary(self):
        """Линии нет: вывод не содержит строки о линии, все ошибки считаются."""
        root = self.project()
        baseline_path(root).unlink()          # init создаёт пустую линию
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertNotIn(support.localized('in the baseline', "в базовой линии"), out)

    def test_json_baseline_and_known_fixed(self):
        """JSON: subject у ошибок, baseline.known и baseline.fixed."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "D1")["subject"], "nope.md")
        code, data = support.check_json(root)
        self.assertEqual(code, 0)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["baseline"], {"known": 1, "fixed": 0})
        support.sub(root / "docs" / "guide.md", " [a](nope.md)", "")
        code, data = support.check_json(root)
        self.assertEqual(code, 0)
        self.assertEqual(data["baseline"], {"known": 0, "fixed": 1})


class TestC1(support.Case):
    """C1: с неверными настройками проверке нельзя доверять — линия не применяется."""

    def test_baseline_refuses_bad_settings(self):
        """lipi baseline при неверных настройках отказывает (код 2) и файла не создаёт."""
        root = self.project()
        baseline_path(root).unlink()          # init создаёт пустую линию
        add_link(root, "nope.md")
        support.set_config(root, anchor="docs")
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 2, out)
        self.assertTrue(support.found(out, "C1"), out)
        self.assertFalse(baseline_path(root).exists())

    def test_baseline_refuses_bad_baseline(self):
        """Нечитаемая линия — тоже C1: baseline не перезаписывает её молча."""
        root = self.project()
        support.w(baseline_path(root), "{\"schema\": 2, \"entries\": []}")
        code, out = support.check(root, "baseline")
        self.assertEqual(code, 2, out)
        self.assertEqual(baseline_path(root).read_text(encoding="utf-8"),
                         "{\"schema\": 2, \"entries\": []}")

    def test_check_with_c1_ignores_baseline(self):
        """C1 останавливает проверку с кодом 2, даже если линия покрывала ошибки."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        support.set_config(root, anchor="docs")
        code, out = support.check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(support.found(out, "C1"), out)
        self.assertNotIn(support.localized('in the baseline', "в базовой линии"), out)


class TestPrune(support.Case):
    """baseline --prune: только уменьшает линию и никогда не добавляет."""

    def test_prune_removes_fixed(self):
        """Исправленная ошибка уходит из линии."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        support.sub(root / "docs" / "guide.md", " [a](nope.md)", "")
        code, out = support.check(root, "baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('had 1, removed 1, 0 remaining', "было 1, убрано 1, осталось 0"), out)
        self.assertEqual(entries(root), [])

    def test_prune_never_adds(self):
        """Новая ошибка не попадает в линию при --prune и продолжает ронять проверку."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        add_link(root, "gone.md", tag="b")
        code, out = support.check(root, "baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('had 1, removed 0, 1 remaining', "было 1, убрано 0, осталось 1"), out)
        self.assertEqual([e["subject"] for e in entries(root)], ["nope.md"])
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_prune_reduces_count(self):
        """Меньше повторов, чем в линии: --prune уменьшает число, а не убирает запись."""
        root = self.project()
        add_link(root, "nope.md")
        add_link(root, "nope.md", tag="b")
        support.check(root, "baseline")
        self.assertEqual(entries(root)[0]["count"], 2)
        support.sub(root / "docs" / "guide.md", " [a](nope.md)", "")
        code, out = support.check(root, "baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertEqual(entries(root)[0]["count"], 1)

    def test_prune_without_baseline(self):
        """--prune без линии: код 2 и подсказка создать линию."""
        root = self.project()
        baseline_path(root).unlink()          # init создаёт пустую линию
        code, out = support.check(root, "baseline", "--prune")
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('no baseline', "базовой линии нет"), out)
        self.assertFalse(baseline_path(root).exists())


class TestSubjects(support.Case):
    """subject — устойчивая суть находки без чисел и формулировки."""

    def test_d1_subject_is_target(self):
        root = self.project()
        add_link(root, "nope.md")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "D1")["subject"], "nope.md")

    def test_d3_subject_is_empty(self):
        root = self.project()
        add_long_page(root)
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "D3")["subject"], "")

    def test_d2_subject_is_anchor(self):
        root = self.project()
        support.sub(root / "docs" / "guide.md", "Текст.",
                    "Текст. <a id=\"max-discount\"></a>")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "D2")["subject"], "max-discount")

    def test_w3_subject_is_header_field(self):
        root = self.project()
        support.header_del(root, "pln", "Status")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "W3")["subject"], "Status")

    def test_w8_subject_is_section(self):
        root = self.project()
        support.header_set(root, "pln", {"Status": "in progress"})
        code, data = support.check_json(root, "--no-baseline")
        subjects = {e["subject"] for e in data["errors"] if e["code"] == "W8"}
        self.assertEqual(subjects, {"Purpose", "Completion criteria"})

    def test_w2_subject_is_id(self):
        root = self.project()
        src = support.doc(root, "pln")
        shutil.copy(src, src.parent / "pln-001-dup.md")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "W2")["subject"], "pln-001")

    def test_w5_subject_is_id(self):
        root = self.project()
        support.sub(root / "workflow" / "masterplan.md", support.localized('## Now\n', "## Сейчас\n"),
                    support.localized('## Now\n\n- PLN-002\n', "## Сейчас\n\n- PLN-002\n"))
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "W5")["subject"], "pln-002")

    def test_w6_subject_is_target(self):
        root = self.project()
        with open(root / "workflow" / "README.md", "a", encoding="utf-8") as stream:
            stream.write("\n[битая](nope.md)\n")
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "W6")["subject"], "nope.md")

    def test_t1_subject_is_target(self):
        root = self.project()
        support.w(root / "src" / "bad.py", "# %s nope.md#missing\n" % support.TAG)
        code, data = support.check_json(root, "--no-baseline")
        self.assertEqual(error_with(data, "T1")["subject"], "nope.md#missing")


class TestA6(support.Case):
    """A6: аудит показывает размер базовой линии по кодам ошибок."""

    def test_a6_fires_with_baseline(self):
        root = self.project()
        add_link(root, "nope.md")
        add_link(root, "nope.md", tag="b")
        add_long_page(root)
        support.check(root, "baseline")
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "A6"), out)
        self.assertIn(support.localized('baseline: D1 — 2, D3 — 1', "базовая линия: D1 — 2, D3 — 1"), out)

    def test_a6_not_in_quick_check(self):
        """A6 — только аудит: быстрые проверки его не печатают."""
        root = self.project()
        add_link(root, "nope.md")
        support.check(root, "baseline")
        code, out = support.check(root)
        self.assertFalse(support.found(out, "A6"), out)

    def test_a6_silent_without_baseline(self):
        code, out = support.check(self.project(), "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A6"), out)

    def test_a6_silent_with_empty_baseline(self):
        root = self.project()
        support.check(root, "baseline")
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A6"), out)


class TestInitBaseline(unittest.TestCase):
    """lipi init: линия вместо ослабленных настроек (ADR-003)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-init-"))
        self.root = self.tmp / "p"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self):
        return json.loads((self.root / "lipi.json").read_text(encoding="utf-8"))

    def test_init_creates_baseline_and_no_weakening(self):
        """init: найденные ошибки в линии, ослабленных ключей в lipi.json нет."""
        support.w(self.root / "docs" / "README.md",
                  "# Старое\n\n## Раздел\n\n[к разделу](#раздел) [битая](net.md)\n"
                  + "строка\n" * 400)
        support.w(self.root / "workflow" / "current" / "plan-old.md", "# Старый план\n")
        support.w(self.root / "AGENTS.md", "мои правила\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        cfg = self.config()
        self.assertNotIn("limits", cfg)
        self.assertNotIn("anchors", cfg)
        self.assertIsNone(cfg["workflow"])
        self.assertTrue(baseline_path(self.root).is_file(), out)
        # Существующий AGENTS.md принадлежит проекту: init не дописывает
        # ссылку, а объясняет действие.
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"),
                         "мои правила\n")
        self.assertIn(support.localized('Add a link to the rules in AGENTS.md', "добавьте вручную в AGENTS.md ссылку"), out)
        self.assertEqual(len(entries(self.root)), 3)
        self.assertNotIn("V2", {entry["code"] for entry in entries(self.root)})
        code, data = support.check_json(self.root)
        self.assertEqual(code, 1, data)
        self.assertEqual([e["code"] for e in data["errors"]], ["V2"])
        self.assertEqual(data["baseline"], {"known": 3, "fixed": 0})
        support.w(self.root / "AGENTS.md", "[Lipi rules](.agents/lipi/README.md)\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        code, out = support.check(self.root, "--no-baseline")
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_init_without_existing_workflow_creates_baseline(self):
        """init без чужих рабочих материалов: создаёт каркас и линию."""
        support.w(self.root / "docs" / "README.md", "# Старое\n\n[битая](net.md)\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.config()["workflow"], "workflow")
        self.assertTrue((self.root / "workflow" / "INDEX.md").is_file())
        self.assertEqual(len(entries(self.root)), 1)
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
