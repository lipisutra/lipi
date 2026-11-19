"""Map repository scope, counts, availability and read-only output (ADR-016)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.map import build_map, render_text


# @trace docs/ru/map.md#repos
class MapRepositories(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-map-repos-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.make_root('client')
        self.engine = self.make_root('engine')
        self.connect()

    def make_root(self, name, **config):
        root = self.base / name
        support.w(root / 'lipi.json', json.dumps(config) + '\n')
        return root

    def connect(self, read=('docs', 'decisions', 'code', 'tests'), **extra):
        repos = {'engine': {'path': '../engine', 'read': list(read)}}
        repos.update(extra)
        support.set_config(self.root, repos=repos)
        support.set_config(self.engine, repos={
            'application': {'path': '../client', 'read': ['docs', 'decisions']}})

    def page(self, root, path, *anchors):
        support.w(root / path, '# ' + path + '\n\n' + '\n'.join(
            '## %s <a id="%s"></a>\n\nText.\n' % (name, name) for name in anchors))

    def mark(self, root, path, *targets):
        support.w(root / path, ''.join('# %s %s\n' % (support.TAG, target)
                                      for target in targets) + 'value = 1\n')

    def decision(self, root, number=1, status='accepted'):
        path = 'workflow/adr/adr-%03d-choice.md' % number
        support.w(root / path, '# Choice\n\n- Status: ' + status +
                  '\n\n## One <a id="one"></a>\n\n## Two <a id="two"></a>\n')
        return path

    def result(self):
        return build_map(Project(self.root, load_config(self.root, None)))

    @staticmethod
    def rows(result):
        return {(row['repo'], row['target']): row for row in result['rows']}

    @staticmethod
    def column_labels():
        return support.localized(['Target', 'Title', 'Status'], ['Цель', 'Название', 'Статус'])

    @staticmethod
    def tests_column(repo=None):
        label = support.localized('Tests', 'Тесты')
        return repo + '::' + label if repo is not None else label

    def git_commit(self, root):
        support.git_init(root)
        code, output = support.commit(root)
        self.assertEqual(code, 0, output)
        return support.git(root, 'rev-parse', 'HEAD')[1].strip()

    def test_no_repos_and_empty_repos_keep_exact_previous_shape(self):
        self.page(self.root, 'docs/guide.md', 'one')
        self.mark(self.root, 'src/main.py', 'docs/guide.md#one')
        support.w(self.root / 'lipi.json', '{}\n')
        without = self.result()
        support.set_config(self.root, repos={})
        self.assertEqual(self.result(), without)
        self.assertEqual(set(without), {'schema', 'layers', 'rows', 'note'})
        self.assertNotIn('repo', without['rows'][0])

    def test_only_foreign_pages_marked_by_own_code_or_tests_expand(self):
        for name in ('marked', 'tested', 'linked', 'covered', 'unused'):
            self.page(self.engine, 'docs/' + name + '.md', 'one', 'two')
        self.page(self.root, 'docs/local.md', 'own')
        support.w(self.root / 'docs/navigation.md', '# Links\n\n'
                  '[Foreign](../../engine/docs/linked.md#one)\n'
                  '<!-- covers: engine::docs/covered.md#one -->\n')
        self.mark(self.root, 'src/main.py', 'engine::docs/marked.md#one')
        self.mark(self.root, 'tests/test_main.py', 'engine::docs/tested.md#one')
        result = self.result()
        rows = self.rows(result)
        self.assertEqual({key for key in rows if key[0] == 'engine'}, {
            ('engine', 'docs/marked.md#one'), ('engine', 'docs/marked.md#two'),
            ('engine', 'docs/tested.md#one'), ('engine', 'docs/tested.md#two')})
        self.assertEqual(rows['engine', 'docs/marked.md#one']['code']['src'], 1)
        self.assertEqual(rows['engine', 'docs/marked.md#two']['code']['src'], 0)
        self.assertEqual(rows['engine', 'docs/tested.md#one']['tests'], 1)
        self.assertIn((None, 'docs/local.md'), rows)

    def test_page_dirs_include_only_allowed_pages_marked_by_own_code(self):
        support.set_config(self.root, repos={'engine': {
            'path': '../engine', 'read': ['docs'], 'page_dirs': ['notes', 'notes/drafts']}})
        allowed = 'notes/drafts/guide.md'
        denied = 'private/guide.md'
        for path in (allowed, denied, 'notes/unused.md'):
            self.page(self.engine, path, 'one', 'two')
        self.mark(self.root, 'src/main.py', 'engine::' + allowed + '#one', 'engine::' + denied + '#one')
        rows = self.rows(self.result())
        self.assertEqual({key for key in rows if key[0] == 'engine'},
                         {('engine', allowed + '#one'), ('engine', allowed + '#two')})
        self.assertEqual(rows['engine', allowed + '#one']['code'], {'src': 1})
        self.assertEqual(rows['engine', allowed + '#two']['code'], {'src': 0})

    def test_reverse_consumers_match_physical_root_and_count_distinct_repositories(self):
        (self.base / 'client-link').symlink_to(self.root, target_is_directory=True)
        support.set_config(self.engine, repos={
            'different': {'path': '../client-link', 'read': ['docs']}})
        self.page(self.root, 'docs/guide.md', 'one', 'zero')
        self.mark(self.root, 'src/main.py', 'docs/guide.md#one', 'docs/guide.md#one')
        self.mark(self.engine, 'src/main.py', 'different::docs/guide.md#one',
                  'different::docs/guide.md#one')
        self.mark(self.engine, 'tests/test_main.py', 'different::docs/guide.md#one')
        self.mark(self.engine, 'src/unrelated.py', 'docs/guide.md#one')
        result = self.result()
        rows = self.rows(result)
        self.assertEqual(result['layers'], ['src', 'engine::src'])
        self.assertEqual(rows[None, 'docs/guide.md#one']['code'], {'src': 1, 'engine::src': 1})
        self.assertEqual(rows[None, 'docs/guide.md#one']['test_counts'],
                         [{'repo': None, 'count': 0}, {'repo': 'engine', 'count': 1}])
        self.assertEqual(rows[None, 'docs/guide.md#one']['tests'], 1)
        self.assertEqual(rows[None, 'docs/guide.md#zero']['code'], {'src': 0, 'engine::src': 0})
        self.assertFalse(any(row['repo'] for row in result['rows']))

    def test_code_and_tests_permissions_are_separate_and_use_neighbor_settings(self):
        self.page(self.root, 'docs/guide.md', 'one')
        support.set_config(self.engine, layers={'ui/*': 'ui', 'zero/*': 'empty', 'checks/*': 'tests'},
                           tests=['verify.*'])
        self.mark(self.engine, 'ui/main.py', 'application::docs/guide.md#one')
        self.mark(self.engine, 'ui/verify.py', 'application::docs/guide.md#one')
        self.mark(self.engine, 'checks/plain.py', 'application::docs/guide.md#one')
        for read, layers, count in ((('code',), ['engine::ui', 'engine::empty'], 0),
                                    (('tests',), [], 2),
                                    (('code', 'tests'), ['engine::ui', 'engine::empty'], 2)):
            with self.subTest(read=read):
                self.connect(read)
                result = self.result()
                row = self.rows(result)[None, 'docs/guide.md#one']
                self.assertEqual(result['layers'], layers)
                self.assertEqual(row['tests'], count)
                self.assertEqual(row['tests'], sum(item['count'] for item in row['test_counts']))
                self.assertEqual(row['code'], dict(zip(layers, (1, 0))))
                self.assertEqual([item['repo'] for item in row['test_counts']],
                                 [None, 'engine'] if 'tests' in read else [None])

    def test_foreign_decisions_and_local_same_number_keep_distinct_rows(self):
        self.decision(self.root)
        foreign_path = self.decision(self.engine, status='rejected')
        self.decision(self.engine, number=2)
        self.mark(self.root, 'src/main.py', 'ADR-001', 'engine::ADR-0001', 'engine::adr-1')
        result = self.result()
        rows = self.rows(result)
        self.assertIn((None, 'ADR-001'), rows)
        self.assertEqual(rows['engine', 'ADR-001']['code']['src'], 1)
        self.assertEqual(rows['engine', 'ADR-001']['status'], 'rejected')
        self.assertEqual(rows['engine', foreign_path + '#one']['status'], 'rejected')
        self.assertNotIn(('engine', 'ADR-002'), rows)
        self.assertFalse(result['signals'])  # Map does not emit T3.
        self.mark(self.root, 'src/main.py', 'engine::' + foreign_path + '#one')
        rows = self.rows(self.result())
        self.assertEqual(rows['engine', 'ADR-001']['code']['src'], 0)
        self.assertEqual(rows['engine', foreign_path + '#one']['code']['src'], 1)
        self.assertEqual(rows['engine', foreign_path + '#two']['code']['src'], 0)

    def test_no_config_exposes_only_page_anchors_and_never_reverse_consumers(self):
        self.page(self.root, 'docs/local.md', 'one')
        self.page(self.engine, 'docs/guide.md', 'one', 'two')
        self.mark(self.root, 'src/main.py', 'engine::docs/guide.md#one')
        self.mark(self.engine, 'src/main.py', 'application::docs/local.md#one')
        (self.engine / 'lipi.json').unlink()
        result = self.result()
        self.assertEqual(result['layers'], ['src'])
        self.assertEqual({key for key in self.rows(result) if key[0]},
                         {('engine', 'docs/guide.md#one'), ('engine', 'docs/guide.md#two')})
        self.assertEqual(self.rows(result)[None, 'docs/local.md']['test_counts'],
                         [{'repo': None, 'count': 0}])

    def test_missing_source_keeps_metadata_without_fake_zero_columns_and_exit_is_zero(self):
        self.page(self.root, 'docs/local.md', 'one')
        support.set_config(self.root, layers={'src/*': 'api'}, repos={
            'missing': {'path': '../missing', 'read': ['docs', 'code', 'tests']}})
        for level in ('warning', 'error', 'off'):
            with self.subTest(level=level):
                support.set_config(self.root, codes={'T4': level})
                code, output = support.cli(self.root, 'map', '--format', 'json')
                self.assertEqual(code, 0, output)
                result = json.loads(output)
                self.assertEqual(result['layers'], ['api'])
                self.assertTrue(result['incomplete'])
                self.assertFalse(result['reproducible'])
                source = result['checks']['repos'][1]
                self.assertEqual(source['state'], 'unavailable')
                self.assertIsNone(source['head'])
                self.assertIsNone(source['dirty'])
                self.assertTrue(source['reason'])
                self.assertEqual(result['rows'][0]['test_counts'], [{'repo': None, 'count': 0}])
                self.assertEqual(len(result['signals']), 0 if level == 'off' else 1)
                if level != 'off':
                    self.assertEqual(result['signals'][0]['target_repo'], 'missing')
                    self.assertEqual(result['signals'][0]['level'], level)
                self.assertIn('repos-incomplete', {note['code'] for note in result['notes']})

    def test_partial_failure_discards_all_source_rows_and_reverse_places(self):
        self.page(self.root, 'docs/local.md', 'one')
        self.page(self.engine, 'docs/good.md', 'one')
        support.wb(self.engine / 'docs/bad.md', b'\xffinvalid')
        self.mark(self.engine, 'ui/main.py', 'application::docs/local.md#one')
        self.mark(self.engine, 'tests/test_main.py', 'application::docs/local.md#one')
        support.set_config(self.engine, layers={'ui/*': 'ui'})
        expected = None
        for targets in (('engine::docs/good.md#one', 'engine::docs/bad.md#one'),
                        ('engine::docs/bad.md#one', 'engine::docs/good.md#one')):
            with self.subTest(targets=targets):
                self.mark(self.root, 'src/main.py', 'docs/local.md#one', *targets)
                result = self.result()
                rows = self.rows(result)
                self.assertEqual(set(rows), {(None, 'docs/local.md#one')})
                self.assertEqual(rows[None, 'docs/local.md#one']['code'], {'src': 1})
                self.assertEqual(rows[None, 'docs/local.md#one']['test_counts'], [{'repo': None, 'count': 0}])
                self.assertEqual(result['checks']['repos'][1]['state'], 'unavailable')
                self.assertTrue(result['incomplete'])
                if expected is not None:
                    self.assertEqual(result, expected)
                expected = result

    def test_unused_foreign_broken_doc_and_links_do_not_make_source_unavailable(self):
        self.page(self.engine, 'docs/used.md', 'one')
        support.wb(self.engine / 'docs/unused.md', b'\xffinvalid')
        with (self.engine / 'docs/used.md').open('a') as stream:
            stream.write('\n[Unused](unused.md#one)\n')
        self.mark(self.root, 'src/main.py', 'engine::docs/used.md#one')
        result = self.result()
        self.assertFalse(result['incomplete'])
        self.assertEqual(result['checks']['repos'][1]['state'], 'no-git')
        self.assertIn(('engine', 'docs/used.md#one'), self.rows(result))

    def test_text_groups_code_and_tests_by_repo_and_keeps_metadata(self):
        self.page(self.root, 'docs/local.md', 'one')
        support.set_config(self.root, layers={'api/*': 'api'})
        support.set_config(self.engine, layers={'ui/*': 'ui'})
        self.mark(self.engine, 'ui/main.py', 'application::docs/local.md#one')
        self.mark(self.engine, 'tests/test_main.py', 'application::docs/local.md#one')
        result = self.result()
        text = render_text(result)
        header = [value.strip() for value in text.splitlines()[0].split('|')]
        self.assertEqual(header, [*self.column_labels(), 'api', self.tests_column(),
                                  'engine::ui', self.tests_column('engine')])
        cells = next(line for line in text.splitlines() if line.startswith('docs/local.md#one'))
        self.assertEqual([int(value.strip()) for value in cells.split('|')[-4:]], [0, 0, 1, 1])
        self.assertIn(support.localized('sources:', 'источники:'), text)
        self.assertIn(support.localized('engine without Git', 'engine без Git'), text)
        self.assertIn(support.localized('Available repositories', 'Доступные источники'), text)

    def test_empty_map_test_columns_follow_permissions_and_source_order(self):
        support.set_config(self.engine, layers={'ui/*': 'ui'})
        other = self.make_root('other')
        for git in (False, True):
            if git:
                for root in (self.root, self.engine, other):
                    self.git_commit(root)
            for read, expected in ((('code', 'tests'), [self.tests_column('engine'), self.tests_column('alpha')]),
                                   (('code',), [])):
                with self.subTest(read=read, git=git):
                    self.connect(read, alpha={'path': '../other',
                                              'read': ['tests'] if 'tests' in read else ['docs']})
                    result = self.result()
                    self.assertEqual(result['rows'], [])
                    self.assertEqual(result['layers'], ['engine::ui'])
                    self.assertEqual(result['schema'], 1)
                    self.assertEqual([source['repo'] for source in result['checks']['repos']],
                                     [None, 'engine', 'alpha'])
                    self.assertEqual({source['state'] for source in result['checks']['repos']},
                                     {'ok' if git else 'no-git'})
                    header = [value.strip() for value in render_text(result).splitlines()[0].split('|')]
                    self.assertEqual(header, [*self.column_labels(), self.tests_column(), 'engine::ui', *expected])
                    self.assertIn(support.localized('no matching targets', 'подходящих целей нет'), render_text(result))

    def test_empty_map_omits_unavailable_test_columns_even_with_t4_off(self):
        self.connect(('tests',), missing={'path': '../missing', 'read': ['tests']})
        for level in ('warning', 'off'):
            with self.subTest(level=level):
                support.set_config(self.root, codes={'T4': level})
                result = self.result()
                self.assertEqual(result['rows'], [])
                self.assertEqual(result['checks']['repos'][-1]['state'], 'unavailable')
                self.assertTrue(result['incomplete'])
                self.assertEqual(len(result['signals']), 0 if level == 'off' else 1)
                header = [value.strip() for value in render_text(result).splitlines()[0].split('|')]
                self.assertEqual(header, [*self.column_labels(), self.tests_column(), self.tests_column('engine')])

    def test_denied_code_contents_are_not_read_while_scanning_tests(self):
        self.connect(('tests',))
        self.page(self.root, 'docs/local.md', 'one')
        self.mark(self.engine, 'tests/test_main.py', 'application::docs/local.md#one')
        support.wb(self.engine / 'src/broken.py', b'\xffinvalid')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), self.engine / 'src/broken.py')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            result = self.result()
        self.assertFalse(result['incomplete'])
        self.assertEqual(self.rows(result)[None, 'docs/local.md#one']['tests'], 1)

    def test_reserved_inferred_layer_is_c1_locally_and_t4_for_neighbor(self):
        self.page(self.root, 'docs/local.md', 'one')
        self.mark(self.root, 'bad::layer/main.py', 'docs/local.md#one')
        code, output = support.cli(self.root, 'map', '--format', 'json')
        self.assertEqual(code, 2, output)
        self.assertEqual(json.loads(output)['errors'][0]['code'], 'C1')
        (self.root / 'bad::layer/main.py').unlink()
        self.mark(self.engine, 'bad::layer/main.py', 'application::docs/local.md#one')
        code, output = support.cli(self.root, 'map', '--format', 'json')
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['signals'][0]['code'], 'T4')
        self.assertEqual(result['layers'], [])
        (self.engine / 'bad::layer/main.py').unlink()
        support.w(self.engine / 'lipi.json', json.dumps({'layers': {'empty/*': 'bad::layer'}}))
        result = self.result()
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['signals'][0]['code'], 'T4')
        self.assertEqual(result['layers'], [])

    def test_source_order_and_metadata_include_unused_sources_and_own_dirty_tree(self):
        other = self.make_root('other')
        self.page(self.root, 'docs/local.md', 'one')
        self.page(self.engine, 'docs/guide.md', 'one')
        self.page(other, 'docs/guide.md', 'one')
        support.set_config(self.root, repos={
            'zeta': {'path': '../other', 'read': ['docs']},
            'alpha': {'path': '../engine', 'read': ['docs']}})
        self.mark(self.root, 'src/main.py', 'alpha::docs/guide.md#one', 'zeta::docs/guide.md#one')
        heads = {root: self.git_commit(root) for root in (self.root, other, self.engine)}
        result = self.result()
        self.assertEqual([item['repo'] for item in result['checks']['repos']], [None, 'zeta', 'alpha'])
        self.assertEqual([row['repo'] for row in result['rows']], [None, 'zeta', 'alpha'])
        self.assertEqual([item['head'] for item in result['checks']['repos']],
                         [heads[self.root], heads[other], heads[self.engine]])
        self.assertTrue(result['reproducible'])
        support.w(self.root / 'untracked.txt', 'new\n')
        result = self.result()
        self.assertFalse(result['reproducible'])
        self.assertFalse(result['incomplete'])
        self.assertIs(result['checks']['repos'][0]['dirty'], True)

    def test_read_only_no_history_foreign_checks_or_third_repository_reads(self):
        third = self.make_root('third')
        self.page(third, 'secret.md', 'secret')
        self.page(self.root, 'docs/local.md', 'one')
        self.page(self.engine, 'docs/guide.md', 'one')
        self.mark(self.root, 'src/main.py', 'engine::docs/guide.md#one')
        self.mark(self.engine, 'src/main.py', 'application::docs/local.md#one')
        support.set_config(self.engine, repos={
            'application': {'path': '../client', 'read': ['docs']},
            'third': {'path': '../third', 'read': ['docs']}}, checks=[{
                'name': 'write', 'run': [sys.executable, '-c', "open('sentinel','w').write('ran')"]}])
        for root in (self.root, self.engine):
            support.w(root / support.BASE_REL, '{"schema":1,"entries":[]}\n')
            self.git_commit(root)
        def snapshot(root):
            return {path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                    for path in root.rglob('*') if path.is_file()}
        before = {root: snapshot(root) for root in (self.root, self.engine)}
        original_read, original_run = Path.read_text, subprocess.run

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(third), str(path))
            return original_read(path, *args, **kwargs)

        def run(command, *args, **kwargs):
            self.assertEqual(command[0], 'git', command)
            self.assertFalse({'blame', 'log'} & set(command), command)
            return original_run(command, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch('subprocess.run', run):
            result = self.result()
        self.assertFalse(result['incomplete'])
        self.assertEqual({root: snapshot(root) for root in before}, before)


if __name__ == '__main__':
    unittest.main()
