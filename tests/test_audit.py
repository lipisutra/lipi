"""test_audit.py — проверки A1–A5: расширенный аудит (--audit).

Каждый тест берёт копию «правильного» проекта из support.Case (init + seed
один раз на класс) и ломает что-то одно; у каждого кода есть обе стороны:
нарушение, которое аудит обязан поймать, и чистый проект без этого кода.

Запуск из корня lipi:
    python3 -m unittest discover -s tests -p "test_audit.py" -v
"""
import datetime
import unittest

from tests import support


class AuditTests(support.Case):
    """A1–A4: план pln-001, замечание iss-001 и метка из support.seed."""

    # --- A1: залежавшиеся работы ------------------------------------------------

    def test_a1_stale_active_plan(self):
        """A1: план «в работе» без движения дольше срока."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "in progress",
                                         "Updated": "2000-01-01"})
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A1"), out)

    def test_a1_plan_waiting_review(self):
        """A1: план «на приёмке» дольше срока."""
        root = self.project()
        support.header_set(root, "pln", {"Status": "pending acceptance",
                                         "Updated": "2000-01-01"})
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A1"), out)

    def test_a1_stale_issue(self):
        """A1: замечание «в работе» дольше срока."""
        root = self.project()
        support.header_set(root, "iss", {"Status": "in progress",
                                         "Updated": "2000-01-01"})
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A1"), out)

    def test_a1_fresh_project(self):
        """A1 не срабатывает: свежие даты в правильном проекте."""
        code, out = support.check(self.project(), "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A1"))

    # --- A2: размер рабочего документа -------------------------------------------

    def test_a2_long_work_doc(self):
        """A2: рабочий документ длиннее 600 строк."""
        root = self.project()
        p = support.doc(root, "pln")
        support.w(p, p.read_text(encoding="utf-8") + "строка\n" * 700)
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A2"), out)

    def test_a2_short_work_doc(self):
        """A2 не срабатывает: короткий документ."""
        code, out = support.check(self.project(), "--audit")
        self.assertFalse(support.found(out, "A2"), out)

    # --- A3: точка входа без метки ------------------------------------------------

    def test_a3_entry_without_tag(self):
        """A3: точка входа без метки @trace в пределах трёх строк выше."""  # lipi: ignore-trace
        root = self.project()
        support.set_config(root, entry=["def entry"])
        support.w(root / "src" / "app.py", "def entry_point():\n    return 1\n")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A3"), out)

    def test_a3_tag_above_entry(self):
        """A3 не срабатывает: над точкой входа стоит метка @trace."""
        root = self.project()
        support.set_config(root, entry=["def entry"])
        support.w(root / "src" / "app.py",
                  "# %s docs/guide.md#max-discount\ndef entry_point():\n    return 1\n" % support.TAG)
        code, out = support.check(root, "--audit")
        self.assertFalse(support.found(out, "A3"), out)

    def test_a3_test_files_ignored(self):
        """A3 не срабатывает: тестовые файлы исключены из аудита."""
        root = self.project()
        support.set_config(root, entry=["def entry"])
        support.w(root / "src" / "test_app.py", "def entry_point():\n    return 1\n")
        support.w(root / "tests" / "app.py", "def entry_point():\n    return 1\n")
        code, out = support.check(root, "--audit")
        self.assertFalse(support.found(out, "A3"), out)

    # --- A4: код под меткой менялся позже описания -------------------------------

    def test_a4_code_newer_than_doc(self):
        """A4: код под меткой закоммичен позже раздела описания."""
        root = self.project()
        support.git_init(root)
        support.commit(root, date="2026-01-01T10:00:00")
        support.sub(root / "src" / "order.py", "return max(o)", "return max(o) + 1")
        support.commit(root, date="2026-01-03T10:00:00")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Изменено.")
        support.commit(root, date="2026-01-02T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A4"), out)
        self.assertIn("2026-01-03", out)
        self.assertIn("2026-01-02", out)

    def test_a4_code_older_than_doc(self):
        """A4 не срабатывает: код закоммичен раньше описания."""
        root = self.project()
        support.git_init(root)
        support.commit(root, date="2026-01-01T10:00:00")
        support.sub(root / "src" / "order.py", "return max(o)", "return max(o) + 1")
        support.commit(root, date="2026-01-01T10:00:00")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Изменено.")
        support.commit(root, date="2026-01-03T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A4"))

    def test_a4_move_region_then_change_function(self):
        """Перенос небольшой функции не старит описание, изменение функции — старит."""
        root = self.project()
        source = root / "src/order.py"
        region = source.read_text()
        helper = "def total(items):\n    return sum(items)\n\n"
        support.w(source, helper + region)
        support.git_init(root)
        self.assertEqual(support.commit(root, date="2026-01-01T09:00:00+00:00")[0], 0)
        support.sub(root / "docs/guide.md", "Текст.", "Текст. Проверено.")
        self.assertEqual(support.commit(root, date="2026-01-01T10:00:00+00:00")[0], 0)
        _, doc_commit = support.git(root, "rev-parse", "--short", "HEAD")

        # Исходный файл остаётся: это перенос региона, а не переименование файла.
        support.w(source, helper)
        moved = root / "src/discount.py"
        support.w(moved, region)
        self.assertEqual(support.commit(root, date="2026-01-01T11:00:00+00:00")[0], 0)
        with self.subTest(stage="move"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertFalse(support.found(out, "A4"), out)

        support.sub(moved, "return max(o)", "return max(o) + 1")
        self.assertEqual(support.commit(root, date="2026-01-01T12:00:00+00:00")[0], 0)
        _, code_commit = support.git(root, "rev-parse", "--short", "HEAD")
        with self.subTest(stage="semantic change"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertTrue(support.found(out, "A4"), out)
            self.assertIn("src/discount.py", out)
            # Даты совпадают: сообщение должно показывать, какое изменение новее.
            for hour, revision in (("10", doc_commit), ("12", code_commit)):
                timestamp = "2026-01-01T%s:00:00" % hour
                self.assertTrue(any(value in out for value in
                                    (timestamp + "Z", timestamp + "+00:00", revision.strip())), out)

    def test_a4_new_marker_then_semantic_change(self):
        """Новая метка не меняет код под ней; последующая правка тела даёт A4."""
        root = self.project()
        source = root / "src/order.py"
        marked = source.read_text()
        support.w(source, marked.split("\n", 1)[1])
        support.git_init(root)
        self.assertEqual(support.commit(root, date="2026-01-01T09:00:00+00:00")[0], 0)
        support.sub(root / "docs/guide.md", "Текст.", "Текст. Проверено.")
        self.assertEqual(support.commit(root, date="2026-01-01T10:00:00+00:00")[0], 0)
        support.w(source, marked)
        self.assertEqual(support.commit(root, date="2026-01-01T11:00:00+00:00")[0], 0)
        with self.subTest(stage="new marker"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertFalse(support.found(out, "A4"), out)

        support.sub(source, "return max(o)", "return max(o) + 1")
        self.assertEqual(support.commit(root, date="2026-01-01T12:00:00+00:00")[0], 0)
        with self.subTest(stage="semantic change"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertTrue(support.found(out, "A4"), out)

    def test_a4_inline_marker_keeps_code_on_same_line(self):
        """Код перед inline-меткой входит в регион и его изменение даёт A4."""
        root = self.project()
        source = root / "src/order.py"
        support.w(source, "def discount(o):\n    return max(o)  # %s docs/guide.md#max-discount\n"
                  % support.TAG)
        support.git_init(root)
        self.assertEqual(support.commit(root, date="2026-01-01T09:00:00+00:00")[0], 0)
        support.sub(root / "docs/guide.md", "Текст.", "Текст. Проверено.")
        self.assertEqual(support.commit(root, date="2026-01-01T10:00:00+00:00")[0], 0)
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A4"), out)

        support.sub(source, "return max(o)", "return max(o) + 1")
        self.assertEqual(support.commit(root, date="2026-01-01T11:00:00+00:00")[0], 0)
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "A4"), out)
        self.assertIn("src/order.py", out)

    def test_a4_whitespace_then_semantic_change(self):
        """Пробелы не дают A4; смысловая правка того же небольшого региона даёт."""
        root = self.project()
        support.git_init(root)
        self.assertEqual(support.commit(root, date="2026-01-01T09:00:00+00:00")[0], 0)
        support.sub(root / "docs/guide.md", "Текст.", "Текст. Проверено.")
        self.assertEqual(support.commit(root, date="2026-01-01T10:00:00+00:00")[0], 0)
        support.sub(root / "src/order.py", "max(o)", "max( o )")
        self.assertEqual(support.commit(root, date="2026-01-01T11:00:00+00:00")[0], 0)
        with self.subTest(stage="whitespace"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertFalse(support.found(out, "A4"), out)

        support.sub(root / "src/order.py", "max( o )", "max( o ) + 1")
        self.assertEqual(support.commit(root, date="2026-01-01T12:00:00+00:00")[0], 0)
        with self.subTest(stage="semantic change"):
            code, out = support.check(root, "--audit")
            self.assertEqual(code, 0, out)
            self.assertTrue(support.found(out, "A4"), out)

    def test_a4_external_section_but_not_work_number(self):
        """A4 сравнивает внешний раздел с кодом; номер работы не устаревает."""
        for target in (".agents/local.md#rule", "PLN-001"):
            with self.subTest(target=target):
                root = self.project()
                support.w(root / ".agents/local.md", '# Правило <a id="rule"></a>\n\nТекст.\n')
                support.w(root / "src/extra.py", "# %s %s\ndef extra():\n    return 0\n"
                          % (support.TAG, target))
                support.git_init(root)
                support.commit(root, date="2026-01-01T10:00:00")
                support.sub(root / "src/extra.py", "return 0", "return 1")
                support.commit(root, date="2026-01-03T10:00:00")
                code, out = support.check(root, "--audit")
                self.assertEqual(code, 0, out)
                self.assertEqual(support.found(out, "A4"), "#" in target, out)
                if "#" in target:
                    support.sub(root / ".agents/local.md", "Текст.", "Новый текст.")
                    support.commit(root, date="2026-01-04T10:00:00")
                    code, out = support.check(root, "--audit")
                    self.assertEqual(code, 0, out)
                    self.assertFalse(support.found(out, "A4"), out)

    # --- A5: статус отстал от коммитов -------------------------------------------

    @staticmethod
    def _date(offset):
        """Дата сегодня + offset дней; вблизи сегодняшней, чтобы не звякал A1."""
        return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()

    def test_a5_new_plan_commits_after_update(self):
        """A5 «работа идёт»: план «новый», коммиты с его ID после даты обновления."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "pln", {"Status": "new",
                                         "Created": self._date(-4),
                                         "Updated": self._date(-3)})
        support.reindex(root)
        support.commit(root, "PLN-001: начинаю", date=self._date(-2) + "T10:00:00")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Ещё.")
        support.commit(root, "PLN-001: продолжаю", date=self._date(-1) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A5"), out)
        self.assertIn(support.localized('work is underway, but the status has not been updated', "работа идёт, статус не обновлён"), out)
        self.assertIn(support.localized('commits after %s: 2', "2 коммита после %s") % self._date(-3), out)
        code, last = support.git(root, "log", "-1", "--format=%h")
        self.assertEqual(code, 0, last)
        self.assertIn(last.strip(), out)

    def test_a5_deferred_plan_commits_after_update(self):
        """A5 «работа идёт»: план «отложен», коммит с его ID после даты обновления."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "pln", {"Status": "deferred",
                                         "Created": self._date(-4),
                                         "Updated": self._date(-3)})
        support.reindex(root)
        support.commit(root, "PLN-001: всё же делаем", date=self._date(-2) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A5"), out)
        self.assertIn(support.localized('work is underway, but the status has not been updated', "работа идёт, статус не обновлён"), out)
        self.assertIn(support.localized('commits after %s: 1', "1 коммит после %s") % self._date(-3), out)

    def test_a5_finished_plan_commits_continue(self):
        """A5 «работа закрыта»: план «завершён» с итогом, коммиты с ID продолжаются."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "pln", {"Status": "completed",
                                         "Created": self._date(-4),
                                         "Updated": self._date(-3)})
        support.sub(support.doc(root, "pln"), "- Status: completed",
                    "- Status: completed\n- Result: сделано")
        support.reindex(root)
        support.commit(root, "PLN-001: постскриптум", date=self._date(-2) + "T10:00:00")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Ещё.")
        support.commit(root, "pln-001: ещё", date=self._date(-1) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A5"), out)
        self.assertIn(support.localized('the work item is closed, but commits continue', "работа закрыта, коммиты продолжаются"), out)
        self.assertIn(support.localized('commits after %s: 2', "2 коммита после %s") % self._date(-3), out)

    def test_a5_closed_issue_commits_continue(self):
        """A5 «работа закрыта»: замечание «закрыто» с итогом, коммит с ID позже."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "iss", {"Status": "closed",
                                         "Created": self._date(-4),
                                         "Updated": self._date(-3)})
        support.sub(support.doc(root, "iss"), "- Status: closed",
                    "- Status: closed\n- Result: исправлено")
        support.reindex(root)
        support.commit(root, "ISS-001: казалось бы", date=self._date(-2) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A5"), out)
        self.assertIn(support.localized('the work item is closed, but commits continue', "работа закрыта, коммиты продолжаются"), out)

    def test_a5_word_boundary(self):
        """A5: ID — отдельное слово без учёта регистра: PLN-0011 не за PLN-001."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "pln", {"Created": self._date(-4),
                                         "Updated": self._date(-3)})
        support.reindex(root)
        support.commit(root, "PLN-0011: другой номер", date=self._date(-2) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertFalse(support.found(out, "A5"), out)
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Ещё.")
        support.commit(root, "pln-001: этот считается", date=self._date(-1) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertTrue(support.found(out, "A5"), out)
        self.assertIn(support.localized('commits after %s: 1', "1 коммит после %s") % self._date(-3), out)

    def test_a5_commits_before_update_date(self):
        """A5 нет: коммиты с ID в день даты обновления и раньше не считаются."""
        root = self.project()
        support.git_init(root)
        support.header_set(root, "pln", {"Created": self._date(-5),
                                         "Updated": self._date(-2)})
        support.reindex(root)
        support.commit(root, "PLN-001: в тот же день", date=self._date(-2) + "T10:00:00")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст. Ещё.")
        support.commit(root, "PLN-001: днём раньше", date=self._date(-3) + "T10:00:00")
        code, out = support.check(root, "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A5"), out)

    def test_a5_without_git(self):
        """A5 нет и ошибок нет: корень проекта — не git-репозиторий."""
        code, out = support.check(self.project(), "--audit")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "A5"), out)


if __name__ == "__main__":
    unittest.main()
