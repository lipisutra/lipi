"""Подсказка похожих открытых замечаний после lipi new iss."""

import json

from tests.support import Case, cli, git_init, set_config, w
from tests.support import localized


class TestSimilarIssues(Case):
    seed_project = False

    def issue(self, root, num, title, status="open", directory="workflow/issue/2024"):
        path = root / directory / ("iss-%03d-example.md" % num)
        w(path, "# %s\n\n- Created: 2024-01-01\n- Updated: 2024-01-01\n"
          "- Status: %s\n- Closed: 2024-02-01\n\n## Observation\n\nПример.\n"
          % (title, status))
        return path

    def new_json(self, root, title, *args):
        code, out = cli(root, "new", "iss", title, *args, "--format", "json")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertTrue((root / data["path"]).is_file())
        return data

    def test_unicode_casefold_punctuation_and_repeated_words(self):
        root = self.project()
        self.issue(root, 1, "Ошибка: СОХРАНЕНИЯ, ошибка!")
        self.issue(root, 2, "STRASSE сохранения")
        data = self.new_json(root, "ошибка_сохранения")
        self.assertEqual(data["similar"], [{
            "id": "ISS-001", "path": "workflow/issue/2024/iss-001-example.md",
            "title": "Ошибка: СОХРАНЕНИЯ, ошибка!", "status": "open"}])
        data = self.new_json(root, "Straße сохранения")
        self.assertEqual([item["id"] for item in data["similar"]], ["ISS-002"])

    def test_fixed_threshold_and_short_word_filter(self):
        cases = [
            ("ошибка загрузки", "ошибка загрузки файла данных", True),
            ("ошибка загрузки", "ошибка загрузки файла данных проекта", False),
            ("ошибка загрузки", "ошибка сохранения", False),
            ("ошибка", "ошибка загрузки", False),
            ("ошибка", "ОШИБКА!", True),
            ("ошибка на", "ошибка в", True),
            ("на до", "на до", False),
            ("на до файла", "на до данных", False),
            ("ошибка загрузки", "ошибки загрузки", False),
            ("", "", False),
        ]
        for title, candidate, expected in cases:
            with self.subTest(title=title, candidate=candidate):
                root = self.project()
                self.issue(root, 1, candidate)
                result = self.new_json(root, title)
                self.assertEqual(bool(result["similar"]), expected)

    def test_ranking_then_id_and_five_results(self):
        root = self.project()
        self.issue(root, 1, "ошибка загрузки")
        self.issue(root, 2, "ошибка загрузки файла")
        for num in (9, 8, 7, 6, 5, 4, 3):
            self.issue(root, num, "ошибка загрузки файла данных")
        data = self.new_json(root, "ошибка загрузки файла данных")
        self.assertEqual([item["id"] for item in data["similar"]],
                         ["ISS-003", "ISS-004", "ISS-005", "ISS-006", "ISS-007"])
        root = self.project()
        self.issue(root, 1, "ошибка загрузки")
        self.issue(root, 2, "ошибка загрузки файла")
        self.issue(root, 3, "ошибка загрузки файла данных")
        data = self.new_json(root, "ошибка загрузки файла данных")
        self.assertEqual([item["id"] for item in data["similar"]],
                         ["ISS-003", "ISS-002", "ISS-001"])

    def test_only_open_issues_excludes_history_and_other_document_types(self):
        root = self.project()
        title = "ошибка загрузки"
        for num, status in enumerate(("open", "in progress", "closed", "rejected", ""), 1):
            self.issue(root, num, title, status)
        self.issue(root, 6, title, directory="workflow/history/issue")
        w(root / "workflow/plan/2024/pln-001-example.md", "# %s\n\n- Status: in progress\n" % title)
        data = self.new_json(root, title)
        self.assertEqual([(item["id"], item["status"]) for item in data["similar"]],
                         [("ISS-001", "open"), ("ISS-002", "in progress")])

    def test_gitignored_and_config_skipped_issues_excluded(self):
        root = self.project()
        git_init(root)
        title = "ошибка загрузки"
        self.issue(root, 1, title)
        self.issue(root, 2, title, directory=".agents/lipi-feedback")
        self.issue(root, 3, title)
        w(root / ".gitignore", "workflow/issue/2024/iss-001-*\n")
        set_config(root, skip_dirs=["lipi-feedback"])
        data = self.new_json(root, title)
        self.assertEqual([item["id"] for item in data["similar"]], ["ISS-003"])

    def test_feedback_and_workflow_share_candidates(self):
        root = self.project()
        title = "ошибка загрузки"
        self.issue(root, 1, title)
        self.issue(root, 2, title, directory=".agents/lipi-feedback")
        data = self.new_json(root, title)
        self.assertEqual(data["id"], "ISS-003")
        self.assertEqual([item["id"] for item in data["similar"]], ["ISS-001", "ISS-002"])
        self.assertTrue(data["index_updated"])
        self.assertIn("ISS-003", (root / "workflow/index/issues.md").read_text())

    def test_feedback_without_workflow(self):
        root = self.project()
        set_config(root, workflow=None)
        self.issue(root, 1, "ошибка загрузки", directory=".agents/lipi-feedback")
        data = self.new_json(root, "ошибка загрузки", "friction", "lipi")
        self.assertFalse(data["index_updated"])
        self.assertEqual([item["id"] for item in data["similar"]], ["ISS-001"])

    def test_text_hint_only_when_similar_and_creation_succeeds(self):
        root = self.project()
        title = "ошибка загрузки"
        code, out = cli(root, "new", "iss", title)
        self.assertEqual(code, 0, out)
        self.assertNotIn(localized('Similar open issues', "Похожие"), out)
        code, out = cli(root, "new", "iss", title)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Similar open issues (check whether the work is already tracked):',
                                "Похожие открытые замечания (проверьте, нет ли уже нужной работы):"), out)
        self.assertIn("ISS-001 — ошибка загрузки (workflow/issue/", out)
        self.assertEqual(len(list((root / "workflow/issue").glob("[0-9][0-9][0-9][0-9]/iss-*.md"))), 2)

    def test_json_empty_and_other_new_types_unchanged(self):
        root = self.project()
        self.assertEqual(self.new_json(root, "ошибка загрузки")["similar"], [])
        code, out = cli(root, "new", "pln", "ошибка загрузки", "--format", "json")
        self.assertEqual(code, 0, out)
        self.assertEqual(set(json.loads(out)), {"id", "path", "index_updated"})
