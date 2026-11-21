"""Разбор ролей у меток и их объединение в группах кода."""

import sys
import unittest

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.marks import standalone_trace, trace_groups, trace_matches, trace_roles


# @trace docs/ru/rules.md#trace-roles
class TraceRoles(unittest.TestCase):
    def test_role_values_and_target_span(self):
        targets = 'docs/a.md#part , docs/b.md#part'
        for suffix, expected in [
            ('', ((), ())),
            (' role=produces,consumes,produces', (('produces', 'consumes'), ())),
            (' role=consumes , reads, reads', (('consumes',), ('reads',))),
            (' role=', ((), ('',))),
            (' role=Reads,produces,', (('produces',), ('Reads', ''))),
        ]:
            with self.subTest(suffix=suffix):
                line = '// %s %s%s' % (support.TAG, targets, suffix)
                match, = trace_matches(line)
                self.assertEqual(match[1], targets)
                self.assertEqual(match.span(1), (len(support.TAG) + 4, len(line) - len(suffix)))
                self.assertEqual(trace_roles(match), expected)

    def test_next_marker_and_comment_closer_remain_outside_roles(self):
        line = '/* %s docs/a.md#part role=consumes, %s docs/b.md#part role=produces*/' % (
            support.TAG, support.TAG)
        first, second = trace_matches(line)
        self.assertEqual((first[1], second[1]), ('docs/a.md#part', 'docs/b.md#part'))
        self.assertLessEqual(first.end(), second.start())
        self.assertEqual(trace_roles(first), (('consumes',), ('',)))
        self.assertEqual(trace_roles(second), (('produces',), ()))
        self.assertEqual(line[second.end():], '*/')
        self.assertTrue(standalone_trace(line))

    def test_standalone_wrappers_and_inline_example(self):
        marker = '%s docs/a.md#part role=consumes' % support.TAG
        for before, after in [('# ', ''), ('// ', ''), ('-- ', ''), ('; ', ''),
                              ('* ', ''), ('/* ', '*/'), ('<!-- ', '-->')]:
            with self.subTest(before=before, after=after):
                line = before + marker + after
                match, = trace_matches(line)
                self.assertEqual(trace_roles(match), (('consumes',), ()))
                self.assertTrue(standalone_trace(line))

        line = 'const example = "/* ' + marker + '*/";'
        match, = trace_matches(line)
        self.assertEqual(trace_roles(match), (('consumes',), ()))
        self.assertFalse(standalone_trace(line))
        ignored = line + ' // lipi: ignore-trace'
        self.assertEqual(tuple(trace_matches(ignored)), ())
        self.assertFalse(standalone_trace(ignored))

    def test_group_roles_merge_by_resolved_target_in_either_order(self):
        a, b = 'docs/a.md#part', 'docs/b.md#part'
        marks = ['# %s %s' % (support.TAG, a),
                 '# %s ./%s,%s role=produces,reads,reads' % (support.TAG, a, b),
                 '# %s %s role=consumes,reads' % (support.TAG, a)]
        tail = ['def first():',
                'x = 1  # %s %s role=reads' % (support.TAG, a),
                '# %s %s role=produces lipi: ignore-trace' % (support.TAG, a),
                '# %s missing.md#part role=reads' % support.TAG,
                '# %s %s role=' % (support.TAG, b),
                'def second():']
        resolved = {a: a, './' + a: a, b: b}
        for ordered in (marks, marks[::-1]):
            with self.subTest(ordered=ordered):
                first, inline, last = trace_groups(ordered + tail, resolved.get)
                self.assertEqual((first['start'], first['end'], first['region_end']), (1, 3, 4))
                self.assertEqual(first['targets'], {a: 1, b: 2})
                self.assertEqual(first['target_roles'],
                                 {a: ({'consumes', 'produces'}, {'reads'}),
                                  b: ({'produces'}, {'reads'})})
                self.assertFalse(inline['standalone'])
                self.assertEqual((inline['start'], inline['end'], inline['region_end']), (5, 5, 6))
                self.assertEqual(inline['target_roles'], {a: (set(), {'reads'})})
                self.assertEqual((last['start'], last['end'], last['region_end']), (7, 8, 9))
                self.assertEqual(last['targets'], {b: 8})
                self.assertEqual(last['target_roles'], {b: (set(), {''})})
