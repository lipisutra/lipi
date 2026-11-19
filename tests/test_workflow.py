"""test_workflow.py — проверки W1–W9: рабочие материалы и их шапки.

Каждый тест берёт копию «правильного» проекта из support.Case (init + seed
один раз на класс) и ломает что-то одно; у каждого кода есть обе стороны:
нарушение, которое чекер обязан поймать, и чистый проект с кодом 0.

Запуск из корня lipi:
    python3 -m unittest discover -s tests -p "test_workflow.py" -v
"""
import sys
import unittest
from datetime import date
from urllib.parse import unquote

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))
from lipi.checker import conventions


class WorkflowFormatTest(unittest.TestCase):
    def test_workflow_format_stays_in_english(self):
        self.assertEqual(
            {value for name, value in vars(conventions).items() if name.startswith("K_")},
            {"Created", "Updated", "Status", "Closed", "Result", "Kind", "Recipient",
             "Source", "Refines", "Due"},
        )
        self.assertEqual(conventions.STATUSES, {
            "pln": ["new", "in progress", "pending acceptance", "deferred", "completed", "canceled"],
            "iss": ["open", "in progress", "closed"],
            "adr": ["proposed", "accepted", "superseded", "rejected"],
            "dsc": ["open", "closed"],
        })
        self.assertEqual(conventions.ISSUE_KINDS, ["bug", "friction", "request", "question"])
        self.assertEqual(conventions.REQUIRED_SECTIONS, {
            ("iss", "open"): ["Observation"],
            ("iss", "in progress"): ["Observation"],
            ("pln", "in progress"): ["Purpose", "Completion criteria"],
            ("pln", "pending acceptance"): ["Purpose", "Completion criteria"],
        })
        self.assertEqual(conventions.DECISION_HEADING, "Decision")
        self.assertEqual(conventions.SOURCE_EXTERNAL, "external")


class WorkflowTests(support.Case):
    """W1–W9: план pln-001 и замечание iss-001 из support.seed."""

    # --- W1: имя, тип и каталог рабочего документа -----------------------------

    def test_w1_bad_file_names(self):
        """W1: имя не по формату, папка без readme, чужой каталог, не-UTF-8."""
        root = self.project()
        support.w(support.doc(root, "pln").parent / "staryy-plan.md", "# X\n")
        support.w(support.doc(root, "pln").parent / "pln-009-tema" / "extra.md", "текст\n")
        support.w(support.doc(root, "iss").parent / "pln-005-ne-tam.md", "# Не там\n")
        support.wb(support.doc(root, "pln").parent / "pln-010-krivo.md", b"\xff\xfe# X")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W1"), out)

    def test_w1_seed_clean(self):
        """W1 не срабатывает: правильный проект проходит с кодом 0."""
        code, out = support.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W1"))

    # --- W2: уникальность номера -----------------------------------------------

    def test_w2_duplicate_id(self):
        """W2: второй документ с уже занятым номером pln-001."""
        root = self.project()
        support.w(support.doc(root, "pln").parent / "pln-001-dubl.md",
                  "# Дубль\n\n- Created: 2026-01-01\n"
                  "- Updated: 2026-01-01\n- Status: new\n\nТекст.\n")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W2"), out)

    def test_w2_seed_clean(self):
        """W2 не срабатывает: номера в правильном проекте уникальны."""
        code, out = support.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W2"))

    # --- W3: шапка: даты, статус, вид замечания --------------------------------

    def test_w3_missing_h1(self):
        """W3: рабочий документ без заголовка первого уровня."""
        root = self.project()
        support.w(support.doc(root, "pln"), "Текст без заголовка\n")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_missing_created_date(self):
        """W3: в шапке нет строки «Дата создания»."""
        root = self.project()
        support.header_del(root, "pln", "Created")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_date_not_iso(self):
        """W3: дата создания не в формате ГГГГ-ММ-ДД."""
        root = self.project()
        support.header_set(root, "pln", {"Created": "01.01.2026"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_update_before_created(self):
        """W3: дата обновления раньше даты создания."""
        root = self.project()
        support.header_set(root, "pln", {"Created": "2026-01-02",
                                         "Updated": "2026-01-01"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_status_not_in_list(self):
        """W3: статус не из списка допустимых значений."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "почти готов"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_missing_status(self):
        """W3: в шапке нет строки «Статус»."""
        root = self.project()
        support.header_del(root, "pln", "Status")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_issue_missing_kind(self):
        """W3: у замечания нет строки «Вид»."""
        root = self.project()
        support.header_del(root, "iss", "Kind")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_issue_bad_kind(self):
        """W3: вид замечания не из списка."""
        root = self.project()
        support.header_set(root, "iss", {"Kind": "никакой"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w3_valid_header(self):
        """W3 не срабатывает: правильная шапка проходит с кодом 0."""
        code, out = support.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W3"))

    # --- W4: итог у завершённой работы ------------------------------------------

    def test_w4_finished_without_result(self):
        """W4: план «завершён» без строки «Итог»."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "completed", "Closed": date.today().isoformat()})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W4"), out)

    def test_w4_cancelled_without_result(self):
        """W4: план «отменён» без строки «Итог»."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "canceled", "Closed": date.today().isoformat()})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W4"), out)

    def test_w4_closed_issue_without_result(self):
        """W4: замечание «закрыто» без строки «Итог»."""
        root = self.project()
        support.header_set(root, "iss", {"Status": "closed", "Closed": date.today().isoformat()})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W4"), out)

    def test_w4_finished_with_result(self):
        """W4 не срабатывает: «завершён» с итогом и свежим указателем."""
        root = self.project()
        p = support.doc(root, "pln")
        support.header_set(root, "pln", {"Status": "completed", "Closed": date.today().isoformat()})
        support.sub(p, "- Status: completed", "- Status: completed\n- Result: сделано")
        support.reindex(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W4"))

    # --- W5: мастер-план ---------------------------------------------------------

    def test_w5_unknown_work(self):
        """W5: мастер-план ссылается на несуществующий документ."""
        root = self.project()
        support.sub(root / "workflow" / "masterplan.md",
                    support.localized('## Now', "## Сейчас"), support.localized('## Now\n\nPLN-099', "## Сейчас\n\nPLN-099"))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W5"), out)

    def test_w5_finished_work_in_masterplan(self):
        """W5: мастер-план упоминает завершённую работу."""
        root = self.project()
        p = support.doc(root, "pln")
        support.header_set(root, "pln", {"Status": "completed", "Closed": date.today().isoformat()})
        support.sub(p, "- Status: completed", "- Status: completed\n- Result: сделано")
        support.reindex(root)
        support.sub(root / "workflow" / "masterplan.md",
                    support.localized('## Now', "## Сейчас"), support.localized('## Now\n\nPLN-001', "## Сейчас\n\nPLN-001"))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W5"), out)

    def test_w5_masterplan_too_long(self):
        """W5: мастер-план длиннее предела в 150 строк."""
        root = self.project()
        mp = root / "workflow" / "masterplan.md"
        support.w(mp, mp.read_text(encoding="utf-8")
                  + "\n## Длинный раздел\n\n" + "строка\n" * 160)
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W5"), out)

    def test_w5_existing_active_work(self):
        """W5 не срабатывает: существующая незавершённая работа."""
        root = self.project()
        support.sub(root / "workflow" / "masterplan.md",
                    support.localized('## Now', "## Сейчас"), support.localized('## Now\n\nPLN-001', "## Сейчас\n\nPLN-001"))
        code, out = support.check(root)
        self.assertEqual(code, 0, out)

    # --- W6, W9: ссылки рабочих материалов и правил -----------------------------

    def test_w6_broken_link_in_work_doc(self):
        """W6: битая ссылка в рабочем документе."""
        root = self.project()
        support.sub(support.doc(root, "iss"),
                    "## Observation", "## Observation\n\n[x](net.md)")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "W6"), out)
        self.assertFalse(support.found(out, "W9"), out)

    def test_w6_broken_link_in_agents(self):
        """W6: битая ссылка в правилах проекта (.agents/README.md)."""
        root = self.project()
        # файлы lipi не правим: это проверка правил самого проекта
        support.w(root / ".agents" / "README.md",
                  "# Правила проекта\n\n[x](net.md)\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "W6"), out)
        self.assertFalse(support.found(out, "W9"), out)

    def test_w6_broken_link_in_root_readme(self):
        """W6: битая ссылка в корневом README.md (проверяется как правила)."""
        root = self.project()
        support.w(root / "README.md", "# Проект\n\n[x](net.md)\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "W6"), out)
        self.assertFalse(support.found(out, "W9"), out)

    def test_w6_w9_fragment_links_in_each_scope(self):
        """W9 — slug заголовка, W6 — отсутствующий якорь; явный якорь чист."""
        for scope, target in (("workflow", "../../../docs/guide.md"),
                              ("agents", "../docs/guide.md"),
                              ("readme", "docs/guide.md")):
            for fragment, expected in (("раздел", "W9"),
                                       ("missing", "W6"),
                                       ("max-discount", None)):
                with self.subTest(scope=scope, fragment=fragment):
                    root = self.project()
                    support.sub(root / "docs" / "guide.md", "Текст.",
                                "Текст.\n\n## Раздел\n\nТекст.")
                    source = {"workflow": support.doc(root, "iss"),
                              "agents": root / ".agents" / "README.md",
                              "readme": root / "README.md"}[scope]
                    text = (source.read_text(encoding="utf-8")
                            if source.exists() else "# Правила проекта\n")
                    support.w(source, text + "\n[раздел](%s#%s)\n"
                              % (target, fragment))
                    code, out = support.check(root)
                    self.assertEqual(code, 1 if expected == "W6" else 0, out)
                    self.assertEqual(support.found(out, "W6"), expected == "W6", out)
                    self.assertEqual(support.found(out, "W9"), expected == "W9", out)
                    self.assertFalse(support.found(out, "D7"), out)
                    if expected == "W9":
                        self.assertIn(support.localized('warning W9', "предупреждение W9"), out)

    # --- W7: актуальность указателя ----------------------------------------------

    def test_w7_stale_index(self):
        """Устаревший указатель: локальный check пересобирает его сам."""
        root = self.project()
        support.header_set(root, "iss", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('rebuilt index', "указатель пересобран"), out)
        self.assertNotIn("W7", out)

    def test_w7_remains_under_ci(self):
        """В CI (и --staged/--diff/github) указатель не пишется — W7 остаётся."""
        root = self.project()
        support.header_set(root, "iss", {"Status": "in progress"})
        code, out = support.check(root, env={"CI": "1"})
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "W7"), out)

    def test_w7_fresh_index(self):
        """W7 не срабатывает: после --write-index всё чисто."""
        root = self.project()
        support.header_set(root, "iss", {"Status": "in progress"})
        support.reindex(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W7"))

    # --- W8: обязательные непустые разделы --------------------------------------

    def test_w8_issue_open_missing_section(self):
        """W8: у замечания «открыто» нет раздела «Что наблюдается»."""
        root = self.project()
        support.sub(support.doc(root, "iss"), "## Observation\n\nТекст.\n\n", "")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized('missing section "Observation"', "нет раздела «Observation»"), out)
        self.assertIn("open", out)

    def test_w8_issue_open_empty_section(self):
        """W8: раздел «Что наблюдается» есть, но пуст."""
        root = self.project()
        support.sub(support.doc(root, "iss"), "## Observation\n\nТекст.\n",
                    "## Observation\n")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized(
            'section "Observation" is empty: status "open" requires "Observation"',
            'раздел «Observation» пуст — статус «open» требует: «Observation»'), out)

    def test_w8_issue_open_filled(self):
        """W8 не срабатывает: раздел «Что наблюдадается» заполнен (как в seed)."""
        code, out = support.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_issue_in_work_empty(self):
        """W8: замечание «в работе» с пустым разделом «Что наблюдается»."""
        root = self.project()
        support.sub(support.doc(root, "iss"), "## Observation\n\nТекст.\n",
                    "## Observation\n")
        support.header_set(root, "iss", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)

    def test_w8_issue_closed_without_section(self):
        """W8 не срабатывает: у замечания «закрыто» раздел не обязателен."""
        root = self.project()
        p = support.doc(root, "iss")
        support.sub(p, "## Observation\n\nТекст.\n\n", "")
        support.header_set(root, "iss", {"Status": "closed", "Closed": date.today().isoformat()})
        support.sub(p, "- Status: closed", "- Status: closed\n- Result: исправлено")
        support.reindex(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_heading_level_and_tag_ignored(self):
        """W8 не срабатывает: заголовок уровня 3 и тег <a id> в строке заголовка."""
        root = self.project()
        support.sub(support.doc(root, "iss"),
                    "## Observation", "### Observation <a id=\"seen\"></a>")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_pln_in_work_missing_zachem(self):
        """W8: план «в работе» без раздела «Зачем»."""
        root = self.project()
        support.sub(support.doc(root, "pln"), "## Purpose\n\n\n", "")
        support.header_set(root, "pln", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized('missing section "Purpose"', "нет раздела «Purpose»"), out)

    def test_w8_pln_in_work_missing_criteria(self):
        """W8: «Зачем» заполнен, а «Критерии завершения» нет."""
        root = self.project()
        p = support.doc(root, "pln")
        support.sub(p, "## Purpose", "## Purpose\n\nТекст.")
        support.sub(p, "## Completion criteria\n", "")
        support.header_set(root, "pln", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized('missing section "Completion criteria"', "нет раздела «Completion criteria»"), out)

    def test_w8_pln_in_work_empty_zachem(self):
        """W8: «Зачем» пуст, хотя «Критерии завершения» заполнены."""
        root = self.project()
        support.sub(support.doc(root, "pln"), "## Completion criteria",
                    "## Completion criteria\n\nТекст.")
        support.header_set(root, "pln", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized('section "Purpose" is empty', "раздел «Purpose» пуст"), out)

    def test_w8_pln_in_work_both_filled(self):
        """W8 не срабатывает: текст в разделах перед следующими разделами считается."""
        root = self.project()
        p = support.doc(root, "pln")
        support.sub(p, "## Purpose", "## Purpose\n\nТекст.")
        support.sub(p, "## Completion criteria", "## Completion criteria\n\nТекст.")
        support.header_set(root, "pln", {"Status": "in progress"})
        support.reindex(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_pln_review_empty(self):
        """W8: план «на приёмке» с пустыми разделами."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "pending acceptance"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)

    def test_w8_pln_new_without_sections(self):
        """W8 не срабатывает: у плана «новый» разделы не обязательны (seed)."""
        code, out = support.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_pln_finished_without_sections(self):
        """W8 не срабатывает: у завершённого плана разделы не обязательны."""
        root = self.project()
        p = support.doc(root, "pln")
        support.header_set(root, "pln", {"Status": "completed", "Closed": date.today().isoformat()})
        support.sub(p, "- Status: completed", "- Status: completed\n- Result: сделано")
        support.reindex(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W8"))

    def test_w8_subsection_text_does_not_count(self):
        """W8: текст только под «### Подраздел» не считается текстом раздела."""
        root = self.project()
        p = support.doc(root, "pln")
        support.sub(p, "## Purpose", "## Purpose\n\n### Подраздел\n\nТекст в подразделе.")
        support.sub(p, "## Completion criteria", "## Completion criteria\n\nТекст.")
        support.header_set(root, "pln", {"Status": "in progress"})
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)
        self.assertIn(support.localized('section "Purpose" is empty', "раздел «Purpose» пуст"), out)


# @trace docs/ru/commands.md#index
class IndexResultLinksTests(support.Case):
    """Итоги сохраняют цели ссылок при переносе в указатель."""

    def assert_index_links(self, root, source, result, expected, targets):
        original = source.read_bytes()
        code, out = support.cli(root, "index")
        self.assertEqual(code, 0, out)
        index = root / "workflow/index/done" / (str(date.today().year) + ".md")
        generated = index.read_bytes()
        code, out = support.check(root)
        self.assertFalse(support.found(out, "W6"), out)
        self.assertEqual(code, 0, out)
        self.assertIn("- Result: " + result, source.read_text(encoding="utf-8"))
        self.assertIn(" — " + expected + " (", generated.decode("utf-8"))
        for before, after in targets:
            with self.subTest(target=before):
                before_path, _, before_anchor = before.partition("#")
                after_path, _, after_anchor = after.partition("#")
                source_target = ((source.parent / unquote(before_path)).resolve()
                                 if before_path else source.resolve())
                index_target = (index.parent / unquote(after_path)).resolve()
                self.assertTrue(source_target.is_file())
                self.assertEqual(source_target, index_target)
                self.assertEqual(unquote(before_anchor), unquote(after_anchor))
        code, out = support.cli(root, "index")
        self.assertEqual(code, 0, out)
        self.assertEqual(index.read_bytes(), generated)
        self.assertEqual(source.read_bytes(), original)

    def test_closed_issue_result_links_preserve_targets_and_text(self):
        root = self.project()
        code, out = support.cli(root, "new", "aud", "Проверка результата")
        self.assertEqual(code, 0, out)
        audit = support.doc(root, "aud")
        support.w(audit, audit.read_text(encoding="utf-8")
                  + '\n## Результат <a id="result"></a>\n\nПроверено.\n')
        audit_link = "../../audit/" + audit.parent.name + "/" + audit.name + "#result"
        repeated_separator_link = "..//../audit/" + audit.parent.name + "/" + audit.name + "#result"
        audit_index_link = "../../audit/" + audit.parent.name + "/" + audit.name + "#result"
        result = ('См. [проверку](%s "Подробный результат") и '
                  '[описание](../../../docs/guide.md#max-discount); '
                  '[повтор проверки](%s); '
                  '[сайт](https://example.com/report#result), '
                  '[почта](mailto:team@example.com). '
                  'Пример: `[пример](missing.md#example)`.') % (
                      audit_link, repeated_separator_link)
        expected = result.replace(repeated_separator_link, audit_index_link)
        support.header_set(root, "iss", {"Status": "closed", "Closed": date.today().isoformat()})
        support.sub(support.doc(root, "iss"), "- Status: closed",
                    "- Status: closed\n- Result: " + result)
        self.assert_index_links(root, support.doc(root, "iss"), result, expected, [
            (audit_link, audit_index_link),
            (repeated_separator_link, audit_index_link),
            ("../../../docs/guide.md#max-discount", "../../../docs/guide.md#max-discount"),
        ])

    def test_finished_nested_plan_result_links_preserve_local_anchor_and_attachment(self):
        root = self.project()
        result = ('Готово: [вывод](#result), '
                  '[приложение](appendix%20notes.md#details "Данные проверки"), '
                  '[повтор приложения](.//appendix%20notes.md#details).')
        support.header_set(root, "pln", {"Status": "completed", "Closed": date.today().isoformat()})
        flat_source = support.doc(root, "pln")
        support.sub(flat_source, "- Status: completed",
                    "- Status: completed\n- Result: " + result)
        source = flat_source.with_suffix("") / "pln-001-readme.md"
        support.w(source, flat_source.read_text(encoding="utf-8")
                  + '\n## Вывод <a id="result"></a>\n\nГотово.\n')
        flat_source.unlink()
        support.w(source.parent / "appendix notes.md",
                  '# Данные\n\n## Проверка <a id="details"></a>\n\nПроверено.\n')
        directory = "../../" + source.parent.relative_to(root / "workflow").as_posix()
        local_link = directory + "/pln-001-readme.md#result"
        attachment_link = directory + "/appendix%20notes.md#details"
        expected = ('Готово: [вывод](%s), '
                    '[приложение](%s "Данные проверки"), '
                    '[повтор приложения](%s).') % (
                        local_link, attachment_link, attachment_link)
        self.assert_index_links(root, source, result, expected, [
            ("#result", local_link),
            ("appendix%20notes.md#details", attachment_link),
            (".//appendix%20notes.md#details", attachment_link),
        ])


if __name__ == "__main__":
    unittest.main()
