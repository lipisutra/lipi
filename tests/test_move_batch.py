"""Перенос каталога и списка: общий план, сохранение связей и полный откат."""
import json
import os
import stat
import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi import move, move_neighbors, move_transaction
from lipi.checker.config import load_config
from lipi.checker.model import Project


# @trace docs/ru/move.md#scope,docs/ru/move.md#plan,docs/ru/move.md#apply,ADR-017
class MoveBatch(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='lipi-move-batch-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        support.git_init(self.root)
        self.write('lipi.json', json.dumps({'docs': 'docs'}))
        self.write('README.md', '[Page](docs/page.md#part)\n')
        self.write('docs/page.md', '# Page\n\n## Part <a id="part"></a>\n\n'
                   '[Root](../README.md) [Nested](nested/other.md) '
                   '![Picture](assets/pic.png)\n')
        self.write('docs/nested/other.md', '[Page](../page.md#part)\n')
        support.wb(self.root / 'docs/assets/pic.png', b'\x89PNG\x00\xff')
        support.wb(self.root / 'docs/nested/unreferenced.dat', b'\x00\xffbinary')
        self.write('src/unrelated.py', 'value = 1\n')
        self.commit()

    def write(self, name, text):
        support.w(self.root / name, text)

    def read(self, name):
        return (self.root / name).read_text(encoding='utf-8')

    def git(self, *args):
        code, output = support.git(self.root, *args)
        self.assertEqual(code, 0, output)
        return output

    def commit(self):
        code, output = support.commit(self.root)
        self.assertEqual(code, 0, output)

    def snapshot(self):
        tree = {str(path.relative_to(self.root)):
                path.read_bytes() if path.is_file() else None
                for path in self.root.rglob('*')
                if '.git' not in path.relative_to(self.root).parts}
        return tree, (self.root / '.git/index').read_bytes()

    def command(self, *args, cwd=None):
        code, output = support.cli(cwd or self.root, 'mv', *args)
        self.assertEqual(code, 0, output)
        return output

    def refuse(self, *args):
        before = self.snapshot()
        code, output = support.cli(self.root, 'mv', *args, '--apply')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.snapshot(), before, output)
        return output

    def manifest(self, contents):
        self.write('moves.txt', contents)
        return self.root / 'moves.txt'

    def unrelated_work(self):
        self.write('src/unrelated.py', 'value = 2\n')
        self.git('add', 'src/unrelated.py')
        self.write('src/unrelated.py', 'value = 3\n')
        self.write('local.txt', 'untracked work\n')

    def test_directory_moves_every_tracked_asset_and_keeps_internal_targets(self):
        support.wb(self.root / 'docs/nested/raw.py', b'\x00\xffbinary')
        self.commit()
        original = self.read('docs/page.md')
        self.command('docs', 'manual', '--apply')
        self.assertEqual(self.read('manual/page.md'), original)
        self.assertEqual(self.read('manual/nested/other.md'), '[Page](../page.md#part)\n')
        self.assertEqual(self.read('README.md'), '[Page](manual/page.md#part)\n')
        self.assertEqual((self.root / 'manual/assets/pic.png').read_bytes(), b'\x89PNG\x00\xff')
        self.assertEqual((self.root / 'manual/nested/unreferenced.dat').read_bytes(), b'\x00\xffbinary')
        self.assertEqual((self.root / 'manual/nested/raw.py').read_bytes(), b'\x00\xffbinary')
        tracked = self.git('ls-files').splitlines()
        self.assertFalse(any(name.startswith('docs/') for name in tracked))
        self.assertIn('manual/nested/unreferenced.dat', tracked)

    def test_directory_into_itself_rebases_outgoing_and_root_relative_markers(self):
        self.write('docs/script.py', '# %s docs/page.md#part\n' % support.TAG)
        self.write('docs/summary.md', '<!-- covers: docs/page.md, docs/nested/other.md -->\n')
        self.commit()
        original = self.read('docs/page.md')
        self.command('docs', 'docs/ru', '--apply')
        self.assertEqual(self.read('docs/ru/page.md'), original.replace('../README.md', '../../README.md'))
        self.assertEqual(self.read('docs/ru/nested/other.md'), '[Page](../page.md#part)\n')
        self.assertEqual(self.read('docs/ru/script.py'), '# %s docs/ru/page.md#part\n' % support.TAG)
        self.assertEqual(self.read('docs/ru/summary.md'),
                         '<!-- covers: docs/ru/page.md, docs/ru/nested/other.md -->\n')
        self.assertFalse((self.root / 'docs/ru/ru').exists())

    def test_list_uses_both_new_addresses_for_cross_links(self):
        self.manifest('docs/page.md guide/index.md\ndocs/nested/other.md reference/deep/other.md\n')
        self.command('--from', 'moves.txt', '--apply')
        self.assertIn('[Nested](../reference/deep/other.md)', self.read('guide/index.md'))
        self.assertIn('![Picture](../docs/assets/pic.png)', self.read('guide/index.md'))
        self.assertEqual(self.read('reference/deep/other.md'), '[Page](../../guide/index.md#part)\n')
        self.assertEqual(self.read('README.md'), '[Page](guide/index.md#part)\n')

    def test_list_filename_is_from_cwd_but_quoted_entries_are_from_root(self):
        self.write('docs/a page.md', '[Other](nested/other.md)\n')
        self.write('docs/hash#page.md', '# Hash\n')
        self.commit()
        self.write('docs/moves.txt', '\n  # comment\n"docs/a page.md" "guide/a page.md"\n'
                   '"docs/hash#page.md" "guide/hash#page.md"\n')
        self.command('--from', 'moves.txt', '--apply', cwd=self.root / 'docs')
        self.assertEqual(self.read('guide/a page.md'), '[Other](../docs/nested/other.md)\n')
        self.assertEqual(self.read('guide/hash#page.md'), '# Hash\n')
        self.assertFalse((self.root / 'docs/guide').exists())

    def test_directory_positional_paths_are_from_cwd(self):
        self.command('nested', 'translated/nested', '--apply', cwd=self.root / 'docs')
        self.assertTrue((self.root / 'docs/translated/nested/other.md').is_file())
        self.assertIn('[Nested](translated/nested/other.md)', self.read('docs/page.md'))

    def test_nested_project_keeps_git_relative_manifest_and_cleanliness_checks(self):
        project = self.root / 'app'
        self.write('app/lipi.json', '{}\n')
        self.write('app/docs/old.md', '# Old\n')
        self.write('app/README.md', '[Old](docs/old.md)\n')
        self.commit()
        self.write('app/moves.txt', 'app/docs/old.md app/new.md\n')
        for staged in (False, True):
            self.write('app/README.md', '[Old](docs/old.md)\n\nLocal edit.\n')
            if staged:
                self.git('add', 'app/README.md')
            before = self.snapshot()
            code, output = support.cli(project, 'mv', '--from', 'moves.txt', '--apply')
            self.assertEqual(code, 2, output)
            self.assertIn(support.localized('uncommitted changes', 'незакоммиченные'), output)
            self.assertEqual(self.snapshot(), before)
            self.git('reset', '--hard', 'HEAD')
        self.command('--from', 'moves.txt', '--apply', cwd=project)
        self.assertEqual(self.read('app/new.md'), '# Old\n')
        self.assertEqual(self.read('app/README.md'), '[Old](new.md)\n')

    def test_dry_run_lists_entire_batch_without_changing_tree_or_index(self):
        self.manifest('docs/page.md guide/page.md\ndocs/nested reference\n')
        self.unrelated_work()
        before = self.snapshot()
        output = self.command('--from', 'moves.txt')
        self.assertEqual(self.snapshot(), before)
        for name in ('docs/page.md', 'guide/page.md', 'docs/nested/other.md',
                     'reference/other.md', 'reference/unreferenced.dat', 'README.md'):
            self.assertIn(name, output)

    def test_planning_clean_files_with_stale_git_stat_cache_preserves_exact_index(self):
        self.git('config', 'diff.autoRefreshIndex', 'true')
        for name in ('README.md', 'docs/page.md'):
            path = self.root / name
            stamp = path.stat()
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns - 60_000_000_000))
        before = self.snapshot()
        plan = move.make_plan(self.root, 'docs', 'manual')
        self.assertIn(self.root / 'docs/page.md', plan.moves)
        self.assertEqual(self.snapshot(), before)

    def test_planning_respects_crlf_normalization_with_stale_git_stat_cache(self):
        self.write('.gitattributes', 'docs/page.md text eol=crlf\n')
        self.commit()
        path = self.root / 'docs/page.md'
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        stamp = path.stat()
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 60_000_000_000))
        before = self.snapshot()
        plan = move.make_plan(self.root, 'docs', 'manual')
        self.assertIn(path, plan.moves)
        self.assertEqual(self.snapshot(), before)

    def test_untracked_and_excluded_files_remain_and_history_is_not_read(self):
        self.write('docs/history/record.md', '[Old](../page.md)\n')
        self.write('docs/generated/page.md', '[Old](../page.md)\n')
        support.set_config(self.root, skip_dirs=['generated'])
        self.commit()
        self.write('docs/local.md', '# Local draft\n')
        preserved = {name: self.read(name) for name in
                     ('docs/history/record.md', 'docs/generated/page.md', 'docs/local.md')}
        read_bytes, read_text = Path.read_bytes, Path.read_text

        def guarded_bytes(path, *args, **kwargs):
            self.assertNotIn('history', path.relative_to(self.root).parts)
            return read_bytes(path, *args, **kwargs)

        def guarded_text(path, *args, **kwargs):
            self.assertNotIn('history', path.relative_to(self.root).parts)
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_bytes', guarded_bytes), patch.object(Path, 'read_text', guarded_text):
            plan = move.make_plan(self.root, 'docs', 'manual')
            move.apply_plan(plan)
        output = '\n'.join(plan.notices)
        for name, contents in preserved.items():
            self.assertEqual(self.read(name), contents)
            self.assertIn(name, output)
        self.assertTrue((self.root / 'manual/page.md').exists())

    def test_conflicting_sources_and_destinations_refuse_before_any_write(self):
        cases = (
            'docs/page.md one.md\ndocs/page.md two.md\n',
            'docs one\ndocs/nested two\n',
            'docs one\ndocs/page.md two.md\n',
            'docs/page.md same.md\ndocs/nested/other.md same.md\n',
            'docs/page.md docs/page.md\n',
            'docs/page.md README.md\n',
            'docs/page.md README.md/child.md\n',
            'docs/page.md output.md\ndocs/nested/other.md output.md/child.md\n',
        )
        for contents in cases:
            with self.subTest(contents=contents):
                self.manifest(contents)
                self.refuse('--from', 'moves.txt')

    def test_invalid_list_and_argument_combinations_refuse_before_write(self):
        for contents in ('', '# only a comment\n', 'docs/page.md\n',
                         'docs/page.md one.md extra\n', '"docs/page.md one.md\n'):
            with self.subTest(contents=contents):
                self.manifest(contents)
                self.refuse('--from', 'moves.txt')
        self.manifest('docs/page.md new.md\n')
        self.refuse('docs/page.md', 'new.md', '--from', 'moves.txt')

    def test_directory_and_single_entry_list_reject_dirty_moved_and_incoming_files(self):
        self.manifest('docs/page.md guide/page.md\n')
        for args in (('docs', 'manual'), ('--from', 'moves.txt')):
            for name in ('docs/page.md', 'README.md'):
                for staged in (False, True):
                    with self.subTest(args=args, name=name, staged=staged):
                        original = self.read(name)
                        self.write(name, original + '\nLocal edit.\n')
                        if staged:
                            self.git('add', name)
                        output = self.refuse(*args)
                        self.assertIn(name, output)
                        self.git('reset', '--hard', 'HEAD')

    def test_untracked_incoming_reference_blocks_directory_and_list(self):
        self.manifest('docs/page.md guide/page.md\n')
        self.write('local.md', '[Page](docs/page.md)\n')
        for args in (('docs', 'manual'), ('--from', 'moves.txt')):
            with self.subTest(args=args):
                self.assertIn('local.md', self.refuse(*args))

    def test_directory_rejects_binary_content_and_mode_changes_in_worktree_or_index(self):
        self.git('config', 'core.filemode', 'true')
        name = 'docs/assets/pic.png'
        path = self.root / name
        for change in ('content', 'mode'):
            for staged in (False, True):
                with self.subTest(change=change, staged=staged):
                    if change == 'content':
                        path.write_bytes(b'\x89PNG\x00\xfe')
                        if staged:
                            self.git('add', name)
                    elif staged:
                        self.git('update-index', '--chmod=+x', '--', name)
                    else:
                        path.chmod(path.stat().st_mode | stat.S_IXUSR)
                        if not path.stat().st_mode & stat.S_IXUSR:
                            self.skipTest('filesystem does not support executable bits')
                    mode = path.stat().st_mode
                    self.assertIn(name, self.refuse('docs', 'manual'))
                    self.assertEqual(path.stat().st_mode, mode)
                    self.git('reset', '--hard', 'HEAD')

    def test_unrelated_staged_and_worktree_content_survives_success(self):
        self.unrelated_work()
        staged = self.git('show', ':src/unrelated.py')
        self.command('docs', 'manual', '--apply')
        self.assertEqual(self.read('src/unrelated.py'), 'value = 3\n')
        self.assertEqual(self.git('show', ':src/unrelated.py'), staged)
        self.assertEqual(self.read('local.txt'), 'untracked work\n')

    def test_post_rename_error_and_interrupt_restore_tree_and_exact_index(self):
        self.unrelated_work()
        real_git = move._git
        for exception in (OSError, KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                plan = move.make_plan(self.root, 'docs', 'manual/deep')
                before = self.snapshot()
                renames = []

                def fail_after_second_rename(root, *args, **kwargs):
                    result = real_git(root, *args, **kwargs)
                    if args[0] == 'mv':
                        renames.append(args)
                        if len(renames) == 2:
                            raise exception('injected after git mv')
                    return result

                with patch.object(move, '_git', fail_after_second_rename):
                    with self.assertRaises((move.MoveError, exception)):
                        move.apply_plan(plan)
                self.assertEqual(len(renames), 2)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / '.git/index.lock').exists())

    def test_replanning_after_rollback_ignores_binary_stat_changes_and_preserves_exact_index(self):
        self.unrelated_work()
        plan = move.make_plan(self.root, 'docs', 'manual/deep')
        before = self.snapshot()
        real_git = move._git
        renames = []

        def fail_after_second_rename(root, *args, **kwargs):
            result = real_git(root, *args, **kwargs)
            if args[0] == 'mv':
                renames.append(args)
                if len(renames) == 2:
                    raise OSError('injected after git mv')
            return result

        with patch.object(move, '_git', fail_after_second_rename):
            with self.assertRaises(move.MoveError):
                move.apply_plan(plan)
        self.assertEqual(len(renames), 2)
        self.assertEqual(self.snapshot(), before)
        path = self.root / 'docs/assets/pic.png'
        stamp = path.stat()
        # Separate stat times without sleeping; keep the index entry non-racy.
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 60_000_000_000))
        os.utime(plan.index, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 120_000_000_000))
        repeated = move.make_plan(self.root, 'docs', 'manual/deep')
        self.assertEqual(repeated.moves, plan.moves)
        self.assertEqual(self.snapshot(), before)

    def test_post_link_write_error_and_interrupt_restore_tree_and_exact_index(self):
        self.unrelated_work()
        real_write = move_transaction._write
        for exception in (OSError, KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                plan = move.make_plan(self.root, 'docs', 'manual/deep')
                before = self.snapshot()
                injected = []

                def fail_after_write(path, data, mode):
                    result = real_write(path, data, mode)
                    if path == self.root / 'README.md' and not injected:
                        injected.append(path)
                        raise exception('injected after link write')
                    return result

                with patch.object(move_transaction, '_write', fail_after_write):
                    with self.assertRaises((move.MoveError, exception)):
                        move.apply_plan(plan)
                self.assertEqual(injected, [self.root / 'README.md'])
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / '.git/index.lock').exists())

    def test_failed_destination_cleanup_reports_incomplete_rollback(self):
        self.unrelated_work()
        plan = move.make_plan(self.root, 'docs', 'manual/deep')
        before_tree, before_index = self.snapshot()
        real_git, real_rmdir = move._git, Path.rmdir
        destination = self.root / 'manual/deep'

        def fail_after_rename(root, *args, **kwargs):
            result = real_git(root, *args, **kwargs)
            if args[0] == 'mv':
                raise OSError('injected application failure')
            return result

        def deny_destination_cleanup(path):
            if path == destination:
                raise PermissionError('injected destination cleanup denial')
            return real_rmdir(path)

        with patch.object(move, '_git', fail_after_rename), \
                patch.object(Path, 'rmdir', deny_destination_cleanup):
            with self.assertRaisesRegex(move.MoveError, support.localized('rollback incomplete', 'откат неполон')) as caught:
                move.apply_plan(plan)
        self.assertIn('injected destination cleanup denial', str(caught.exception))
        after_tree, after_index = self.snapshot()
        self.assertEqual(after_index, before_index)
        self.assertEqual(after_tree, {**before_tree, 'manual': None, 'manual/deep': None})
        self.assertFalse((self.root / '.git/index.lock').exists())

    def test_changed_file_after_plan_is_rejected_without_partial_application(self):
        plan = move.make_plan(self.root, 'docs', 'manual')
        self.write('README.md', self.read('README.md') + '\nConcurrent edit.\n')
        before = self.snapshot()
        with self.assertRaises(move.MoveError):
            move.apply_plan(plan)
        self.assertEqual(self.snapshot(), before)

    def test_post_index_install_interrupt_restores_index_and_removed_source_directories(self):
        self.unrelated_work()
        (self.root / 'docs').chmod(0o777)
        plan = move.make_plan(self.root, 'docs', 'manual/deep')
        before = self.snapshot()
        real_replace = os.replace
        installed = []

        def interrupt_after_install(source, target, *args, **kwargs):
            result = real_replace(source, target, *args, **kwargs)
            if Path(target) == plan.index and not installed:
                installed.append(Path(target))
                raise KeyboardInterrupt('injected after installing real Git index')
            return result

        with patch.object(move.os, 'replace', interrupt_after_install):
            with self.assertRaises((move.MoveError, KeyboardInterrupt)):
                move.apply_plan(plan)
        self.assertEqual(installed, [plan.index])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(stat.S_IMODE((self.root / 'docs').stat().st_mode), 0o777)
        self.assertFalse((self.root / '.git/index.lock').exists())

    def test_hundred_moves_parse_each_eligible_project_file_once(self):
        for number in range(100):
            self.write('pages/p%d.md' % number,
                       '[Next](p%d.md)\n' % ((number + 1) % 100))
        self.commit()
        self.manifest(''.join('pages/p%d.md new/section%d/p%d.md\n' % (number, number % 3, number)
                              for number in range(100)))
        with patch.object(move, 'replacements', wraps=move.replacements) as parse:
            plan = move.make_plan(self.root, from_file='moves.txt')
        counts = Counter(call.kwargs['path'] for call in parse.call_args_list)
        expected = {self.root / name for name in self.git('ls-files').splitlines()
                    if Path(name).suffix in {'.md', '.py'}}
        self.assertEqual(set(counts), expected)
        self.assertEqual(set(counts.values()), {1})
        move.apply_plan(plan)
        self.assertEqual(self.read('new/section0/p0.md'), '[Next](../section1/p1.md)\n')
        self.assertEqual(self.read('new/section0/p99.md'), '[Next](p0.md)\n')

    def test_neighbor_batch_report_counts_each_target_line_once_in_one_parse(self):
        temporary = TemporaryDirectory(prefix='lipi-move-neighbor-')
        self.addCleanup(temporary.cleanup)
        neighbor = Path(temporary.name).resolve()
        support.git_init(neighbor)
        support.w(neighbor / 'lipi.json', json.dumps({
            'repos': {'upstream': {'path': os.path.relpath(self.root, neighbor), 'read': ['docs']}}}))
        support.w(neighbor / 'src/client.py',
                  '# %s upstream::docs/page.md#part, upstream::docs/page.md#other, '
                  'upstream::docs/nested/other.md, upstream::docs/nested/other.md#section\n' % support.TAG)
        code, output = support.commit(neighbor)
        self.assertEqual(code, 0, output)
        support.set_config(self.root, repos={
            'client': {'path': os.path.relpath(neighbor, self.root), 'read': ['code']}})
        project = Project(self.root, load_config(self.root, None))
        moves = {self.root / old: self.root / new for old, new in (
            ('docs/page.md', 'manual/page.md'),
            ('docs/nested/other.md', 'manual/nested/other.md'))}
        before = (neighbor / 'src/client.py').read_bytes(), (neighbor / '.git/index').read_bytes()
        with patch.object(move_neighbors, 'trace_targets', wraps=move_neighbors.trace_targets) as parse:
            notices = move_neighbors.neighbor_notices(project, moves)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(len(notices), 2)
        for old in ('docs/page.md', 'docs/nested/other.md'):
            self.assertEqual(sum(old in notice and ' 1 ' in notice for notice in notices), 1)
        self.assertEqual(((neighbor / 'src/client.py').read_bytes(),
                          (neighbor / '.git/index').read_bytes()), before)


if __name__ == '__main__':
    unittest.main()
