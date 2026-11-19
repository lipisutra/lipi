"""Годовые работы в общих потребителях ID, путей и Git diff."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests import support


# @trace ADR-020,docs/ru/slice.md#target,docs/ru/map.md#rows
class YearlyConsumers(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='lipi-year-consumers-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'project'
        self.root.mkdir()
        support.w(self.root / 'lipi.json', '{}\n')
        self.plan = 'workflow/plan/2024/pln-101-change.md'
        self.audit = 'workflow/audit/2025/aud-201-report/aud-201-readme.md'
        self.document(self.plan, 'new')
        self.document(self.audit, None, '2025-01-01')
        self.document('workflow/discussion/2024/dsc-301-choice.md', 'open')
        self.document('workflow/adr/adr-401-choice.md', 'accepted', body=
                      '[Обсуждение](../discussion/2024/dsc-301-choice.md)\n')
        self.write('docs/guide.md', '# Guide\n\n## Rule <a id="rule"></a>\n\nText.\n')
        self.write('src/feature.py', '# %s PLN-101\ndef feature():\n    return 0\n' % support.TAG)
        self.write('src/audit.py', '# %s AUD-201\ndef report():\n    return 0\n' % support.TAG)
        self.write('src/path.py', '# %s %s#scope\ndef scope():\n    return 0\n' % (support.TAG, self.plan))

    def write(self, path, text):
        support.w(self.root / path, text)

    def document(self, path, status, created='2024-01-01', body=''):
        header = '- Status: %s\n' % status if status else ''
        self.write(path, '# Work\n\n- Created: %s\n- Updated: %s\n%s\n'
                   '## Scope <a id="scope"></a>\n\nText.\n%s' % (created, created, header, body))

    def command(self, *args, expected=0):
        code, output = support.cli(self.root, *args, '--format', 'json')
        self.assertEqual(code, expected, output)
        return json.loads(output)

    @staticmethod
    def items(result, kind):
        return [item for block in result.get('blocks', []) if block['kind'] == kind
                for item in block['items']]

    def test_slice_id_path_anchor_and_map_share_yearly_identity(self):
        for query, kind in (('PLN-101', 'work'), ('AUD-201', 'work'),
                            (self.plan, 'page'), (self.plan + '#scope', 'section')):
            with self.subTest(query=query):
                result = self.command('slice', query, '--full')
                self.assertEqual(result['target']['target'], query)
                self.assertEqual(result['target']['kind'], kind)
        rows = {item['target']: item for item in self.command('map')['rows']}
        for target in ('PLN-101', 'AUD-201', self.plan + '#scope'):
            self.assertEqual(rows[target]['code'], {'src': 1})
        old = self.command('slice', 'workflow/plan/pln-101-change.md', expected=1)
        self.assertEqual(old['error'], 'not-found')

    def test_duplicate_years_are_ambiguous_and_attachment_is_only_a_page(self):
        self.document('workflow/plan/2025/pln-101-other.md', 'new', '2025-01-01')
        attachment = 'workflow/audit/2025/aud-201-report/pln-999-not-a-work.md'
        self.document(attachment, 'new', '2025-01-01')
        result = self.command('slice', 'PLN-101', expected=1)
        self.assertEqual(result['error'], 'ambiguous')
        self.assertEqual({item['target'] for item in result['candidates']},
                         {self.plan, 'workflow/plan/2025/pln-101-other.md'})
        self.assertEqual(self.command('slice', 'PLN-999', expected=1)['error'], 'not-found')
        self.assertEqual(self.command('slice', attachment)['target']['kind'], 'page')

    # @trace docs/ru/slice-diff.md#selection
    def test_move_preserves_id_and_diff_resolves_rewritten_yearly_anchor(self):
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root, 'baseline')[0], 0)
        new_path = 'workflow/plan/2024/pln-101-renamed.md'
        code, output = support.cli(self.root, 'mv', self.plan, new_path, '--apply')
        self.assertEqual(code, 0, output)
        self.assertIn(new_path + '#scope', (self.root / 'src/path.py').read_text())
        self.assertEqual(self.command('slice', self.plan, expected=1)['error'], 'not-found')
        self.assertEqual(self.command('slice', 'PLN-101')['target']['kind'], 'work')
        self.assertEqual(self.command('slice', new_path)['target']['kind'], 'page')
        support.sub(self.root / 'src/feature.py', 'return 0', 'return 1')
        result = self.command('slice', '--diff', 'HEAD', '--full')
        targets = {item.get('target') for block in result.get('blocks', [])
                   for item in block['items']}
        self.assertIn(new_path + '#scope', targets)
        self.assertIn('PLN-101', targets)
        self.assertEqual(result['checks']['diff']['files'], 2)

    # @trace docs/ru/codes.md#a1,docs/ru/codes.md#a7
    def test_audit_and_structure_use_yearly_main_files(self):
        code, result = support.check_json(self.root, '--audit', '--structure')
        self.assertNotEqual(code, 2, result)
        findings = result['errors'] + result['warnings']
        self.assertTrue(any(item['code'] == 'A1' and item['file'] == self.plan for item in findings))
        self.assertTrue(any(item['code'] == 'A7' and item['subject'] == 'dsc-301' for item in findings))
        self.assertFalse(any(item['code'] in ('T1', 'W10', 'W11') for item in findings), findings)
        nodes = {item['id']: item for item in result['structure']['nodes']}
        self.assertEqual(nodes['PLN-101']['path'], self.plan)
        self.assertEqual(nodes['AUD-201']['path'], self.audit)

    # @trace docs/ru/settings.md#repos,docs/ru/codes.md#t4,ADR-016
    def test_neighbor_other_major_is_unavailable_even_with_t4_off(self):
        neighbor = self.root.parent / 'neighbor'
        support.w(neighbor / 'lipi.json', '{}\n')
        support.w(neighbor / 'docs/rule.md', '# Rule <a id="rule"></a>\n\nText.\n')
        support.w(neighbor / support.LOCK_REL, json.dumps({'lipi': support.VERSION, 'files': {}}))
        support.set_config(self.root, codes={'T4': 'off'}, repos={
            'neighbor': {'path': '../neighbor', 'read': ['docs', 'decisions']}})
        self.write('src/neighbor.py', '# %s neighbor::docs/rule.md#rule\nvalue = 1\n' % support.TAG)
        result = self.command('slice', 'neighbor::docs/rule.md#rule')
        self.assertEqual(result['target']['target'], 'docs/rule.md#rule')
        major = int(support.VERSION.split('.')[0])
        incompatible = '%d.0.0' % (major + 1)
        support.w(neighbor / support.LOCK_REL, json.dumps({'lipi': incompatible, 'files': {}}))
        result = self.command('slice', 'src/neighbor.py')
        self.assertTrue(result['incomplete'])
        source = next(item for item in result['checks']['repos'] if item['repo'] == 'neighbor')
        self.assertEqual(source['state'], 'unavailable')
        self.assertIn(incompatible, source['reason'])

    def test_neighbor_archives_never_become_map_or_slice_context(self):
        neighbor = self.root.parent / 'neighbor'
        support.w(neighbor / 'lipi.json', json.dumps({'docs': '.', 'decisions': 'decisions'}))
        for path in ('history/old.md', 'decisions/history/adr-501-old.md',
                     'workflow/history/plan/pln-501-old.md'):
            support.w(neighbor / path, '# Archive <a id="scope"></a>\n\nOld.\n')
        support.w(neighbor / 'guide.md', '# Guide\n\nText.\n')
        support.set_config(self.root, repos={
            'neighbor': {'path': '../neighbor', 'read': ['docs', 'decisions']}})
        rows = self.command('map')['rows']
        self.assertFalse(any('history/' in item['target'] for item in rows), rows)
        from lipi.checker.config import load_config
        from lipi.checker.model import Project
        source = Project(self.root, load_config(self.root, None)).sources.get('neighbor')
        for path in ('history/old.md', 'decisions/history/adr-501-old.md',
                     'workflow/history/plan/pln-501-old.md'):
            self.assertIsNone(source.resolve_path(path), path)


if __name__ == '__main__':
    unittest.main()
