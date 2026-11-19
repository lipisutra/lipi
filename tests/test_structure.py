"""test_structure.py — граф структуры (--format json --structure) и цепочка устаревания (--staged).
"""
import unittest

from tests.support import (
    Case, TAG, check_json, commit, doc, git, git_init, localized, set_config, sub, w,
)


class StructureGraphCase(Case):
    """Граф структуры проекта, наполненного support.seed."""

    def test_structure_basic_graph(self):
        """Базовая структура: узлы doc/anchor/code/work, рёбра trace/anchor/link, counts."""
        root = self.project()
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        st = data["structure"]
        ids = {n["id"]: n["type"] for n in st["nodes"]}
        self.assertEqual(ids.get("docs/guide.md"), "doc")
        self.assertEqual(ids.get("docs/guide.md#max-discount"), "anchor")
        self.assertEqual(ids.get("src/order.py"), "code")
        self.assertTrue(any(n["type"] == "work" for n in st["nodes"]))
        edges = st["edges"]
        self.assertTrue(any(e["type"] == "trace" and e["from"] == "src/order.py"
                            and e["to"] == "docs/guide.md#max-discount" for e in edges))
        self.assertTrue(any(e["type"] == "anchor" and e["from"] == "docs/guide.md#max-discount"
                            and e["to"] == "docs/guide.md" for e in edges))
        self.assertTrue(any(e["type"] == "link" and e["from"] == "docs/README.md"
                            and e["to"] == "docs/guide.md"
                            and e.get("anchor") == "docs/guide.md#max-discount" for e in edges))
        counts = st["counts"]
        self.assertGreater(counts["nodes"], 0)
        self.assertGreater(counts["edges"], 0)
        self.assertIn("nodeTypes", counts)
        self.assertIn("edgeTypes", counts)
        for key in ("doc", "anchor", "code", "work"):
            self.assertIn(key, counts["nodeTypes"])
        for key in ("trace", "anchor", "link"):
            self.assertIn(key, counts["edgeTypes"])

    def test_structure_masterplan_ref(self):
        """Строка «PLN-001» в «## Сейчас» мастер-плана даёт ребро ref."""
        root = self.project()
        sub(root / "workflow" / "masterplan.md", localized('## Now', "## Сейчас"), localized('## Now\n\nPLN-001', "## Сейчас\n\nPLN-001"))
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        self.assertTrue(any(e["type"] == "ref" and e["from"] == "workflow/masterplan.md"
                            and e["to"] == "PLN-001"
                            for e in data["structure"]["edges"]))

    def test_structure_work_link(self):
        """Ссылка рабочего документа идёт от ID работы и попадает в counts."""
        root = self.project()
        plan = doc(root, "pln")
        sub(plan, "## Purpose", "## Purpose\n\n[раздел](../../../docs/guide.md#max-discount)")
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        self.assertTrue(any(e["type"] == "link" and e["from"] == "PLN-001"
                            and e["to"] == "docs/guide.md"
                            and e.get("anchor") == "docs/guide.md#max-discount"
                            for e in data["structure"]["edges"]))
        counts = data["structure"]["counts"]
        self.assertGreaterEqual(counts["nodeTypes"].get("work", 0), 1)
        self.assertGreaterEqual(counts["edgeTypes"].get("link", 0), 1)

    def test_structure_absent_without_flag(self):
        """Без --structure в JSON нет ключа structure."""
        root = self.project()
        code, data = check_json(root)
        self.assertEqual(code, 0)
        self.assertNotIn("structure", data)


class CoversGraphCase(Case):
    """Ребро covers в графе приложения ведёт к узлу якоря описания системы."""

    base_args = ("--type", "app")

    def test_covers_edge_points_to_anchor_node(self):
        """covers полной формы: ребро covers -> узел «страница.md#якорь»."""
        root = self.project()
        w(root / "docs" / "help.md",
          "# Справка\n\n<!-- covers: docs/development/README.md#processes -->\n")
        sub(root / "docs" / "README.md", "| --- | --- |",
            "| --- | --- |\n| Справка | [Справка](help.md) |")
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0)
        st = data["structure"]
        ids = {n["id"]: n["type"] for n in st["nodes"]}
        self.assertEqual(ids.get("docs/development/README.md#processes"), "anchor")
        self.assertTrue(any(e["type"] == "covers" and e["from"] == "docs/help.md"
                            and e["to"] == "docs/development/README.md#processes"
                            for e in st["edges"]), st["edges"])
        # цели рёбер covers — существующие узлы, а не голые имена якорей
        dangling = [e for e in st["edges"] if e["type"] == "covers"
                    and e["to"] not in ids]
        self.assertEqual(dangling, [])

    def test_external_sections_and_work_targets(self):
        """Новые цели trace/covers существуют в графе и имеют стабильные ID."""
        root = self.project()
        targets = (".agents/local.md#rule", "architecture.md#rule", "PLN-001")
        for path in (".agents/local.md", "architecture.md"):
            w(root / path, '# Правило <a id="rule"></a>\n')
        w(root / "src/extra.py", "".join("# %s %s\n" % (TAG, target) for target in targets)
          + "def extra():\n    pass\n")
        w(root / "docs/help.md", "# Справка\n\n<!-- covers: %s -->\n" % ",".join(targets))
        sub(root / "docs/README.md", "| --- | --- |",
            "| --- | --- |\n| Справка | [Справка](help.md) |")
        code, data = check_json(root, "--structure")
        self.assertEqual(code, 0, data)
        graph = data["structure"]
        ids = {node["id"]: node["type"] for node in graph["nodes"]}
        self.assertEqual(ids[".agents/local.md"], "rules")
        self.assertEqual(ids["architecture.md"], "file")
        for target in targets:
            self.assertEqual(ids[target], "anchor" if "#" in target else "work")
            for kind, source in (("trace", "src/extra.py"), ("covers", "docs/help.md")):
                self.assertTrue(any(edge["type"] == kind and edge["from"] == source
                                    and edge["to"] == target for edge in graph["edges"]), graph)
        self.assertTrue(all(edge["from"] in ids and edge["to"] in ids
                            for edge in graph["edges"] if edge["type"] in ("trace", "covers")), graph)

    def test_stale_covers_goes_by_full_id(self):
        """Одинаковый якорь на двух страницах: stale по полному id находит
        только справку, которая указывает изменённую страницу."""
        tag = "@" + "trace"
        root = self.project()
        w(root / "docs" / "development" / "rules.md",
          "# Правила\n\n## Процессы <a id=\"processes\"></a>\n\nТекст.\n")
        sub(root / "docs" / "development" / "README.md",
            localized('## Processes', "## Процессы"), localized('- [Правила](rules.md)\n\n## Processes', "- [Правила](rules.md)\n\n## Процессы"))
        for name, target in (("help-first.md", "docs/development/README.md#processes"),
                             ("help-second.md", "docs/development/rules.md#processes")):
            w(root / "docs" / name,
              "# Справка\n\n<!-- covers: %s -->\n" % target)
            sub(root / "docs" / "README.md", "| --- | --- |",
                "| --- | --- |\n| %s | [%s](%s) |" % (name, name, name))
        w(root / "src" / "work.py",
          "# %s docs/development/rules.md#processes\ndef run():\n    pass\n" % tag)
        git_init(root)
        commit(root)
        sub(root / "src" / "work.py", "def run():", "def run():\n    return 1")
        git(root, "add", "src/work.py")
        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0)
        stale = [s for s in data["structure"]["stale"]
                 if s["anchor"] == "docs/development/rules.md#processes"]
        self.assertTrue(stale, data["structure"]["stale"])
        self.assertEqual(stale[0]["page"], "docs/development/rules.md")
        self.assertEqual(stale[0]["covers"], ["docs/help-second.md"])


class JsonOutputCase(Case):
    """Машинный вывод --format json: итог, ошибки и создание документа."""

    def test_json_clean_and_broken(self):
        """Чистый проект — 0 ошибок; битая ссылка — код 1 и ошибка D1 с путём."""
        root = self.project()
        code, data = check_json(root)
        self.assertEqual(code, 0)
        self.assertEqual(data["summary"]["errors"], 0)

        broken = self.project()
        w(broken / "docs" / "guide.md", "# X\n\n[a](nope.md)\n")
        code, data = check_json(broken)
        self.assertEqual(code, 1)
        self.assertTrue(any(i["code"] == "D1" and i["file"] == "docs/guide.md"
                            for i in data["errors"]))

    def test_json_new_flag_before_and_after_new(self):
        """--format json new: ID и путь документа при любом порядке флага."""
        root = self.project()
        code, data = check_json(root, "new", "pln", "План для JSON")
        self.assertEqual(code, 0)
        self.assertTrue(data["id"].startswith("PLN-"))
        self.assertTrue(data["path"].startswith("workflow/plan/"))

        root2 = self.project()
        code, data = check_json(root2, "new", "pln", "План до new", "--format", "json")
        self.assertEqual(code, 0)
        self.assertTrue(data["id"].startswith("PLN-"))
        self.assertTrue(data["path"].startswith("workflow/plan/"))


class StaleChainCase(Case):
    """Цепочка устаревания по проиндексированным изменениям (--staged)."""

    def test_stale_chain_from_staged_code(self):
        """Изменённый код под меткой даёт запись stale с работой и статусом."""
        root = self.project()
        plan = doc(root, "pln")
        sub(plan, "## Purpose", "## Purpose\n\n[раздел](../../../docs/guide.md#max-discount)")
        git_init(root)
        commit(root)
        sub(root / "src" / "order.py", "def discount(o):",
            "def discount(o):\n    return 0")
        git(root, "add", "src/order.py")
        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0)
        stale = data["structure"]["stale"]
        self.assertTrue(any(s["anchor"] == "docs/guide.md#max-discount" and s["file"] == "src/order.py"
                            and s["page"] == "docs/guide.md"
                            and any(wk["id"] == "PLN-001" and "status" in wk
                                    for wk in s["works"])
                            for s in stale))

    def test_stale_gone_when_code_and_section_changed(self):
        """Код и раздел изменены вместе: записи stale с якорем max-discount нет."""
        root = self.project()
        plan = doc(root, "pln")
        sub(plan, "## Purpose", "## Purpose\n\n[раздел](../../../docs/guide.md#max-discount)")
        git_init(root)
        commit(root)
        sub(root / "src" / "order.py", "def discount(o):",
            "def discount(o):\n    return 0")
        git(root, "add", "src/order.py")
        sub(root / "docs" / "guide.md", "Текст.", "Текст.\n\nИзменено.")
        git(root, "add", "docs/guide.md")
        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0)
        stale = data["structure"]["stale"]
        self.assertFalse(any(s["anchor"] == "docs/guide.md#max-discount" for s in stale))


if __name__ == "__main__":
    unittest.main()
