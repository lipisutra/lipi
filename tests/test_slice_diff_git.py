"""Git snapshots, changed code markers and Markdown regions."""
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import DEFAULTS
from lipi.checker.model import Project
from lipi.slice_diff import collect_diff
from lipi.slice_index import SliceIndex

TARGET = 'docs/concept.md#one'
SECOND = 'docs/concept.md#two'


# @trace docs/ru/slice-diff.md#selection
class SliceDiffGit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='lipi-diff-git-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        support.git_init(self.root)
        self.write('docs/concept.md', '# Concept\n\n## One <a id="one"></a>\n\n'
                   'One.\n\n## Two <a id="two"></a>\n\nTwo.\n')

    def write(self, path, content):
        support.w(self.root / path, content)

    def mark(self, body='value = 1\n', target=TARGET):
        return '# %s %s\n%s' % (support.TAG, target, body)

    def git(self, *args):
        code, output = support.git(self.root, *args)
        self.assertEqual(code, 0, output)
        return output

    def commit(self):
        code, output = support.commit(self.root)
        self.assertEqual(code, 0, output)

    def collect(self, base='HEAD', staged=False, **config):
        cfg = dict(DEFAULTS, **config)
        return collect_diff(SliceIndex(Project(self.root, cfg)),
                            base=None if staged else base, staged=staged)

    def test_marked_shared_targets_deduplicate_and_unmarked_replacements(self):
        self.write('src/one.py', self.mark())
        self.write('src/two.py', self.mark())
        self.write('src/plain.py', 'first = 1\nsecond = 1\n')
        self.commit()
        self.write('src/one.py', self.mark('value = 2\n'))
        self.write('src/two.py', self.mark('value = 3\n'))
        self.write('src/plain.py', 'first = 2\nsecond = 2\n')
        result = self.collect()
        self.assertEqual(result, {'seeds': {TARGET}, 'changed': {('src/one.py', 1),
                         ('src/two.py', 1)}, 'unmarked': 1, 'files': 3})

    def test_deleted_line_uses_old_marker_and_not_next_marker(self):
        self.write('src/main.py', self.mark('remove = 1\n') + self.mark('keep = 2\n', SECOND))
        self.commit()
        self.write('src/main.py', self.mark('', TARGET) + self.mark('keep = 2\n', SECOND))
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['unmarked'], 0)
        self.assertEqual(result['changed'], {('src/main.py', 1)})

    def test_deleted_whole_place_does_not_hide_unchanged_same_target(self):
        first = self.mark('def removed():\n    return 0\n\n')
        second = self.mark('def surviving():\n    return 0\n')
        self.write('src/main.py', first + second)
        self.commit()
        self.write('src/main.py', second)
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['changed'], set())

    def test_deleted_marker_keeps_historical_target_and_shifted_declaration(self):
        self.write('src/main.py', self.mark('keep = 1\n'))
        self.commit()
        self.write('src/main.py', 'keep = 1\n')
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['changed'], set())
        self.assertEqual(result['unmarked'], 0)

    def test_deleted_file_reads_old_blob(self):
        self.write('src/main.py', self.mark())
        self.commit()
        self.git('rm', 'src/main.py')
        result = self.collect(staged=True)
        self.assertEqual(result, {'seeds': {TARGET}, 'changed': set(), 'unmarked': 0, 'files': 1})

    def test_staged_uses_index_despite_dirty_marker_and_line_offsets(self):
        self.write('src/main.py', self.mark())
        self.commit()
        self.write('src/main.py', self.mark('value = 2\n'))
        self.git('add', 'src/main.py')
        self.write('src/main.py', '\n\n' + self.mark('value = 2\n', SECOND))
        result = self.collect(staged=True)
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['changed'], {('src/main.py', 3)})
        self.assertEqual(result['unmarked'], 0)

    def test_staged_resolves_code_markers_against_each_document_snapshot(self):
        contract, code, unrelated = 'docs/export.md', 'src/export.py', 'src/other.py'
        row, record = contract + '#row', contract + '#record'
        old_marker = './docs/%65xport.md#%72ow'
        old_document = '## Row <a id="row"></a>\nName before value.\n'
        self.write(contract, old_document)
        self.write(code, self.mark(target=old_marker))
        self.write(unrelated, self.mark(target=SECOND))
        self.commit()
        self.write(contract, '## Record <a id="record"></a>\nName before value.\n')
        self.write(code, self.mark('value = 2\n', record))
        self.write(unrelated, self.mark('value = 2\n', SECOND))
        self.git('add', '--', contract, code, unrelated)
        self.write(contract, old_document)

        diff = self.collect(staged=True)
        self.assertEqual(diff['seeds'], {row, record, SECOND})
        self.assertEqual(diff['unmarked'], 0)

        self.write(code, self.mark('value = 2\n', old_marker))
        self.git('add', '--', code)
        diff = self.collect(staged=True)
        self.assertEqual(diff['seeds'], {row, SECOND})
        self.assertEqual(diff['unmarked'], 1)

    def test_unborn_index_and_untracked_files(self):
        self.write('src/added.py', self.mark())
        self.git('add', '.')
        self.write('src/untracked.py', 'new = True\n')
        self.write('docs/untracked.md', '## Untracked <a id="untracked"></a>\n')
        result = self.collect(staged=True)
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['sections'], {
            TARGET: {'before': None, 'after': ['## One <a id="one"></a>', '', 'One.', '']},
            SECOND: {'before': None, 'after': ['## Two <a id="two"></a>', '', 'Two.']},
        })
        self.assertEqual(result['unanchored'], 1)

    def test_contract_diff_uses_index_code_snapshots_for_staged_and_worktree_changes(self):
        renamed, removed, dirty = 'src/old.py', 'src/removed.py', 'src/dirty.py'
        indexed = self.mark()
        for path in (renamed, removed, dirty):
            self.write(path, indexed)
        self.commit()
        new_name = 'src/new.py'
        self.git('mv', renamed, new_name)
        self.git('rm', removed)
        self.write('docs/concept.md', '# New requirement\n')
        self.git('add', 'docs/concept.md')
        self.write(new_name, self.mark(target=SECOND))
        (self.root / dirty).unlink()
        self.write('src/untracked.py', self.mark(target=SECOND))

        diff = self.collect(staged=True)
        snapshots = {row['old_path']: row for row in diff['code_snapshots']}
        rows = indexed.splitlines()
        self.assertEqual(snapshots, {
            renamed: {'old_path': renamed, 'new_path': new_name,
                      'before': rows, 'after': rows, 'hunks': []},
            removed: {'old_path': removed, 'new_path': None,
                      'before': rows, 'after': [], 'hunks': [(1, 2, 0, 0)]},
            dirty: {'old_path': dirty, 'new_path': dirty,
                    'before': rows, 'after': rows, 'hunks': []},
        })
        self.assertEqual(diff['worktree_only_paths'], {new_name, dirty, 'src/untracked.py'})
        self.assertEqual(diff['files'], 2)

    def test_contract_diff_preserves_readable_edge_of_code_type_change(self):
        path = 'src/main.py'
        self.write(path, self.mark())
        self.commit()
        (self.root / path).unlink()
        try:
            (self.root / path).symlink_to('../docs/concept.md')
        except (NotImplementedError, OSError):
            self.skipTest('cannot create symbolic links')
        self.git('config', 'core.symlinks', 'true')
        self.assertEqual(self.collect()['seeds'], {TARGET})

        self.write('docs/concept.md', '# New requirement\n')
        self.assertEqual(self.collect()['code_snapshots'], [
            {'old_path': path, 'new_path': None, 'before': self.mark().splitlines(),
             'after': [], 'hunks': [(1, 2, 0, 0)]},
        ])

    def test_contract_diff_preserves_readable_edge_of_excluded_code_content(self):
        binary, large = 'src/binary.py', 'src/large.py'
        self.write(binary, self.mark())
        self.write(large, 'x' * 1000001)
        self.commit()
        (self.root / binary).write_bytes(b'\0binary')
        self.write(large, self.mark())
        self.write('docs/concept.md', '# New requirement\n')

        diff = self.collect()
        self.assertEqual(diff['files'], 0)
        self.assertEqual(diff['unmarked'], 0)
        self.assertEqual(diff['code_snapshots'], [
            {'old_path': binary, 'new_path': None, 'before': self.mark().splitlines(),
             'after': [], 'hunks': []},
            {'old_path': None, 'new_path': large, 'before': [],
             'after': self.mark().splitlines(), 'hunks': [(1, 1, 1, 2)]},
        ])

    def test_decision_numbers_use_main_files_and_each_snapshots_catalog(self):
        removed = 'decisions/0007-result.md'
        grouped = 'decisions/adr-008-grouped/adr-008-readme.md'
        attachment = 'decisions/adr-009-grouped/adr-009-attachment.md'
        misplaced = 'docs/adr-010-misplaced.md'
        for path in (removed, attachment, misplaced):
            self.write(path, '# Decision\n\nOriginal.\n')
        self.commit()
        self.git('rm', removed)
        for path in (grouped, attachment, misplaced):
            self.write(path, '# Decision\n\nIndexed change.\n')
        self.git('add', '--', grouped, attachment, misplaced)
        self.write('decisions/008-duplicate.md', '# Duplicate number\n')
        self.assertEqual(self.collect(staged=True, decisions='decisions')['decisions'],
                         {'ADR-007', 'ADR-008'})
        self.assertEqual(self.collect(decisions='decisions')['decisions'], {'ADR-007'})

    def test_decision_number_ambiguous_in_selected_snapshot_is_not_a_target(self):
        first = 'workflow/adr/adr-012-first.md'
        second = 'workflow/adr/0012-second.md'
        for path in (first, second):
            self.write(path, '# Decision\n\nOriginal.\n')
        self.commit()
        self.write(first, '# Decision\n\nIndexed change.\n')
        self.git('add', '--', first)
        (self.root / second).unlink()
        self.assertEqual(self.collect(staged=True)['decisions'], set())
        self.assertEqual(self.collect()['decisions'], {'ADR-012'})

    def test_markdown_uses_selected_revision_and_isolates_staged_sections(self):
        path = 'docs/concept.md'
        heading = '## One <a id="one"></a>\n'
        untouched = '## Two <a id="two"></a>\n\nTwo.\n'

        def write_version(rule, subheading='', intro='Original introduction.'):
            section = heading + '\n' + subheading + rule + '\n\n'
            self.write(path, '# Concept\n\n' + intro + '\n\n' + section + untouched)
            return section.splitlines()

        original = write_version('Write the name first.')
        self.commit()
        revision = self.git('rev-parse', 'HEAD').strip()
        committed = write_version('Write the key first.')
        self.commit()
        indexed = write_version('Write the key first.', '### Field order\n\n')
        self.git('add', path)
        working = write_version('Write the value first.', '### Field order\n\n',
                                'Draft introduction.\nMore detail.')
        self.write('docs/untracked.md', '## Untracked <a id="untracked"></a>\n')

        staged = self.collect(staged=True)
        self.assertEqual(staged['sections'], {TARGET: {'before': committed, 'after': indexed}})
        self.assertEqual(staged['unanchored'], 0)
        diff = self.collect(base=revision)
        self.assertEqual(diff['sections'], {TARGET: {'before': original, 'after': working}})
        self.assertEqual(diff['unanchored'], 1)
        for result in (staged, diff):
            self.assertEqual(result['files'], 0)
            self.assertEqual(result['unmarked'], 0)

    def test_renamed_anchor_and_deleted_markdown_have_absent_sides(self):
        old_heading = '## Row <a id="row"></a>'
        new_heading = '## Record <a id="record"></a>'
        removed_heading = '## Limit <a id="limit"></a>'
        self.write('docs/export.md', '# Export\n\n' + old_heading + '\n\nName before value.\n')
        self.write('docs/limit.md', '# Limits\n\n' + removed_heading + '\n\nTen rows.\n')
        self.commit()
        self.write('docs/export.md', '# Export\n\n' + new_heading + '\n\nName before value.\n')
        self.git('add', 'docs/export.md')
        self.git('rm', 'docs/limit.md')

        expected = {
            'docs/export.md#row': {'before': [old_heading, '', 'Name before value.'], 'after': None},
            'docs/export.md#record': {'before': None, 'after': [new_heading, '', 'Name before value.']},
            'docs/limit.md#limit': {'before': [removed_heading, '', 'Ten rows.'], 'after': None},
        }
        for staged in (False, True):
            with self.subTest(staged=staged):
                result = self.collect(staged=staged)
                self.assertEqual(result['sections'], expected)
                self.assertEqual(result['unanchored'], 1)

    def test_markdown_file_and_symlink_type_changes_use_only_regular_files(self):
        to_link = 'docs/spec.md'
        to_file = 'docs/other-spec.md'
        heading = '## Contract <a id="contract"></a>'
        self.write(to_link, '# Specification\n\n' + heading + '\nOld contents.\n')
        self.write('docs/shared.md', '# Shared\n\n## Destination <a id="destination"></a>\nLinked contents.\n')
        try:
            (self.root / to_file).symlink_to('shared.md')
        except (NotImplementedError, OSError):
            self.skipTest('cannot create symbolic links')
        self.git('config', 'core.symlinks', 'true')
        self.commit()

        (self.root / to_link).unlink()
        (self.root / to_link).symlink_to('shared.md')
        (self.root / to_file).unlink()
        self.write(to_file, '# Specification\n\n' + heading + '\nNew contents.\n')
        expected = {
            to_link + '#contract': {'before': [heading, 'Old contents.'], 'after': None},
            to_file + '#contract': {'before': None, 'after': [heading, 'New contents.']},
        }
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    self.git('add', '--', to_link, to_file)
                result = self.collect(staged=staged)
                self.assertEqual(result['sections'], expected)
                self.assertEqual(result['document_paths'], {to_link, to_file})
                self.assertEqual(result['unanchored'], 2)

    def test_file_move_and_insertion_preserve_both_section_addresses(self):
        old = 'docs/concept.md'
        new = 'docs/moved.md'
        self.commit()
        self.git('mv', old, new)
        original = (self.root / new).read_text(encoding='utf-8')
        self.write(new, original.replace('One.\n', 'One.\nAdded line.\n'))
        self.git('add', new)

        heading = '## One <a id="one"></a>'
        expected = {
            old + '#one': {'before': [heading, '', 'One.', ''], 'after': None},
            new + '#one': {'before': None, 'after': [heading, '', 'One.', 'Added line.', '']},
        }
        self.assertEqual(self.collect(staged=True)['sections'], expected)

    def test_unreadable_markdown_preserves_the_readable_side(self):
        path = 'docs/export.md'
        heading = '## Row <a id="row"></a>'
        self.write(path, heading + '\nName before value.\n')
        self.commit()
        (self.root / path).write_bytes(heading.encode() + b'\n\xff\n')
        self.assertEqual(self.collect()['sections'], {
            path + '#row': {'before': [heading, 'Name before value.'], 'after': None},
        })

    def test_shared_table_header_touches_both_discontinuous_regions(self):
        path = 'docs/table.md'
        old_header = '| Field | Meaning |'
        new_header = '| Column | Description |'
        one = '| Name <a id="name"></a> | First value |'
        two = '| Key <a id="key"></a> | Second value |'

        def write_table(header, neighbor):
            self.write(path, '\n'.join(['# Fields', '', header, '| --- | --- |',
                                         one, neighbor, two, '']))

        write_table(old_header, '| Other | Old |')
        self.commit()
        write_table(new_header, '| Other | New |')
        result = self.collect()
        self.assertEqual(result['sections'], {
            path + '#name': {'before': [old_header, one], 'after': [new_header, one]},
            path + '#key': {'before': [old_header, two], 'after': [new_header, two]},
        })
        self.assertEqual(result['unanchored'], 1)

    def test_markdown_hunk_uses_larger_count_of_continuous_unanchored_intervals(self):
        path = 'docs/concept.md'
        old_heading = '## Old requirement <a id="one"></a>'
        new_heading = '## New requirement <a id="one"></a>'
        self.write(path, '# Concept\n\nOld introduction.\n' + old_heading +
                   '\nOld rule.\n## Old remarks\nOld remark.\n')
        self.commit()
        self.write(path, '# Concept\n\n' + new_heading + '\nNew rule.\n## New details\nNew detail.\n')
        result = self.collect()
        self.assertEqual(result['sections'], {
            TARGET: {'before': [old_heading, 'Old rule.'], 'after': [new_heading, 'New rule.']},
        })
        self.assertEqual(result['unanchored'], 2)

    def test_markdown_applies_trace_target_exclusions(self):
        included = {
            '.agents/rule.md': '# Rules\n\n',
            'examples/history/rule.MD': '# Example\n\n',
            'work/issue/2026/iss-001-example.md': '# Issue\n\n'
                '- Created: 2026-01-01\n- Updated: 2026-01-01\n- Status: open\n- Kind: request\n\n',
            'decisions/adr-001-example.md': '# Decision\n\n- Status: accepted\n\n',
            'docs/large.md': '# Large page\n\n' + 'x' * 1000001 + '\n\n',
        }
        excluded = ('custom/rule.md', '.agents/lipi/rule.md', 'neighbor/docs/rule.md',
                    'history/rule.md', 'work/history/rule.md', 'decisions/history/rule.md')
        heading = '## Rule <a id="rule"></a>'
        anchorless = 'decisions/adr-002-example.md'
        for path, prefix in included.items():
            self.write(path, prefix + heading + '\nOld.\n')
        self.write(anchorless, '# Decision\n\n- Status: accepted\n\nOld.\n')
        for path in excluded:
            self.write(path, '# Example\n\n' + heading + '\nOld.\n')
        self.commit()
        for path, prefix in included.items():
            self.write(path, prefix + heading + '\nNew.\n')
        self.write(anchorless, '# Decision\n\n- Status: accepted\n\nNew.\n')
        self.git('rm', '--', *excluded)

        result = self.collect(workflow='work', decisions='decisions', skip_dirs=['custom'],
                              repos={'neighbor': {'path': 'neighbor', 'read': ['docs']}})
        self.assertEqual(result['sections'], {
            path + '#rule': {'before': [heading, 'Old.'], 'after': [heading, 'New.']}
            for path in included
        })
        self.assertEqual(result['document_paths'], set(included) | {anchorless})
        self.assertEqual(result['unanchored'], 1)

    def test_paths_spaces_unicode_quotes_and_rename(self):
        old = 'src/имя "old".py'
        new = 'src/новое имя.py'
        self.write(old, self.mark('first = 1\nsecond = 2\nthird = 3\nfourth = 4\n'))
        self.commit()
        self.git('mv', old, new)
        self.write(new, self.mark('first = 5\nsecond = 2\nthird = 3\nfourth = 4\n'))
        result = self.collect()
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['changed'], {(new, 1)})

    def test_pure_rename_has_no_changed_lines(self):
        self.write('src/old.py', self.mark())
        self.write('docs/old.md', '# Old\n\n## Rule <a id="rule"></a>\n\nRule.\n')
        self.commit()
        self.git('mv', 'src/old.py', 'src/new.py')
        self.git('mv', 'docs/old.md', 'docs/new.md')
        self.assertEqual(self.collect(), {'seeds': set(), 'changed': set(), 'unmarked': 0, 'files': 1})

    def test_invalid_refs_and_missing_git_are_errors(self):
        self.commit()
        for ref in ('missing-ref', '--output=bad', 'HEAD..HEAD', ''):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.collect(base=ref)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                collect_diff(SliceIndex(Project(Path(folder), dict(DEFAULTS))), base='HEAD')

    def test_unresolved_markers_count_continuous_unmarked_intervals(self):
        self.write('src/main.py', self.mark('a = 1\n', 'docs/concept.md#missing') +
                   self.mark('b = 1\n', 'docs/concept.md#absent'))
        self.commit()
        self.write('src/main.py', self.mark('a = 2\n', 'docs/concept.md#missing') +
                   self.mark('b = 2\n', 'docs/concept.md#absent'))
        result = self.collect()
        self.assertEqual(result['seeds'], set())
        self.assertEqual(result['unmarked'], 2)

    def test_deleted_target_resolves_before_but_is_unmarked_after(self):
        self.write('src/main.py', self.mark())
        self.commit()
        self.write('docs/concept.md', '# Concept\n')
        self.write('src/main.py', self.mark('value = 2\n'))
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['unmarked'], 1)
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['unanchored'], 1)

    def test_adjacent_standalone_markers_are_one_place(self):
        self.write('src/main.py', self.mark(self.mark('value = 1\n', SECOND)))
        self.commit()
        self.write('src/main.py', self.mark(self.mark('value = 2\n', SECOND)))
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET, SECOND})
        self.assertEqual(result['changed'], {('src/main.py', 1)})

    def test_code_exclusions_and_markdown_without_anchors(self):
        for path in ('docs/sample.py', 'workflow/sample.py', 'node_modules/sample.py',
                     'custom/sample.py', 'src/readme.MD'):
            self.write(path, self.mark())
        self.write('src/large.py', 'a' * 1000001)
        (self.root / 'src/binary.bin').write_bytes(b'\x00binary')
        self.write('.gitignore', 'ignored/\n')
        self.commit()
        for path in ('docs/sample.py', 'workflow/sample.py', 'node_modules/sample.py',
                     'custom/sample.py', 'src/readme.MD'):
            self.write(path, self.mark('value = 2\n'))
        self.write('src/large.py', 'b' * 1000001)
        (self.root / 'src/binary.bin').write_bytes(b'\x00changed')
        self.write('ignored/new.py', self.mark())
        self.assertEqual(self.collect(skip_dirs=['custom']),
                         {'seeds': set(), 'changed': set(), 'unmarked': 0, 'files': 0,
                          'sections': {}, 'unanchored': 1, 'document_paths': {'src/readme.MD'},
                          'decisions': set(), 'code_snapshots': []})


if __name__ == '__main__':
    unittest.main()
