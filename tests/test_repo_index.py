"""Shared repository index: scope, identity, refinements and atomic exclusion."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.repo_index import RepoConfigError, RepoIndex, qualify, split_id


# @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
class RepositoryIndex(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-repo-index-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root, self.neighbor = self.base / 'app', self.base / 'engine'
        support.w(self.root / 'lipi.json', json.dumps({'repos': {
            'engine': {'path': '../engine', 'read': ['docs', 'decisions', 'code', 'tests']}}}))
        support.w(self.neighbor / 'lipi.json', json.dumps({'repos': {
            'application': {'path': '../app', 'read': ['docs']}}}))
        for root in (self.root, self.neighbor):
            support.w(root / 'docs/guide.md', '# Guide\n\n## Request <a id="request"></a>\n')

    def index(self, **kwargs):
        return RepoIndex(Project(self.root, load_config(self.root, None)), **kwargs)

    def mark(self, root, path, *targets):
        support.w(root / path, '# ' + support.TAG + ' ' + ','.join(targets) + '\nvalue = 1\n')

    def test_qualified_nodes_bare_paths_and_reverse_aliases(self):
        self.mark(self.root, 'src/main.py', 'docs/guide.md#request', 'engine::docs/guide.md#request')
        self.mark(self.neighbor, 'src/main.py', 'application::docs/guide.md#request')
        self.mark(self.neighbor, 'tests/test_main.py', 'application::docs/guide.md#request')
        index = self.index()
        self.assertEqual(qualify('engine', 'ADR-001'), 'engine::ADR-001')
        self.assertEqual(split_id('docs/guide.md#request'), (None, 'docs/guide.md#request'))
        self.assertEqual(index.nodes['engine::docs/guide.md#request']['repo'], 'engine')
        self.assertEqual(index.count('docs/guide.md#request'), 2)
        self.assertEqual(index.count('engine::docs/guide.md#request'), 1)
        self.assertEqual([place['repo'] for place in index.by_target['engine::docs/guide.md#request']], [None])
        self.assertEqual([place['repo'] for place in index.by_file['engine::src/main.py']], ['engine'])
        self.assertEqual(index.by_file['engine::src/main.py'][0]['path'], 'src/main.py')
        self.assertEqual(index.by_file['engine::src/main.py'][0]['layer'], 'src')

    def test_code_only_does_not_read_documents_or_third_repository(self):
        support.set_config(self.root, repos={'engine': {'path': '../engine', 'read': ['code']}})
        third = self.base / 'third'
        support.w(third / 'lipi.json', '{bad')
        support.set_config(self.neighbor, repos={
            'application': {'path': '../app', 'read': ['docs']},
            'third': {'path': '../third', 'read': ['docs']}})
        self.mark(self.neighbor, 'src/main.py', 'application::docs/guide.md#request',
                  'third::docs/guide.md#request', 'docs/guide.md#request')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(third))
            self.assertFalse(path.is_relative_to(self.neighbor / 'docs'))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            index = self.index()
        self.assertEqual(index.count('docs/guide.md#request'), 1)
        self.assertFalse(any(node['repo'] for node in index.nodes.values()))

    def test_code_symlink_cannot_escape_source(self):
        third = self.base / 'third'
        self.mark(third, 'main.py', 'application::docs/guide.md#request')
        (self.neighbor / 'escape.py').symlink_to(third / 'main.py')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(third))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            index = self.index()
        self.assertFalse(index.places)

    def test_page_dirs_keep_git_workflow_and_source_exclusions(self):
        support.set_config(self.root, repos={'engine': {
            'path': '../engine', 'read': ['docs'],
            'page_dirs': ['notes', 'third', 'history', 'workflow', '.agents']}})
        support.set_config(self.neighbor, repos={'third': {'path': 'third', 'read': ['docs']}},
                           skip_dirs=['notes/private'])
        allowed = 'notes/guide.md'
        denied = ('notes/private/hidden.md', 'notes/ignored.md', 'third/hidden.md',
                  'history/hidden.md', 'workflow/hidden.md', 'workflow/adr/adr-001-hidden.md',
                  '.agents/rules.md', 'notes/AGENTS.md')
        for path in (allowed, *denied):
            support.w(self.neighbor / path, '# Document <a id="section"></a>\n')
        support.w(self.neighbor / '.gitignore', 'notes/ignored.md\n')
        support.git_init(self.neighbor)
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertNotIn(path, {self.neighbor / item for item in denied})
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            index = self.index()
            self.assertIn('engine::' + allowed, index.nodes)
            for path in denied:
                with self.subTest(path=path):
                    target = 'engine::' + path
                    self.assertNotIn(target, index.nodes)
                    self.assertIsNone(index.mark(target + '#section'))

    def test_page_dirs_apply_git_and_lexical_skip_dirs_to_directory_aliases(self):
        relative = 'notes/guide.md'
        support.w(self.neighbor / relative, '# Document <a id="section"></a>\n')
        (self.neighbor / 'notes/work').mkdir()
        (self.neighbor / 'skipped').mkdir()
        for alias in ('alias', 'skipped/alias'):
            (self.neighbor / alias).symlink_to(self.neighbor / 'notes/work', target_is_directory=True)
        support.set_config(self.neighbor, skip_dirs=['skipped'])
        target = 'engine::' + relative
        for alias, git, allowed in (('skipped/alias/..', False, False),
                                    ('alias/..', False, True), ('alias/..', True, False)):
            if git:
                support.git_init(self.neighbor)
            support.set_config(self.root, repos={'engine': {
                'path': '../engine', 'read': ['docs'], 'page_dirs': [alias]}})
            index = self.index()
            self.assertEqual(target in index.nodes, allowed, alias)
            self.assertEqual(index.mark(target + '#section') is not None, allowed, alias)

    def test_page_dirs_do_not_reopen_history_under_an_aliased_decisions_directory(self):
        support.set_config(self.root, repos={'engine': {
            'path': '../engine', 'read': ['docs', 'decisions'], 'page_dirs': ['notes']}})
        support.set_config(self.neighbor, decisions='decision-link')
        live = 'notes/decisions/adr-001-live.md'
        archived = 'notes/decisions/history/adr-002-archived.md'
        for path in (live, archived):
            support.w(self.neighbor / path, '# Decision <a id="section"></a>\n')
        (self.neighbor / 'decision-link').symlink_to('notes/decisions', target_is_directory=True)
        index = self.index()
        self.assertIn('engine::ADR-001', index.nodes)
        self.assertNotIn('engine::' + archived, index.nodes)
        self.assertIsNone(index.mark('engine::' + archived + '#section'))

    def test_external_decision_refinements_keep_namespace_and_status_metadata(self):
        support.w(self.neighbor / 'workflow/adr/adr-001-base.md',
                  '# Base\n\n- Status: accepted\n\n## Decision\n\nBase.\n')
        support.w(self.neighbor / 'workflow/adr/adr-002-child.md',
                  '# Child\n\n- Status: accepted\n- Refines: [ADR-001](adr-001-base.md)\n'
                  '\n## Decision\n\nChild.\n')
        self.mark(self.root, 'src/main.py', 'engine::ADR-001')
        index = self.index()
        self.assertEqual(index.refinements['engine::ADR-001'], {'engine::ADR-002'})
        self.assertEqual(index.local_explicit_decisions, {'engine::ADR-001'})
        self.assertEqual(index.pr.mark_external['engine::ADR-002']['target'], 'ADR-002')
        self.assertIs(index.pr.mark_work['engine::ADR-002'], index.nodes['engine::ADR-002']['page'])

    def test_failure_removes_all_source_data_and_only_its_target_references(self):
        self.mark(self.root, 'src/main.py', 'docs/guide.md#request', 'engine::docs/guide.md#request')
        self.mark(self.neighbor, 'src/main.py', 'application::docs/guide.md#request')
        index = self.index()
        source = index.sources.get('engine')
        source.mark_unavailable('reading failed')
        index.prune_unavailable()
        self.assertEqual(list(index.indices), [None])
        self.assertFalse(any(node['repo'] for node in index.nodes.values()))
        self.assertEqual(index.count('docs/guide.md#request'), 1)
        self.assertEqual(index.places[0]['targets'], {'docs/guide.md#request': 1})
        self.assertEqual(index.checks_repos()[1]['state'], 'unavailable')
        self.assertIsNone(index.checks_repos()[1]['dirty'])

    def test_no_config_supports_exact_anchor_without_search_or_reverse(self):
        (self.neighbor / 'lipi.json').unlink()
        self.mark(self.neighbor, 'src/main.py', 'application::docs/guide.md#request')
        index = self.index()
        node, error = index.resolve('engine::docs/guide.md#request')
        self.assertIsNone(error)
        self.assertEqual(node['target'], 'engine::docs/guide.md#request')
        self.assertEqual(index.count('docs/guide.md#request'), 0)
        for query in ('engine::request', 'engine::docs/guide.md', 'engine::ADR-001'):
            with self.subTest(query=query):
                node, error = index.resolve(query)
                self.assertIsNone(node)
                self.assertEqual(error['error'], 'not-found')

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain ::")
    def test_own_implicit_reserved_layer_is_configuration_error(self):
        self.mark(self.root, 'bad::layer/main.py', 'docs/guide.md#request')
        with self.assertRaises(RepoConfigError):
            self.index()

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain ::")
    def test_neighbor_implicit_reserved_layer_is_unavailable(self):
        self.mark(self.neighbor, 'bad::layer/main.py', 'application::docs/guide.md#request')
        index = self.index()
        self.assertEqual(index.checks_repos()[1]['state'], 'unavailable')
        self.assertNotIn('engine', index.indices)

    def test_nested_source_and_symlink_alias_have_one_owner(self):
        nested = self.root / 'nested'
        support.w(nested / 'lipi.json', '{}')
        support.w(nested / 'docs/guide.md', '# Nested <a id="request"></a>\n')
        self.mark(nested, 'src/private.py', 'docs/guide.md#request')
        self.mark(self.root, 'src/main.py', 'docs/guide.md#request')
        (self.root / 'alias').symlink_to(nested, target_is_directory=True)
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(nested / 'src'))
            return original(path, *args, **kwargs)

        for connection in ('nested', 'alias'):
            with self.subTest(connection=connection):
                support.set_config(self.root, repos={
                    'engine': {'path': connection, 'read': ['docs']}})
                with patch.object(Path, 'read_text', read):
                    index = self.index()
                    for prefix in ('nested', 'alias'):
                        for query in ('%s/src/private.py' % prefix,
                                      '%s/docs/guide.md' % prefix,
                                      '%s/docs/guide.md#request' % prefix):
                            self.assertIsNotNone(index.resolve(query)[1], query)
                        self.assertIsNone(index.mark('%s/docs/guide.md#request' % prefix))
                    node, error = index.resolve('engine::docs/guide.md#request')
                self.assertIsNone(error)
                self.assertEqual(node['repo'], 'engine')
                self.assertEqual(index.count('docs/guide.md#request'), 1)
                self.assertEqual([place['path'] for place in index.places], ['src/main.py'])

    def test_tracked_nested_third_files_are_filtered_before_path_resolution(self):
        third = self.neighbor / 'third'
        support.set_config(self.neighbor, docs='.', repos={
            'third': {'path': 'third', 'read': ['docs']},
            'application': {'path': '../app', 'read': ['docs']}})
        support.w(third / 'lipi.json', '{invalid third config')
        support.w(third / 'secret.md', '# Secret <a id="secret"></a>\n')
        support.git_init(self.neighbor)
        code, output = support.commit(self.neighbor)
        self.assertEqual(code, 0, output)
        project = Project(self.root, load_config(self.root, None))
        original_read, original_resolve = Path.read_text, Path.resolve

        def read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(third), str(path))
            return original_read(path, *args, **kwargs)

        def resolve(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(third), str(path))
            return original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch.object(Path, 'resolve', resolve):
            index = RepoIndex(project)
            source = index.sources.get('engine')
            self.assertEqual(source.state, 'ok')
            self.assertIsNotNone(source.project.page(self.neighbor / 'docs/guide.md'))
            self.assertFalse(any(path.is_relative_to(third) for path in source.project.git_files))
            self.assertFalse(any('third' in target for target in index.nodes))


if __name__ == '__main__':
    unittest.main()
