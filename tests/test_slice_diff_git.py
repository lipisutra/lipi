"""Git snapshots, changed marker ownership and unmarked intervals."""
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

    def test_unborn_index_and_untracked_files(self):
        self.write('src/added.py', self.mark())
        self.git('add', '.')
        self.write('src/untracked.py', 'new = True\n')
        result = self.collect(staged=True)
        self.assertEqual(result['seeds'], {TARGET})
        self.assertEqual(result['files'], 1)

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
        self.commit()
        self.git('mv', 'src/old.py', 'src/new.py')
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

    def test_deleted_target_is_unmarked_in_current_index(self):
        self.write('src/main.py', self.mark())
        self.commit()
        self.write('docs/concept.md', '# Concept\n')
        self.write('src/main.py', self.mark('value = 2\n'))
        result = self.collect()
        self.assertEqual(result['seeds'], set())
        self.assertEqual(result['unmarked'], 1)

    def test_adjacent_standalone_markers_are_one_place(self):
        self.write('src/main.py', self.mark(self.mark('value = 1\n', SECOND)))
        self.commit()
        self.write('src/main.py', self.mark(self.mark('value = 2\n', SECOND)))
        result = self.collect()
        self.assertEqual(result['seeds'], {TARGET, SECOND})
        self.assertEqual(result['changed'], {('src/main.py', 1)})

    def test_noncode_ignored_untracked_and_large_files_are_excluded(self):
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
                         {'seeds': set(), 'changed': set(), 'unmarked': 0, 'files': 0})


if __name__ == '__main__':
    unittest.main()
