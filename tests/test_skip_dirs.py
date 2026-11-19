"""Общие правила skip_dirs для проверок, индексов и переноса."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config, validate_settings
from lipi.checker.conventions import SKIP_DIRS
from lipi.checker.docs import check_docs
from lipi.checker.model import Project, walk_md
from lipi.checker.paths import SkipDirs
from lipi.checker.report import Report
from lipi.checker.runner import main
from lipi.checker.targets import target_excluded
from lipi.checker.trace import scan_code
from lipi.move_neighbors import neighbor_notices
from lipi.slice_diff import _code_path
from lipi.slice_index import SliceIndex


# @trace docs/ru/settings.md#skip-dirs
class SkipDirectories(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-skip-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'project'
        self.root.mkdir()
        self.write('lipi.json', '{}\n')
        self.write('docs/feature.md', '# Feature\n\n## Part <a id="part"></a>\n')
        self.target = 'docs/feature.md#part'

    def write(self, name, text):
        support.w(self.root / name, text)

    def project(self, **cfg):
        support.set_config(self.root, **cfg)
        return Project(self.root, load_config(self.root, None))

    def mark(self, name, target=None):
        self.write(name, '# %s %s\nvalue = 1\n' % (support.TAG, target or self.target))

    def test_path_prefix_uses_components_and_basename_keeps_any_depth(self):
        for configured, excluded, included in (
            (['tests/fixtures'], ['tests/fixtures/a.py', 'tests/fixtures/deep/a.py'],
             ['src/fixtures/a.py', 'tests/fixtures-old/a.py', 'nested/tests/fixtures/a.py']),
            (['fixtures'], ['tests/fixtures/a.py', 'src/fixtures/a.py'],
             ['tests/fixtures-old/a.py']),
            (['fixtures/'], ['fixtures/a.py'], ['nested/fixtures/a.py']),
            (['./fixtures'], ['fixtures/a.py'], ['nested/fixtures/a.py']),
            (['./tests//temporary/../fixtures/'], ['tests/fixtures/a.py'],
             ['src/fixtures/a.py']),
            (['tests/*'], ['tests/*/a.py'], ['tests/fixtures/a.py']),
            (['tests\\fixtures'], ['tests\\fixtures/a.py'], ['tests/fixtures/a.py']),
        ):
            if os.name == 'nt' and '\\' in configured[0]:
                continue  # Обратная косая не может быть буквальным именем Windows.
            matcher = SkipDirs(self.root, configured)
            with self.subTest(configured=configured):
                for name in excluded:
                    self.assertTrue(matcher.excludes(self.root / name), name)
                for name in included:
                    self.assertFalse(matcher.excludes(self.root / name), name)
                if '/' in configured[0]:
                    self.assertFalse(matcher.excludes(self.base / 'other/tests/fixtures/a.py'))

    def test_invalid_entries_are_c1_before_check_slice_and_map(self):
        for value in ('/tmp/fixtures', '../fixtures', 'a/../../fixtures', '.', './',
                      'a/..', '', '\x00', 'C:/fixtures', 'C:\\fixtures',
                      '\\\\server\\fixtures', 'tests/fi\\xtures'):
            with self.subTest(value=value):
                self.assertTrue(validate_settings(self.root, {'skip_dirs': [value]}))
        support.set_config(self.root, skip_dirs=['../fixtures'])
        for command in ('check', 'slice', 'map'):
            args = [command] + ([self.target] if command == 'slice' else [])
            code, out = support.cli(self.root, *args)
            self.assertEqual(code, 2, out)
            self.assertIn('skip_dirs', out)

    def test_check_slice_map_and_deleted_diff_paths_agree(self):
        names = ['tests/fixtures/a.py', 'src/fixtures/b.py', 'tests/fixtures-old/c.py']
        for name in names:
            self.mark(name)
        for entry, expected in (('tests/fixtures', set(names[1:])),
                                ('fixtures', {names[2]})):
            with self.subTest(entry=entry):
                pr = self.project(skip_dirs=[entry])
                tags, _ = scan_code(pr, Report())
                self.assertEqual({path for path, _ in tags[self.target]}, expected)
                index = SliceIndex(pr)
                self.assertEqual(set(index.by_file), expected)
                self.assertEqual({name for name in names if _code_path(pr, name)}, expected)
                code, out = support.cli(self.root, 'slice', self.target, '--format', 'json')
                self.assertEqual(code, 0, out)
                result = json.loads(out)
                places = {item['path'] for block in result['blocks']
                          if block['kind'] in ('code', 'tests') for item in block['items']}
                self.assertEqual(places, expected)
                code, out = support.cli(self.root, 'map', '--format', 'json')
                self.assertEqual(code, 0, out)
                row = next(row for row in json.loads(out)['rows'] if row['target'] == self.target)
                self.assertEqual(sum(row['code'].values()) + row['tests'], len(expected))

    def test_code_symlink_into_excluded_directory_is_not_indexed(self):
        self.mark('tests/fixtures/a.py')
        self.mark('src/keep.py')
        try:
            (self.root / 'src/alias.py').symlink_to('../tests/fixtures/a.py')
        except OSError as error:
            self.skipTest('создание символических ссылок недоступно: %s' % error)
        for git in (False, True):
            if git:
                support.git_init(self.root)
            pr = self.project(skip_dirs=['tests/fixtures'])
            tags, _ = scan_code(pr, Report())
            self.assertEqual({path for path, _ in tags[self.target]}, {'src/keep.py'})
            self.assertEqual(set(SliceIndex(pr).by_file), {'src/keep.py'})

    def test_markdown_walk_targets_and_rules_honor_path_exclusions(self):
        self.write('docs/fixtures/bad.md', '# Bad\n\n[Missing](gone.md)\n')
        self.write('docs/fixtures-old/kept.md', '# Kept\n')
        self.write('.agents/custom/bad.md', '# Bad\n\n[Missing](gone.md)\n')
        pr = self.project(skip_dirs=['docs/fixtures', '.agents/custom'])
        pages, _, _, _ = check_docs(pr, Report())
        self.assertNotIn('docs/fixtures/bad.md', {pr.rel(page.path) for page in pages})
        self.assertIn('docs/fixtures-old/kept.md', {pr.rel(page.path) for page in pages})
        self.assertTrue(target_excluded(pr, self.root / 'docs/fixtures/bad.md'))
        self.assertEqual(list(walk_md(self.root / 'docs/fixtures', root=self.root,
                                      exclusions=pr.skip_dirs)), [])
        code, out = support.check(self.root)
        self.assertNotIn('gone.md', out)
        self.assertNotEqual(code, 2, out)

    def test_excluded_page_cannot_bridge_document_reachability(self):
        self.write('docs/README.md', '# Index\n\n[Bridge](fixtures/bridge.md)\n')
        self.write('docs/fixtures/bridge.md', '# Bridge\n\n[Feature](../feature.md)\n')
        pr = self.project(skip_dirs=['docs/fixtures'])
        report = Report()
        _, _, _, reachable = check_docs(pr, report)
        self.assertNotIn(self.root / 'docs/feature.md', reachable)
        self.assertTrue(any(item[0] == 'docs/feature.md' and item[3] == 'D4'
                            for item in report.items))
        self.assertFalse(any(item[3] == 'D1' for item in report.items))

    def test_external_docs_keep_basename_scope_below_walk_root(self):
        external = self.base / 'build/manual'
        support.w(external / 'README.md', '# Index\n\n[Page](page.md)\n')
        support.w(external / 'page.md', '# Page\n')
        support.w(external / 'build/ignored.md', '# Ignored\n')
        support.w(external / 'tests/fixtures/kept.md', '# Kept\n')
        pr = self.project(docs='../build/manual', skip_dirs=['tests/fixtures'])
        pages = list(walk_md(pr.docs, root=pr.root, exclusions=pr.skip_dirs))
        self.assertEqual({path.relative_to(external).as_posix() for path in pages},
                         {'README.md', 'page.md', 'tests/fixtures/kept.md'})
        _, _, _, reachable = check_docs(pr, Report())
        self.assertIn(external / 'page.md', reachable)

    def test_checker_configuration_does_not_leak_between_runs_or_roots(self):
        self.mark('private/bad.py', 'docs/missing.md#part')
        original = set(SKIP_DIRS)
        for skip, expected in ((['private'], False), ([], True)):
            self.project(skip_dirs=skip)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                with patch.object(sys, 'argv', ['lipi', '--root', str(self.root), '--format', 'json']):
                    main()
            self.assertEqual('T1' in output.getvalue(), expected, output.getvalue())
        self.assertEqual(SKIP_DIRS, original)
        other = self.base / 'other'
        support.w(other / 'lipi.json', '{}\n')
        support.w(other / 'private/bad.py', '# %s absent.md\n' % support.TAG)
        pr = Project(other, load_config(other, None))
        rep = Report()
        scan_code(pr, rep)
        self.assertTrue(rep.items)

    def test_audit_excludes_only_configured_path(self):
        for name in ('src/fixtures/a.py', 'src/fixtures-old/b.py'):
            self.write(name, 'def public_entry():\n    pass\n')
        self.project(skip_dirs=['src/fixtures'], entry=['^def public_entry'])
        code, out = support.check(self.root, '--audit')
        self.assertNotEqual(code, 2, out)
        self.assertNotIn('src/fixtures/a.py', out)
        self.assertIn('src/fixtures-old/b.py', out)
        self.assertIn('A3', out)

    def test_move_updates_same_consumers_as_check_and_slice(self):
        support.git_init(self.root)
        names = ['tests/fixtures/a.py', 'src/fixtures/b.py', 'tests/fixtures-old/c.py']
        for name in names:
            self.mark(name)
        self.project(skip_dirs=['tests/fixtures'])
        support.commit(self.root)
        code, out = support.cli(self.root, 'mv', 'docs/feature.md', 'docs/new.md', '--apply')
        self.assertEqual(code, 0, out)
        for name in names:
            expected = 'docs/feature.md' if name == names[0] else 'docs/new.md'
            self.assertIn(expected, (self.root / name).read_text())

    def test_neighbor_uses_own_root_for_targets_code_and_move_notices(self):
        neighbor = self.base / 'neighbor'
        support.w(neighbor / 'lipi.json', json.dumps({
            'skip_dirs': ['tests/fixtures'],
            'repos': {'origin': {'path': '../project', 'read': ['docs']}},
        }))
        for directory in ('tests/fixtures', 'src/fixtures'):
            support.w(neighbor / directory / 'page.md', '# Page\n')
            support.w(neighbor / directory / 'use.py',
                      '# %s origin::%s\n' % (support.TAG, self.target))
        pr = self.project(skip_dirs=['src/fixtures'], repos={
            'neighbor': {'path': '../neighbor', 'read': ['docs', 'code', 'tests']}})
        source = pr.sources.get('neighbor')
        self.assertIsNone(source.unavailable_reason)
        self.assertIsNone(source.resolve_path('tests/fixtures/page.md'))
        self.assertEqual(source.resolve_path('src/fixtures/page.md'), neighbor / 'src/fixtures/page.md')
        notices = neighbor_notices(pr, {self.root / 'docs/feature.md': self.root / 'docs/new.md'})
        self.assertEqual(len(notices), 1, notices)
        self.assertIn(support.localized('1 trace marker', '1 метка'), notices[0])


if __name__ == '__main__':
    unittest.main()
