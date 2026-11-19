"""test_docs.py — проверки D1–D6 чекера lipi: страницы описания.

Каждый код проверяется с обеих сторон: нарушение даёт код возврата 1 и маркер
«[ошибка DX]» в выводе, предупреждение — код 0 и «[предупреждение DX]», а
исправный случай проходит без маркера. Маркер ищет support.found().

Запуск: python3 -m unittest discover -s tests -p "test_docs.py" -v
"""
import unittest

from tests import support


class DocChecks(support.Case):
    """Страницы описания в проекте-пакете (docs/ — описание и справка)."""

    # --- весь набор: чистый проект -------------------------------------------

    def test_clean_project_has_no_d_codes(self):
        """Чистый проект: ни одна из проверок D1–D6 не срабатывает."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        for d in ("D1", "D2", "D3", "D4", "D5", "D6"):
            self.assertFalse(support.found(out, d), out)

    # --- D1: ссылки описания ---------------------------------------------------

    def test_d1_broken_file_link(self):
        """Ссылка ведёт в несуществующий файл: ошибка D1."""
        root = self.project()
        support.w(root / "docs" / "guide.md", "# X\n\n[a](nope.md)\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)
        self.assertIn(support.localized('a file that does not exist', "несуществующий файл"), out)

    def test_d1_link_to_heading_without_anchor(self):
        """Ссылка на заголовок вместо явного якоря: D7; D1 — только в никуда."""
        root = self.project()
        support.sub(root / "docs" / "README.md",
                    "guide.md#max-discount", "guide.md#наибольшая")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D7"), out)
        self.assertIn(support.localized('without an explicit anchor', "без явного якоря"), out)
        self.assertFalse(support.found(out, "D1"), out)

    def test_d1_page_not_utf8(self):
        """Страница описания не читается как UTF-8: ошибка D1."""
        root = self.project()
        support.wb(root / "docs" / "guide.md", b"\xff\xfe\x00")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)
        self.assertIn(support.localized('cannot read the file as UTF-8', "не читается как UTF-8"), out)

    # --- D2: якоря -------------------------------------------------------------

    def test_d2_invalid_anchor_characters(self):
        """Якорь с недопустимыми символами (Max_Discount): ошибка D2."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "max-discount", "Max_Discount")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D2"), out)

    def test_d2_anchor_repeated_in_file(self):
        """Якорь повторяется в одном файле: ошибка D2."""
        root = self.project()
        support.sub(root / "docs" / "guide.md",
                    "Текст.", "Текст. <a id=\"max-discount\"></a>")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D2"), out)
        self.assertIn(support.localized('is repeated in the file', "повторяется в файле"), out)

    def test_d2_same_anchor_on_different_pages(self):
        """Одинаковый якорь на разных страницах: D2 не срабатывает (уникальность
        в пределах страницы), как у описаний с якорями section-N на каждой."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "max-discount", "section-1")
        support.sub(root / "src" / "order.py", "docs/guide.md#max-discount", "docs/guide.md#section-1")
        support.w(root / "docs" / "other.md",
                  "# Другое\n\n## Раздел <a id=\"section-1\"></a>\n")
        support.sub(root / "docs" / "README.md",
                    "| Скидки | [Скидки](guide.md#max-discount) |",
                    "| Скидки | [Скидки](guide.md#section-1) |\n"
                    "| Другое | [Другое](other.md#section-1) |")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D2"), out)

    def test_d2_duplicate_heading_slug_warns(self):
        """Два заголовка с одинаковым slug на странице: предупреждение D2."""
        root = self.project()
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст.\n\n## Наибольшая\n")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "D2"), out)
        self.assertIn("slug", out)

    def test_d2_distinct_anchors_pass(self):
        """Валидные и разные якоря: D2 не срабатывает."""
        root = self.project()
        support.w(root / "docs" / "other.md",
                  "# Другое\n\n## Раздел <a id=\"other-anchor\"></a>\n")
        support.sub(root / "docs" / "README.md",
                    "| Скидки | [Скидки](guide.md#max-discount) |",
                    "| Скидки | [Скидки](guide.md#max-discount) |\n"
                    "| Другое | [Другое](other.md#other-anchor) |")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D2"), out)

    # --- D3: размер страницы ----------------------------------------------------

    def test_d3_page_too_long(self):
        """Страница длиннее предела строк: ошибка D3."""
        root = self.project()
        support.w(root / "docs" / "guide.md",
                  "# Скидки\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nТекст.\n"
                  + "строка\n" * 400)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D3"), out)

    def test_d3_page_too_big(self):
        """Страница больше предела байт: ошибка D3."""
        root = self.project()
        support.w(root / "docs" / "guide.md",
                  "# Скидки\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nТекст.\n"
                  + "б" * 30000 + "\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D3"), out)

    def test_d3_regular_page_passes(self):
        """Обычная страница укладывается в пределы: D3 не срабатывает."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D3"), out)

    def test_d3_limits_disabled(self):
        """Пределы 0 отключают D3 даже для большой страницы."""
        root = self.project()
        support.w(root / "docs" / "guide.md",
                  "# Скидки\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nТекст.\n"
                  + "строка\n" * 400)
        support.set_config(root, limits={"docs_lines": 0, "docs_bytes": 0})
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D3"), out)

    # --- release_notes: страница с записями о выпусках вне предела D3 ----------

    def big_releases_page(self, root, text=None):
        """Большая страница docs/releases.md, достижимая из указателя."""
        support.w(root / "docs" / "releases.md",
                  "# Выпуски\n\n" + (text if text is not None else "")
                  + "строка\n" * 400)
        support.sub(root / "docs" / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Выпуски | [Выпуски](releases.md) |")

    def test_d3_release_notes_page_exempt(self):
        """Страница из ключа release_notes не проверяется на размер."""
        root = self.project()
        self.big_releases_page(root)
        support.set_config(root, release_notes="releases.md")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D3"), out)

    def test_d3_without_release_notes_rings(self):
        """Без ключа release_notes та же страница даёт D3."""
        root = self.project()
        self.big_releases_page(root)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D3"), out)

    def test_release_notes_missing_page_not_error(self):
        """Файла из release_notes нет — не ошибка: пропускать нечего."""
        root = self.project()
        support.set_config(root, release_notes="nope.md")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D3"), out)

    def test_release_notes_page_still_checked_by_links(self):
        """Страница release_notes проходит D1: битая ссылка в ней — ошибка."""
        root = self.project()
        self.big_releases_page(root, "[нет такой](nope.md)\n\n")
        support.set_config(root, release_notes="releases.md")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)
        self.assertFalse(support.found(out, "D3"), out)

    # --- D4: достижимость -------------------------------------------------------

    def test_d4_orphan_page(self):
        """Страница без ссылки из указателя: ошибка D4."""
        root = self.project()
        support.w(root / "docs" / "orphan.md", "# Сирота\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn(support.localized('is unreachable', "недостижима"), out)

    def test_d4_missing_readme(self):
        """Нет указателя docs/README.md: ошибка D4."""
        root = self.project()
        (root / "docs" / "README.md").unlink()
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn(support.localized('missing README.md index', "нет указателя README.md"), out)

    def test_d4_all_pages_reachable(self):
        """Каждая страница достижима из указателя: D4 не срабатывает."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D4"), out)

    def test_d6_ignores_code_examples_but_checks_real_comment(self):
        """Примеры covers в коде не связи; настоящий комментарий проверяется и в package."""
        root = self.project()
        page = root / "docs/guide.md"
        support.w(page, page.read_text() + "\n```markdown\n<!-- covers: missing.md#rule -->\n```\n"
                  + "\nПример: `<!-- covers: missing.md#rule -->`.\n")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D6"), out)
        support.w(page, page.read_text() + "\n<!-- covers: missing.md#rule -->\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertFalse(support.found(out, "T1"), out)

    # --- D5: описание не ссылается на рабочие материалы -------------------------

    def test_d5_link_to_workflow(self):
        """Описание ссылается на рабочие материалы: ошибка D5."""
        root = self.project()
        support.sub(root / "docs" / "guide.md",
                    "Текст.", "[план](../workflow/README.md)")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D5"), out)

    def test_d5_link_to_other_doc_page(self):
        """Ссылка на другую страницу описания: D5 не срабатывает."""
        root = self.project()
        support.w(root / "docs" / "other.md", "# Другое\n\n[назад](README.md)\n")
        support.sub(root / "docs" / "README.md",
                    "| Скидки | [Скидки](guide.md#max-discount) |",
                    "| Скидки | [Скидки](guide.md#max-discount) |\n"
                    "| Другое | [Другое](other.md) |")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D5"), out)


class AppDocChecks(support.Case):
    """Справка и описание системы в приложении (--type app)."""
    base_args = ("--type", "app")

    def help_page(self, root, name, covers):
        """Страница справки с covers, достижимая из docs/README.md."""
        support.w(root / "docs" / name,
                  "# Справка\n\n<!-- covers: %s -->\n" % covers)
        support.sub(root / "docs" / "README.md", "| --- | --- |",
                    "| --- | --- |\n| %s | [%s](%s) |" % (name, name, name))

    def second_descr_page(self, root):
        """Вторая страница описания системы с тем же якорем processes."""
        support.w(root / "docs" / "development" / "rules.md",
                  "# Правила\n\n## Процессы <a id=\"processes\"></a>\n\nТекст.\n")
        support.sub(root / "docs" / "development" / "README.md",
                    support.localized('## Processes', "## Процессы"), support.localized('- [Правила](rules.md)\n\n## Processes', "- [Правила](rules.md)\n\n## Процессы"))

    # --- D6: covers в справке ----------------------------------------------------
    #
    # covers, как метка: путь от корня и якорь либо номер работы.

    def test_d6_covers_full_form_passes(self):
        """covers полной формы (страница и якорь существуют): D6 не срабатывает."""
        root = self.project()
        self.help_page(root, "help.md", "docs/development/README.md#processes")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D6"), out)

    def test_d6_covers_unknown_page(self):
        """covers указывает на несуществующую страницу: ошибка D6."""
        root = self.project()
        self.help_page(root, "help.md", "docs/development/nope.md#processes")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertIn(support.localized('no page docs/development/nope.md', "нет страницы docs/development/nope.md"), out)

    def test_d6_covers_unknown_anchor(self):
        """Страница есть, а якоря на ней нет: ошибка D6."""
        root = self.project()
        self.help_page(root, "help.md", "docs/development/README.md#no-such")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertIn(support.localized('page docs/development/README.md has no anchor "no-such"', "на странице docs/development/README.md нет якоря «no-such»"), out)

    def test_d6_covers_page_outside_description(self):
        """covers разрешается и на страницу справки вне описания системы."""
        root = self.project()
        self.help_page(root, "help.md", "docs/README.md#start")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D6"), out)

    def test_d6_bare_anchor_rejected(self):
        """Один якорь без пути: D6, даже если он единственный."""
        root = self.project()
        self.help_page(root, "help.md", "processes")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertIn(support.localized('in the form path/page.md#anchor or TYPE-number', "неверная форма"), out)

    def test_d6_old_form_without_anchor(self):
        """Старая форма, такого якоря нет: D6 требует страницу, без подсказки."""
        root = self.project()
        self.help_page(root, "help.md", "no-such")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertIn(support.localized('in the form path/page.md#anchor or TYPE-number', "неверная форма"), out)
        self.assertNotIn("старая форма; полная", out)

    def test_d6_old_form_ambiguous_anchor(self):
        """Старая форма, якорь есть на двух страницах: D6 без подсказки."""
        root = self.project()
        self.second_descr_page(root)
        self.help_page(root, "help.md", "processes")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D6"), out)
        self.assertIn(support.localized('in the form path/page.md#anchor or TYPE-number', "неверная форма"), out)
        self.assertNotIn("старая форма; полная", out)

    # --- T2 и covers: связь по полному id ---------------------------------------

    def test_t2_covers_same_anchor_on_two_pages(self):
        """Одинаковый якорь на двух страницах описания: правка одной даёт T2
        только справке, которая указывает эту страницу, и не трогает другую."""
        root = self.project()
        self.second_descr_page(root)
        self.help_page(root, "help-first.md", "docs/development/README.md#processes")
        self.help_page(root, "help-second.md", "docs/development/rules.md#processes")
        support.git_init(root)
        support.commit(root)
        support.sub(root / "docs" / "development" / "rules.md", "Текст.", "Изменено.")
        support.git(root, "add", "docs/development/rules.md")
        code, out = support.check(root, "--staged")
        self.assertEqual(code, 0, out)
        warned = [line for line in out.split("\n")
                  if support.found(line, "T2")]
        self.assertTrue(any("help-second.md" in line for line in warned), out)
        self.assertFalse(any("help-first.md" in line for line in warned), out)
        self.assertIn("docs/development/rules.md#processes", out)


if __name__ == "__main__":
    unittest.main()
