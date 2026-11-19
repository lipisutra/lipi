"""Дата вне области просмотра не отменяет доказанный перенос пары."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tests import support
from tests.support import localized
from lipi.checker.config import DEFAULTS
from lipi.checker.model import Project
from lipi.checker.reviews import REVIEWS_NAME, ReviewContext, serialize_reviews
from lipi.layout_reviews import validate_final_reviews
from lipi.move import FileChange
from lipi.move_links import replacements
from lipi.move_reviews import AddressReceipt, TransferError, prepare_transfer


# @trace docs/ru/review.md#move,ADR-020
class LayoutReviewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='lipi-layout-reviews-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.old = self.root / 'workflow/plan/pln-001-one.md'
        self.new = self.root / 'workflow/plan/2024/pln-001-one.md'
        self.source = self.root / 'src/main.py'
        self.cfg = dict(DEFAULTS)

    def project(self):
        return Project(self.root, self.cfg)

    def setup_pair(self, *, header_anchor=False):
        anchor = '<a id="scope"></a>'
        support.w(self.old, '# Plan%s\n\n- Created: 2024-01-01\n'
                  '- Updated: 2024-02-02\n- Status: completed\n- Result: готово\n\n'
                  '%sText.\n' % (' ' + anchor if header_anchor else '',
                                  '' if header_anchor else '## Scope ' + anchor + '\n\n'))
        support.w(self.source, '# %s workflow/plan/pln-001-one.md#scope\nvalue = 1\n' % support.TAG)
        pair, = ReviewContext(self.project()).pairs
        entry = {key: pair[key] for key in ('id', 'relation', 'source', 'target')}
        entry.update(reviewer='tester', reviewed_at='2024-03-03T12:00:00Z', reason='Checked.', head=None)
        registry = dict(schema=1, algorithm='sha256-lines-v1', entries=[entry])
        support.wb(self.root / REVIEWS_NAME, serialize_reviews(registry))
        return entry

    def make_plan(self, *, move=True):
        moves = {self.old: self.new} if move else {}
        changes = []
        for path in (self.old, self.source):
            before = path.read_bytes()
            text = before.decode()
            edits = replacements(text, path=path, moves=moves, root=self.root,
                                 markdown=path.suffix == '.md')
            if edits or path in moves:
                for edit in reversed(edits):
                    text = text[:edit.start] + edit.after + text[edit.end:]
                after = text.encode()
                receipt = AddressReceipt(self.root, path, before, after, frozenset(moves.items()), tuple(edits))
                changes.append(FileChange(path, before, after, (), edits, receipt))
        project = self.project()
        transfer = prepare_transfer(project, moves, changes)
        return project, SimpleNamespace(reviews=transfer, moves=moves), changes

    def date_change(self, changes):
        change = next((change for change in changes if change.path == self.old), None)
        if change is None:
            change = FileChange(self.old, self.old.read_bytes(), self.old.read_bytes(), (), [])
            changes.append(change)
        change.after = change.after.replace(
            '- Result: готово\n'.encode(), '- Result: готово\n- Closed: 2024-02-02\n'.encode())

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_header_outside_anchor_survives_move_with_same_allowed_hashes(self):
        original = self.setup_pair()
        project, plan, changes = self.make_plan()
        address_registry = plan.reviews.after
        address_entry, = json.loads(address_registry)['entries']
        self.assertNotEqual(address_entry['source']['sha256'], original['source']['sha256'])
        self.assertEqual(address_entry['target']['sha256'], original['target']['sha256'])
        self.date_change(changes)
        before = self.snapshot()
        validate_final_reviews(project, plan, changes)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(plan.reviews.after, address_registry)
        for key in ('reviewer', 'reviewed_at', 'reason', 'head'):
            self.assertEqual(address_entry[key], original[key])

    def test_header_anchor_rejects_date_without_writing_or_refreshing(self):
        self.setup_pair(header_anchor=True)
        project, plan, changes = self.make_plan()
        self.date_change(changes)
        before, registry = self.snapshot(), plan.reviews.after
        with self.assertRaisesRegex(TransferError, localized('reviewed region', 'просмотренную область')):
            validate_final_reviews(project, plan, changes)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(plan.reviews.after, registry)

    def test_header_only_update_guards_unchanged_source_and_allows_line_shift(self):
        original = self.setup_pair()
        project, plan, changes = self.make_plan(move=False)
        self.assertEqual(plan.reviews.entries, [])
        self.date_change(changes)
        changes.append(FileChange(self.source, self.source.read_bytes(),
                                  b'# Intro\n' + self.source.read_bytes(), (), []))
        validate_final_reviews(project, plan, changes)
        self.assertEqual(plan.reviews.entries, [original])
        self.assertIn(self.source, plan.reviews.files)
        self.assertIn(self.old, plan.reviews.files)
        self.assertEqual(plan.reviews.after, plan.reviews.before)
        self.source.write_bytes(self.source.read_bytes() + b'# Concurrent edit\n')
        with self.assertRaisesRegex(TransferError, localized('changed', 'изменилась')):
            plan.reviews.validate(self.project())

    def test_changed_managed_source_region_refuses(self):
        self.setup_pair()
        project, plan, changes = self.make_plan(move=False)
        changes.append(FileChange(self.source, self.source.read_bytes(),
                                  self.source.read_bytes().replace(b'value = 1', b'value = 2'), (), []))
        before = self.snapshot()
        with self.assertRaisesRegex(TransferError, localized('reviewed region', 'просмотренную область')):
            validate_final_reviews(project, plan, changes)
        self.assertEqual(self.snapshot(), before)

    def test_final_duplicate_source_groups_are_not_an_unambiguous_review(self):
        self.setup_pair()
        project, plan, changes = self.make_plan(move=False)
        changes.append(FileChange(self.source, self.source.read_bytes(),
                                  self.source.read_bytes() * 2, (), []))
        with self.assertRaisesRegex(TransferError, localized('reviewed region', 'просмотренную область')):
            validate_final_reviews(project, plan, changes)
        self.assertEqual(plan.reviews.entries, [])

    def test_stale_entry_stays_unchanged_without_new_acknowledgment(self):
        original = self.setup_pair(header_anchor=True)
        self.source.write_bytes(self.source.read_bytes().replace(b'value = 1', b'value = 2'))
        project, plan, changes = self.make_plan()
        self.assertEqual(plan.reviews.entries, [])
        self.date_change(changes)
        before = self.snapshot()
        validate_final_reviews(project, plan, changes)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(plan.reviews.after, plan.reviews.before)
        self.assertEqual(json.loads(plan.reviews.after)['entries'], [original])
        self.assertEqual(plan.reviews.entries, [])


if __name__ == '__main__':
    unittest.main()
