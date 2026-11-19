"""test_trace.py — проверки T1–T2 чекера lipi: метки @trace и расхождение. — lipi: ignore-trace

T1 — ошибка (код 1): метка указывает на несуществующий якорь. T2 —
предупреждение (код 0) на --staged/--diff: код под меткой изменён, а раздел
описания нет; или раздел описания системы изменён, а страница справки с
covers нет. Маркер ищет support.found().

Запуск: python3 -m unittest discover -s tests -p "test_trace.py" -v
"""
import unittest

from tests import support


# @trace docs/ru/codes.md#t1,ADR-013
class TraceChecks(support.Case):
    """Метки @trace и расхождение кода с описанием (тип package)."""  # lipi: ignore-trace

    # --- T1: метки @trace -------------------------------------------------------  # lipi: ignore-trace

    def test_t1_tag_to_missing_page(self):
        """Метка на несуществующую страницу описания: ошибка T1."""
        root = self.project()
        support.w(root / "src" / "extra.py", "# %s nope.md#max-discount\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('no page nope.md', "нет страницы nope.md"), out)

    def test_t1_tag_to_missing_anchor(self):
        """Метка на страницу без такого якоря: ошибка T1."""
        root = self.project()
        support.w(root / "src" / "extra.py", "# %s docs/guide.md#nope\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('has no anchor "nope"', "нет якоря «nope»"), out)

    def test_t1_bare_anchor_rejected(self):
        """Один якорь без пути: T1, даже если он единственный."""
        root = self.project()
        support.w(root / "src" / "extra.py", "# %s max-discount\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('in the form path/page.md#anchor or TYPE-number', "неверная форма"), out)

    def test_t1_old_form_without_unique_anchor(self):
        """Старая форма, якоря нет: T1 требует страницу."""
        root = self.project()
        support.w(root / "src" / "extra.py", "# %s no-such-anchor\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('in the form path/page.md#anchor or TYPE-number', "неверная форма"), out)

    def test_t1_bad_form(self):
        """Мусор вместо пути и якоря: T1 о неверной форме."""
        root = self.project()
        support.w(root / "src" / "extra.py", "# %s !!!\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('expected a trace or link target', "неверная форма метки"), out)

    def test_t1_valid_tag_passes(self):
        """Метка @trace на существующий якорь (из seed): T1 не срабатывает."""  # lipi: ignore-trace
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T1"), out)

    # --- T2: расхождение кода и описания (--staged / --diff) --------------------

    # @trace docs/ru/codes.md#t2
    def test_t2_staged_code_change(self):
        """Изменён только код под меткой: предупреждение T2 (--staged)."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        support.sub(root / "src" / "order.py",
                    "def discount(o):", "def discount(o):\n    return 0")
        support.git(root, "add", "src/order.py")
        code, out = support.check(root, "--staged")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "T2"), out)

    def test_t2_diff_code_change(self):
        """Изменён только код под меткой: предупреждение T2 (--diff)."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        support.sub(root / "src" / "order.py",
                    "def discount(o):", "def discount(o):\n    return 0")
        support.git(root, "add", "src/order.py")
        support.commit(root, "код под меткой")
        code, out = support.check(root, "--diff", "HEAD~1...HEAD")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "T2"), out)

    def test_t2_code_and_section_changed(self):
        """Изменены и код, и раздел описания: T2 не срабатывает."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        support.sub(root / "src" / "order.py",
                    "def discount(o):", "def discount(o):\n    return 0")
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст.\n\nИзменено.")
        support.git(root, "add", "-A")
        code, out = support.check(root, "--staged")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T2"), out)

    def test_t2_clean_staged(self):
        """Без изменений --staged ничего не сообщает: T2 не срабатывает."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        code, out = support.check(root, "--staged")
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T2"), out)


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,ADR-013
class AppTraceChecks(support.Case):
    """Расхождение справки и описания системы в приложении (--type app)."""
    base_args = ("--type", "app")

    def target_project(self, target, kind):
        """Один и тот же target проверяем через метку и covers."""
        root = self.project()
        if kind == "T1":
            support.w(root / "src" / "extra.py", "# %s %s\ndef extra():\n    pass\n"
                      % (support.TAG, target))
        else:
            support.w(root / "docs" / "help.md",
                      "# Справка\n\n<!-- covers: %s -->\n" % target)
            support.sub(root / "docs" / "README.md", "| --- | --- |",
                        "| --- | --- |\n| Справка | [Справка](help.md) |")
        return root

    def assert_target_error(self, root, kind, message):
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, kind), out)
        self.assertFalse(support.found(out, "D6" if kind == "T1" else "T1"), out)
        self.assertIn(message, out)

    def test_targets_sections_and_work_numbers(self):
        """Обе связи разрешают разделы docs, AGENTS/.agents и номер работы."""
        for kind in ("T1", "D6"):
            for target in ("docs/guide.md#max-discount", "AGENTS.md#local-rule",
                           ".agents/local.md#local-rule", "PLN-001", "ISS-001"):
                with self.subTest(kind=kind, target=target):
                    root = self.target_project(target, kind)
                    for path in ("AGENTS.md", ".agents/local.md"):
                        existing = (root / path).read_text() if (root / path).exists() else "# Правила\n"
                        support.w(root / path, existing + '\n## Правило <a id="local-rule"></a>\n')
                    code, out = support.check(root)
                    self.assertEqual(code, 0, out)
                    self.assertFalse(support.found(out, kind), out)

    def test_targets_reject_paths_relative_to_docs(self):
        """Прежний путь от docs не ищется относительно каталога описания."""
        for kind in ("T1", "D6"):
            with self.subTest(kind=kind):
                self.assert_target_error(self.target_project("guide.md#max-discount", kind),
                                         kind, support.localized("no page guide.md", "нет страницы guide.md"))

    def test_targets_excluded_directories(self):
        """skip_dirs, управляемые правила и архив исключены для обеих связей."""
        for kind in ("T1", "D6"):
            for path in ("vendor/rule.md", ".agents/lipi/local.md", "work/history/local.md"):
                with self.subTest(kind=kind, path=path):
                    root = self.target_project(path + "#rule", kind)
                    (root / "workflow").rename(root / "work")
                    support.set_config(root, workflow="work", skip_dirs=["vendor"])
                    support.w(root / path, '# Правило <a id="rule"></a>\n')
                    self.assert_target_error(root, kind, support.localized("excluded", "исключ"))

    def test_target_errors_keep_configured_levels(self):
        """Общее разрешение целей сохраняет отдельные уровни T1 и D6."""
        for kind in ("T1", "D6"):
            with self.subTest(kind=kind):
                root = self.target_project("PLN-999", kind)
                support.set_config(root, codes={kind: "warning"})
                code, out = support.check(root)
                self.assertEqual(code, 0, out)
                self.assertIn(support.localized('[warning %s]', "[предупреждение %s]") % kind, out)
                support.set_config(root, codes={kind: "off"})
                code, out = support.check(root)
                self.assertEqual(code, 0, out)
                self.assertFalse(support.found(out, kind), out)

    def test_targets_workflow_disabled(self):
        """При workflow:null номер даёт свой код с объяснением."""
        for kind in ("T1", "D6"):
            with self.subTest(kind=kind):
                root = self.target_project("PLN-001", kind)
                support.set_config(root, workflow=None)
                self.assert_target_error(
                    root, kind, support.localized("workflow documents are disabled",
                                                  "рабочие материалы отключены"))

    def test_targets_ambiguous_anchor_or_number(self):
        """Повтор якоря вне docs и повтор номера не выбирают случайную цель."""
        for kind in ("T1", "D6"):
            for target in (".agents/local.md#rule", "PLN-001"):
                with self.subTest(kind=kind, target=target):
                    root = self.target_project(target, kind)
                    support.w(root / ".agents/local.md",
                              '# Правило <a id="rule"></a>\n\n## Дубль <a id="rule"></a>\n')
                    if target == "PLN-001":
                        support.w(support.doc(root, "pln").parent / "pln-001-copy.md",
                                  support.doc(root, "pln").read_text())
                    self.assert_target_error(root, kind, support.localized("ambiguous", "неоднознач"))

    def test_targets_number_not_found_in_archive(self):
        """Архив не разрешает номер и не создаёт дубль активного номера."""
        for kind in ("T1", "D6"):
            with self.subTest(kind=kind):
                root = self.target_project("PLN-001", kind)
                plan = support.doc(root, "pln")
                archived = root / "workflow/history" / plan.name
                support.w(archived, plan.read_text())
                code, out = support.check(root)
                self.assertEqual(code, 0, out)
                plan.unlink()
                self.assert_target_error(root, kind, "PLN-001")

    # @trace docs/ru/codes.md#t2
    def test_t2_external_section_and_work_number(self):
        """T2 видит внешние разделы и их covers, но не номера работ."""
        for target in (".agents/local.md#rule", "PLN-001"):
            with self.subTest(target=target):
                root = self.target_project(target, "D6")
                support.w(root / ".agents/local.md", '# Правило <a id="rule"></a>\n\nТекст.\n')
                support.w(root / "src/extra.py", "# %s %s\ndef extra():\n    return 0\n"
                          % (support.TAG, target))
                support.git_init(root)
                support.commit(root)
                support.sub(root / "src/extra.py", "return 0", "return 1")
                support.git(root, "add", "src/extra.py")
                code, out = support.check(root, "--staged")
                self.assertEqual(code, 0, out)
                self.assertEqual(support.found(out, "T2"), "#" in target, out)
                support.commit(root)
                page = root / ".agents/local.md" if "#" in target else support.doc(root, "pln")
                support.w(page, page.read_text() + "\nИзменено.\n")
                support.git(root, "add", str(page.relative_to(root)))
                code, out = support.check(root, "--staged")
                self.assertEqual(code, 0, out)
                self.assertEqual(support.found(out, "T2"), "#" in target, out)
                if "#" in target:
                    self.assertIn(support.localized('reference page', "страница справки"), out)

    def test_t2_descr_section_changed(self):
        """Раздел описания системы изменён, а страница справки нет: предупреждение T2."""
        root = self.project()
        support.w(root / "docs" / "help.md",
                  "# Справка\n\n<!-- covers: docs/development/README.md#processes -->\n")
        support.sub(root / "docs" / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Справка | [Справка](help.md) |")
        support.git_init(root)
        support.commit(root)
        support.sub(root / "docs" / "development" / "README.md",
                    support.localized('## Processes <a id="processes"></a>', "## Процессы <a id=\"processes\"></a>"),
                    support.localized('## Processes <a id="processes"></a>\n\nИзменено.', "## Процессы <a id=\"processes\"></a>\n\nИзменено."))
        support.git(root, "add", "docs/development/README.md")
        code, out = support.check(root, "--staged")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "T2"), out)
        self.assertIn(support.localized('reference page', "страница справки"), out)


if __name__ == "__main__":
    unittest.main()
