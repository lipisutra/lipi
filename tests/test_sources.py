"""Explicit, read-only repository sources (ADR-016)."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.model import Project


# @trace docs/ru/settings.md#repos,ADR-016
class Sources(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-sources-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.make_root('client')
        self.neighbor = self.make_root('engine')
        self.configure(self.root, repos={
            'engine': {'path': '../engine', 'read': ['docs', 'decisions']}})

    def make_root(self, name, **config):
        root = self.base / name
        root.mkdir()
        self.configure(root, **config)
        support.w(root / 'docs/guide.md', '# Guide\n\n## Request <a id="request"></a>\n')
        return root

    def configure(self, root, **config):
        support.w(root / 'lipi.json', json.dumps(config) + '\n')

    def project(self):
        return Project(self.root, load_config(self.root, None))

    def source(self):
        return self.project().sources.get('engine')

    def commit(self, root):
        support.git_init(root)
        code, output = support.commit(root)
        self.assertEqual(code, 0, output)
        code, head = support.git(root, 'rev-parse', 'HEAD')
        self.assertEqual(code, 0, head)
        return head.strip()

    def snapshot(self, root):
        """Include Git index/refs and metadata; atime changes from reading are harmless."""
        result = {}
        for path in sorted(root.rglob('*')):
            info = path.lstat()
            content = (os.readlink(path) if path.is_symlink()
                       else path.read_bytes() if path.is_file() else None)
            result[path.relative_to(root).as_posix()] = (
                stat.S_IMODE(info.st_mode), info.st_mtime_ns, content)
        return result

    def test_clean_git_records_head_and_is_reproducible(self):
        own_head = self.commit(self.root)
        neighbor_head = self.commit(self.neighbor)
        sources = self.project().sources
        source = sources.get('engine')
        self.assertEqual(source.root, self.neighbor)
        self.assertEqual(source.read, ('docs', 'decisions'))
        self.assertTrue(source.has_config)
        self.assertEqual(source.state, 'ok')
        self.assertEqual(source.head, neighbor_head)
        self.assertIs(source.dirty, False)
        self.assertEqual(sources.local.head, own_head)
        self.assertIs(sources.local.dirty, False)
        self.assertTrue(sources.reproducible)

    def test_dirty_neighbor_tracks_staged_unstaged_and_untracked_changes(self):
        head = self.commit(self.neighbor)
        for kind in ('unstaged', 'staged', 'untracked'):
            with self.subTest(kind=kind):
                support.git(self.neighbor, 'reset', '--hard', 'HEAD')
                support.git(self.neighbor, 'clean', '-fd')
                path = 'new.txt' if kind == 'untracked' else 'docs/guide.md'
                support.w(self.neighbor / path, 'changed\n')
                if kind == 'staged':
                    code, output = support.git(self.neighbor, 'add', path)
                    self.assertEqual(code, 0, output)
                source = self.source()
                self.assertEqual(source.state, 'ok')
                self.assertEqual(source.head, head)
                self.assertIs(source.dirty, True)

    def test_reproducible_includes_own_working_tree(self):
        self.commit(self.root)
        self.commit(self.neighbor)
        support.w(self.root / 'new.txt', 'local change\n')
        sources = self.project().sources
        self.assertIs(sources.get('engine').dirty, False)
        self.assertIs(sources.local.dirty, True)
        self.assertFalse(sources.reproducible)

    def test_reproducible_requires_git_in_own_project(self):
        self.commit(self.neighbor)
        sources = self.project().sources
        self.assertEqual(sources.local.state, 'no-git')
        self.assertIsNone(sources.local.head)
        self.assertIsNone(sources.local.dirty)
        self.assertFalse(sources.reproducible)

    def test_no_git_is_readable_with_unknown_head_and_dirty(self):
        sources = self.project().sources
        source = sources.get('engine')
        self.assertEqual(source.state, 'no-git')
        self.assertIsNone(source.head)
        self.assertIsNone(source.dirty)
        self.assertIsNotNone(source.project)
        self.assertEqual(source.resolve_path('docs/guide.md'),
                         self.neighbor / 'docs/guide.md')
        self.assertFalse(sources.reproducible)

    def test_unborn_git_preserves_unknown_head(self):
        self.commit(self.root)
        support.git_init(self.neighbor)
        sources = self.project().sources
        source = sources.get('engine')
        self.assertEqual(source.state, 'ok')
        self.assertIsNone(source.head)
        self.assertIs(source.dirty, True)
        self.assertFalse(sources.reproducible)

    def test_missing_directory_is_unavailable(self):
        self.configure(self.root, repos={
            'engine': {'path': '../missing', 'read': ['docs']}})
        sources = self.project().sources
        source = sources.get('engine')
        self.assertEqual(source.state, 'unavailable')
        self.assertTrue(source.reason)
        self.assertIsNone(source.head)
        self.assertIsNone(source.dirty)
        self.assertIsNone(source.project)
        self.assertFalse(sources.reproducible)

    def test_invalid_neighbor_config_is_unavailable(self):
        for content in ('{invalid', '[]', '{"docs": 12}', '{"unknown": true}'):
            with self.subTest(content=content):
                support.w(self.neighbor / 'lipi.json', content)
                source = self.source()
                self.assertEqual(source.state, 'unavailable')
                self.assertIn('lipi.json', source.reason)
                self.assertIsNone(source.project)
                self.assertIsNone(source.head)
                self.assertIsNone(source.dirty)

    def test_different_major_in_lock_is_unavailable(self):
        other_major = int(support.VERSION.split('.')[0]) + 1
        support.w(self.neighbor / support.LOCK_REL,
                  json.dumps({'lipi': '%d.0.0' % other_major, 'files': {}}))
        source = self.source()
        self.assertEqual(source.state, 'unavailable')
        self.assertIn(str(other_major), source.reason)
        self.assertIsNone(source.project)

    def test_same_major_lock_allows_different_minor(self):
        major = support.VERSION.split('.')[0]
        support.w(self.neighbor / support.LOCK_REL,
                  json.dumps({'lipi': major + '.0.0', 'files': {}}))
        source = self.source()
        self.assertEqual(source.state, 'no-git')
        self.assertIsNotNone(source.project)

    def test_invalid_or_dangling_lock_is_unavailable(self):
        lock = self.neighbor / support.LOCK_REL
        support.w(lock, '{invalid lock')
        source = self.source()
        self.assertEqual(source.state, 'unavailable')
        self.assertIn('lipi.lock', source.reason)
        lock.unlink()
        lock.symlink_to(self.neighbor / 'missing-lock')
        source = self.source()
        self.assertEqual(source.state, 'unavailable')
        self.assertIn('lipi.lock', source.reason)

    def test_missing_config_uses_explicit_paths_without_workflow_inference(self):
        (self.neighbor / 'lipi.json').unlink()
        support.w(self.neighbor / 'workflow/adr/adr-001-choice.md', '# Choice\n')
        source = self.source()
        self.assertFalse(source.has_config)
        self.assertEqual(source.state, 'no-git')
        self.assertEqual(source.project.docs, self.neighbor)
        self.assertIsNone(source.project.wf)
        self.assertIsNone(source.project.decisions)
        self.assertEqual(source.resolve_path('docs/guide.md'),
                         self.neighbor / 'docs/guide.md')

    def test_neighbors_keep_declared_order_and_sources_are_cached(self):
        self.make_root('extra')
        self.configure(self.root, repos={
            'second': {'path': '../extra', 'read': ['tests']},
            'first': {'path': '../engine', 'read': ['code', 'docs']}})
        project = self.project()
        sources = project.sources
        self.assertIs(project.sources, sources)
        self.assertIs(sources.get(None), sources.local)
        self.assertIs(sources.get('first'), sources.get('first'))
        self.assertIsNone(sources.get('unknown'))
        self.assertEqual([name for name, _ in sources.items()], [None, 'second', 'first'])
        self.assertEqual([source.name for source in sources.all], [None, 'second', 'first'])

    def test_absent_repos_does_not_probe_sources(self):
        self.configure(self.root)
        project = self.project()
        with patch('pathlib.Path.read_text', side_effect=AssertionError('unexpected read')), \
                patch('subprocess.run', side_effect=AssertionError('unexpected process')):
            sources = project.sources
            self.assertEqual(list(sources.items()), [(None, sources.local)])
            self.assertIsNone(sources.get('unknown'))
            self.assertEqual(sources.local.root, self.root)

    def test_aliases_match_physical_root_in_both_directions(self):
        (self.base / 'client-link').symlink_to(self.root, target_is_directory=True)
        (self.base / 'engine-link').symlink_to(self.neighbor, target_is_directory=True)
        self.configure(self.root, repos={
            'engine': {'path': '../engine-link', 'read': ['docs']}})
        self.configure(self.neighbor, repos={
            'different-name': {'path': '../client-link', 'read': ['docs']},
            'engine': {'path': '../unrelated', 'read': ['docs']}})
        source = self.source()
        self.assertEqual(source.root, self.neighbor)
        self.assertTrue(source.points_to_local('different-name'))
        self.assertFalse(source.points_to_local('engine'))
        self.assertFalse(source.points_to_local('unknown'))

    def test_target_symlinks_and_parent_paths_are_rejected_before_reading(self):
        outside = self.make_root('outside')
        target = outside / 'docs/guide.md'
        link = self.neighbor / 'docs/linked.md'
        link.symlink_to(target)
        (self.neighbor / 'linked-dir').symlink_to(outside, target_is_directory=True)
        source = self.source()
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outside), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            for path in ('docs/linked.md', 'linked-dir/docs/guide.md',
                         '../outside/docs/guide.md', str(target)):
                with self.subTest(path=path):
                    self.assertIsNone(source.resolve_path(path))
                    self.assertIsNone(source.project.page(self.neighbor / path))
            self.assertIsNotNone(source.project.page(self.neighbor / 'docs/guide.md'))

    def test_config_symlink_is_rejected_before_reading_outside_root(self):
        outside = self.make_root('outside')
        config = self.neighbor / 'lipi.json'
        config.unlink()
        config.symlink_to(outside / 'lipi.json')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outside), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            source = self.source()
            self.assertEqual(source.state, 'unavailable')
            self.assertTrue(source.reason)
            self.assertIsNone(source.project)

    def test_lock_symlink_is_rejected_before_reading_outside_root(self):
        outside = self.make_root('outside')
        support.w(outside / 'lock.json',
                  json.dumps({'lipi': support.VERSION, 'files': {}}))
        lock = self.neighbor / support.LOCK_REL
        lock.parent.mkdir(parents=True)
        lock.symlink_to(outside / 'lock.json')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outside), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            source = self.source()
            self.assertEqual(source.state, 'unavailable')
            self.assertTrue(source.reason)

    def test_neighbor_directory_settings_cannot_escape_resolved_root(self):
        outside = self.make_root('outside')
        (self.neighbor / 'outside-link').symlink_to(outside, target_is_directory=True)
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outside), str(path))
            return original(path, *args, **kwargs)

        for config in ({'docs': '../outside/docs'}, {'docs': 'outside-link/docs'},
                       {'workflow': '../outside'}, {'description': 'outside-link'}):
            with self.subTest(config=config):
                self.configure(self.neighbor, **config)
                with patch.object(Path, 'read_text', read):
                    source = self.source()
                    self.assertEqual(source.state, 'unavailable')
                    self.assertTrue(source.reason)
                    self.assertIsNone(source.project)

    def test_neighbor_baseline_is_not_read_or_validated(self):
        baseline = self.neighbor / support.BASE_REL
        support.w(baseline, '{invalid baseline')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), baseline)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            source = self.source()
            self.assertEqual(source.state, 'no-git')
            self.assertIsNotNone(source.project)
        self.assertEqual(baseline.read_text(), '{invalid baseline')

    def test_neighbor_skip_dirs_are_honored_before_content_read(self):
        self.configure(self.neighbor, docs='manual', skip_dirs=['private'])
        support.w(self.neighbor / 'manual/guide.md', '# Public\n')
        support.w(self.neighbor / 'private/secret.md', '# Private\n')
        support.w(self.neighbor / 'node_modules/secret.md', '# Dependency\n')
        source = self.source()
        self.assertEqual(source.project.docs, self.neighbor / 'manual')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertNotIn('private', path.relative_to(self.neighbor).parts)
            self.assertNotIn('node_modules', path.relative_to(self.neighbor).parts)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            for relative in ('private/secret.md', 'node_modules/secret.md'):
                with self.subTest(path=relative):
                    self.assertIsNone(source.resolve_path(relative))
                    self.assertIsNone(source.project.page(self.neighbor / relative))
            self.assertIsNotNone(source.project.page(self.neighbor / 'manual/guide.md'))

    def test_configured_docs_and_decisions_under_agents_are_readable(self):
        self.configure(self.neighbor, docs='.agents/manual', decisions='.agents/decisions')
        support.w(self.neighbor / '.agents/manual/guide.md', '# Guide\n')
        support.w(self.neighbor / '.agents/decisions/adr-001-choice.md', '# Choice\n')
        support.w(self.neighbor / '.agents/lipi/README.md', '# Managed rules\n')
        source = self.source()
        self.assertEqual(source.project.docs, self.neighbor / '.agents/manual')
        self.assertEqual(source.project.decisions, self.neighbor / '.agents/decisions')
        for relative in ('.agents/manual/guide.md', '.agents/decisions/adr-001-choice.md'):
            with self.subTest(path=relative):
                self.assertIsNotNone(source.project.page(self.neighbor / relative))
        self.assertIsNone(source.resolve_path('.agents/lipi/README.md'))
        self.assertIsNone(source.project.page(self.neighbor / '.agents/lipi/README.md'))

    def test_connections_are_nontransitive_and_never_execute_neighbor_checks(self):
        third = self.make_root('third')
        sentinel = self.base / 'executed.txt'
        self.configure(self.neighbor, repos={
            'client': {'path': '../client', 'read': ['docs']},
            'third': {'path': '../third', 'read': ['docs', 'code']}}, checks=[{
                'name': 'unsafe', 'run': [sys.executable, '-c',
                    'from pathlib import Path; Path(%r).touch()' % str(sentinel)]}])
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(third), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            sources = self.project().sources
            source = sources.get('engine')
            self.assertTrue(source.points_to_local('client'))
            self.assertFalse(source.points_to_local('third'))
            self.assertEqual([item.name for item in sources.all], [None, 'engine'])
            self.assertIsNone(sources.get('third'))
            self.assertIsNone(source.project.sources.get('third'))
            self.assertEqual([item.root for item in source.project.sources.all],
                             [self.neighbor])
            self.assertIsNotNone(source.project.page(self.neighbor / 'docs/guide.md'))
            self.assertFalse(sources.reproducible)
        self.assertFalse(sentinel.exists())

    def test_sources_leave_working_trees_index_refs_lock_and_baseline_unchanged(self):
        for root in (self.root, self.neighbor):
            support.w(root / support.LOCK_REL,
                      json.dumps({'lipi': support.VERSION, 'files': {}}))
            support.w(root / support.BASE_REL, '{"schema": 1, "entries": []}\n')
            self.commit(root)
            path = root / 'docs/guide.md'
            old = path.stat()
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 2_000_000_000))
        before = {root: self.snapshot(root) for root in (self.root, self.neighbor)}
        sources = self.project().sources
        for source in sources.all:
            self.assertEqual(source.state, 'ok')
            self.assertIs(source.dirty, False)
            self.assertIsNotNone(source.project.page(source.root / 'docs/guide.md'))
        self.assertTrue(sources.reproducible)
        for root in (self.root, self.neighbor):
            self.assertEqual(self.snapshot(root), before[root], str(root))


if __name__ == '__main__':
    unittest.main()
