"""Source boundaries and editor addresses for document search."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.search_sources import search_documents
from lipi.slice_query import build_slice


# @trace docs/ru/slice-search.md#scope,docs/ru/slice-search.md#output
class SearchSources(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-search-sources-')
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root, self.neighbor = base / 'app', base / 'library'
        self.connect('docs', 'decisions', 'code', 'tests')
        support.w(self.neighbor / 'lipi.json', '{}')

    def connect(self, *read, page_dirs=(), **others):
        support.w(self.root / 'lipi.json', json.dumps({'repos': {
            'library': {'path': '../library', 'read': read, 'page_dirs': page_dirs},
            **others}}))

    def project(self):
        return Project(self.root, load_config(self.root, None))

    def search(self, query, cwd=None):
        return search_documents(self.project(), query, cwd or self.root)

    def test_local_search_reads_only_documents_in_local_scope(self):
        nested = self.root / 'nested'
        self.connect('docs', nested={'path': 'nested', 'read': ['docs']})
        allowed = self.root / 'docs/storage.md'
        support.w(allowed, '# Storage\n\nProtocol [manual](other.md).\n')
        denied = [self.root / 'src/main.py', self.root / 'history/archived.md',
                  self.neighbor / 'docs/remote.md', nested / 'lipi.json',
                  nested / 'docs/nested.md']
        for path in denied:
            support.w(path, 'Protocol\n')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(self.neighbor))
            self.assertFalse(path.is_relative_to(nested))
            self.assertNotIn(path, denied)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch(
                'lipi.checker.model.markdown_links', side_effect=AssertionError('link graph')):
            result, code = self.search('protocol')
        self.assertEqual(code, 0)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['candidates'], [
            {'repo': None, 'target': 'docs/storage.md', 'title': 'Storage',
             'excerpt': 'Protocol manual.', 'file': os.path.join('docs', 'storage.md'), 'line': 3}])

    def test_neighbor_section_in_page_dirs_opens_at_stable_line(self):
        self.connect('docs', page_dirs=['notes'])
        local = self.root / 'docs/elsewhere.md'
        page = self.neighbor / 'notes/storage.md'
        support.w(local, '# Logs\n\nЖурнал хранится 10 дней.\n')
        support.w(page, '# Хранилище\n\n## Политика очистки <a id="cleanup"></a>\n'
                        + '\n' * 8 + 'Копия хранится 30 дней.\n')
        subdirectory = self.root / 'src'
        subdirectory.mkdir()
        query = 'library::Сколько дней хранится копия?'
        from_root, code = self.search(query)
        self.assertEqual(code, 0)
        self.assertEqual(from_root['total'], 1)
        expected = {'repo': 'library', 'target': 'notes/storage.md#cleanup',
                    'title': 'Политика очистки', 'excerpt': 'Копия хранится 30 дней.',
                    'line': 12}
        self.assertEqual(from_root['candidates'], [dict(expected, file=os.path.relpath(page, self.root))])
        from_subdirectory, code = self.search(query, subdirectory)
        self.assertEqual(code, 0)
        self.assertEqual(from_subdirectory['candidates'],
                         [dict(expected, file=os.path.relpath(page, subdirectory))])
        chosen = from_subdirectory['candidates'][0]
        source_lines = (subdirectory / chosen['file']).read_text(encoding='utf-8').splitlines()
        self.assertEqual(source_lines[chosen['line'] - 1], chosen['excerpt'])
        opened, code = build_slice(self.project(), chosen['repo'] + '::' + chosen['target'])
        self.assertEqual(code, 0)
        self.assertEqual(opened['target']['target'], expected['target'])
        self.assertEqual(opened['target']['repo'], expected['repo'])
        with patch('lipi.search_sources.relpath', side_effect=ValueError('different drives')):
            across_drives, code = self.search(query, subdirectory)
        self.assertEqual(code, 0)
        self.assertEqual(across_drives['candidates'], [dict(expected, file=str(page))])

    def test_neighbor_scope_excludes_code_third_repos_and_closed_pages(self):
        self.connect('docs', 'code', page_dirs=['notes', 'workflow', 'third'],
                     other={'path': '../other', 'read': ['docs']})
        support.set_config(self.neighbor, repos={'third': {'path': 'third', 'read': ['docs']}},
                           skip_dirs=['notes/private'])
        local = self.root / 'docs/local.md'
        other = self.root.parent / 'other/lipi.json'
        third = self.neighbor / 'third/lipi.json'
        for path in (local, other, third):
            support.w(path, 'Workaround\n')
        denied = [self.neighbor / relative for relative in (
            'src/main.py', 'outside.md', 'notes/private/hidden.md', 'notes/ignored.md',
            'notes/AGENTS.md', 'third/hidden.md', 'workflow/adr/adr-001-hidden.md')]
        for path in denied:
            support.w(path, '# Workaround\n')
        support.w(self.neighbor / '.gitignore', 'notes/ignored.md\n')
        support.w(self.neighbor / 'notes/setup.md', '# Setup\n\nWorkaround.\n')
        support.git_init(self.neighbor)
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertNotIn(path, [local, other, third, *denied])
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            result, code = self.search('library::workaround')
        self.assertEqual(code, 0)
        self.assertEqual(result['total'], 1)
        self.assertEqual([item['target'] for item in result['candidates']], ['notes/setup.md'])

    def test_neighbor_decisions_are_searchable_with_decisions_scope_alone(self):
        self.connect('decisions')
        decision = 'workflow/adr/adr-001-retention.md'
        for path in (decision, 'docs/storage.md'):
            support.w(self.neighbor / path, '# Retention\n\nBackups.\n')
        result, code = self.search('library::backups')
        self.assertEqual(code, 0)
        self.assertEqual([item['target'] for item in result['candidates']], [decision])

    def test_source_misses_and_partial_reads_have_distinct_results(self):
        result, code = self.search('unknown::nothing')
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'not-found')
        self.assertTrue(result['message'])
        (self.neighbor / 'lipi.json').unlink()
        result, code = self.search('library::nothing')
        self.assertEqual(code, 1)
        self.assertEqual(result['reason'], 'no-config')
        self.neighbor.rmdir()
        result, code = self.search('library::nothing')
        self.assertEqual(code, 0)
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['candidates'], [])
        support.w(self.neighbor / 'lipi.json', '{}')
        self.connect('code')
        result, code = self.search('library::nothing')
        self.assertEqual(code, 1)
        self.assertEqual(result['reason'], 'scope-not-enabled')
        self.connect('docs')
        result, code = self.search('library::nothing')
        self.assertEqual(code, 1)
        self.assertEqual(result, {'schema': 1, 'query': 'library::nothing',
                                  'candidates': [], 'total': 0, 'error': 'not-found'})
        support.w(self.neighbor / 'docs/a.md', '# Nothing\n')
        (self.neighbor / 'docs/z.md').write_bytes(b'\xff')
        result, code = self.search('library::nothing')
        self.assertEqual(code, 0)
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['total'], 0)
        self.assertNotIn('error', result)
        self.assertTrue(result['message'])

    def test_full_count_and_order_are_independent_of_local_pages(self):
        for number in range(7):
            support.w(self.neighbor / 'docs' / ('%d.md' % number), '# Guide\n\nCopier.\n')
        query = 'library::copier'
        initial, code = self.search(query)
        self.assertEqual(code, 0)
        self.assertEqual(initial['total'], 7)
        self.assertEqual([item['target'] for item in initial['candidates']],
                         ['docs/%d.md' % number for number in range(5)])
        support.w(self.root / 'docs/local.md', '# Copier\n')
        self.assertEqual(self.search(query), (initial, 0))
