"""Физическая строка примера не создаёт связи и границы кода."""

import sys
from pathlib import Path

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))
from lipi.checker.config import load_config
from lipi.checker.history import GitBlame
from lipi.checker.marks import ignores_trace, trace_matches
from lipi.checker.model import Project
from lipi.checker.report import Report
from lipi.checker.trace import check_drift, scan_code
from lipi.map import build_map
from lipi.move_links import replacements, trace_targets
from lipi.slice_diff import collect_diff
from lipi.slice_index import SliceIndex


TARGET = "docs/guide.md#max-discount"
OTHER = "docs/guide.md#other"
IGNORE = "lipi: ignore-trace"


# @trace ADR-018
class IgnoreTrace(support.Case):
    def load(self, root):
        return Project(root.resolve(), load_config(root, None))

    def scan(self, root):
        pr, rep = self.load(root), Report()
        tags, lines = scan_code(pr, rep)
        return pr, rep, tags, lines

    def test_examples_in_strings_docstrings_and_comments_leave_neighbor_marks(self):
        root = self.project()
        support.w(root / "src/examples.py", '\n'.join([
            'sample = "# %s missing"  # %s' % (support.TAG, IGNORE),
            '"""%s missing %s"""' % (support.TAG, IGNORE),
            '# %s %s missing' % (IGNORE, support.TAG),
            '# %s missing %s %s %s' % (support.TAG, support.TAG, TARGET, IGNORE),
            '# %s %s' % (support.TAG, TARGET),
            'value = 1',
            '# %s missing' % support.TAG,
        ]) + '\n')
        pr, rep, tags, lines = self.scan(root)
        self.assertEqual(tags[TARGET], [('src/examples.py', 5), ('src/order.py', 1)])
        self.assertEqual(lines['src/examples.py'], [(5, [TARGET]), (7, [])])
        self.assertEqual([(item[1], item[3]) for item in rep.items], [(7, 'T1')])
        self.assertEqual(pr.ignored_trace_lines, 4)

    def test_exact_literal_and_each_physical_line(self):
        for value in ('lipi:ignore-trace', 'Lipi: ignore-trace', 'lipi: ignore_trace',
                      'lipi:  ignore-trace'):
            line = '# %s missing %s' % (support.TAG, value)
            with self.subTest(value=value):
                self.assertFalse(ignores_trace(line))
                self.assertEqual(len(list(trace_matches(line))), 1)
        root = self.project()
        support.w(root / 'src/examples.py', '# %s\n# %s missing\n' % (IGNORE, support.TAG))
        pr, rep, _, lines = self.scan(root)
        self.assertEqual(pr.ignored_trace_lines, 1)
        self.assertEqual(lines['src/examples.py'], [(2, [])])
        self.assertEqual(rep.items[0][3], 'T1')

    def test_counter_counts_lines_without_marks_and_resets_with_scan_scope(self):
        root = self.project()
        support.w(root / 'src/plain.py', '# %s %s\n# %s\n' % (IGNORE, IGNORE, IGNORE))
        for path in ('README.md', 'docs/example.py', 'workflow/example.py',
                     '.git/example.py', 'node_modules/example.py'):
            support.w(root / path, '# %s\n' % IGNORE)
        support.wb(root / 'src/binary.bin', b'\xff' + IGNORE.encode())
        pr, rep, _, _ = self.scan(root)
        self.assertEqual(pr.ignored_trace_lines, 2)
        support.w(root / 'src/plain.py', '# plain\n')
        scan_code(pr, rep)
        self.assertEqual(pr.ignored_trace_lines, 0)

    def test_ignored_closed_work_does_not_emit_t3(self):
        root = self.project()
        support.header_set(root, 'pln', {'Status': 'completed'})
        support.w(root / 'src/examples.py', '# %s PLN-001 %s\n# %s PLN-001\n' %
                  (support.TAG, IGNORE, support.TAG))
        _, rep, tags, _ = self.scan(root)
        self.assertEqual(tags['PLN-001'], [('src/examples.py', 2)])
        self.assertEqual([(item[1], item[3]) for item in rep.items], [(2, 'T3')])

    def test_check_slice_map_and_drift_share_real_boundaries(self):
        root = self.project()
        guide = root / 'docs/guide.md'
        support.w(guide, guide.read_text() + '\n## Other <a id="other"></a>\n')
        support.w(root / 'src/order.py', '# %s %s\ndef discount():\n'
                  '    sample = "%s %s"  # %s\n    return sample\n' %
                  (support.TAG, TARGET, support.TAG, OTHER, IGNORE))
        pr, rep, tags, lines = self.scan(root)
        index = SliceIndex(pr)
        self.assertEqual(set(tags), {TARGET})
        self.assertEqual(lines['src/order.py'], [(1, [TARGET])])
        self.assertEqual(index.boundaries['src/order.py'], [1])
        self.assertEqual(set(index.by_target), {TARGET})
        rows = {row['target']: row for row in build_map(pr)['rows']}
        self.assertEqual(rows[TARGET]['code'], {'src': 1})
        self.assertEqual(rows[OTHER]['code'], {'src': 0})
        check_drift(pr, rep, {}, {TARGET: (pr.page(guide), 3)}, {}, lines,
                    {'src/order.py': [(3, 3)]})
        self.assertEqual([item[3] for item in rep.items], ['T2'])
        history = GitBlame(root)
        history.cache['src/order.py'] = [(10, '# %s %s' % (support.TAG, TARGET)),
                                         (10, 'def discount():'),
                                         (30, '# %s %s %s' % (support.TAG, OTHER, IGNORE)),
                                         (10, '    return 0')]
        self.assertEqual(history.region_time('src/order.py', 1, [1], code=True), 30)

    def test_a3_requires_unignored_nearby_mark(self):
        root = self.project()
        support.set_config(root, entry=['^def entry'])
        path = root / 'src/entry.py'
        ignored = '# %s %s %s\n' % (support.TAG, TARGET, IGNORE)
        support.w(path, ignored + 'def entry():\n    pass\n')
        _, output = support.check(root, '--audit')
        self.assertTrue(support.found(output, 'A3'), output)
        support.w(path, ignored + '# %s %s\ndef entry():\n    pass\n' % (support.TAG, TARGET))
        _, output = support.check(root, '--audit')
        self.assertFalse(support.found(output, 'A3'), output)

    def test_unicode_separators_do_not_split_a_physical_line(self):
        root = self.project()
        path = root / 'src/order.py'
        for separator in ('\v', '\f', '\x85', '\u2028', '\u2029'):
            with self.subTest(separator=repr(separator)):
                text = '# %s missing%s%s\r\n# %s %s\r\ndef discount():\r\n    pass\r\n' % (
                    support.TAG, separator, IGNORE, support.TAG, TARGET)
                support.w(path, text)
                pr, rep, tags, lines = self.scan(root)
                self.assertEqual(rep.items, [])
                self.assertEqual(tags[TARGET], [('src/order.py', 2)])
                self.assertEqual(lines['src/order.py'], [(2, [TARGET])])
                self.assertEqual(SliceIndex(pr).boundaries['src/order.py'], [2])
                self.assertEqual(pr.ignored_trace_lines, 1)

    def test_diff_uses_exclusion_on_old_new_and_staged_sides(self):
        root = self.project()
        guide = root / 'docs/guide.md'
        support.w(guide, guide.read_text() + '\n## Other <a id="other"></a>\n')
        path = root / 'src/order.py'
        before = '# %s %s\ndef discount():\n    sample = "%s %s"  # %s\n    return 1\n' % (
            support.TAG, TARGET, support.TAG, OTHER, IGNORE)
        support.w(path, before)
        support.git_init(root)
        self.assertEqual(support.commit(root)[0], 0)
        support.w(path, before.replace('return 1', 'return 2'))
        current = collect_diff(SliceIndex(self.load(root)), base='HEAD')
        self.assertEqual(current['seeds'], {TARGET})
        self.assertEqual(current['unmarked'], 0)
        support.w(path, before.replace('    sample = "%s %s"  # %s\n' %
                                      (support.TAG, OTHER, IGNORE), ''))
        deleted = collect_diff(SliceIndex(self.load(root)), base='HEAD')
        self.assertEqual(deleted['seeds'], {TARGET})
        self.assertEqual(deleted['unmarked'], 0)
        self.assertEqual(support.git(root, 'add', '-A')[0], 0)
        staged = collect_diff(SliceIndex(self.load(root)), staged=True)
        self.assertEqual(staged['seeds'], {TARGET})
        self.assertEqual(staged['unmarked'], 0)

    def test_move_keeps_ignored_comments_and_lexer_and_offsets(self):
        text = ('// %s old.md#part %s\r\n'
                '/* %s\n * %s old.md#part\n'
                ' * %s old.md#part %s\n */\n'
                'value = "%s"; /* %s old.md#part */\n'
                '/* %s old.md#part */ value = "%s";\n'
                'value = "// %s old.md#part";\n'
                '// %s old.md#part\n') % (
                    support.TAG, IGNORE, IGNORE, support.TAG, support.TAG, IGNORE,
                    IGNORE, support.TAG, support.TAG, IGNORE, support.TAG, support.TAG)
        found = list(trace_targets(text, Path('source.js')))
        self.assertEqual(len(found), 2)
        for offset, token in found:
            self.assertEqual(text[offset:offset + len(token)], 'old.md#part')
        changes = replacements(text, path=support.LIPI / 'source.js', root=support.LIPI,
                               moves={support.LIPI / 'old.md': support.LIPI / 'new.md'},
                               markdown=False)
        self.assertEqual([change.start for change in changes], [offset for offset, _ in found])
        self.assertEqual([change.after for change in changes], ['new.md#part'] * 2)
