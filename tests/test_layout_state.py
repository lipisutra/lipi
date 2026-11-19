"""Адресный перенос базовой линии без нового долга и записи файлов."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests import support
from tests.support import localized
from lipi.checker.conventions import BASE_NAME
from lipi.layout_state import BaselineTransferError, transfer_baseline
from lipi.move import FileChange
from lipi.move_links import replacements
from lipi.move_reviews import AddressReceipt


# @trace docs/ru/commands.md#baseline,ADR-020
class LayoutStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='lipi-layout-state-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.old = self.root / 'workflow/plan/pln-001-one.md'
        self.new = self.root / 'workflow/plan/2024/pln-001-one.md'
        self.moves = {self.old: self.new}

    def baseline(self, entries):
        data = json.dumps({'schema': 1, 'entries': entries}, ensure_ascii=False).encode()
        path = self.root / BASE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data

    def entry(self, code='W6', file=None, subject='../../missing.md#part', count=3):
        return {'code': code, 'file': file or self.old.relative_to(self.root).as_posix(),
                'subject': subject, 'count': count}

    def change(self, source, text, moves=None):
        moves = self.moves if moves is None else moves
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text)
        edits = replacements(text, path=source, moves=moves, root=self.root,
                             markdown=source.suffix == '.md')
        after = text
        for edit in reversed(edits):
            after = after[:edit.start] + edit.after + after[edit.end:]
        before, after = text.encode(), after.encode()
        receipt = AddressReceipt(self.root, source, before, after, frozenset(moves.items()), tuple(edits))
        return FileChange(source, before, after, (), edits, receipt)

    def test_broken_relative_link_subject_and_file_move_keep_count_and_other_debt(self):
        change = self.change(self.old, '# Plan\n\n[Missing](../../missing.md#part)\n')
        baseline = self.baseline([self.entry(), self.entry('D2', subject='../../missing.md#part', count=2)])
        before, after, notices = transfer_baseline(self.root, self.moves, [change])
        result = json.loads(after)
        self.assertEqual(before, baseline)
        self.assertEqual(result['schema'], 1)
        self.assertEqual(result['entries'], [
            self.entry(file='workflow/plan/2024/pln-001-one.md', subject='../../../missing.md#part'),
            self.entry('D2', file='workflow/plan/2024/pln-001-one.md', subject='../../missing.md#part', count=2)])
        self.assertEqual((self.root / BASE_NAME).read_bytes(), baseline)
        self.assertEqual(self.old.read_bytes(), change.before)
        self.assertFalse(self.new.exists())
        self.assertEqual(len(notices), 2)

    def test_relative_and_rooted_codes_use_their_own_bases(self):
        target = self.root / 'workflow/issue/iss-002-note.md'
        destination = self.root / 'workflow/issue/2024/iss-002-note.md'
        moves = dict(self.moves)
        moves[target] = destination
        doc = self.root / 'docs/page.md'
        source = self.root / 'src/main.py'
        old_rel = '../workflow/issue/iss-002-note.md#absent'
        old_root = 'workflow/issue/iss-002-note.md#absent'
        changes = [self.change(doc, '[Work](%s)\n<!-- covers: %s -->\n' % (old_rel, old_root), moves),
                   self.change(source, '# %s %s\n' % (support.TAG, old_root), moves)]
        entries = [self.entry(code, 'docs/page.md', old_rel, 1) for code in ('D1', 'D5', 'D7', 'W9')]
        entries += [self.entry('D6', 'docs/page.md', old_root, 2), self.entry('T1', 'src/main.py', old_root, 4)]
        self.baseline(entries)
        _, after, _ = transfer_baseline(self.root, moves, changes)
        actual = json.loads(after)['entries']
        for old, new in zip(entries, actual):
            self.assertEqual(new['subject'], old['subject'].replace('/issue/', '/issue/2024/'))
            self.assertEqual(new['code'], old['code'])
            self.assertEqual(new['count'], old['count'])

    def test_missing_registry_and_unchanged_registry_preserve_exact_bytes(self):
        self.assertEqual(transfer_baseline(self.root, self.moves, []), (None, None, []))
        self.assertFalse((self.root / BASE_NAME).exists())
        original = self.baseline([self.entry('D2', 'docs/page.md', 'part')])
        self.assertEqual(transfer_baseline(self.root, self.moves, []), (original, original, []))

    def test_stale_address_subject_without_matching_edit_refuses(self):
        change = self.change(self.old, '# Plan\n\n[Other](../../different.md)\n')
        original = self.baseline([self.entry()])
        with self.assertRaisesRegex(BaselineTransferError, 'subject'):
            transfer_baseline(self.root, self.moves, [change])
        self.assertEqual((self.root / BASE_NAME).read_bytes(), original)

    def test_same_subject_with_two_address_meanings_refuses(self):
        moves = dict(self.moves)
        moves[self.root / 'workflow/note.md'] = self.root / 'workflow/2024/note.md'
        change = self.change(self.old, '[Link](workflow/note.md)\n'
                             '<!-- covers: workflow/note.md -->\n', moves)
        self.assertEqual(len({edit.after for edit in change.edits}), 2)
        original = self.baseline([self.entry(subject='workflow/note.md')])
        with self.assertRaisesRegex(BaselineTransferError, 'subject'):
            transfer_baseline(self.root, moves, [change])
        self.assertEqual((self.root / BASE_NAME).read_bytes(), original)

    def test_local_anchor_and_work_id_subjects_remain_unchanged(self):
        change = self.change(self.old, '[Local](#missing)\n<!-- covers: PLN-002 -->\n')
        entries = [self.entry(subject='#missing'), self.entry('D6', subject='PLN-002')]
        self.baseline(entries)
        _, after, _ = transfer_baseline(self.root, self.moves, [change])
        expected = [dict(entry, file=self.new.relative_to(self.root).as_posix()) for entry in entries]
        self.assertEqual(json.loads(after)['entries'], expected)

    def test_transferred_debt_covers_old_finding_but_not_a_new_broken_link(self):
        from lipi.checker.config import DEFAULTS
        from lipi.checker.docs import check_links
        from lipi.checker.model import Project
        from lipi.checker.report import Report
        from lipi.checker.state import apply_baseline
        change = self.change(self.old, '# Plan\n\n[Old](../../missing.md#part)\n'
                             '[New](../../another.md)\n')
        self.baseline([self.entry(count=1)])
        _, after, _ = transfer_baseline(self.root, self.moves, [change])
        self.new.parent.mkdir(parents=True)
        self.new.write_bytes(change.after)
        self.old.unlink()
        (self.root / BASE_NAME).write_bytes(after)
        project, report = Project(self.root, dict(DEFAULTS)), Report()
        check_links(project, report, project.page(self.new), 'W6')
        self.assertEqual(len(report.items), 2)
        self.assertEqual(apply_baseline(self.root, report), (1, 0))
        self.assertEqual([(item[3], item[5]) for item in report.items], [('W6', '../../../another.md')])

    def test_unproved_receipt_and_semantic_or_raced_changes_refuse(self):
        change = self.change(self.old, '# Plan\n\n[Missing](../../missing.md#part)\n')
        self.baseline([self.entry()])
        for broken in (replace(change, address_receipt=None),
                       replace(change, after=change.after + b'Extra text.\n'),
                       replace(change, address_receipt=replace(change.address_receipt, moves=frozenset()))):
            with self.subTest(change=broken):
                with self.assertRaises(BaselineTransferError):
                    transfer_baseline(self.root, self.moves, [broken])
        self.old.write_bytes(change.before + b'Changed.\n')
        with self.assertRaisesRegex(BaselineTransferError, localized('changed', 'изменился')):
            transfer_baseline(self.root, self.moves, [change])

    def test_collision_refuses_instead_of_merging_counts(self):
        self.baseline([self.entry('D2', subject='part'),
                       self.entry('D2', file=self.new.relative_to(self.root).as_posix(), subject='part', count=8)])
        with self.assertRaisesRegex(BaselineTransferError, localized('collide', 'коллизия')):
            transfer_baseline(self.root, self.moves, [])

    def test_malformed_registry_and_symlink_refuse(self):
        original = self.baseline([self.entry()])
        path = self.root / BASE_NAME
        for bad in (b'{bad', b'{"schema": 9, "entries": []}',
                    b'{"schema": 1, "entries": [{"count": -1}]}'):
            path.write_bytes(bad)
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(BaselineTransferError, 'C1'):
                    transfer_baseline(self.root, self.moves, [])
                self.assertEqual(path.read_bytes(), bad)
        path.unlink()
        target = self.root / 'saved.json'
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaisesRegex(BaselineTransferError, localized('symlink', 'символическая')):
            transfer_baseline(self.root, self.moves, [])
        self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
