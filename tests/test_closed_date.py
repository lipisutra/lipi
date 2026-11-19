"""Доказательство даты последнего закрытия по Git."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests import support
from lipi.layout_migration import infer_closed_date
from lipi import layout_migration


# @trace ADR-020
class ClosedDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='lipi-closed-date-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'workflow/plan/pln-001-one.md'
        support.git_init(self.root)
        self.branch = self.git('branch', '--show-current').strip()

    def git(self, *args):
        code, output = support.git(self.root, *args)
        self.assertEqual(code, 0, output)
        return output

    def write(self, status, body='Text.'):
        support.w(self.path, '# Plan\n\n- Created: 2024-01-01\n'
                  '- Updated: 2024-10-01\n- Status: %s\n\n%s\n' % (status, body))

    def commit(self, status, day, body='Text.'):
        self.write(status, body)
        code, output = support.commit(self.root, status + ' ' + day, day + 'T12:00:00+00:00')
        self.assertEqual(code, 0, output)
        return self.git('rev-parse', 'HEAD').strip()

    def infer(self, **values):
        args = dict(top=self.root, path=self.path, prefix='pln', created='2024-01-01',
                    updated='2024-10-01', latest_date='2024-12-31')
        args.update(values)
        return infer_closed_date(**args)

    def test_last_closure_survives_reopen_late_edit_and_final_status_change(self):
        self.commit('new', '2024-01-01')
        self.commit('completed', '2024-02-02')
        self.commit('in progress', '2024-03-03')
        closure = self.commit('completed', '2024-04-04')
        self.commit('canceled', '2024-05-05')
        self.commit('canceled', '2024-06-06', 'Late edit.')
        self.assertEqual(self.infer(), ('2024-04-04', 'Git ' + closure))

    def test_rename_keeps_closure_and_reads_z_timestamp_on_python39(self):
        self.commit('new', '2024-01-01')
        closure = self.commit('completed', '2024-02-02')
        renamed = self.path.with_name('pln-001-renamed.md')
        self.git('mv', str(self.path.relative_to(self.root)), str(renamed.relative_to(self.root)))
        self.path = renamed
        self.assertEqual(support.commit(self.root, 'rename', '2024-03-03T12:00:00+00:00')[0], 0)
        original = layout_migration._git

        def zulu(root, *args, **kwargs):
            value = original(root, *args, **kwargs)
            return value.replace(b'+00:00', b'Z') if value is not None and args[0] == 'log' else value

        with patch.object(layout_migration, '_git', zulu):
            self.assertEqual(self.infer(), ('2024-02-02', 'Git ' + closure))

    def test_uncommitted_closure_with_history_refuses_without_guessing_update_date(self):
        self.commit('new', '2024-01-01')
        self.write('completed')
        with self.assertRaisesRegex(ValueError, support.localized('HEAD has no final status', 'HEAD.*финального')):
            self.infer()

    def test_commit_calendar_day_keeps_its_recorded_timezone(self):
        self.write('completed')
        self.assertEqual(support.commit(self.root, 'closed', '2024-01-01T02:26:26+03:00')[0], 0)
        closure = self.git('rev-parse', 'HEAD').strip()
        self.assertEqual(self.infer(), ('2024-01-01', 'Git ' + closure))

    def test_untracked_and_no_git_fallbacks_validate_raw_calendar_dates(self):
        self.write('completed')
        self.assertEqual(self.infer()[0], '2024-10-01')
        self.assertIn(support.localized('Updated date', 'Дата обновления'), self.infer(top=None)[1])
        for field, value in (('created', '2024-02-30'), ('created', '20240101'),
                             ('updated', '2024-02-30'), ('updated', '20240101'),
                             ('updated', '2023-12-31'), ('updated', '2025-01-01')):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.infer(top=None, **{field: value})

    def test_shallow_boundary_refuses_unproven_closure_but_accepts_visible_transition(self):
        opened = self.commit('new', '2024-01-01')
        closed = self.commit('completed', '2024-02-02')
        self.commit('completed', '2024-03-03', 'Late edit.')
        shallow = self.root / '.git/shallow'
        shallow.write_text(closed + '\n')
        with self.assertRaisesRegex(ValueError, support.localized('shallow history', 'усечённой')):
            self.infer()
        shallow.write_text(opened + '\n')
        self.assertEqual(self.infer(), ('2024-02-02', 'Git ' + closed))

    def test_unrelated_merge_keeps_single_closure(self):
        self.commit('new', '2024-01-01')
        closure = self.commit('completed', '2024-02-02')
        self.git('checkout', '-qb', 'side')
        support.w(self.root / 'side.txt', 'Side.\n')
        self.assertEqual(support.commit(self.root, 'side', '2024-03-03T12:00:00Z')[0], 0)
        self.git('checkout', '-q', self.branch)
        support.w(self.root / 'main.txt', 'Main.\n')
        self.assertEqual(support.commit(self.root, 'main', '2024-04-04T12:00:00Z')[0], 0)
        self.git('merge', '--no-ff', '-m', 'merge', 'side')
        self.assertEqual(self.infer(), ('2024-02-02', 'Git ' + closure))

    def test_merge_of_distinct_closures_refuses_ambiguous_history(self):
        self.commit('new', '2024-01-01')
        self.git('checkout', '-qb', 'side')
        self.commit('completed', '2024-02-02', 'Side.')
        self.git('checkout', '-q', self.branch)
        self.commit('completed', '2024-03-03', 'Main.')
        code, _ = support.git(self.root, 'merge', '--no-commit', 'side')
        self.assertEqual(code, 1)
        self.commit('completed', '2024-04-04', 'Merged.')
        with self.assertRaisesRegex(ValueError, support.localized('Ambiguous Closed date after merge', 'неоднозначная.*merge')):
            self.infer()

    def test_merge_of_late_edits_with_same_closure_keeps_that_closure(self):
        self.commit('new', '2024-01-01')
        closure = self.commit('completed', '2024-02-02')
        self.git('checkout', '-qb', 'side')
        self.commit('completed', '2024-03-03', 'Side.')
        self.git('checkout', '-q', self.branch)
        self.commit('canceled', '2024-04-04', 'Main.')
        code, _ = support.git(self.root, 'merge', '--no-commit', 'side')
        self.assertEqual(code, 1)
        self.commit('completed', '2024-05-05', 'Merged.')
        self.assertEqual(self.infer(), ('2024-02-02', 'Git ' + closure))

    def test_git_read_errors_and_invalid_raw_commit_dates_do_not_fallback(self):
        self.commit('new', '2024-01-01')
        self.commit('completed', '2024-02-02')
        original = layout_migration._git

        def invalid_stamp(root, *args, **kwargs):
            value = original(root, *args, **kwargs)
            return value.replace(b'2024-02-02T12:00:00', b'2024-02-30T12:00:00') if value and args[0] == 'log' else value

        with patch.object(layout_migration, '_git', invalid_stamp):
            with self.assertRaisesRegex(ValueError, support.localized('Invalid commit date', 'дата коммита')):
                self.infer()
        with patch.object(layout_migration, '_git', side_effect=ValueError('history read failed')):
            with self.assertRaisesRegex(ValueError, 'history read failed'):
                self.infer()


if __name__ == '__main__':
    unittest.main()
