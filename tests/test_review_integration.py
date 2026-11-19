"""Проверка одной отметки сквозь audit, slice и неизменённый T2."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import support


# @trace docs/ru/review.md#summary,docs/ru/review.md#pair
class ReviewIntegration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-review-integration-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def prepare_project(self, *, nested=False):
        repository = self.base / 'repo'
        self.root = repository / 'project' if nested else repository
        self.root.mkdir(parents=True)
        support.w(self.root / 'lipi.json', '{"workflow": null}\n')
        support.w(self.root / 'docs/README.md', '# Описание\n\n[Правило](api.md#rule)\n')
        support.w(self.root / 'docs/api.md', '# Договор\n\n## Правило <a id="rule"></a>\n\nВерно.\n')
        self.code = ('# %s docs/api.md#rule\ndef first():\n    return 0\n\n'
                     '# %s docs/api.md#rule\ndef second():\n    return 10\n') % (support.TAG, support.TAG)
        support.w(self.root / 'src/code.py', self.code)
        support.git_init(repository)
        self.assertEqual(support.commit(repository, date='2026-01-01T00:00:00+00:00')[0], 0)
        support.w(self.root / 'src/code.py', self.code.replace('return 0', 'return 1').replace('return 10', 'return 11'))
        self.assertEqual(support.commit(repository, date='2026-01-02T00:00:00+00:00')[0], 0)

    def cli_json(self, *arguments, expected=0):
        code, output = support.cli(self.root, *arguments, '--format', 'json')
        self.assertEqual(code, expected, output)
        return json.loads(output)

    def acknowledge(self, line):
        args = ('review', 'docs/api.md#rule', '--at', 'src/code.py:%d' % line)
        preview = self.cli_json(*args)
        return self.cli_json(*args, '--confirm', preview['token'], '--by', 'tester',
                             '--reason', 'Изменена внутренняя реализация, правило остаётся верным.')

    def test_one_pair_filters_audit_and_slice_before_budget_without_hiding_second(self):
        self.prepare_project()
        self.assert_audit_and_slice_review_one_pair()

    def test_nested_project_audit_and_slice_review_the_same_pair(self):
        self.prepare_project(nested=True)
        self.assert_audit_and_slice_review_one_pair()

    def assert_audit_and_slice_review_one_pair(self):
        self.acknowledge(1)
        audit = self.cli_json('audit')
        self.assertEqual(audit['summary']['reviewed_pairs'], 1)
        self.assertEqual(audit['summary']['reviewed_obsolete'], 0)
        self.assertEqual(sum(row['code'] == 'A4' for row in audit['warnings']), 1)
        support.set_config(self.root, slice_budget=1, codes={'A4': 'error'})
        sliced = self.cli_json('slice', 'docs/api.md#rule', '--only', 'tests')
        self.assertEqual(sliced['checks']['staleness'], {'state': 'full', 'checked': 2, 'total': 2})
        self.assertEqual(sliced['summary']['reviewed_pairs'], 1)
        self.assertEqual(sliced['summary']['errors'], 1)
        audited = self.cli_json('audit', '--no-baseline', expected=1)
        self.assertEqual(sum(row['code'] == 'A4' for row in audited['errors']), 1)
        self.assertEqual(audited['summary']['reviewed_pairs'], 1)

    def test_review_does_not_filter_t2_or_count_disabled_a4(self):
        self.prepare_project()
        self.acknowledge(1)
        self.acknowledge(5)
        checked = self.cli_json('check', '--diff', 'HEAD~1')
        self.assertTrue(any(row['code'] == 'T2' for row in checked['warnings']))
        self.assertEqual(checked['summary']['reviewed_pairs'], 0)
        support.set_config(self.root, codes={'A4': 'off'})
        audit = self.cli_json('audit')
        self.assertEqual(audit['summary']['reviewed_pairs'], 0)
        self.assertEqual(audit['summary']['reviewed_obsolete'], 0)
        self.assertEqual(audit['summary']['reviewed_unchecked'], 0)

    def test_repository_slice_retains_local_review_counter(self):
        self.prepare_project()
        self.acknowledge(1)
        neighbor = self.root.parent / 'neighbor'
        support.w(neighbor / 'lipi.json', '{"workflow": null}\n')
        support.w(neighbor / 'docs/README.md', '# Описание\n')
        support.git_init(neighbor)
        self.assertEqual(support.commit(neighbor)[0], 0)
        support.set_config(self.root, repos={'neighbor': {'path': '../neighbor', 'read': ['docs']}})
        sliced = self.cli_json('slice', 'docs/api.md#rule')
        self.assertEqual(sliced['summary']['reviewed_pairs'], 1)
        self.assertEqual(sliced['summary']['warnings'], 1)
        self.assertEqual(sliced['checks']['staleness']['checked'], 2)

    def test_unavailable_repository_slice_reports_zero_reviewed_pairs(self):
        self.prepare_project()
        from lipi.checker.reviews import ALGORITHM, REVIEWS_NAME
        support.w(self.root / REVIEWS_NAME,
                  json.dumps({'schema': 1, 'algorithm': ALGORITHM, 'entries': []}))
        support.set_config(self.root, repos={'neighbor': {'path': '../missing', 'read': ['docs']}})
        sliced = self.cli_json('slice', 'neighbor::docs/api.md#rule')
        self.assertEqual(sliced['summary']['reviewed_pairs'], 0)
        code, output = support.cli(self.root, 'slice', 'neighbor::docs/api.md#rule')
        self.assertEqual(code, 0, output)
        self.assertIn(support.localized('staleness pairs reviewed: 0', 'просмотрено пар устаревания: 0'), output)
