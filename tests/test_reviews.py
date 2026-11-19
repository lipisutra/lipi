"""Реестр A4: строгая форма, точные строки, независимые пары и уборка."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config, validate_config
from lipi.checker.audit import audit
from lipi.checker.marks import trace_groups
from lipi.checker.model import Project
from lipi.checker.report import Report, level_of_project
from lipi.checker.reviews import (
    ALGORITHM, REVIEWS_NAME, ReviewContext, ReviewError, canonical_json,
    fingerprint, load_reviews, pair_id, raw_lines, serialize_reviews, validate_reviews,
)
from lipi.slice_index import SliceIndex


def entry(pair):
    return {key: pair[key] for key in ('id', 'relation', 'source', 'target')} | {
        'reviewer': 'Ирина', 'reviewed_at': '2026-11-18T12:30:00Z',
        'reason': 'Описание сохраняет верный результат', 'head': None}


def registry(*entries):
    return {'schema': 1, 'algorithm': ALGORITHM, 'entries': list(entries)}


# @trace docs/ru/review.md#state,docs/ru/review.md#pair,docs/ru/review.md#prune
class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'src/a.py'
        self.target = self.root / 'docs/a.md'
        self.trace = '# ' + support.TAG + ' docs/a.md#rule\n'
        support.w(self.source, self.trace + 'value = 1\n')
        support.w(self.target, '# A\n\n## Rule <a id="rule"></a>\nDescription\n')
        self.path = self.root / REVIEWS_NAME

    def context(self, **settings):
        cfg = load_config(self.root, None)
        cfg.update(settings)
        return ReviewContext(Project(self.root, cfg))

    def save(self, *entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(serialize_reviews(registry(*entries)))

    def test_exact_lines_and_canonical_hash(self):
        text = 'Первая\r\nвторая\rтретья\u2028ещё\nбез конца'
        lines = ['Первая\n', 'вторая\n', 'третья\u2028ещё\n', 'без конца']
        self.assertEqual(raw_lines(text), lines)
        expected = hashlib.sha256(json.dumps([ALGORITHM, 'trace', lines],
            ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(fingerprint('trace', lines), expected)
        self.assertNotEqual(fingerprint('trace', ['a']), fingerprint('trace', ['a\n']))
        self.assertNotEqual(fingerprint('trace', lines), fingerprint('anchor', lines))
        self.assertEqual(raw_lines(''), [])
        self.assertEqual(raw_lines('\n'), ['\n'])
        with self.assertRaises(UnicodeError):
            canonical_json(['\ud800'])

    def test_grouping_boundaries_inline_unresolved_and_ignored(self):
        rows = [self.trace.rstrip(), '# ' + support.TAG + ' docs/a.md#rule',
                'value = 1', '# ' + support.TAG + ' missing.md#x',
                'value = 2', '# ' + support.TAG + ' ignored.md#x lipi: ignore-trace',
                'value = 3 # ' + support.TAG + ' docs/a.md#rule',
                '# ' + support.TAG + ' docs/a.md#rule', 'value = 4']
        groups = trace_groups(rows, lambda token: token if token.startswith('docs/') else None)
        self.assertEqual([(g['start'], g['end'], g['region_end']) for g in groups],
                         [(1, 2, 3), (4, 4, 6), (7, 7, 7), (8, 8, 9)])
        self.assertEqual(groups[0]['targets'], {'docs/a.md#rule': 1})
        self.assertFalse(groups[2]['standalone'])

    def test_exact_source_and_discontinuous_anchor_regions(self):
        support.w(self.target, '# A\n\n| Name | Value |\n| --- | --- |\n'
                  '| Other | x |\n| Selected <a id="rule"></a> | y |\n| Last | z |\n')
        support.w(self.source, 'before\n' + self.trace + '# comment\nvalue = 1\n')
        pair = self.context().pairs[0]
        self.assertEqual(pair['source_ranges'], [[2, 4]])
        self.assertEqual(pair['source_lines'], [self.trace, '# comment\n', 'value = 1\n'])
        self.assertEqual(pair['target_ranges'], [[3, 3], [6, 6]])
        self.assertEqual(pair['target_lines'], ['| Name | Value |\n', '| Selected <a id="rule"></a> | y |\n'])
        old = pair['id']
        support.sub(self.target, '| Other | x |', '| Other | changed |\n| Extra | row |')
        self.assertEqual(self.context().pairs[0]['id'], old)
        support.sub(self.target, '| Name | Value |', '| Label | Value |')
        self.assertNotEqual(self.context().pairs[0]['id'], old)

    def test_unicode_separator_kept_in_anchor_physical_line(self):
        support.w(self.target, '# A\n\n## Rule <a id="rule"></a>\nOne\u2028two\nlast\n')
        self.assertEqual(self.context().pairs[0]['target_lines'],
                         ['## Rule <a id="rule"></a>\n', 'One\u2028two\n', 'last\n'])

    def test_existing_index_is_reused_and_no_history_read(self):
        pr = Project(self.root, load_config(self.root, None))
        index = SliceIndex(pr)
        with patch('lipi.slice_index.SliceIndex', side_effect=AssertionError('second index')), \
                patch('lipi.checker.history.GitBlame', side_effect=AssertionError('blame')):
            context = ReviewContext(pr, index=index)
            self.assertIs(context.index, index)
            self.assertEqual(len(context.pairs), 1)

    def test_absent_and_empty_registry(self):
        self.assertIsNone(load_reviews(self.root))
        self.save()
        self.assertEqual(load_reviews(self.root), registry())
        self.assertEqual(self.context().lifecycle(), ([], []))

    def test_pair_id_ignores_metadata_and_serialization_is_stable(self):
        pair = self.context().pairs[0]
        review = entry(pair)
        self.assertEqual(pair['id'], pair_id('trace', pair['source'], pair['target']))
        self.save(review)
        raw = self.path.read_bytes()
        self.assertTrue(raw.endswith(b'\n'))
        self.assertNotIn(b'\r', raw)
        self.assertEqual(serialize_reviews(load_reviews(self.root)), raw)
        context = self.context()
        self.assertEqual(context.existing(context.pairs[0]), review)

    def test_validation_rejects_every_invalid_entry_shape(self):
        base = registry(entry(self.context().pairs[0]))
        changes = [
            lambda d: d.update(schema=True), lambda d: d.update(schema=2),
            lambda d: d.update(algorithm='unknown'), lambda d: d.update(extra=0),
            lambda d: d.update(entries={}), lambda d: d['entries'].append(copy.deepcopy(d['entries'][0])),
            lambda d: d['entries'][0].update(id='0' * 64),
            lambda d: d['entries'][0].update(relation='covers'),
            lambda d: d['entries'][0].update(reviewer=' \n'),
            lambda d: d['entries'][0].update(reason=''),
            lambda d: d['entries'][0].update(reason='\ud800'),
            lambda d: d['entries'][0].update(head='a' * 39),
            lambda d: d['entries'][0].update(head='A' * 40),
            lambda d: d['entries'][0].update(head=True),
            lambda d: d['entries'][0].update(reviewed_at='2026-02-30T12:00:00Z'),
            lambda d: d['entries'][0].update(reviewed_at='2026-01-01T12:00:00+00:00'),
            lambda d: d['entries'][0].update(reviewed_at='2026-01-01T25:00:00Z'),
            lambda d: d['entries'][0].update(line=1),
            lambda d: d['entries'][0]['source'].update(kind='anchor'),
            lambda d: d['entries'][0]['source'].update(sha256='A' * 64),
            lambda d: d['entries'][0]['target'].update(anchor='#rule'),
            lambda d: d['entries'][0]['target'].update(anchor=''),
            lambda d: d['entries'][0]['target'].update(ordinal=1),
        ]
        for path in ['/tmp/a', '../a', 'src/../a', './a', 'src//a', 'src/a/',
                     'C:/a', 'C:a', 'src\\a', 'src/\0a']:
            changes.append(lambda d, path=path: d['entries'][0]['source'].update(path=path))
        for change in changes:
            data = copy.deepcopy(base)
            change(data)
            with self.subTest(data=repr(data)), self.assertRaises(ReviewError):
                validate_reviews(data)
        for key in ('id', 'relation', 'source', 'target', 'reviewer', 'reviewed_at', 'reason', 'head'):
            data = copy.deepcopy(base)
            del data['entries'][0][key]
            with self.subTest(missing=key), self.assertRaises(ReviewError):
                validate_reviews(data)

    def test_invalid_file_is_c1_before_checks(self):
        self.path.parent.mkdir(parents=True)
        for raw in [b'\xff', b'{', b'{"schema":1,"schema":1}',
                    b'{"schema":1,"algorithm":"sha256-lines-v1","entries":[],"x":NaN}']:
            self.path.write_bytes(raw)
            with self.assertRaises(ReviewError):
                load_reviews(self.root)
            errors = validate_config(self.root, load_config(self.root, None))
            self.assertTrue(any(path == REVIEWS_NAME for path, _ in errors))
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(ReviewError):
            load_reviews(self.root)

    def test_shift_and_move_inside_file_preserve_exact_unique_state(self):
        pair = self.context().pairs[0]
        self.save(entry(pair))
        support.w(self.source, 'outside = 0\n' + self.source.read_text())
        support.w(self.target, 'prefix\n' + self.target.read_text())
        context = self.context()
        self.assertEqual(context.classify(entry(pair)), ('current', None))
        self.assertTrue(context.acknowledges(context.pairs[0]))
        block = self.trace + 'value = 1\n'
        other = '# ' + support.TAG + ' missing.md#x\nother = 2\n'
        support.w(self.source, block + other)
        context = self.context()
        self.assertTrue(context.acknowledges(context.pairs[0]))
        support.w(self.source, other + block)
        context = self.context()
        self.assertTrue(context.acknowledges(context.pairs[0]))

    def test_comment_marker_whitespace_and_final_lf_change_identity(self):
        base = self.trace + 'value = 1\n'
        reviewed = entry(self.context().pairs[0])
        self.save(reviewed)
        for text in [self.trace + 'value = 1', self.trace + 'value  = 1\n',
                     self.trace + '# comment\nvalue = 1\n',
                     self.trace.replace('# ', '// ') + 'value = 1\n']:
            support.w(self.source, text)
            with self.subTest(text=text):
                context = self.context()
                self.assertEqual(context.classify(reviewed), ('obsolete', 'changed'))
                self.assertFalse(context.acknowledges(context.pairs[0]))
        support.w(self.source, base)
        self.assertEqual(self.context().classify(reviewed), ('current', None))

    def test_duplicate_groups_never_acknowledge_or_prune(self):
        reviewed = entry(self.context().pairs[0])
        self.save(reviewed)
        block = self.trace + 'value = 1\n'
        support.w(self.source, block + block)
        context = self.context()
        self.assertEqual(len(context.matching(reviewed)), 2)
        self.assertFalse(any(context.acknowledges(pair) for pair in context.pairs))
        self.assertEqual(context.classify(reviewed), ('unchecked', 'ambiguous'))
        self.assertEqual(len(context.lifecycle()[1]), 1)

    def test_missing_relation_source_target_and_changed_target(self):
        reviewed = entry(self.context().pairs[0])
        self.save(reviewed)
        support.w(self.source, 'value = 1\n')
        self.assertEqual(self.context().classify(reviewed), ('obsolete', 'missing-relation'))
        self.source.unlink()
        self.assertEqual(self.context().classify(reviewed), ('obsolete', 'missing-source'))
        support.w(self.source, self.trace + 'value = 1\n')
        support.sub(self.target, 'Description', 'Changed')
        self.assertEqual(self.context().classify(reviewed), ('obsolete', 'changed'))
        support.sub(self.target, 'id="rule"', 'id="other"')
        self.assertEqual(self.context().classify(reviewed), ('obsolete', 'missing-target'))
        self.target.unlink()
        context = self.context()
        self.assertEqual(context.classify(reviewed), ('obsolete', 'missing-target'))
        self.assertIn('docs/a.md', context.missing_paths)

    def test_unreadable_excluded_and_duplicate_anchor_are_unchecked(self):
        reviewed = entry(self.context().pairs[0])
        self.save(reviewed)
        self.assertEqual(self.context(skip_dirs=['src']).classify(reviewed), ('unchecked', 'excluded'))
        self.source.write_bytes(b'\xff')
        self.assertEqual(self.context().classify(reviewed), ('unchecked', 'unreadable'))
        support.w(self.source, self.trace + 'value = 1\n')
        support.w(self.target, self.target.read_text() + '\n## Other <a id="rule"></a>\n')
        self.assertEqual(self.context().classify(reviewed), ('unchecked', 'ambiguous'))

    def test_code_off_and_no_git_do_not_make_valid_review_obsolete(self):
        reviewed = entry(self.context().pairs[0])
        self.save(reviewed)
        self.assertEqual(self.context(codes={'A4': 'off'}).classify(reviewed), ('current', None))
        self.assertEqual(self.context().lifecycle(), ([], []))

    def test_multiple_versions_remain_distinct_until_prune(self):
        first = entry(self.context().pairs[0])
        support.sub(self.source, 'value = 1', 'value = 2')
        second = entry(self.context().pairs[0])
        self.save(second, first)
        context = self.context()
        remove, unchecked = context.lifecycle()
        self.assertEqual([item['id'] for item in remove], [first['id']])
        self.assertEqual(unchecked, [])
        self.assertTrue(context.acknowledges(context.pairs[0]))
        ids = [item['id'] for item in load_reviews(self.root)['entries']]
        self.assertEqual(ids, sorted(ids))

    def audit(self, **settings):
        cfg = load_config(self.root, None)
        cfg.update(settings)
        pr = Project(self.root, cfg)
        rep = Report(level_of_project(cfg))
        audit(pr, rep, {}, {}, {}, {})
        return pr, [item for item in rep.items if item[3] == 'A4']

    def test_audit_group_one_pair_filter_off_and_independent_place(self):
        support.w(self.source, self.trace + self.trace + 'value = 1\n')
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        support.sub(self.source, 'value = 1', 'value = 2')
        self.assertEqual(support.commit(self.root, date='2026-01-03T10:00:00')[0], 0)
        self.assertEqual(len(self.audit()[1]), 1)
        self.save(entry(self.context().pairs[0]))
        pr, findings = self.audit()
        self.assertEqual(findings, [])
        self.assertEqual(len(pr.reviewed_pairs), 1)
        self.assertEqual(pr.reviewed_obsolete, 0)
        pr, findings = self.audit(codes={'A4': 'off'})
        self.assertEqual(findings, [])
        self.assertEqual(pr.reviewed_pairs, set())
        support.w(self.root / 'src/b.py', self.trace + 'independent = 3\n')
        self.assertEqual(support.commit(self.root, date='2026-01-04T10:00:00')[0], 0)
        pr, findings = self.audit(codes={'A4': 'error'})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][2], 'E')
        self.assertEqual(len(pr.reviewed_pairs), 1)

    def test_audit_adjacent_new_standalone_markers_do_not_date_code(self):
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        support.w(self.source, self.trace + self.trace + 'value = 1\n')
        self.assertEqual(support.commit(self.root, date='2026-01-03T10:00:00')[0], 0)
        self.assertEqual(self.audit()[1], [])
        support.w(self.source, 'value = 2 ' + self.trace)
        self.assertEqual(support.commit(self.root, date='2026-01-04T10:00:00')[0], 0)
        self.assertEqual(len(self.audit()[1]), 1)


if __name__ == '__main__':
    unittest.main()
