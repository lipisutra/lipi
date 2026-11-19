"""Единый план: детерминированные ошибки после записи и полный откат."""
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi import move, move_transaction as transaction


class MoveTransactionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-transaction-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        support.git_init(self.root)
        for name, data in (('old/page.md', b'page\n'), ('remove.txt', b'obsolete\n'),
                           ('config.json', b'old\n'), ('unrelated.txt', b'committed\n')):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / 'old').chmod(0o750)
        (self.root / 'config.json').chmod(0o640)
        self.assertEqual(support.commit(self.root)[0], 0)
        (self.root / 'unrelated.txt').write_bytes(b'staged\n')
        self.assertEqual(support.git(self.root, 'add', 'unrelated.txt')[0], 0)
        (self.root / 'unrelated.txt').write_bytes(b'worktree\n')
        (self.root / 'untracked.txt').write_bytes(b'leave alone\n')

    def change(self, name, after, mode=None):
        path = self.root / name
        return SimpleNamespace(path=path, before=path.read_bytes() if path.exists() else None,
                               after=after, stamp=move._stamp(path) if path.exists() else None,
                               edits=[], mode=mode)

    def plan(self, git=True):
        index = self.root / '.git/index' if git else None
        return SimpleNamespace(
            root=self.root, moves={self.root / 'old/page.md': self.root / 'new/deep/page.md'},
            changes=[self.change('old/page.md', b'new page\n'),
                     self.change('remove.txt', None),
                     self.change('config.json', b'new config\n', 0o600),
                     self.change('bin/hook', b'#!/bin/sh\n', 0o755)],
            source_dirs=[self.root / 'old'], index=index,
            index_before=index.read_bytes() if index else None,
            reviews=None, config={})

    def snapshot(self):
        tree = {}
        for path in self.root.rglob('*'):
            if '.git' in path.relative_to(self.root).parts:
                continue
            tree[path.relative_to(self.root).as_posix()] = (
                path.read_bytes() if path.is_file() else None,
                stat.S_IMODE(path.stat().st_mode))
        index = self.root / '.git/index'
        return tree, index.read_bytes(), stat.S_IMODE(index.stat().st_mode)

    def assert_clean_temporaries(self):
        self.assertFalse(list((self.root / '.git').glob('lipi-mv-*')))
        self.assertFalse((self.root / '.git/index.lock').exists())
        self.assertFalse(list(self.root.rglob('.lipi-write-*')))

    def test_success_preserves_unrelated_staged_and_worktree(self):
        plan = self.plan()
        staged = move._git(self.root, 'show', ':unrelated.txt')
        transaction.apply_transaction(plan)
        self.assertFalse((self.root / 'old').exists())
        self.assertEqual((self.root / 'new/deep/page.md').read_bytes(), b'new page\n')
        self.assertFalse((self.root / 'remove.txt').exists())
        self.assertEqual(stat.S_IMODE((self.root / 'bin/hook').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'config.json').stat().st_mode), 0o600)
        self.assertEqual(move._git(self.root, 'show', ':unrelated.txt'), staged)
        self.assertEqual((self.root / 'unrelated.txt').read_bytes(), b'worktree\n')
        self.assertEqual(move._git(self.root, 'show', ':new/deep/page.md'), b'page\n')
        self.assertEqual(move._git(self.root, 'show', ':remove.txt'), b'obsolete\n')
        self.assert_clean_temporaries()

    def test_every_file_write_and_delete_rolls_back_on_error_or_interrupt(self):
        real_write = transaction._write
        for exception in (OSError, KeyboardInterrupt):
            for nth in range(1, 5):
                with self.subTest(exception=exception.__name__, write=nth):
                    plan, before = self.plan(), self.snapshot()
                    calls = []
                    def fail_after_write(path, data, mode):
                        real_write(path, data, mode)
                        calls.append(path)
                        if len(calls) == nth:
                            raise exception('after write')
                    with patch.object(transaction, '_write', fail_after_write):
                        with self.assertRaisesRegex(move.MoveError, support.localized('changes rolled back', 'изменения отменены')):
                            transaction.apply_transaction(plan)
                    self.assertEqual(self.snapshot(), before)
                    self.assert_clean_temporaries()

    def test_git_move_and_index_publication_roll_back_after_side_effect(self):
        for stage in ('move', 'index'):
            for exception in (OSError, KeyboardInterrupt):
                with self.subTest(stage=stage, exception=exception.__name__):
                    plan, before = self.plan(), self.snapshot()
                    real_git, real_replace = move._git, os.replace
                    injected = []
                    def fail_git(root, *args, **kwargs):
                        result = real_git(root, *args, **kwargs)
                        if args[0] == 'mv' and stage == 'move' and not injected:
                            injected.append(True)
                            raise exception('after git mv')
                        return result
                    def fail_replace(source, destination):
                        result = real_replace(source, destination)
                        if Path(destination) == plan.index and stage == 'index' and not injected:
                            injected.append(True)
                            raise exception('after index replace')
                        return result
                    with patch.object(move, '_git', fail_git), patch.object(os, 'replace', fail_replace):
                        with self.assertRaisesRegex(move.MoveError, support.localized('changes rolled back', 'изменения отменены')):
                            transaction.apply_transaction(plan)
                    self.assertEqual(self.snapshot(), before)
                    self.assert_clean_temporaries()

    def test_directory_removal_rolls_back_original_mode(self):
        plan, before = self.plan(), self.snapshot()
        real_rmdir = Path.rmdir
        injected = []
        def fail_after_rmdir(path):
            result = real_rmdir(path)
            if path == self.root / 'old' and not injected:
                injected.append(True)
                raise KeyboardInterrupt()
            return result
        with patch.object(Path, 'rmdir', fail_after_rmdir):
            with self.assertRaises(move.MoveError):
                transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_temporaries()

    def test_directory_creation_failure_after_effect_rolls_back(self):
        plan, before = self.plan(), self.snapshot()
        real_mkdir = Path.mkdir
        injected = []
        def fail_after_mkdir(path, *args, **kwargs):
            result = real_mkdir(path, *args, **kwargs)
            if path == self.root / 'new/deep' and not injected:
                injected.append(True)
                raise KeyboardInterrupt()
            return result
        with patch.object(Path, 'mkdir', fail_after_mkdir):
            with self.assertRaises(move.MoveError):
                transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_temporaries()

    def test_no_git_create_delete_and_mode_only_change(self):
        plan = self.plan(git=False)
        plan.moves, plan.source_dirs = {}, []
        plan.changes = [self.change('config.json', b'old\n', 0o700),
                        self.change('remove.txt', None), self.change('new/file', b'created\n')]
        index = (self.root / '.git/index').read_bytes()
        with patch.object(move, '_git', side_effect=AssertionError('Git disabled')):
            transaction.apply_transaction(plan)
        self.assertEqual((self.root / '.git/index').read_bytes(), index)
        self.assertEqual(stat.S_IMODE((self.root / 'config.json').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / 'new/file').stat().st_mode), 0o644)
        self.assertFalse((self.root / 'remove.txt').exists())

    def test_no_git_rolls_back_new_nested_tree_and_modes(self):
        plan = self.plan(git=False)
        plan.moves, plan.source_dirs = {}, []
        plan.changes = [self.change('config.json', b'old\n', 0o700),
                        self.change('remove.txt', None), self.change('new/deep/file', b'created\n')]
        before, real_write = self.snapshot(), transaction._write
        injected = []
        def fail_after_create(path, data, mode):
            real_write(path, data, mode)
            if path.name == 'file' and not injected:
                injected.append(True)
                raise OSError('after creation')
        with patch.object(transaction, '_write', fail_after_create):
            with self.assertRaises(move.MoveError):
                transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_temporaries()

    def test_revalidates_existing_and_absent_files_before_any_mutation(self):
        for kind in ('bytes', 'mode', 'new', 'index'):
            with self.subTest(kind=kind):
                plan = self.plan()
                path = self.root / 'config.json'
                if kind == 'bytes':
                    path.write_bytes(b'external\n')
                elif kind == 'mode':
                    path.chmod(0o600)
                elif kind == 'new':
                    path = self.root / 'bin/hook'
                    path.parent.mkdir()
                    path.write_bytes(b'external\n')
                else:
                    (self.root / 'unrelated.txt').write_bytes(b'another staged\n')
                    move._git(self.root, 'add', 'unrelated.txt')
                before = self.snapshot()
                with self.assertRaises(move.MoveError):
                    transaction.apply_transaction(plan)
                self.assertEqual(self.snapshot(), before)
                if kind == 'new':
                    path.unlink()
                    path.parent.rmdir()

    def test_planned_empty_directories_are_created_and_rolled_back(self):
        plan = self.plan(git=False)
        plan.changes, plan.moves, plan.source_dirs = [], {}, []
        plan.directories = [self.root / 'workflow/plan', self.root / 'workflow/audit']
        before, real_mkdir = self.snapshot(), Path.mkdir
        injected = []
        def fail_after_mkdir(path, *args, **kwargs):
            result = real_mkdir(path, *args, **kwargs)
            if path == plan.directories[-1] and not injected:
                injected.append(True)
                raise OSError('after empty directory')
            return result
        with patch.object(Path, 'mkdir', fail_after_mkdir):
            with self.assertRaises(move.MoveError):
                transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)
        transaction.apply_transaction(plan)
        for directory in plan.directories:
            self.assertTrue(directory.is_dir())
            self.assertEqual(list(directory.iterdir()), [])

    def test_concurrent_edit_is_not_overwritten_by_rollback(self):
        plan, real_write = self.plan(), transaction._write
        target = self.root / 'new/deep/page.md'
        injected = []
        def interfere(path, data, mode):
            real_write(path, data, mode)
            if path == self.root / 'config.json' and not injected:
                injected.append(True)
                target.write_bytes(b'concurrent edit\n')
                raise OSError('concurrent writer')
        with patch.object(transaction, '_write', interfere):
            with self.assertRaisesRegex(move.MoveError, support.localized('rollback incomplete', 'откат неполон')):
                transaction.apply_transaction(plan)
        self.assertEqual(target.read_bytes(), b'concurrent edit\n')
        self.assertEqual((self.root / '.git/index').read_bytes(), plan.index_before)
        self.assert_clean_temporaries()


if __name__ == '__main__':
    unittest.main()
