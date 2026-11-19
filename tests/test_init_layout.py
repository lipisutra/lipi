"""Применение каркаса, перенос по годам и откат init."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import timezone
from unittest.mock import patch

from tests import support
from tests.support import localized

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi import init, layout_migration, layout_state, move_transaction
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.checker.reviews import REVIEWS_NAME, ReviewContext, load_reviews, serialize_reviews
from lipi.checker.workflow_index import FIXED, MARKER, refresh_index
from lipi.checker import workflow_index
from lipi.checker.workflow import scan_workflow
from lipi.checker.report import Report


# @trace docs/ru/workflow.md#upgrade,ADR-020
class InitLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-init-layout-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cfg = {'docs': 'docs', 'workflow': 'workflow'}
        self.write('lipi.json', json.dumps(self.cfg) + '\n')
        self.write('docs/README.md', '# Описание\n\n## Работа <a id="work"></a>\n\nОписание.\n')
        self.write('workflow/README.md', '# Рабочие материалы\n')
        self.write('workflow/INDEX.md', MARKER + '\n# Указатель рабочих материалов\n')
        self.write('.agents/lipi/workflow.md', '# Правила до применения\n')
        self.write('.agents/lipi/lipi.lock', init.lock_text(support.VERSION, {}, False))

    def write(self, name, text):
        path = self.root / name
        support.w(path, text)
        return path

    def document(self, prefix='pln', status='new', *, year=None, number=1,
                 closed=None, created='2024-01-01', updated='2024-01-01', folder=False,
                 feedback=False):
        kinds = {'pln': 'plan', 'iss': 'issue', 'dsc': 'discussion', 'adr': 'adr', 'aud': 'audit'}
        directory = '.agents/lipi-feedback' if feedback else 'workflow/' + kinds[prefix]
        if year is not None:
            directory += '/' + str(year)
        filename = '%s-%03d-tema.md' % (prefix, number)
        if folder:
            directory += '/' + filename[:-3]
            filename = '%s-%03d-readme.md' % (prefix, number)
        fields = [('Created', created), ('Updated', updated)]
        if prefix != 'aud':
            fields.append(('Status', status))
        if prefix == 'iss':
            fields.append(('Kind', 'bug'))
        if closed is not None:
            fields.append(('Closed', closed))
        fields.append(('Result', 'Проверено.'))
        body = ('\n## Purpose <a id="why"></a>\n\nСодержание работы.\n'
                '\n## Completion criteria <a id="acceptance"></a>\n\nПроверка.\n'
                '\n## Observation <a id="observed"></a>\n\nНаблюдение.\n')
        return self.write(directory + '/' + filename,
                          '# Проверка\n\n' + ''.join('- %s: %s\n' % item for item in fields) + body)

    def git(self, *args):
        code, output = support.git(self.root, *args)
        self.assertEqual(code, 0, output)
        return output

    def commit(self, date='2024-02-01T12:00:00+00:00'):
        code, output = support.commit(self.root, date=date)
        self.assertEqual(code, 0, output)

    def git_start(self):
        support.git_init(self.root)
        self.commit()

    def updates(self):
        return [(self.root / '.agents/lipi/workflow.md', '# Правила после применения\n'),
                (self.root / '.agents/lipi/lipi.lock', init.lock_text(support.VERSION, {}, True))]

    def prepare(self, *, updates=None):
        return layout_migration.prepare_layout(self.root, self.cfg,
                                               self.updates() if updates is None else updates)

    def snapshot(self):
        tree = {path.relative_to(self.root).as_posix():
                (path.read_bytes() if path.is_file() else None, stat.S_IMODE(path.stat().st_mode))
                for path in self.root.rglob('*') if '.git' not in path.relative_to(self.root).parts}
        index = self.root / '.git/index'
        return tree, index.read_bytes() if index.exists() else None

    def run_init(self, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = init.initialize(self.root, **kwargs)
        return code, output.getvalue()

    def add_review(self, document):
        relative = document.relative_to(self.root).as_posix()
        self.write('src/main.py', '# %s %s#why\nvalue = 1\n' % (support.TAG, relative))
        self.commit()
        context = ReviewContext(Project(self.root, load_config(self.root, None)))
        pair = next(pair for pair in context.pairs if pair['target']['path'] == relative)
        entry = {key: pair[key] for key in ('id', 'relation', 'source', 'target')}
        entry.update(reviewer='reviewer', reviewed_at='2024-02-02T12:00:00Z',
                     reason='Описание проверено.', head=self.git('rev-parse', 'HEAD').strip())
        registry = {'schema': 1, 'algorithm': 'sha256-lines-v1', 'entries': [entry]}
        path = self.root / REVIEWS_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(serialize_reviews(registry))
        self.commit()
        return entry

    def test_prepare_is_pure_and_moves_yearly_documents_and_folder_attachments(self):
        documents = [self.document(prefix, status) for prefix, status in
                     (('pln', 'new'), ('iss', 'open'), ('dsc', 'open'))]
        audit = self.document('aud', folder=True)
        attachment = self.write(str(audit.parent.relative_to(self.root) / 'appendix.md'), '# Приложение\n')
        binary = audit.parent / 'evidence.bin'
        binary.write_bytes(b'\x00\xff\xfe evidence')
        adr = self.document('adr', 'accepted')
        feedback = self.document('iss', 'open', number=2, feedback=True)
        archived = self.write('workflow/history/pln-090-old.md', '')
        archived.write_bytes(b'\xff\xfe archive without UTF-8')
        self.write('workflow/masterplan.md', '# План\n\n[PLN-001](plan/pln-001-tema.md#why)\n')
        self.git_start()
        before = self.snapshot()
        plan = self.prepare()
        self.assertEqual(self.snapshot(), before)
        for path in documents + [audit, attachment, binary]:
            relative = path.relative_to(self.root / 'workflow')
            self.assertEqual(plan.moves[path], self.root / 'workflow' / relative.parts[0] / '2024' / Path(*relative.parts[1:]))
        self.assertNotIn(adr, plan.moves)
        self.assertNotIn(feedback, plan.moves)
        self.assertNotIn(archived, plan.moves)
        layout_migration.apply_layout(plan)
        for old, new in plan.moves.items():
            self.assertFalse(old.exists())
            self.assertTrue(new.is_file())
        self.assertIn('plan/2024/pln-001-tema.md#why', (self.root / 'workflow/masterplan.md').read_text())
        for name in FIXED:
            self.assertTrue((self.root / 'workflow' / name).read_text().startswith(MARKER))
        self.assertEqual(archived.read_bytes(), b'\xff\xfe archive without UTF-8')
        self.assertEqual(plan.moves[binary].read_bytes(), b'\x00\xff\xfe evidence')

    def test_yearly_input_has_no_moves_and_keeps_same_document_identity(self):
        path = self.document(year=2024)
        self.git_start()
        plan = self.prepare()
        self.assertFalse(plan.moves)
        layout_migration.apply_layout(plan)
        self.assertEqual(path.name, 'pln-001-tema.md')
        self.assertIn('PLN-001', (self.root / 'workflow/index/plans.md').read_text())

    def test_git_closure_comes_from_closing_commit_not_late_body_edit_and_is_one_time(self):
        path = self.document()
        self.git_start()
        support.sub(path, '- Status: new', '- Status: completed')
        support.sub(path, '- Updated: 2024-01-01', '- Updated: 2025-03-02')
        self.commit('2025-03-02T14:00:00+00:00')
        support.sub(path, 'Содержание работы.', 'Поздняя правка тела.')
        self.commit('2026-01-04T14:00:00+00:00')
        plan = self.prepare()
        self.assertTrue(any('2025-03-02 (Git ' in notice for notice in plan.notices), plan.notices)
        layout_migration.apply_layout(plan)
        target = plan.moves[path]
        self.assertIn('- Closed: 2025-03-02\n', target.read_text())
        self.assertIn('PLN-001', (self.root / 'workflow/index/done/2025.md').read_text())
        with patch.object(layout_migration, 'infer_closed_date', side_effect=AssertionError('history reread')):
            repeat = self.prepare()
        self.assertFalse(repeat.moves)
        self.assertFalse(repeat.changes)

    def test_git_closure_survives_change_of_header_format(self):
        path = self.document()
        support.sub(path, '- Status: new', '- Статус: новый')
        self.git_start()
        support.sub(path, '- Статус: новый', '- Статус: завершён')
        self.commit('2025-03-02T14:00:00+00:00')
        support.sub(path, '- Статус: завершён', '- Status: completed')
        self.commit('2026-01-04T14:00:00+00:00')

        plan = self.prepare()
        layout_migration.apply_layout(plan)
        self.assertIn('- Closed: 2025-03-02\n', plan.moves[path].read_text())

    def test_existing_closure_preserved_without_history_reconstruction(self):
        path = self.document(status='completed', closed='2024-04-03', updated='2025-01-01')
        self.git_start()
        with patch.object(layout_migration, 'infer_closed_date', side_effect=AssertionError('history reread')):
            plan = self.prepare()
        layout_migration.apply_layout(plan)
        self.assertIn('- Closed: 2024-04-03\n', plan.moves[path].read_text())
        self.assertTrue((self.root / 'workflow/index/done/2024.md').is_file())

    def test_initialize_accepts_utc_closure_limit_and_rejects_the_following_day(self):
        cases = (('2026-11-18', '2026-11-19', '2026-11-20'),
                 ('2026-11-30', '2026-12-01', '2026-12-02'),
                 ('2026-12-31', '2027-01-01', '2027-01-02'))
        for utc_date, latest, future in cases:
            for utc_offset in (0, 3):
                for closed, accepted in ((latest, True), (future, False)):
                    with self.subTest(utc_date=utc_date, utc_offset=utc_offset, closed=closed):
                        self.document('adr', 'superseded', closed=closed)
                        before = self.snapshot()
                        with support.freeze_workflow_clock(utc_date + 'T21:30:00+00:00',
                                                           utc_offset) as clock:
                            code, output = self.run_init(dry_run=True)
                        clock.now.assert_called_once_with(timezone.utc)
                        self.assertEqual(code, 0 if accepted else 2, output)
                        if accepted:
                            self.assertIn('workflow/index/done/%s.md' % closed[:4], output)
                        else:
                            self.assertIn(localized('Invalid Closed date', 'неверная Дата закрытия'), output)
                        self.assertEqual(self.snapshot(), before)

    def test_git_closure_uses_utc_limit_and_preserves_the_commit_calendar_date(self):
        self.document(status='completed')
        later = self.document(number=2)
        support.git_init(self.root)
        self.commit('2026-11-19T00:30:00+03:00')
        with support.freeze_workflow_clock('2026-11-18T21:30:00+00:00') as clock:
            plan = self.prepare()
        clock.now.assert_called_once_with(timezone.utc)
        self.assertTrue(any('2026-11-19 (Git ' in notice for notice in plan.notices), plan.notices)

        support.sub(later, '- Status: new', '- Status: completed')
        self.commit('2026-11-20T00:30:00+03:00')
        before = self.snapshot()
        with support.freeze_workflow_clock('2026-11-18T21:30:00+00:00', 3):
            with self.assertRaisesRegex(ValueError, localized('2026-11-20 is outside the range', '2026-11-20 вне диапазона')):
                self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_closure_fallback_validates_updated_date_against_utc_limit(self):
        path = self.document('adr', 'superseded', updated='2027-01-01')
        before = self.snapshot()
        with support.freeze_workflow_clock('2026-12-31T21:30:00+00:00', 3):
            from lipi.checker.workflow_layout import latest_closed_date
            limit = latest_closed_date()
            self.assertEqual(layout_migration.infer_closed_date(
                None, path, 'adr', '2024-01-01', '2027-01-01', limit),
                ('2027-01-01', localized('Updated date (no Git history)',
                                                        'Дата обновления (без истории Git)')))
            with self.assertRaisesRegex(ValueError, localized('2027-01-02 is outside the range', '2027-01-02 вне диапазона')):
                layout_migration.infer_closed_date(
                    None, path, 'adr', '2024-01-01', '2027-01-02', limit)
        self.assertEqual(self.snapshot(), before)

    def test_all_final_types_and_feedback_receive_closure_without_changing_other_dates(self):
        pairs = [('pln', 'new', 'canceled'), ('iss', 'open', 'closed'),
                 ('dsc', 'open', 'closed'), ('adr', 'accepted', 'rejected')]
        documents = [(self.document(prefix, initial), initial, final)
                     for prefix, initial, final in pairs]
        documents.append((self.document('iss', 'open', number=2, feedback=True), 'open', 'closed'))
        self.git_start()
        for path, initial, final in documents:
            support.sub(path, '- Status: ' + initial, '- Status: ' + final)
        self.commit('2025-08-09T12:00:00+00:00')
        plan = self.prepare()
        layout_migration.apply_layout(plan)
        for path, _, _ in documents:
            text = plan.moves.get(path, path).read_text()
            self.assertIn('- Closed: 2025-08-09\n', text)
            self.assertIn('- Created: 2024-01-01\n', text)
            self.assertIn('- Updated: 2024-01-01\n', text)
        done = (self.root / 'workflow/index/done/2025.md').read_text()
        for prefix, _, _ in pairs:
            self.assertIn(prefix.upper() + '-001', done)
        self.assertNotIn('ISS-002', done)

    def test_folded_result_keeps_continuation_separate_from_added_closure(self):
        path = self.document('adr', 'superseded', updated='2025-06-07')
        support.sub(path, '- Result: Проверено.', '- Result: Первая строка\n  продолжение результата.')
        before = Project(self.root, self.cfg).page(path).header()['Result']
        self.document()
        self.git_start()
        plan = self.prepare()
        layout_migration.apply_layout(plan)
        header = Project(self.root, self.cfg).page(path).header()
        self.assertEqual(header['Result'], before)
        self.assertEqual(header['Closed'], '2024-02-01')

    def test_closure_derivation_refuses_concurrent_source_change_during_prepare(self):
        path = self.document('adr', 'superseded', updated='2025-06-07')
        self.document()
        self.git_start()
        original = path.read_text()
        real = layout_migration._closed_text

        def concurrent(text, value):
            result = real(text, value)
            path.write_text(original + '\nConcurrent user edit\n')
            return result

        with patch.object(layout_migration, '_closed_text', side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, localized('changed', 'изменился')):
                self.prepare()
        self.assertEqual(path.read_text(), original + '\nConcurrent user edit\n')
        self.assertFalse((self.root / 'workflow/index').exists())

    def test_baseline_derivation_refuses_concurrent_registry_change_during_prepare(self):
        self.document()
        registry = {'schema': 1, 'entries': [{'code': 'W3', 'file': 'workflow/plan/pln-001-tema.md',
                                             'subject': 'Created', 'count': 1}]}
        path = self.write('.agents/lipi/baseline.json', json.dumps(registry))
        self.git_start()
        real = layout_state.transfer_baseline
        concurrent = json.dumps(dict(registry, entries=[dict(registry['entries'][0], count=2)]))

        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            path.write_text(concurrent)
            return result

        with patch.object(layout_state, 'transfer_baseline', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, localized('changed', 'изменился')):
                self.prepare()
        self.assertEqual(path.read_text(), concurrent)
        self.assertFalse((self.root / 'workflow/plan/2024').exists())

    def test_index_snapshot_refuses_concurrent_user_file_during_prepare(self):
        self.document()
        self.git_start()
        real = workflow_index.plan_index
        path = self.root / 'workflow/index/plans.md'

        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            support.w(path, '# Concurrent user page\n')
            return result

        with patch.object(workflow_index, 'plan_index', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, localized('changed', 'изменился')):
                self.prepare()
        self.assertEqual(path.read_text(), '# Concurrent user page\n')
        self.assertFalse((self.root / 'workflow/plan/2024').exists())

    def test_unchanged_baseline_and_config_are_guarded_until_apply(self):
        self.document()
        baseline = self.write('.agents/lipi/baseline.json', '{"schema": 1, "entries": []}\n')
        self.git_start()
        for path in (baseline, self.root / 'lipi.json'):
            with self.subTest(path=path.name):
                plan = self.prepare()
                self.assertNotIn(path, {change.path for change in plan.changes})
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                changed = self.snapshot()
                with self.assertRaisesRegex(ValueError, localized('changed', 'изменился')):
                    layout_migration.apply_layout(plan)
                self.assertEqual(self.snapshot(), changed)
                path.write_bytes(original)

    def test_flat_without_git_refused_before_any_update(self):
        self.document()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, localized('requires Git', 'без Git')):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_canonical_layout_requires_missing_closure_to_be_corrected(self):
        path = self.document('adr', 'superseded', updated='2025-06-07')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, localized('no valid Closed date', 'нет корректной Даты закрытия')):
            self.prepare()
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('- Closed:', path.read_text())

    def test_external_workflow_refused_before_any_update(self):
        with tempfile.TemporaryDirectory(prefix='lipi-external-layout-') as folder:
            external = Path(folder).resolve()
            support.w(external / 'plan/pln-001-tema.md', '# Внешний документ\n')
            self.cfg['workflow'] = str(external)
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, localized('External workflow', 'внешний workflow')):
                self.prepare()
            self.assertEqual(self.snapshot(), before)
            self.assertEqual((external / 'plan/pln-001-tema.md').read_text(), '# Внешний документ\n')

    def test_duplicate_identity_across_flat_and_year_refused(self):
        self.document()
        self.document(year=2024)
        self.git_start()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, localized('Ambiguous document number', 'неоднозначный номер')):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_invalid_creation_or_closure_refused(self):
        for fields in ({'created': '2024-02-30'}, {'closed': '2024-02-30'},
                       {'closed': '2023-01-01'}, {'closed': '2999-01-01'}):
            with self.subTest(fields=fields):
                self.document(status='completed', **fields)
                if not (self.root / '.git').exists():
                    self.git_start()
                else:
                    self.commit()
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, localized('Invalid', 'неверн')):
                    self.prepare()
                self.assertEqual(self.snapshot(), before)

    def test_dirty_affected_document_refused_but_unrelated_staged_is_preserved(self):
        path = self.document()
        self.write('unrelated.txt', 'committed\n')
        self.git_start()
        support.sub(path, 'Содержание работы.', 'Незакоммиченная правка.')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, localized('uncommitted|changed|dirty', 'незакоммич|изменен|изменён|грязн')):
            self.prepare()
        self.assertEqual(self.snapshot(), before)
        self.git('checkout', '--', path.relative_to(self.root).as_posix())
        self.write('unrelated.txt', 'staged\n')
        self.git('add', 'unrelated.txt')
        self.write('unrelated.txt', 'worktree\n')
        plan = self.prepare()
        layout_migration.apply_layout(plan)
        self.assertEqual(self.git('show', ':unrelated.txt'), 'staged\n')
        self.assertEqual((self.root / 'unrelated.txt').read_text(), 'worktree\n')

    def test_unowned_index_target_refuses_complete_plan(self):
        self.document()
        self.write('workflow/index/issues.md', '# Пользовательский список\n')
        self.git_start()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, localized('user file', 'пользовательским')):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_absent_lock_does_not_skip_existing_flat_document(self):
        path = self.document()
        (self.root / '.agents/lipi/lipi.lock').unlink()
        self.git_start()
        plan = self.prepare()
        self.assertIn(path, plan.moves)
        layout_migration.apply_layout(plan)
        self.assertTrue(plan.moves[path].exists())

    def test_existing_review_transfers_identity_and_keeps_author_reason_and_time(self):
        path = self.document()
        self.git_start()
        entry = self.add_review(path)
        plan = self.prepare()
        layout_migration.apply_layout(plan)
        after, = load_reviews(self.root)['entries']
        self.assertNotEqual(after['id'], entry['id'])
        self.assertEqual(after['target']['path'], 'workflow/plan/2024/pln-001-tema.md')
        for key in ('reviewer', 'reviewed_at', 'reason', 'head'):
            self.assertEqual(after[key], entry[key])
        context = ReviewContext(Project(self.root, load_config(self.root, None)))
        self.assertEqual(context.classify(after)[0], 'current')

    def test_failures_after_index_rules_lock_or_reviews_restore_everything(self):
        path = self.document()
        self.git_start()
        self.add_review(path)
        targets = ['.agents/lipi/workflow.md', '.agents/lipi/lipi.lock', REVIEWS_NAME,
                   'workflow/index/plans.md']
        for target in targets:
            for error in (OSError, KeyboardInterrupt):
                with self.subTest(target=target, error=error.__name__):
                    plan, before = self.prepare(), self.snapshot()
                    real_write, injected = move_transaction._write, []

                    def fail_after_write(destination, data, mode):
                        real_write(destination, data, mode)
                        if destination == self.root / target and not injected:
                            injected.append(destination)
                            raise error('injected after write')

                    with patch.object(move_transaction, '_write', side_effect=fail_after_write):
                        with self.assertRaisesRegex(ValueError, localized('rolled back', 'отменены')):
                            layout_migration.apply_layout(plan)
                    self.assertTrue(injected)
                    self.assertEqual(self.snapshot(), before)
                    self.assertFalse(list(self.root.rglob('.lipi-write-*')))
                    self.assertFalse(list((self.root / '.git').glob('lipi-mv-*')))

    def test_initialize_dry_run_then_apply_and_repeat_for_flat_documents(self):
        path = self.document(status='completed', closed='2024-04-03', updated='2024-04-03')
        support.w(path, path.read_text() + '\n[Описание](../../docs/README.md#work)\n')
        self.git_start()
        before = self.snapshot()
        code, output = self.run_init(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn('workflow/plan/2024/pln-001-tema.md', output)
        self.assertIn('workflow/index/done/2024.md', output)
        self.assertEqual(self.snapshot(), before)
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        target = self.root / 'workflow/plan/2024/pln-001-tema.md'
        self.assertFalse(path.exists())
        self.assertIn('[Описание](../../../docs/README.md#work)', target.read_text())
        lock = json.loads((self.root / '.agents/lipi/lipi.lock').read_text())
        self.assertEqual(lock['lipi'], support.VERSION)
        self.assertIn('.agents/lipi/workflow.md', lock['files'])
        after = self.snapshot()
        with patch.object(layout_migration, 'infer_closed_date', side_effect=AssertionError('history reread')):
            code, output = self.run_init()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.snapshot(), after)

    def test_initialize_new_yearly_project_keeps_addresses_and_all_index_files(self):
        path = self.document(year=2024)
        self.write('.agents/lipi/lipi.lock', init.lock_text(support.VERSION, {}, False))
        (self.root / 'workflow/INDEX.md').unlink()
        project = Project(self.root, load_config(self.root, None))
        documents, _ = scan_workflow(project, Report())
        refresh_index(project, documents)
        self.git_start()
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        self.assertTrue(path.exists())
        self.assertFalse((self.root / 'workflow/plan/pln-001-tema.md').exists())
        self.assertEqual(len(list((self.root / 'workflow').rglob('pln-001-*.md'))), 1)
        for name in FIXED:
            self.assertTrue((self.root / 'workflow' / name).is_file())

    def test_initialize_partial_lock_still_converts_flat_documents(self):
        path = self.document()
        (self.root / '.agents/lipi/workflow.md').unlink()
        self.git_start()
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        self.assertFalse(path.exists())
        self.assertTrue((self.root / 'workflow/plan/2024/pln-001-tema.md').is_file())
        self.assertTrue((self.root / '.agents/lipi/workflow.md').is_file())
        self.assertEqual(json.loads((self.root / '.agents/lipi/lipi.lock').read_text())['lipi'], support.VERSION)

    def test_initialize_rejects_flat_without_git_and_keeps_lock(self):
        self.document()
        before = self.snapshot()
        code, output = self.run_init()
        self.assertEqual(code, 2, output)
        self.assertIn(localized('requires Git', 'без Git'), output)
        self.assertEqual(self.snapshot(), before)

    def test_initialize_failure_after_final_lock_or_generated_index_rolls_back(self):
        self.document()
        self.git_start()
        for target in ('.agents/lipi/lipi.lock', 'workflow/index/plans.md'):
            with self.subTest(target=target):
                before = self.snapshot()
                real_write, injected = move_transaction._write, []

                def fail_after_write(destination, data, mode):
                    real_write(destination, data, mode)
                    if destination == self.root / target and not injected:
                        injected.append(destination)
                        raise OSError('injected init failure')

                with patch.object(move_transaction, '_write', side_effect=fail_after_write):
                    code, output = self.run_init()
                self.assertEqual(code, 2, output)
                self.assertTrue(injected)
                self.assertIn(localized('rolled back', 'отменены'), output)
                self.assertEqual(self.snapshot(), before)

    def test_apply_refuses_changes_since_plan_including_new_index_collision(self):
        path = self.document()
        self.git_start()
        self.add_review(path)
        for name in ('workflow/plan/pln-001-tema.md', '.agents/lipi/lipi.lock', REVIEWS_NAME,
                     'workflow/index/plans.md'):
            with self.subTest(name=name):
                plan = self.prepare()
                target = self.root / name
                old = target.read_bytes() if target.exists() else None
                self.write(name, (old.decode() if old else '') + '\nConcurrent change\n')
                changed = self.snapshot()
                with self.assertRaises(ValueError):
                    layout_migration.apply_layout(plan)
                self.assertEqual(self.snapshot(), changed)
                if old is not None:
                    target.write_bytes(old)
                else:
                    target.unlink()
                    target.parent.rmdir()

    def test_missing_lock_and_config_with_flat_documents_still_convert(self):
        path = self.document()
        (self.root / 'lipi.json').unlink()
        (self.root / '.agents/lipi/lipi.lock').unlink()
        self.git_start()
        before = self.snapshot()
        code, output = self.run_init(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn('workflow/plan/2024/pln-001-tema.md', output)
        self.assertEqual(self.snapshot(), before)
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        self.assertFalse(path.exists())
        self.assertTrue((self.root / 'workflow/plan/2024/pln-001-tema.md').exists())

    def test_missing_lock_and_config_without_git_refuses_flat_documents(self):
        self.document()
        (self.root / 'lipi.json').unlink()
        (self.root / '.agents/lipi/lipi.lock').unlink()
        before = self.snapshot()
        code, output = self.run_init()
        self.assertEqual(code, 2, output)
        self.assertIn(localized('requires Git', 'без Git'), output)
        self.assertEqual(self.snapshot(), before)

    def test_newer_major_refused_without_moving_flat_document(self):
        self.document()
        major = int(support.VERSION.split('.')[0])
        self.write('.agents/lipi/lipi.lock', init.lock_text('%d.0.0' % (major + 1), {}, False))
        self.git_start()
        before = self.snapshot()
        code, output = self.run_init()
        self.assertEqual(code, 2, output)
        self.assertIn(localized('Update the installed lipi', 'новее установленного'), output)
        self.assertEqual(self.snapshot(), before)

    def test_initial_baseline_runs_checks_in_real_worktree_with_ignored_dependencies(self):
        (self.root / '.agents/lipi/lipi.lock').unlink()
        script = self.write('check.sh', '#!/bin/sh\n'
                            'test "$(pwd)" = "$1" || exit 1\n'
                            'test -f ignored/dependency.txt || exit 2\n'
                            'test "$(git show :staged.txt)" = staged || exit 3\n')
        script.chmod(0o755)
        self.write('.gitignore', 'ignored/\n')
        self.write('ignored/dependency.txt', 'available only in the real worktree\n')
        self.write('staged.txt', 'committed\n')
        self.cfg['checks'] = [{'name': 'real-worktree', 'run': ['./check.sh', str(self.root)]},
                              {'name': 'known-failure', 'run': [sys.executable, '-c', 'raise SystemExit(7)']}]
        self.write('lipi.json', json.dumps(self.cfg))
        self.git_start()
        self.write('staged.txt', 'staged\n')
        self.git('add', 'staged.txt')
        self.write('staged.txt', 'worktree\n')
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        baseline = json.loads((self.root / '.agents/lipi/baseline.json').read_text())
        self.assertEqual({entry['subject'] for entry in baseline['entries'] if entry['code'] == 'P1'},
                         {'known-failure'})
        self.assertEqual(self.git('show', ':staged.txt'), 'staged\n')
        self.assertEqual((self.root / 'staged.txt').read_text(), 'worktree\n')

    def test_initial_baseline_resolves_relative_neighbor_at_real_location(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-baseline-neighbor-')
        self.addCleanup(temporary.cleanup)
        neighbor = Path(temporary.name).resolve()
        support.w(neighbor / 'lipi.json', '{"docs": "docs", "workflow": null}\n')
        support.w(neighbor / 'docs/guide.md', '# Guide\n\n## Request <a id="request"></a>\n\nText.\n')
        (self.root / '.agents/lipi/lipi.lock').unlink()
        self.cfg['repos'] = {'engine': {'path': os.path.relpath(neighbor, self.root), 'read': ['docs']}}
        self.cfg['codes'] = {'T4': 'error'}
        self.write('lipi.json', json.dumps(self.cfg))
        self.write('src/main.py', '# %s engine::docs/guide.md#request\nvalue = 1\n' % support.TAG)
        before = {path.relative_to(neighbor): path.read_bytes() for path in neighbor.rglob('*') if path.is_file()}
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        baseline = json.loads((self.root / '.agents/lipi/baseline.json').read_text())
        self.assertFalse([entry for entry in baseline['entries'] if entry['code'] in ('T1', 'T4')], baseline)
        self.assertEqual({path.relative_to(neighbor): path.read_bytes() for path in neighbor.rglob('*') if path.is_file()}, before)

    def test_first_baseline_dry_run_does_not_execute_project_checks(self):
        (self.root / '.agents/lipi/lipi.lock').unlink()
        self.write('record.py', 'from pathlib import Path\np = Path("check-runs.txt")\n'
                   'p.write_text((p.read_text() if p.exists() else "") + "run\\n")\n')
        self.cfg['checks'] = [{'name': 'record', 'run': [sys.executable, 'record.py']}]
        self.write('lipi.json', json.dumps(self.cfg))
        before = self.snapshot()
        code, output = self.run_init(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn(localized('run when the plan is applied', 'будут выполнены только при применении'), output)
        self.assertEqual(self.snapshot(), before)
        code, output = self.run_init()
        self.assertEqual(code, 0, output)
        self.assertEqual((self.root / 'check-runs.txt').read_text(), 'run\n')


class ExternalDocsInitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-external-docs-init-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'project'
        self.root.mkdir()
        self.docs = self.base / 'nested/documentation'

    def snapshot(self):
        return {path.relative_to(self.base).as_posix():
                (path.read_bytes() if path.is_file() else None,
                 stat.S_IMODE(path.stat().st_mode))
                for path in self.base.rglob('*')}

    def apply(self, **options):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = init.initialize(self.root, docs='../nested/documentation', **options)
        return code, output.getvalue()

    def test_external_seeds_dry_run_apply_repeat_and_projected_links(self):
        before = self.snapshot()
        code, output = self.apply(kind='app', dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.snapshot(), before)
        code, output = self.apply(kind='app')
        self.assertEqual(code, 0, output)
        self.assertTrue((self.docs / 'README.md').is_file())
        self.assertTrue((self.docs / 'development/README.md').is_file())
        baseline = json.loads((self.root / '.agents/lipi/baseline.json').read_text())
        self.assertEqual(baseline['entries'], [], baseline)
        code, output = support.check(self.root, '--no-baseline')
        self.assertEqual(code, 0, output)
        before = self.snapshot()
        times = {path: path.stat().st_mtime_ns for path in self.docs.rglob('*') if path.is_file()}
        code, output = self.apply(kind='app')
        self.assertEqual(code, 0, output)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({path: path.stat().st_mtime_ns for path in times}, times)

    def test_failure_after_external_seed_rolls_back_files_and_parent_directories(self):
        for exception in (OSError, KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                before, original = self.snapshot(), move_transaction._write
                injected = []
                def fail_after_seed(path, data, mode):
                    original(path, data, mode)
                    if path == self.docs / 'README.md' and not injected:
                        injected.append(path)
                        raise exception('after external seed')
                with patch.object(move_transaction, '_write', fail_after_seed):
                    code, output = self.apply()
                self.assertEqual(code, 2, output)
                self.assertTrue(injected, output)
                self.assertIn(localized('changes rolled back', 'изменения отменены'), output)
                self.assertEqual(self.snapshot(), before)

    def test_existing_external_docs_preserved_and_baseline_paths_mapped_back(self):
        page = self.docs / 'README.md'
        support.w(page, '# Внешнее описание\n\n[Нет страницы](missing.md)\n')
        page.chmod(0o640)
        before = page.read_bytes(), page.stat().st_mode, page.stat().st_mtime_ns
        code, output = self.apply()
        self.assertEqual(code, 0, output)
        self.assertEqual((page.read_bytes(), page.stat().st_mode, page.stat().st_mtime_ns), before)
        baseline = json.loads((self.root / '.agents/lipi/baseline.json').read_text())
        findings = [entry for entry in baseline['entries'] if entry['code'] == 'D1']
        self.assertEqual(len(findings), 1, baseline)
        self.assertEqual(findings[0]['file'], '../nested/documentation/README.md')
        self.assertEqual(findings[0]['subject'], 'missing.md')

    def test_nested_description_is_copied_once_with_existing_symlink(self):
        page = self.docs / 'development/existing.md'
        support.w(page, '# Существующая страница\n')
        alias = page.with_name('alias.md')
        alias.symlink_to(page.name)
        before = self.snapshot()
        code, output = self.apply(kind='app', dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(alias.is_symlink())

    def test_git_projection_never_writes_through_historical_symlinks(self):
        victim = self.base / 'victim.txt'
        victim.write_text('untouched')
        paths = [self.root / 'asset.txt', self.docs / 'asset.txt']
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(victim)
        support.w(self.root / 'target.md', '# Страница\n')
        (self.root / 'kept.md').symlink_to('target.md')
        support.w(self.docs / 'README.md', '# Описание\n\n[Страница](../../project/kept.md)\n')
        for args in (('init',), ('config', 'user.email', 'synthetic@example.invalid'),
                     ('config', 'user.name', 'Synthetic Test'), ('add', '.'),
                     ('commit', '-m', 'historical symlinks')):
            result = subprocess.run(['git', *args], cwd=self.base, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for path in paths:
            path.unlink()
            path.write_text('working copy')
        before = self.snapshot()
        code, output = self.apply(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(victim.read_text(), 'untouched')
        self.assertEqual(self.snapshot(), before)
        code, output = self.apply()
        self.assertEqual(code, 0, output)
        baseline = json.loads((self.root / '.agents/lipi/baseline.json').read_text())
        self.assertFalse([entry for entry in baseline['entries'] if entry['code'] == 'D1'], baseline)
        self.assertTrue((self.root / 'kept.md').is_symlink())
        self.assertEqual(victim.read_text(), 'untouched')

    def test_ancestor_docs_does_not_copy_its_own_temporary_projection(self):
        output = io.StringIO()
        with patch.object(tempfile, 'tempdir', str(self.base)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = init.initialize(self.root, docs='..')
        self.assertEqual(code, 0, output.getvalue())
        self.assertTrue((self.base / 'README.md').is_file())
        self.assertFalse(list(self.base.glob('lipi-init-baseline-*')))

    def test_external_docs_symlink_is_rejected_before_creating_seed(self):
        self.docs.parent.mkdir()
        destination = self.base / 'target'
        destination.mkdir()
        self.docs.symlink_to(destination, target_is_directory=True)
        before = self.snapshot()
        code, output = self.apply()
        self.assertEqual(code, 2, output)
        self.assertIn(localized('symbolic links are not allowed', 'символическая ссылка'), output)
        self.assertEqual(self.snapshot(), before)

    def test_whitelist_cannot_modify_existing_file_or_allow_external_moves(self):
        from types import SimpleNamespace
        from lipi.move import FileChange, MoveError, _stamp
        outside = self.docs / 'README.md'
        support.w(outside, '# Существующее описание\n')
        plan = SimpleNamespace(root=self.root, moves={}, source_dirs=[], index=None,
                               index_before=None, reviews=None, config={},
                               changes=[FileChange(outside, outside.read_bytes(), b'changed', _stamp(outside), [])],
                               external_creates=frozenset([outside]))
        before = self.snapshot()
        with self.assertRaises(MoveError):
            move_transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)
        plan.external_creates = frozenset()
        with self.assertRaises(MoveError):
            move_transaction.apply_transaction(plan)
        plan.external_creates = frozenset([outside])
        plan.moves = {outside: self.root / 'moved.md'}
        with self.assertRaises(MoveError):
            move_transaction.apply_transaction(plan)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
