"""test_feedback.py — замечания к lipi без рабочих материалов (.agents/lipi-feedback/).

При `"workflow": null` команда
`new iss … lipi` пишет замечание в `.agents/lipi-feedback/`; чекер проверяет
такие файлы как замечания (W1, W2, W3, W4, W6, W8), в указатель они не входят,
а `src/lipi/collect.py` забирает их наравне с `workflow/issue/`.

Запуск из корня lipi:
    python3 -m unittest discover -s tests -p "test_feedback.py" -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

FEEDBACK = ".agents/lipi-feedback"

# Правильно оформленное замечание к lipi: шапка и оба раздела заполнены.
GOOD_ISSUE = """# Замечание

- Created: 2026-01-01
- Updated: 2026-01-01
- Status: open
- Kind: friction
- Recipient: lipi

## Observation

Текст.

## Как воспроизвести или где встретилось

Текст.
"""


def feedback(root):
    """Каталог замечаний к lipi в проекте."""
    return root / FEEDBACK


def feedback_doc(root, num="001"):
    """Файл замечания в .agents/lipi-feedback/ с номером."""
    return next(feedback(root).glob("iss-%s-*.md" % num))


class NewFeedbackTests(support.Case):
    """`new` при отключённых материалах: замечание к lipi и прежние отказы."""

    def no_workflow(self):
        root = self.project()
        support.set_config(root, workflow=None)
        return root

    def new(self, root, *args):
        return support.check(root, "new", *args)

    def test_new_issue_lipi_writes_feedback(self):
        """new iss … трение lipi при workflow: null создаёт файл с той же шапкой."""
        root = self.no_workflow()
        code, out = self.new(root, "iss", "Правило мешает", "friction", "lipi")
        self.assertEqual(code, 0, out)
        text = feedback_doc(root).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Правило мешает\n"), text)
        for line in ("- Created: ", "- Updated: ",
                     "- Status: open", "- Kind: friction", "- Recipient: lipi"):
            self.assertIn(line, text)
        self.assertIn("## Observation", text)
        self.assertIn(support.localized('## How to reproduce or where it occurred', "## Как воспроизвести или где встретилось"), text)
        self.assertIn(support.localized('fill in the "Observation" section', "заполните раздел «Observation»"), out)
        self.assertIn(support.localized('created .agents/lipi-feedback/iss-001-', "создан .agents/lipi-feedback/iss-001-"), out)
        self.assertFalse(list((root / "workflow" / "issue").rglob("iss-*-pravilo-meshaet.md")), out)

    def test_new_issue_without_lipi_refused(self):
        """new iss без адресата lipi при workflow: null по-прежнему отказывает."""
        root = self.no_workflow()
        code, out = self.new(root, "iss", "Без адресата", "bug")
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('workflow documents are disabled in this project', "рабочие материалы в этом проекте не подключены"), out)
        self.assertFalse(feedback(root).exists())

    def test_new_plan_refused(self):
        """new pln при workflow: null отказывает с прежним объяснением."""
        root = self.no_workflow()
        code, out = self.new(root, "pln", "План")
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized('workflow documents are disabled in this project', "рабочие материалы в этом проекте не подключены"), out)
        self.assertFalse(feedback(root).exists())

    def test_new_issue_lipi_goes_to_workflow(self):
        """При подключённых материалах new iss … lipi пишет в workflow/issue/."""
        root = self.project()
        code, out = self.new(root, "iss", "Правило мешает", "friction", "lipi")
        self.assertEqual(code, 0, out)
        p = support.doc(root, "iss", "002")
        self.assertIn("- Recipient: lipi", p.read_text(encoding="utf-8"))
        self.assertFalse(feedback(root).exists())

    def test_numbers_common_with_feedback(self):
        """Очередной номер учитывает и workflow/issue/, и .agents/lipi-feedback/."""
        root = self.project()
        support.w(feedback(root) / "iss-002-iz-feedback.md", GOOD_ISSUE)
        code, out = self.new(root, "iss", "Третье замечание", "bug")
        self.assertEqual(code, 0, out)
        self.assertTrue(support.doc(root, "iss", "003"), out)
        self.assertTrue((feedback(root) / "iss-002-iz-feedback.md").is_file())

    def test_feedback_dir_created_on_demand(self):
        """Каталог .agents/lipi-feedback/ появляется только с первым замечанием."""
        root = self.no_workflow()
        self.assertFalse(feedback(root).exists())
        self.assertEqual(self.new(root, "iss", "Правило", "friction", "lipi")[0], 0)
        self.assertTrue(feedback(root).is_dir())

    def test_feedback_numbers_do_not_overlap(self):
        """Два new в feedback получают разные номера, W2 молчит."""
        root = self.no_workflow()
        self.assertEqual(self.new(root, "iss", "Первое", "bug", "lipi")[0], 0)
        self.assertEqual(self.new(root, "iss", "Второе", "friction", "lipi")[0], 0)
        nums = sorted(p.name.split("-")[1] for p in feedback(root).glob("iss-*.md"))
        self.assertEqual(nums, ["001", "002"])
        code, out = support.check(root)     # W8: разделы ещё пусты
        self.assertFalse(support.found(out, "W2"), out)


class FeedbackCheckTests(support.Case):
    """Чекер: файлы .agents/lipi-feedback/ проверяются как замечания."""

    def no_workflow(self):
        root = self.project()
        support.set_config(root, workflow=None)
        return root

    def test_w1_bad_name(self):
        """W1: имя в feedback не по формату iss-NNN-imya.md."""
        root = self.no_workflow()
        support.w(feedback(root) / "zamechanie.md", GOOD_ISSUE)
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W1"), out)

    def test_w1_wrong_type(self):
        """W1: в каталоге замечаний к lipi лежит не замечание."""
        root = self.no_workflow()
        support.w(feedback(root) / "pln-001-ne-tuda.md", "# План\n")
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W1"), out)

    def test_w1_not_a_file(self):
        """W1: в каталоге замечаний к lipi лежит подкаталог."""
        root = self.no_workflow()
        (feedback(root) / "notes").mkdir(parents=True)
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W1"), out)

    def test_w3_bad_header(self):
        """W3: у замечания в feedback нет строки «Вид»."""
        root = self.no_workflow()
        support.w(feedback(root) / "iss-001-bez-vida.md",
                  GOOD_ISSUE.replace("- Kind: friction\n", ""))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W3"), out)

    def test_w4_closed_without_result(self):
        """W4: замечание в feedback «закрыто», а «Итог» не записан."""
        root = self.no_workflow()
        support.w(feedback(root) / "iss-001-zakryto.md",
                  GOOD_ISSUE.replace("- Status: open", "- Status: closed"))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W4"), out)

    def test_w6_broken_link(self):
        """W6: битая ссылка в замечании из feedback."""
        root = self.no_workflow()
        support.w(feedback(root) / "iss-001-ssylka.md",
                  GOOD_ISSUE.replace("Текст.\n\n## Как", "[x](net.md)\n\n## Как"))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W6"), out)

    def test_w8_empty_observed(self):
        """W8: у открытого замечания в feedback пуст «Что наблюдается»."""
        root = self.no_workflow()
        support.w(feedback(root) / "iss-001-pustoe.md",
                  GOOD_ISSUE.replace("## Observation\n\nТекст.\n", "## Observation\n"))
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W8"), out)

    def test_valid_feedback_clean(self):
        """Правильно оформленное замечание в feedback не ловится."""
        root = self.no_workflow()
        support.w(feedback(root) / "iss-002-zam.md", GOOD_ISSUE)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        for found in ("W1", "W2", "W3", "W4", "W6", "W8"):
            self.assertFalse(support.found(out, found), out)

    def test_w2_same_number_in_both_places(self):
        """W2: один номер и в workflow/issue/, и в .agents/lipi-feedback/."""
        root = self.project()
        support.w(feedback(root) / "iss-001-dubl.md", GOOD_ISSUE)
        code, out = support.check(root)
        self.assertTrue(support.found(out, "W2"), out)
        self.assertIn("ISS-001", out)

    def test_index_ignores_feedback(self):
        """Указатель собирается без feedback-файлов, W7 молчит."""
        root = self.project()
        support.w(feedback(root) / "iss-002-iz-feedback.md", GOOD_ISSUE)
        code, out = support.reindex(root)
        self.assertEqual(code, 0, out)
        index = (root / "workflow" / "INDEX.md").read_text(encoding="utf-8")
        self.assertNotIn("ISS-002", index)
        self.assertNotIn("lipi-feedback", index)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W7"), out)

    def test_w5_sees_feedback_id(self):
        """W5: мастер-план может ссылаться на замечание из feedback."""
        root = self.project()
        support.w(feedback(root) / "iss-002-iz-feedback.md", GOOD_ISSUE)
        support.sub(root / "workflow" / "masterplan.md",
                    support.localized('## Now', "## Сейчас"), support.localized('## Now\n\nISS-002', "## Сейчас\n\nISS-002"))
        self.assertEqual(support.reindex(root)[0], 0)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "W5"), out)


class CollectFeedbackTests(unittest.TestCase):
    """collect.py: замечание из .agents/lipi-feedback/ собирается как из workflow."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-feedback-"))
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

    def project(self, name="пример-проекта", workflow=None):
        root = self.tmp / name
        root.mkdir()
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        if workflow is None:
            support.set_config(root, workflow=None)
        code, out = support.check(root, "new", "iss", "Правило мешает", "friction", "lipi")
        self.assertEqual(code, 0, out)
        return root

    def test_collects_from_feedback(self):
        """Замечание из .agents/lipi-feedback/ переносится в копию lipi."""
        project = self.project()
        code, out = self.collect(project)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('New issues: 1', "новых замечаний: 1"), out)
        self.assertIn(support.localized('collected: external d2796a ISS-001 → ', "забрано: external d2796a ISS-001 → "), out)
        self.assertNotIn(project.name, out)
        files = list((self.vc / "workflow" / "issue").glob("[0-9][0-9][0-9][0-9]/iss-001-*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertEqual([line for line in text.splitlines()
                          if line.startswith("- Source: ")],
                         ["- Source: external d2796a ISS-001"])
        self.assertNotIn(project.name, text)
        self.assertIn("- Kind: friction", text)
        self.assertNotIn("Recipient", text)
        self.assertIn("## Observation", text)

    def test_no_duplicates_on_second_run(self):
        """Повторный запуск замечание из feedback не дублирует."""
        project = self.project()
        self.assertEqual(self.collect(project)[0], 0)
        code, out = self.collect(project)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('New issues: 0', "новых замечаний: 0"), out)
        self.assertNotIn(project.name, out)
        self.assertEqual(len(list((self.vc / "workflow" / "issue").glob("[0-9][0-9][0-9][0-9]/*.md"))), 1)

    def test_same_as_workflow_issue(self):
        """Замечание из проекта с материалами и из feedback собирается одинаково."""
        wf = self.project("with-workflow", workflow="workflow")
        fb = self.project("without-workflow")
        code, out = self.collect(wf, fb)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('New issues: 2', "новых замечаний: 2"), out)
        texts = [p.read_text(encoding="utf-8")
                 for p in sorted((self.vc / "workflow" / "issue").glob("[0-9][0-9][0-9][0-9]/*.md"))]
        self.assertEqual(len(texts), 2)
        sources = sorted(line for text in texts for line in text.split("\n")
                         if line.startswith("- Source: "))
        self.assertEqual(sources, ["- Source: external 240498 ISS-001",
                                  "- Source: external 4ef858 ISS-001"])
        for project in (wf, fb):
            self.assertNotIn(project.name, out)
            for text in texts:
                self.assertNotIn(project.name, text)
        normalized = ["\n".join("- Source: <источник>" if s.startswith("- Source: ") else s
                                for s in text.split("\n")) for text in texts]
        self.assertEqual(normalized[0], normalized[1])


if __name__ == "__main__":
    unittest.main()
