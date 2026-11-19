"""test_collect.py — тесты сбора замечаний к lipi (src/lipi/collect.py).

В setUp разворачивается проект с замечанием, адресованным lipi, и готовится
копия lipi с пустыми рабочими материалами. collect.py всегда запускается
из копии, чтобы не писать в настоящий lipi.
"""
import datetime
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.support import localized


class CollectTest(unittest.TestCase):
    """collect.py: перенос замечаний с адресатом lipi в копию lipi."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-collect-"))
        self.project = self.tmp / "пример-проекта"
        self.project.mkdir()
        code, out = support.init(self.project)
        self.assertEqual(code, 0, out)
        support.seed(self.project)
        code, out = support.check(self.project, "new", "iss", "Правило мешает",
                                  "friction", "lipi")
        self.assertEqual(code, 0, out)
        issue = support.doc(self.project, "iss", "002")
        self.assertIn("- Recipient: lipi", issue.read_text(encoding="utf-8"))
        self.vc = self.tmp / "lipicopy"
        support.lipi_copy(self.vc)
        shutil.rmtree(self.vc / "workflow")
        (self.vc / "workflow").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def collect(self, *roots):
        """collect.py из копии lipi — чтобы не писать в настоящий lipi."""
        return support.run(support.PY + [str(self.vc / "src" / "lipi" / "collect.py")]
                           + [str(r) for r in roots])

    def test_collects_addressed_issue(self):
        """Замечание с адресатом lipi переносится в копию под новым номером."""
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('New issues: 1', "новых замечаний: 1"), out)
        self.assertIn(localized('collected: external d2796a ISS-002 → ', "забрано: external d2796a ISS-002 → "), out)
        self.assertNotIn(self.project.name, out)
        files = list((self.vc / "workflow" / "issue").rglob("iss-001-*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.name, str(datetime.date.today().year))
        text = files[0].read_text(encoding="utf-8")
        self.assertEqual([line for line in text.splitlines()
                          if line.startswith("- Source: ")],
                         ["- Source: external d2796a ISS-002"])
        self.assertNotIn(self.project.name, text)
        self.assertIn("- Kind: friction", text)
        self.assertNotIn("Recipient", text)
        self.assertIn("## Observation", text)
        index = (self.vc / "workflow" / "index/issues.md").read_text(encoding="utf-8")
        self.assertIn("ISS-001", index)

    def test_no_duplicates_on_second_run(self):
        """Повторный запуск уже забранное замечание не дублирует."""
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('New issues: 0', "новых замечаний: 0"), out)
        self.assertNotIn(self.project.name, out)
        self.assertEqual(len(list((self.vc / "workflow" / "issue").rglob("*.md"))), 1)

    def test_skips_issues_without_addressee(self):
        """Замечание без адресата lipi остаётся в проекте."""
        code, out = support.check(self.project, "new", "iss", "Чужое замечание", "bug")
        self.assertEqual(code, 0, out)
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('New issues: 1', "новых замечаний: 1"), out)
        files = list((self.vc / "workflow" / "issue").rglob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("Чужое замечание", files[0].read_text(encoding="utf-8"))

    def test_source_is_deduplicated_across_years(self):
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        issue = next((self.vc / "workflow" / "issue").rglob("iss-001-*.md"))
        older = issue.parent.parent / "2024" / issue.name
        older.parent.mkdir(parents=True, exist_ok=True)
        issue.rename(older)
        text = older.read_text(encoding="utf-8").replace(
            "- Created: " + datetime.date.today().isoformat(),
            "- Created: 2024-01-01")
        older.write_text(text, encoding="utf-8")
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('New issues: 0', "новых замечаний: 0"), out)
        self.assertEqual(len(list((self.vc / "workflow" / "issue").rglob("iss-*.md"))), 1)

    def test_number_reserves_both_archives_and_feedback(self):
        for relative, number in (("workflow/history", 20), ("history", 30),
                                 (".agents/lipi-feedback", 40)):
            with self.subTest(relative=relative):
                support.w(self.vc / relative / ("iss-%03d-old.md" % number),
                          "archived data is not parsed\n")
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        self.assertTrue(list((self.vc / "workflow" / "issue").rglob("iss-041-*.md")))

    def test_copy_creation_date_is_today(self):
        issue = support.doc(self.project, "iss", "002")
        text = issue.read_text(encoding="utf-8").replace(
            "- Created: " + datetime.date.today().isoformat(),
            "- Created: 2024-01-01")
        issue.write_text(text, encoding="utf-8")
        code, out = self.collect(self.project)
        self.assertEqual(code, 0, out)
        copy = next((self.vc / "workflow" / "issue").rglob("iss-001-*.md"))
        self.assertEqual(copy.parent.name, str(datetime.date.today().year))
        self.assertIn("- Created: " + datetime.date.today().isoformat(),
                      copy.read_text(encoding="utf-8"))

    def test_broken_project_is_skipped(self):
        """Проект с невалидным lipi.json пропускается, остальные обрабатываются."""
        broken = self.tmp / "broken"
        broken.mkdir()
        support.w(broken / "lipi.json", "{")
        code, out = self.collect(broken, self.project)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('cannot read project settings', "настройки не читаются"), out)
        self.assertIn(localized('New issues: 1', "новых замечаний: 1"), out)


if __name__ == "__main__":
    unittest.main()
