"""Общая раскладка, номера, приложения и Дата закрытия."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timezone
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests import support
from lipi.checker.commands import cmd_new
from lipi.checker.config import DEFAULTS
from lipi.checker.conventions import K_CLOSED, K_CREATED, STATUSES, TYPES
from lipi.checker.model import Project
from lipi.checker.report import Report
from lipi.checker.runner import main as check_main
from lipi.checker.targets import resolve_mark, work_targets
from lipi.checker.workflow import check_workflow, next_number, scan_workflow
from lipi.checker.workflow_layout import is_final, reserved_numbers


# @trace ADR-020,docs/ru/codes.md#w10,docs/ru/codes.md#w11
class WorkflowLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='lipi-layout-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'workflow').mkdir()
        self.cfg = deepcopy(DEFAULTS)

    def project(self):
        return Project(self.root, self.cfg)

    def write_doc(self, relative, prefix='pln', created='2024-01-01', status=None, closed=None):
        fields = ['# Проверка раскладки', '', '- Created: ' + created,
                  '- Updated: ' + created]
        if status is None and prefix in STATUSES:
            status = STATUSES[prefix][0]
        if status:
            fields.append('- Status: ' + status)
        if closed is not None:
            fields.append('- Closed: ' + closed)
        if prefix == 'iss':
            fields.append('- Kind: bug')
        fields += ['- Result: проверено', '', '## Observation', '', 'Пример.', '']
        path = self.root / relative
        support.w(path, '\n'.join(fields))
        return path

    def scan(self):
        pr, rep = self.project(), Report()
        docs, others = scan_workflow(pr, rep)
        check_workflow(pr, rep, docs, others)
        return pr, docs, rep

    def test_years_folder_main_and_attachments_have_one_identity(self):
        for prefix in ('pln', 'iss', 'dsc', 'aud'):
            folder = TYPES[prefix][0]
            self.write_doc('workflow/%s/2024/%s-001-one.md' % (folder, prefix), prefix)
        self.write_doc('workflow/plan/2025/pln-002-two.md', created='2025-01-01')
        main = self.write_doc('workflow/audit/2024/aud-002-run/aud-002-readme.md', 'aud')
        self.write_doc('workflow/audit/2024/aud-002-run/pln-999-attachment.md')
        support.wb(main.parent / 'data.bin', b'\xff\x00')
        pr, docs, rep = self.scan()
        self.assertEqual(len(docs), 6)
        self.assertEqual(rep.items, [])
        self.assertEqual(work_targets(pr)['AUD-002'], [main])
        self.assertNotIn('PLN-999', work_targets(pr))
        self.assertEqual(next_number(pr, 'pln'), '003')
        self.assertEqual(resolve_mark(pr, 'PLN-002'), ('PLN-002', None))

    def test_wrong_layout_does_not_hide_header_links_or_duplicates(self):
        self.write_doc('workflow/plan/pln-001-flat.md', status='completed')
        duplicate = self.write_doc('workflow/plan/2024/pln-001-year.md', status='неизвестен')
        support.w(duplicate, duplicate.read_text() + '\n[нет](missing.md)\n')
        pr, docs, rep = self.scan()
        codes = {item[3] for item in rep.items}
        self.assertTrue({'W10', 'W2', 'W3', 'W4', 'W6'} <= codes, rep.items)
        target, error = resolve_mark(pr, 'PLN-001')
        self.assertIsNone(target)
        self.assertIn(support.localized('ambiguous', 'неоднозначный'), error)
        self.assertTrue(docs['pln-001']['ambiguous'])

    def test_wrong_year_suggests_moving_entire_container(self):
        main = self.write_doc('workflow/audit/2025/aud-003-run/aud-003-readme.md', 'aud')
        _, _, rep = self.scan()
        warning, = [item for item in rep.items if item[3] == 'W11']
        self.assertEqual(warning[2], 'W')
        self.assertIn('lipi mv "workflow/audit/2025/aud-003-run" "workflow/audit/2024/aud-003-run"', warning[4])
        self.assertEqual(warning[0], main.relative_to(self.root).as_posix())

    def test_decisions_flat_bare_and_prefixed_and_feedback(self):
        self.write_doc('workflow/adr/0007-choice.md', 'adr')
        self.write_doc('workflow/adr/adr-008-choice/adr-008-readme.md', 'adr')
        self.write_doc('.agents/lipi-feedback/iss-015-note.md', 'iss')
        pr, docs, rep = self.scan()
        self.assertEqual(rep.items, [])
        self.assertEqual(set(docs), {'adr-007', 'adr-008', 'iss-015'})
        self.assertEqual(next_number(pr, 'adr'), '009')
        self.assertEqual(next_number(pr, 'iss'), '016')
        self.assertEqual(resolve_mark(pr, 'ADR-7'), ('ADR-007', None))
        self.assertNotIn('ISS-015', work_targets(pr))
        self.write_doc('workflow/adr/2024/adr-009-wrong.md', 'adr', status='rejected')
        _, docs, rep = self.scan()
        self.assertIn('adr-009', docs)
        self.assertTrue({'W10', 'W4'} <= {item[3] for item in rep.items})
        self.assertEqual(next_number(self.project(), 'adr'), '010')

    def test_number_reservation_reads_names_only_in_both_archives(self):
        for prefix, directory in TYPES.items():
            support.wb(self.root / ('workflow/history/%s/2022/%s-021-old.md' % (directory, prefix)), b'\xff')
            support.wb(self.root / ('history/%s/2021/%s-025-old.md' % (directory, prefix)), b'\xff')
        self.write_doc('.agents/lipi-feedback/iss-030-note.md', 'iss')
        pr = self.project()
        with patch.object(pr, 'page', side_effect=AssertionError('archive text read')):
            for prefix in TYPES:
                self.assertEqual(next_number(pr, prefix), '031' if prefix == 'iss' else '026')
                self.assertIn(25, reserved_numbers(pr, prefix))
        _, docs, rep = self.scan()
        self.assertEqual(set(docs), {'iss-030'})
        self.assertEqual(rep.items, [])

    def test_bare_four_digit_decision_folder_is_not_a_year(self):
        self.write_doc('workflow/adr/0009/0009-readme.md', 'adr')
        self.write_doc('workflow/adr/0009/adr-999-attachment.md', 'adr')
        pr, docs, rep = self.scan()
        self.assertEqual(rep.items, [])
        self.assertEqual(set(docs), {'adr-009'})
        self.assertEqual(next_number(pr, 'adr'), '010')
        self.assertEqual(resolve_mark(pr, 'ADR-009'), ('ADR-009', None))

    def test_closed_date_required_only_for_valid_final_type_and_status(self):
        for prefix in TYPES:
            for status in list(STATUSES.get(prefix, ())) + ['чужой', 'closed']:
                with self.subTest(prefix=prefix, status=status):
                    path = ('workflow/adr/adr-001-choice.md' if prefix == 'adr' else
                            'workflow/%s/2024/%s-001-one.md' % (TYPES[prefix][0], prefix))
                    doc = self.write_doc(path, prefix, status=status)
                    _, _, rep = self.scan()
                    missing = [item for item in rep.items if item[3] == 'W4' and item[5] == K_CLOSED]
                    self.assertEqual(bool(missing), is_final(prefix, status), rep.items)
                    doc.unlink()

    def test_invalid_closed_dates_and_calendar_created_date(self):
        for value in ('2024-02-30', '2023-12-31', '20240102'):
            with self.subTest(value=value):
                self.write_doc('workflow/plan/2024/pln-001-one.md', status='completed', closed=value)
                _, _, rep = self.scan()
                self.assertTrue(any(item[3] == 'W3' and item[5] == K_CLOSED for item in rep.items), rep.items)
        self.write_doc('workflow/plan/2024/pln-001-one.md', created='2024-02-30')
        _, _, rep = self.scan()
        self.assertTrue(any(item[3] == 'W3' and item[5] == K_CREATED for item in rep.items), rep.items)
        self.assertFalse(any(item[3] == 'W11' for item in rep.items))

    def test_check_uses_one_utc_closure_limit_for_w3_and_index(self):
        cases = (('2026-11-18', '2026-11-19', '2026-11-20'),
                 ('2026-11-30', '2026-12-01', '2026-12-02'),
                 ('2026-12-31', '2027-01-01', '2027-01-02'))
        argv = ['lipi check', '--root', str(self.root), '--format', 'json', '--write-index']
        for utc_date, latest, future in cases:
            for utc_offset in (0, 3):
                for closed, accepted in ((latest, True), (future, False)):
                    with self.subTest(utc_date=utc_date, utc_offset=utc_offset, closed=closed):
                        self.write_doc('workflow/plan/2024/pln-001-one.md',
                                       status='completed', closed=closed)
                        output = StringIO()
                        fixed = support.freeze_workflow_clock(utc_date + 'T21:30:00+00:00',
                                                              utc_offset)
                        with fixed as clock, patch.object(sys, 'argv', argv), redirect_stdout(output):
                            code = check_main()
                        clock.now.assert_called_once_with(timezone.utc)
                        report = json.loads(output.getvalue())
                        self.assertEqual(code, 0 if accepted else 1, report)
                        if accepted:
                            index = self.root / 'workflow/index/done' / (closed[:4] + '.md')
                            self.assertIn('(%s)' % closed, index.read_text(encoding='utf-8'))
                        else:
                            finding, = report['errors']
                            self.assertEqual((finding['code'], finding['subject']), ('W3', K_CLOSED))

    def test_final_date_does_not_extend_result_requirement(self):
        for prefix, status in (('adr', 'rejected'), ('dsc', 'closed')):
            relative = ('workflow/adr/adr-001-choice.md' if prefix == 'adr' else
                        'workflow/discussion/2024/dsc-001-one.md')
            path = self.write_doc(relative, prefix, status=status, closed='2024-02-01')
            support.sub(path, '- Result: проверено\n', '')
        _, _, rep = self.scan()
        self.assertEqual(rep.items, [])

    def test_new_uses_creation_year_and_finds_old_similar_issue(self):
        old = self.write_doc('workflow/issue/2024/iss-041-old.md', 'iss')
        support.wb(self.root / 'history/iss-042-old.md', b'\xff')
        pr = self.project()
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cmd_new(pr, ['iss', 'Проверка раскладки', 'bug'], fmt='json'), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['id'], 'ISS-043')
        self.assertEqual(Path(result['path']).parent, Path('workflow/issue') / str(date.today().year))
        self.assertEqual(result['similar'][0]['path'], old.relative_to(self.root).as_posix())
        path = self.root / result['path']
        support.sub(path, '- Status: open', '- Status: closed\n- Closed: ' + date.today().isoformat())
        self.assertTrue(path.exists())

    def test_external_decisions_without_workflow(self):
        self.cfg.update(workflow=None, decisions='decisions')
        self.write_doc('decisions/0001-choice.md', 'adr', status='superseded', closed='2024-02-01')
        pr, docs, rep = self.scan()
        self.assertEqual(rep.items, [])
        self.assertEqual(resolve_mark(pr, 'ADR-001'), ('ADR-001', None))
        with redirect_stdout(StringIO()):
            self.assertEqual(cmd_new(pr, ['adr', 'Следующий выбор']), 0)
        self.assertTrue((self.root / 'decisions/0002-sleduyuschiy-vybor.md').is_file())


if __name__ == '__main__':
    unittest.main()
