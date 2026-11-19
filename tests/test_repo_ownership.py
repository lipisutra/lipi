"""A connected physical root cannot be read again as local checker content."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.docs import check_docs, check_edition_docs
from lipi.checker.model import Project
from lipi.checker.report import Report
from lipi.checker.targets import resolve_mark
from lipi.checker.trace import scan_code
from lipi.repo_index import RepoIndex


# @trace docs/ru/settings.md#repos
class RepositoryOwnership(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-ownership-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.nested = self.root / 'nested'
        support.w(self.root / 'lipi.json', json.dumps({
            'repos': {'engine': {'path': 'nested', 'read': ['docs']}}}))
        support.w(self.root / 'docs/README.md', '# Local <a id="local"></a>\n')
        support.w(self.nested / 'lipi.json', '{}\n')
        support.w(self.nested / 'docs/guide.md', '# Foreign <a id="foreign"></a>\n')
        support.w(self.nested / 'src/private.py',
                  '# %s docs/README.md#local\nsecret = 1\n' % support.TAG)
        support.w(self.root / 'src/main.py',
                  '# %s docs/README.md#local\nlocal = 1\n' % support.TAG)

    def project(self):
        return Project(self.root, load_config(self.root, None))

    def forbid_project_text_reads(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(self.root), str(path))
            return original(path, *args, **kwargs)

        return patch.object(Path, 'read_text', read)

    def test_nested_code_is_excluded_before_reading_even_without_git(self):
        project, report = self.project(), Report()
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(self.nested), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            tags, lines = scan_code(project, report)
        self.assertEqual(tags, {'docs/README.md#local': [('src/main.py', 1)]})
        self.assertEqual(set(lines), {'src/main.py'})
        self.assertFalse(report.items)

    def test_unprefixed_target_and_page_cannot_enter_nested_root(self):
        project = self.project()
        with self.forbid_project_text_reads():
            self.assertIsNone(project.page(self.nested / 'docs/guide.md'))
            target, error = resolve_mark(project, 'nested/docs/guide.md#foreign')
        self.assertIsNone(target)
        self.assertIn(support.localized('excluded', 'исключ'), error)
        self.assertEqual(resolve_mark(project, 'engine::docs/guide.md#foreign'),
                         ('engine::docs/guide.md#foreign', None))

    def test_physical_alias_and_symlink_into_neighbor_keep_ownership(self):
        (self.root / 'alias').symlink_to(self.nested, target_is_directory=True)
        (self.root / 'docs/linked.md').symlink_to(self.nested / 'docs/guide.md')
        support.set_config(self.root, repos={
            'engine': {'path': 'alias', 'read': ['docs']}})
        project = self.project()
        with self.forbid_project_text_reads():
            for target in ('alias/docs/guide.md#foreign', 'nested/docs/guide.md#foreign',
                           'docs/linked.md#foreign'):
                with self.subTest(target=target):
                    self.assertIsNone(resolve_mark(project, target)[0])
            self.assertIsNone(project.page(self.root / 'docs/linked.md'))

    def test_root_description_skips_nested_docs_without_unreadable_findings(self):
        support.set_config(self.root, docs='.')
        support.w(self.root / 'README.md', '# Root\n\n[Local](docs/README.md)\n')
        project, report = self.project(), Report()
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(self.nested), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            pages, _, _, _ = check_docs(project, report)
        self.assertEqual({page.path for page in pages},
                         {self.root / 'README.md', self.root / 'docs/README.md'})
        self.assertFalse(report.items, report.items)

    def test_language_edition_skips_connected_root(self):
        support.set_config(self.root, docs='docs', languages={
            'default': 'en', 'editions': {'en': 'docs', 'xx': 'nested/docs'}})
        project, report = self.project(), Report()
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(self.nested), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            pages = check_edition_docs(project, report)
        self.assertFalse([page for collection in pages.values() for page in collection.values()
                          if page.path.is_relative_to(self.nested)])
        self.assertFalse([item for item in report.items if item[3] == 'D1'], report.items)

    def test_own_root_has_priority_over_connected_ancestor(self):
        support.set_config(self.root, repos={
            'parent': {'path': '..', 'read': ['docs']}})
        project = self.project()
        self.assertFalse(project.in_connected_repo(self.root / 'docs/README.md'))
        self.assertEqual(resolve_mark(project, 'docs/README.md#local'), ('docs/README.md#local', None))
        self.assertIsNotNone(project.page(self.root / 'docs/README.md'))

    def test_without_repos_nested_files_keep_previous_local_behavior(self):
        support.set_config(self.root, repos={})
        project, report = self.project(), Report()
        self.assertFalse(project.in_connected_repo(self.nested / 'src/private.py'))
        tags, _ = scan_code(project, report)
        self.assertEqual(set(tags['docs/README.md#local']),
                         {('src/main.py', 1), ('nested/src/private.py', 1)})
        self.assertEqual(resolve_mark(project, 'nested/docs/guide.md#foreign'),
                         ('nested/docs/guide.md#foreign', None))

    def test_foreign_declared_nested_root_is_excluded_without_resolving_or_reading_it(self):
        third = self.nested / 'third'
        support.set_config(self.nested, docs='.', repos={
            'third': {'path': 'third', 'read': ['docs']},
            'client': {'path': '..', 'read': ['docs']}})
        support.w(third / 'lipi.json', '{invalid third config')
        support.w(third / 'secret.md', '# Secret <a id="secret"></a>\n')
        project = self.project()
        original_read, original_resolve = Path.read_text, Path.resolve

        def read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(third), str(path))
            return original_read(path, *args, **kwargs)

        def resolve(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(third), str(path))
            return original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch.object(Path, 'resolve', resolve):
            index = RepoIndex(project)
            source = project.sources.get('engine')
            self.assertEqual(source.state, 'no-git')
            self.assertIsNone(source.resolve_path('third/secret.md'))
            self.assertIsNone(source.project.page(third / 'secret.md'))
            self.assertIsNotNone(source.project.page(self.nested / 'docs/guide.md'))
            self.assertTrue(source.points_to_local('client'))
            self.assertFalse(any('third' in target for target in index.nodes))


if __name__ == '__main__':
    unittest.main()
