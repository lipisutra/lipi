"""test_languages.py — языковые редакции описания: L1–L3, D4, метки.

Без ключа `languages` поведение прежнее: описание — один каталог `docs`.
С ключом `languages` страницы пары — один относительный путь внутри редакций,
каталог описания — редакция по умолчанию. Проверяется:

- L1 — страница есть в одной редакции, а в обязательной (`required`) её нет;
- L2 — у пары страниц разные наборы явных якорей;
- D4 — недостижимая страница в редакции: от `README.md` этой редакции;
- L3 — ссылка между редакциями ведёт не на парную страницу; ссылка внутри
  редакции, внешняя и якорная не трогаются;
- путь в метке `@trace` от корня разрешается в любой редакции;
- C1 — неверный `default`, типы, `required` и конфликт с `docs`.

Запуск: python3 -m unittest discover -s tests -p "test_languages.py" -v
"""
import json
import unittest

from tests import support

EN, RU = "en", "ru"
# Редакция ru повторяет относительные пути и явные якоря редакции en.
RU_README = ("# Документация\n\n## С чего начать <a id=\"start\"></a>\n\n"
             "## Найти по вопросу <a id=\"by-question\"></a>\n\n"
             "| Вопрос | Страница |\n| --- | --- |\n"
             "| Скидки | [Скидки](guide.md#max-discount) |\n")
RU_GUIDE = "# Скидки\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nТекст.\n"


def write_config(root, cfg):
    support.w(root / "lipi.json", json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


class LanguagesCase(support.Case):
    """Проект-пакет, переведённый на две редакции: docs/en и docs/ru."""

    def editions(self, required=(EN,)):
        """Проект с редакциями; required=None — ключа required нет."""
        root = self.project()
        en, ru = root / "docs" / EN, root / "docs" / RU
        en.mkdir()
        for name in ("README.md", "guide.md"):
            (root / "docs" / name).rename(en / name)
        support.sub(root / "AGENTS.md", "docs/README.md", "docs/en/README.md")
        support.sub(root / "src" / "order.py", "docs/guide.md", "docs/en/guide.md")
        support.w(ru / "README.md", RU_README)
        support.w(ru / "guide.md", RU_GUIDE)
        cfg = json.loads((root / "lipi.json").read_text(encoding="utf-8"))
        cfg["languages"] = {"default": EN,
                            "editions": {EN: "docs/en", RU: "docs/ru"}}
        if required is not None:
            cfg["languages"]["required"] = list(required)
        cfg["docs"] = "docs/en"           # каталог редакции по умолчанию
        write_config(root, cfg)
        return root

    @staticmethod
    def link_into(page, target):
        """Добавляет в конец страницы ссылку с уникальным текстом."""
        support.sub(page, "Текст.", "Текст. [ссылка](%s)" % target)


class NoLanguages(support.Case):
    """Без ключа languages поведение прежнее."""

    def test_without_languages_no_l_codes(self):
        """Обычный проект из support.py: L1–L3 не срабатывают."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        for name in ("L1", "L2", "L3"):
            self.assertFalse(support.found(out, name), out)

    def test_without_languages_d4_single_index(self):
        """D4 по-прежнему от одного docs/README.md."""
        root = self.project()
        support.w(root / "docs" / "orphan.md", "# Сирота\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn(support.localized('unreachable from docs/README.md', 'недостижима из docs/README.md'), out)


class PairPages(LanguagesCase):
    """L1: страницы пары в обязательных редакциях; L2: явные якоря пары."""

    def test_clean_editions(self):
        """Обе редакции полные, якоря пары совпадают: L1–L3 молчат."""
        root = self.editions(required=(EN, RU))
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        for name in ("L1", "L2", "L3", "D4"):
            self.assertFalse(support.found(out, name), out)

    def test_decision_inside_an_edition_is_not_a_translation_or_cross_edition_link(self):
        root = self.editions(required=(EN, RU))
        support.set_config(root, decisions="docs/ru/adr")
        support.w(root / "docs/ru/adr/0001-rule.md",
                  '# Decision\n\n- Created: 2026-11-01\n'
                  '- Updated: 2026-11-01\n- Status: accepted\n\n'
                  '## Decision <a id="rule"></a>\n\nRule.\n')
        self.link_into(root / "docs/en/guide.md", "../ru/adr/0001-rule.md#rule")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        for check in ("L1", "L2", "L3", "D4"):
            self.assertFalse(support.found(out, check), out)

    def test_l1_missing_in_required_edition(self):
        """Страницы нет в обязательной редакции ru: ошибка L1 с её путём."""
        root = self.editions(required=(EN, RU))
        (root / "docs" / RU / "guide.md").unlink()
        support.sub(root / "docs" / RU / "README.md",
                    "| Скидки | [Скидки](guide.md#max-discount) |", "")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "L1"), out)
        self.assertIn(support.localized('page missing from required edition "ru"', 'нет страницы в обязательной редакции «ru»'), out)
        self.assertIn("docs/ru/guide.md", out)
        self.assertFalse(support.found(out, "L2"), out)

    def test_l1_optional_edition_without_page(self):
        """Редакция не обязательна: страница только в en — не ошибка."""
        root = self.editions()            # required — только en
        support.w(root / "docs" / EN / "extra.md",
                  "# Дополнительно\n\n## Раздел <a id=\"extra\"></a>\n")
        support.sub(root / "docs" / EN / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Дополнительно | [Дополнительно](extra.md#extra) |")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "L1"), out)

    def test_l1_required_omitted(self):
        """Ключа required нет: L1 не срабатывает, страницы не обязательны."""
        root = self.editions(required=None)
        (root / "docs" / RU / "guide.md").unlink()
        support.sub(root / "docs" / RU / "README.md",
                    "| Скидки | [Скидки](guide.md#max-discount) |", "")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "L1"), out)

    def test_l2_anchor_sets_differ(self):
        """У пары разные наборы явных якорей: ошибка L2 с обоими отличиями."""
        root = self.editions()
        support.sub(root / "docs" / RU / "guide.md", 'id="max-discount"', 'id="skidki"')
        support.sub(root / "docs" / RU / "README.md",
                    "guide.md#max-discount", "guide.md#skidki")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "L2"), out)
        self.assertIn(support.localized('anchors differ from edition "en"', 'разошлись с редакцией «en»'), out)
        self.assertIn(support.localized('"max-discount"', "«max-discount»"), out)
        self.assertIn(support.localized('"skidki"', "«skidki»"), out)
        self.assertIn("docs/ru/guide.md", out)


class EditionReach(LanguagesCase):
    """D4: у каждой редакции свой указатель README.md."""

    def test_d4_unreachable_in_edition(self):
        """Страница вне указателя своей редакции: D4 этой редакции."""
        root = self.editions(required=(RU,))
        support.w(root / "docs" / RU / "orphan.md", "# Сирота\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn("docs/ru/orphan.md", out)
        self.assertIn(support.localized('unreachable from docs/ru/README.md', 'недостижима из docs/ru/README.md'), out)
        self.assertFalse(support.found(out, "L1"), out)

    def test_d4_missing_index_in_edition(self):
        """В редакции ru нет README.md: D4 с путём редакции."""
        root = self.editions()
        (root / "docs" / RU / "README.md").unlink()
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn(support.localized('missing README.md index', 'нет указателя README.md'), out)
        self.assertIn("docs/ru", out)


class EditionLinks(LanguagesCase):
    """L3: между редакциями — только на парную страницу."""

    def test_l3_pair_links_pass(self):
        """Ссылки на парные страницы в обе стороны: L3 молчит."""
        root = self.editions()
        self.link_into(root / "docs" / EN / "guide.md", "../ru/guide.md#max-discount")
        self.link_into(root / "docs" / RU / "guide.md", "../en/guide.md")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "L3"), out)

    def test_l3_other_page_in_edition(self):
        """С en на другую страницу ru: ошибка L3 с парным путём."""
        root = self.editions()
        self.link_into(root / "docs" / EN / "guide.md", "../ru/README.md")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "L3"), out)
        self.assertIn(support.localized('points to ../ru/README.md', 'не на парную страницу'), out)
        self.assertIn("docs/en/guide.md", out)
        self.assertIn(support.localized('matching page is docs/ru/guide.md', 'пара — docs/ru/guide.md'), out)

    def test_l3_reverse_other_page(self):
        """Обратное направление проверяется так же: ru → не парная страница en."""
        root = self.editions()
        self.link_into(root / "docs" / RU / "guide.md", "../en/README.md")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "L3"), out)
        self.assertIn("docs/ru/guide.md", out)

    def test_l3_inside_edition_not_checked(self):
        """Ссылка внутри своей редакции — обычная D1, не L3."""
        root = self.editions()
        self.link_into(root / "docs" / EN / "guide.md", "README.md")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "L3"), out)

    def test_l3_external_and_anchor_ignored(self):
        """Внешние ссылки и якоря на своей странице — не межредакционные."""
        root = self.editions()
        page = root / "docs" / EN / "guide.md"
        support.sub(page, "Текст.",
                    "Текст. [внешняя](https://example.com/x) [якорь](#max-discount)")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "L3"), out)


class TraceInDefaultEdition(LanguagesCase):
    """Метка @trace: путь от корня проекта в любой редакции."""

    def test_trace_resolves_in_default_edition(self):
        """Метка на страницу редакции по умолчанию разрешается: T1 молчит."""
        root = self.editions()
        support.w(root / "src" / "extra.py",
                  "# %s docs/en/guide.md#max-discount\ndef f():\n    return 0\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T1"), out)

    def test_trace_page_without_pair(self):
        """Страница есть только в редакции по умолчанию: метка разрешается."""
        root = self.editions()
        support.w(root / "docs" / EN / "only-en.md",
                  "# Только en\n\n## Раздел <a id=\"only\"></a>\n")
        support.sub(root / "docs" / EN / "README.md", "| --- | --- |",
                    "| --- | --- |\n| Только en | [Только en](only-en.md#only) |")
        support.w(root / "src" / "extra.py",
                  "# %s docs/en/only-en.md#only\ndef f():\n    return 0\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T1"), out)

    def test_trace_other_edition_passes(self):
        """Метка от корня на другую редакцию разрешается."""
        root = self.editions()
        support.w(root / "src" / "extra.py",
                  "# %s docs/ru/guide.md#max-discount\ndef f():\n    return 0\n"
                  % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "T1"), out)

    def test_trace_missing_page_in_default_edition(self):
        """Метка на отсутствующую страницу редакции по умолчанию: ошибка T1."""
        root = self.editions()
        support.w(root / "src" / "extra.py",
                  "# %s nope.md#x\ndef f():\n    return 0\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn(support.localized('no page nope.md', 'нет страницы nope.md'), out)


class LanguagesConfig(support.Case):
    """C1: схема ключа languages."""

    def config(self, languages, docs="docs"):
        """Проект с заданным ключом languages (docs можно убрать: docs=None)."""
        root = self.project()
        cfg = json.loads((root / "lipi.json").read_text(encoding="utf-8"))
        cfg["languages"] = languages
        if docs is None:
            cfg.pop("docs", None)
        else:
            cfg["docs"] = docs
        write_config(root, cfg)
        return root

    def assert_c1(self, root, text):
        code, out = support.check(root)
        self.assertEqual(code, 2, out)
        self.assertTrue(support.found(out, "C1"), out)
        self.assertIn(text, out)

    def test_c1_default_not_in_editions(self):
        """default не из editions: C1 с подсказкой ближайшей редакции."""
        root = self.config({"default": "en", "editions": {RU: "docs/ru"}})
        self.assert_c1(root, support.localized('edition "en" is missing from "editions"', 'редакции «en» нет в «editions»'))

    def test_c1_required_unknown(self):
        """required называет редакцию не из editions: C1."""
        root = self.config({"default": EN, "editions": {EN: "docs/en"},
                            "required": [RU]})
        self.assert_c1(root, support.localized('edition "ru" is missing from "editions"', 'редакции «ru» нет в «editions»'))

    def test_c1_unknown_key_hint(self):
        """Опечатка в ключе languages: C1 с подсказкой difflib."""
        root = self.config({"default": EN, "editions": {EN: "docs/en"},
                            "require": [EN]})
        self.assert_c1(root, support.localized('did you mean "required"', 'имелось в виду «required»'))

    def test_c1_docs_conflict(self):
        """docs не совпадает с редакцией по умолчанию: C1."""
        root = self.config({"default": EN,
                            "editions": {EN: "docs/en", RU: "docs/ru"}})
        self.assert_c1(root, support.localized('set "docs" to the default edition directory', 'каталог описания — каталог редакции по умолчанию'))

    def test_c1_wrong_values(self):
        """Неверные типы и значения languages: C1 и код 2."""
        cases = [
            ([], support.localized('expected an object', 'ожидается объект')),
            ({"default": 1, "editions": {EN: "docs/en"}}, support.localized('"default": expected a string', '«default»: ожидается строка')),
            ({"default": EN, "editions": ["docs/en"]}, support.localized('"editions": expected a "language: directory" object', '«editions»: ожидается объект')),
            ({"default": EN, "editions": {}}, support.localized('empty object', 'пустой объект')),
            ({"default": EN, "editions": {EN: 1}}, support.localized('expected a string', 'ожидается строка')),
            ({"default": EN, "editions": {EN: ""}}, support.localized('empty path', 'пустой путь')),
            ({"default": EN, "editions": {EN: "docs/en", RU: "docs/en"}},
             support.localized('share a directory', 'один каталог')),
            ({"default": EN, "editions": {EN: "docs/en", RU: "docs/en/ru"}},
             support.localized('is inside', 'вложен в')),
            ({"default": EN, "editions": {EN: ".", RU: "docs/ru"}},
             support.localized('is inside', 'вложен в')),
            ({"default": EN, "editions": {EN: "docs/en"}, "required": "en"},
             support.localized('"required": expected a list', '«required»: ожидается список')),
            ({"default": EN, "editions": {EN: "docs/en"}, "required": [1]},
             support.localized('item 1: expected a string', 'элемент 1: ожидается строка')),
        ]
        for languages, text in cases:
            with self.subTest(languages=languages):
                root = self.config(languages)
                self.assert_c1(root, text)

    def test_c1_docs_must_match_default_edition(self):
        """docs не задан: C1 — задайте каталог редакции по умолчанию."""
        root = self.config({"default": EN,
                            "editions": {EN: "docs/en", RU: "docs/ru"}},
                           docs=None)
        self.assert_c1(root, support.localized('set "docs" to the default edition directory', 'задайте его в «docs»'))


if __name__ == "__main__":
    unittest.main()
