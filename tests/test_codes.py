"""test_codes.py — уровни проверок в проекте (ADR-012).

Ключ `codes` в lipi.json: код → `"error"`, `"warning"`, `"off"`. Без ключа
действует таблица `CODE_LEVELS` чекера; уровень проекта работает в отчёте,
коде возврата, базовой линии и пересборке указателя. Отдельные случаи:
D1/W6 (ссылка в никуда) и D7/W9 (ссылка на заголовок без явного якоря), C1 на
неизвестный код/уровень и на попытку настроить C1/V1, автопересборка
указателя локальным `lipi check`.

Каждый тест получает свежий развёрнутый проект в setUp и портит ровно один
аспект. Запуск: python3 -m unittest tests.test_codes -v
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support


class CodesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-codes-"))
        self.root = self.tmp / "p"
        self.root.mkdir()
        code, out = support.init(self.root)
        if code != 0:
            raise AssertionError("init не прошёл: %s" % out)
        support.seed(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def codes(self, **fields):
        support.set_config(self.root, **fields)

    # @trace docs/ru/checking.md#levels,ADR-012
    def test_defaults_without_key(self):
        """Без ключа codes — уровни из таблицы: D1 ошибка, T2 предупреждение."""
        support.w(self.root / "docs" / "guide.md", "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [нет](gone.md).\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_warning_changes_report_and_exit(self):
        """codes: {"D1": "warning"} — D1 в предупреждениях, код возврата 0."""
        support.w(self.root / "docs" / "guide.md", "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [нет](gone.md).\n")
        self.codes(codes={"D1": "warning"})
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('warning D1', "предупреждение D1"), out)
        self.assertNotIn(support.localized('error D1', "ошибка D1"), out)
        # строгий режим снова ловит предупреждения
        code, out = support.check(self.root, "--strict")
        self.assertEqual(code, 1, out)

    def test_off_removes_finding(self):
        """codes: {"D1": "off"} — находки нет, код возврата 0."""
        support.w(self.root / "docs" / "guide.md", "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [нет](gone.md).\n")
        self.codes(codes={"D1": "off"})
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn("D1", out)

    # @trace docs/ru/codes.md#c1,ADR-012
    def test_c1_unknown_code(self):
        self.codes(codes={"Z9": "off"})
        code, out = support.check(self.root)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('unknown code', "неизвестный код"), out)

    def test_c1_unknown_level(self):
        self.codes(codes={"D1": "sometimes"})
        code, out = support.check(self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("error, warning, off", out)

    def test_c1_non_configurable(self):
        for code in ("C1", "V1"):
            with self.subTest(code=code):
                self.codes(codes={code: "off"})
                code_out, out = support.check(self.root)
                self.assertEqual(code_out, 2, out)
                self.assertIn(support.localized('cannot be configured', "не настраивается"), out)

    # @trace docs/ru/checking.md#levels,ADR-012
    def test_d7_heading_link(self):
        """Ссылка на заголовок без якоря — D7; D1 остаётся для ссылок в никуда."""
        support.w(self.root / "docs" / "other.md", "# Другое\n\n## Раздел\n\nТекст.\n")
        support.w(self.root / "docs" / "guide.md",
                  "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [заголовок](other.md#раздел) и [нет](gone.md).\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D7"), out)
        self.assertTrue(support.found(out, "D1"), out)
        # off принимает ссылку на заголовок, ссылка в никуда остаётся
        self.codes(codes={"D7": "off"})
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertNotIn("D7", out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_d7_off_graph_edge(self):
        """D7: off — ребро графа к странице с полем anchor, узла-якоря нет."""
        support.w(self.root / "docs" / "other.md", "# Другое\n\n## Раздел\n\nТекст.\n")
        support.w(self.root / "docs" / "guide.md",
                  "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [заголовок](other.md#раздел).\n")
        self.codes(codes={"D7": "off"})
        code, out = support.check(self.root, "--format", "json", "--structure")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        nodes = data["structure"]["nodes"]
        edges = data["structure"]["edges"]
        self.assertNotIn("docs/other.md#раздел",
                         [n["id"] for n in nodes if n.get("type") == "anchor"],
                         "узла-якоря для заголовка быть не должно")
        edge = next(e for e in edges
           if e.get("type") == "link" and e.get("from") == "docs/guide.md"
           and e.get("anchor") == "раздел")
        self.assertEqual(edge["to"], "docs/other.md")
        self.assertEqual(edge["anchor"], "раздел")

    def test_w9_levels_in_each_scope(self):
        """W9 настраивается для работ, правил и README: warning, error, off."""
        support.sub(self.root / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n## Раздел\n\nТекст.")
        support.sub(support.doc(self.root, "iss"), "## Observation",
                    "## Observation\n\n[раздел](../../../docs/guide.md#раздел)")
        support.w(self.root / ".agents" / "README.md",
                  "# Правила\n\n[раздел](../docs/guide.md#раздел)\n")
        support.w(self.root / "README.md",
                  "# Проект\n\n[раздел](docs/guide.md#раздел)\n")
        for level, expected_exit, label in (("warning", 0, "предупреждение"),
                                            ("error", 1, "ошибка"),
                                            ("off", 0, None)):
            with self.subTest(level=level):
                self.codes(codes={"W9": level})
                code, out = support.check(self.root)
                self.assertEqual(code, expected_exit, out)
                self.assertFalse(support.found(out, "W6"), out)
                if label:
                    self.assertEqual(out.count("[%s W9]" % support.localized(level, label)), 3, out)
                else:
                    self.assertFalse(support.found(out, "W9"), out)

    def test_w9_off_keeps_broken_links_as_w6(self):
        """Отключение W9 не скрывает ни отсутствующий файл, ни битый якорь."""
        support.w(self.root / "README.md",
                  "# Проект\n\n[заголовок](docs/guide.md#скидки)\n"
                  "[файл](gone.md)\n[якорь](docs/guide.md#missing)\n")
        self.codes(codes={"W9": "off"})
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertFalse(support.found(out, "W9"), out)
        self.assertEqual(out.count(support.localized('[error W6]', "[ошибка W6]")), 2, out)

    def test_d7_remains_error_when_w9_is_off(self):
        """Описание, включая README при docs: '.', сохраняет ошибку D7."""
        support.sub(self.root / "docs" / "guide.md", "Текст.",
                    "Текст.\n\n[заголовок](#скидки)\n")
        self.codes(codes={"W9": "off"})
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn(support.localized('[error D7]', "[ошибка D7]"), out)
        self.assertFalse(support.found(out, "W9"), out)

        support.sub(self.root / "docs" / "guide.md",
                    "[заголовок](#скидки)", "")
        support.w(self.root / "README.md",
                  "# Проект\n\n[описание](docs/README.md)\n"
                  "[заголовок](docs/guide.md#скидки)\n")
        self.codes(docs=".")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn(support.localized('[error D7]', "[ошибка D7]"), out)
        self.assertFalse(support.found(out, "W9"), out)

    # @trace docs/ru/codes.md#t1
    def test_trace_to_heading_still_t1(self):
        """@trace на заголовок без якоря — по-прежнему T1, codes не помогает."""  # lipi: ignore-trace
        support.w(self.root / "docs" / "other.md", "# Другое\n\n## Раздел\n\nТекст.\n")
        support.w(self.root / "src" / "main.py",
                  "x = 1\n# @trace docs/other.md#раздел\ny = 2\n")  # lipi: ignore-trace
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)

    # @trace docs/ru/checking.md#levels,ADR-012
    def test_baseline_ignores_demoted(self):
        """Пониженный до warning код не попадает в базовую линию; prune убирает."""
        support.w(self.root / "docs" / "guide.md", "# Гид\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nСм. [нет](gone.md).\n")
        code, out = support.check(self.root, "baseline")
        self.assertEqual(code, 0, out)
        base = json.loads((self.root / support.BASE_REL).read_text(encoding="utf-8"))
        self.assertTrue(any(e["code"] == "D1" for e in base["entries"]))
        # понижаем D1 — prune убирает его запись
        self.codes(codes={"D1": "warning"})
        code, out = support.check(self.root, "baseline", "--prune")
        self.assertEqual(code, 0, out)
        base = json.loads((self.root / support.BASE_REL).read_text(encoding="utf-8"))
        self.assertFalse(any(e["code"] == "D1" for e in base["entries"]),
                         "пониженный код должен уйти из базовой линии")

    # @trace docs/ru/codes.md#w7
    def test_index_rebuilds_locally(self):
        """Локальный check пересобирает устаревший указатель и молчит о W7."""
        support.sub(self.root / "workflow" / "INDEX.md", '# Workflow index', "# мусор")
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('rebuilt index', "указатель пересобран"), out)
        self.assertNotIn("W7", out)
        text = (self.root / "workflow" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn('Workflow index', text)

    def test_index_not_rebuilt_in_other_modes(self):
        """--staged/--diff/CI/github: W7 остаётся, файл не пишется."""
        support.sub(self.root / "workflow" / "INDEX.md", '# Workflow index', "# мусор")
        stale = (self.root / "workflow" / "INDEX.md").read_text(encoding="utf-8")
        support.git_init(self.root)
        support.commit(self.root, "init")
        for args, env in [
            (["--staged"], {}),
            (["--diff", "HEAD"], {}),
            ([], {"CI": "1"}),
            (["--format", "github"], {}),
        ]:
            with self.subTest(args=args, env=env):
                code, out = support.check(self.root, *args, env=env)
                self.assertEqual(code, 1, out)
                if args == ["--format", "github"]:
                    self.assertIn("title=W7", out, out)
                else:
                    self.assertTrue(support.found(out, "W7"), out)
                self.assertEqual(
                    (self.root / "workflow" / "INDEX.md").read_text(encoding="utf-8"),
                    stale)


if __name__ == "__main__":
    unittest.main()
