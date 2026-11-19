"""Просмотр переносится только вместе с доказанными адресными заменами."""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi import move, move_links
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.move_reviews import TransferError, prepare_transfer
from lipi.checker.reviews import (REVIEWS_NAME, ReviewContext, ReviewError,
                          load_reviews, serialize_reviews)


# @trace docs/ru/review.md#move,docs/ru/move.md#apply,ADR-019
class MoveReviews(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='lipi-move-reviews-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        support.git_init(self.root)
        self.write('lipi.json', json.dumps({'docs': 'docs'}))
        self.write('docs/old.md', '# Page\n\n## Part <a id="part"></a>\n'
                   '[Other](other.md#other)\n')
        self.write('docs/other.md', '# Other\n\n## Other <a id="other"></a>\nText.\n')
        self.write('src/main.py', '# %s docs/old.md#part,docs/other.md#other\nvalue = 1\n' % support.TAG)
        self.commit()
        pair = next(pair for pair in self.context().pairs if pair['target']['anchor'] == 'part')
        self.entry = {key: pair[key] for key in ('id', 'relation', 'source', 'target')}
        self.entry.update(reviewer='reader', reviewed_at='2026-01-02T03:04:05Z',
                          reason='Description still explains this behavior.',
                          head=self.git('rev-parse', 'HEAD').strip())
        self.registry = {'schema': 1, 'algorithm': 'sha256-lines-v1', 'entries': [self.entry]}
        self.state = self.root / REVIEWS_NAME
        self.state.parent.mkdir(parents=True)
        self.state.write_bytes(serialize_reviews(self.registry))
        self.commit()

    def write(self, path, text):
        support.w(self.root / path, text)

    def git(self, *args):
        code, output = support.git(self.root, *args)
        self.assertEqual(code, 0, output)
        return output

    def commit(self):
        code, output = support.commit(self.root)
        self.assertEqual(code, 0, output)

    def context(self):
        return ReviewContext(Project(self.root, load_config(self.root, None)))

    def snapshot(self):
        return ({str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                 for path in self.root.rglob('*') if '.git' not in path.relative_to(self.root).parts},
                (self.root / '.git/index').read_bytes())

    def assert_preserved(self):
        entry, = load_reviews(self.root)['entries']
        self.assertNotEqual(entry['id'], self.entry['id'])
        self.assertEqual(len(self.context().matching(entry)), 1)
        for key in ('reviewer', 'reviewed_at', 'reason', 'head'):
            self.assertEqual(entry[key], self.entry[key])
        return entry

    def test_preview_is_readonly_and_apply_preserves_both_changed_regions(self):
        before = self.snapshot()
        plan = move.make_plan(self.root, 'docs/old.md', 'docs/deep/new.md')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any(self.entry['id'] in notice and '→' in notice for notice in plan.notices))
        staged_state = self.git('show', ':' + REVIEWS_NAME)
        move.apply_plan(plan)
        entry = self.assert_preserved()
        self.assertEqual(entry['target']['path'], 'docs/deep/new.md')
        for side in ('source', 'target'):
            self.assertNotEqual(entry[side]['sha256'], self.entry[side]['sha256'])
        self.assertEqual(self.git('show', ':' + REVIEWS_NAME), staged_state)

    def test_address_edits_change_both_hashes_even_when_both_paths_stay(self):
        move.apply_plan(move.make_plan(self.root, 'docs/other.md', 'docs/new-other.md'))
        entry = self.assert_preserved()
        for side in ('source', 'target'):
            self.assertEqual(entry[side]['path'], self.entry[side]['path'])
            self.assertNotEqual(entry[side]['sha256'], self.entry[side]['sha256'])

    def test_directory_move_transfers_source_without_blame(self):
        with patch('subprocess.run', wraps=__import__('subprocess').run) as run:
            move.apply_plan(move.make_plan(self.root, 'src', 'lib'))
        self.assertFalse(any('blame' in call.args[0] for call in run.call_args_list))
        entry = self.assert_preserved()
        self.assertEqual(entry['source']['path'], 'lib/main.py')
        self.assertEqual(entry['source']['sha256'], self.entry['source']['sha256'])

    def test_single_move_preserves_dirty_registry_metadata_and_staged_version(self):
        self.registry['entries'][0]['reason'] = 'Updated explanation before move.'
        self.state.write_bytes(serialize_reviews(self.registry))
        staged = self.git('show', ':' + REVIEWS_NAME)
        move.apply_plan(move.make_plan(self.root, 'docs/old.md', 'docs/new.md'))
        self.assert_preserved()
        self.assertEqual(self.git('show', ':' + REVIEWS_NAME), staged)

    def test_bulk_refuses_dirty_worktree_and_index_registry(self):
        original = self.state.read_bytes()
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.state.write_bytes(original + b'\n')
                if staged:
                    self.git('add', REVIEWS_NAME)
                before = self.snapshot()
                with self.assertRaisesRegex(move.MoveError, support.localized('uncommitted changes', 'незакоммиченные')):
                    move.make_plan(self.root, 'src', 'lib')
                self.assertEqual(self.snapshot(), before)
                self.git('reset', '--', REVIEWS_NAME)
                self.state.write_bytes(original)

    def test_obsolete_and_ambiguous_are_reported_without_refresh(self):
        for ambiguous in (False, True):
            with self.subTest(ambiguous=ambiguous):
                original = '# %s docs/old.md#part,docs/other.md#other\nvalue = 1\n' % support.TAG
                self.write('src/main.py', original * 2 if ambiguous else original.replace('1', '2'))
                before = self.state.read_bytes()
                plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
                label = support.localized('Unchecked', 'Непроверенная') if ambiguous else support.localized('Obsolete', 'Устаревшая')
                self.assertTrue(any(label in notice for notice in plan.notices))
                self.assertEqual(plan.reviews.after, before)
                self.assertEqual(self.state.read_bytes(), before)

    def test_absent_registry_stays_absent(self):
        self.state.unlink()
        move.apply_plan(move.make_plan(self.root, 'docs/old.md', 'docs/new.md'))
        self.assertFalse(self.state.exists())

    def test_single_move_keeps_untracked_registry_untracked(self):
        self.git('rm', '--cached', REVIEWS_NAME)
        move.apply_plan(move.make_plan(self.root, 'docs/old.md', 'docs/new.md'))
        self.assert_preserved()
        self.assertNotIn(REVIEWS_NAME, self.git('ls-files').splitlines())

    def test_obsolete_registry_bytes_survive_applied_move(self):
        self.write('src/main.py', '# %s docs/old.md#part\nvalue = 2\n' % support.TAG)
        before = self.state.read_bytes()
        move.apply_plan(move.make_plan(self.root, 'docs/old.md', 'docs/new.md'))
        self.assertEqual(self.state.read_bytes(), before)

    def test_unmodified_counterpart_is_guarded_before_apply(self):
        plan = move.make_plan(self.root, 'src', 'lib')
        self.write('docs/old.md', (self.root / 'docs/old.md').read_text() + 'New content.\n')
        before = self.snapshot()
        with self.assertRaisesRegex(TransferError, support.localized('review region changed', 'область просмотра изменилась')):
            move.apply_plan(plan)
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_registry_refuses_before_any_write(self):
        self.state.write_text('{broken', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ReviewError):
            move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        self.assertEqual(self.snapshot(), before)

    def test_registry_race_and_unchanged_side_race_refuse_before_rename(self):
        for path in (self.state, self.root / 'src/main.py'):
            with self.subTest(path=path):
                original = path.read_bytes()
                plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
                path.write_bytes(original + b'\n')
                before = self.snapshot()
                with self.assertRaises((move.MoveError, ReviewError, TransferError)):
                    move.apply_plan(plan)
                self.assertEqual(self.snapshot(), before)
                path.write_bytes(original)

    def test_readonly_registry_refuses_before_write(self):
        self.state.chmod(0o444)
        self.addCleanup(self.state.chmod, 0o644)
        before = self.snapshot()
        with self.assertRaisesRegex(move.MoveError, support.localized('no write access', 'нет доступа')):
            move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        self.assertEqual(self.snapshot(), before)

    def test_failure_and_interrupt_restore_dirty_registry_and_exact_index(self):
        self.state.write_bytes(self.state.read_bytes() + b'\n')
        before = self.snapshot()
        for error in (OSError('synthetic failure'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
                replace = move.os.replace

                def fail_index(source, destination):
                    if Path(destination) == plan.index:
                        raise error
                    return replace(source, destination)

                with patch.object(move.os, 'replace', side_effect=fail_index):
                    with self.assertRaises(move.MoveError):
                        move.apply_plan(plan)
                self.assertEqual(self.snapshot(), before)

    def test_non_address_edit_is_never_treated_as_review(self):
        plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        changes = [change for change in plan.changes if change.path != self.state]
        source = next(change for change in changes if change.path.name == 'main.py')
        source.after = source.after.replace(b'value = 1', b'value = 2')
        with self.assertRaisesRegex(TransferError, support.localized('planned address replacement', 'адресной заменой')):
            prepare_transfer(Project(self.root, load_config(self.root, None)), plan.moves, changes)

    def test_review_transfer_parses_each_files_addresses_only_once(self):
        with patch.object(move_links, 'mask_examples', wraps=move_links.mask_examples) as markdown, \
                patch.object(move_links, 'trace_targets', wraps=move_links.trace_targets) as code:
            move.apply_plan(move.make_plan(self.root, 'docs/old.md', 'docs/deep/new.md'))
        self.assertEqual(markdown.call_count, 2)
        self.assertEqual(code.call_count, 1)
        self.assertEqual(code.call_args.args[1], self.root / 'src/main.py')
        self.assert_preserved()

    def test_changed_planned_edits_do_not_inherit_original_address_receipt(self):
        plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        changes = [change for change in plan.changes if change.path != self.state]
        source = next(change for change in changes if change.path.name == 'main.py')
        source.edits.clear()
        source.after = source.before
        with self.assertRaisesRegex(TransferError, support.localized('planned address replacement', 'адресной заменой')):
            prepare_transfer(Project(self.root, load_config(self.root, None)), plan.moves, changes)

    def test_excluded_symlink_source_is_preserved_as_unchecked(self):
        source = self.root / 'src/main.py'
        self.write('generated/main.py', source.read_text())
        source.unlink()
        source.symlink_to('../generated/main.py')
        support.set_config(self.root, skip_dirs=['generated'])
        before = self.state.read_bytes()
        plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        self.assertTrue(any(support.localized('Unchecked', 'Непроверенная') in notice for notice in plan.notices))
        move.apply_plan(plan)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertTrue(source.is_symlink())

    def test_in_root_symlink_source_is_not_refreshed_as_a_regular_file(self):
        source = self.root / 'src/main.py'
        self.write('src/actual.py', source.read_text())
        source.unlink()
        source.symlink_to('actual.py')
        before = self.state.read_bytes()
        plan = move.make_plan(self.root, 'docs/other.md', 'docs/new-other.md')
        self.assertTrue(any(support.localized('Unchecked', 'Непроверенная') in notice for notice in plan.notices))
        move.apply_plan(plan)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertTrue(source.is_symlink())

    def test_existing_future_id_collision_refuses(self):
        plan = move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        future = json.loads(plan.reviews.after)['entries'][0]
        self.registry['entries'].append(future)
        self.state.write_bytes(serialize_reviews(self.registry))
        before = self.snapshot()
        with self.assertRaisesRegex(TransferError, support.localized('review mark IDs collide', 'коллизия')):
            move.make_plan(self.root, 'docs/old.md', 'docs/new.md')
        self.assertEqual(self.snapshot(), before)

    def test_move_that_loses_source_group_is_refused(self):
        self.write('moves.txt', 'src/main.py docs/main.md\n')
        before = self.snapshot()
        with self.assertRaisesRegex(TransferError, support.localized('could not verify', 'доказать')):
            move.make_plan(self.root, from_file='moves.txt')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
