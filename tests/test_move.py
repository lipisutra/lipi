"""Перенос страницы: сохраняет связи и проверяет весь план до записи."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.move_neighbors import neighbor_notices


# @trace docs/ru/commands.md#mv,ADR-017
class MovePage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='lipi-move-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / 'project'
        self.root.mkdir()
        support.git_init(self.root)
        self.write('lipi.json', json.dumps({'docs': 'docs'}))
        self.write('docs/old.md', '# Page\n\n## Part <a id="part"></a>\n\nText.\n')

    def write(self, path, text):
        support.w(self.root / path, text)

    def read(self, path):
        return (self.root / path).read_text(encoding='utf-8')

    def git(self, *args):
        code, out = support.git(self.root, *args)
        self.assertEqual(code, 0, out)
        return out

    def commit(self):
        code, out = support.commit(self.root)
        self.assertEqual(code, 0, out)

    @staticmethod
    def snapshot(root):
        """Содержимое и каталоги рабочего дерева плюс точные байты индекса."""
        tree = {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
                for p in root.rglob('*') if '.git' not in p.relative_to(root).parts}
        index = root / '.git/index'
        return tree, index.read_bytes() if index.exists() else None

    def move(self, *args, cwd=None):
        code, out = support.cli(cwd or self.root, 'mv', *args)
        self.assertEqual(code, 0, out)
        return out

    def refused(self, old='docs/old.md', new='docs/new.md'):
        before = self.snapshot(self.root)
        code, out = support.cli(self.root, 'mv', old, new, '--apply')
        self.assertNotEqual(code, 0, out)
        self.assertEqual(self.snapshot(self.root), before, out)

    def test_help_exposes_apply_without_requiring_a_repository(self):
        for args in (('mv', '--help'), ('help', 'mv')):
            with self.subTest(args=args):
                code, out = support.cli(self.base, *args)
                self.assertEqual(code, 0, out)
                self.assertIn('lipi mv', out)
                self.assertIn('--apply', out)

    # @trace docs/ru/commands.md#mv,docs/ru/move.md#links,ADR-017
    def test_apply_updates_incoming_links_rules_closed_discussion_and_markers(self):
        originals = {
            'docs/README.md': '# Docs\n\n[Page](old.md) and [Part](old.md#part).\n',
            'workflow/plan/pln-001-task.md': '# Task\n\n[Part](../../docs/old.md#part).\n',
            'workflow/discussion/dsc-001-choice.md':
                '# Choice\n\n- Status: closed\n\n## Вывод\n\n[Page](../../docs/old.md).\n',
            'AGENTS.md': '# Rules\n\n[Part](docs/old.md#part).\n',
            '.agents/local.md': '# Rules\n\n[Part](../docs/old.md#part).\n',
            'src/main.py': '# %s docs/old.md, docs/old.md#part\nvalue = 1\n' % support.TAG,
            'tests/test_main.py': '# %s docs/old.md#part\nassert True\n' % support.TAG,
            'docs/summary.md': '# Summary\n\n<!-- covers: docs/old.md, docs/old.md#part -->\n',
        }
        for path, text in originals.items():
            self.write(path, text)
        self.commit()
        page = self.read('docs/old.md')
        self.move('docs/old.md', 'docs/deeper/new.md', '--apply')
        self.assertFalse((self.root / 'docs/old.md').exists())
        self.assertEqual(self.read('docs/deeper/new.md'), page)
        for path, text in originals.items():
            with self.subTest(path=path):
                self.assertEqual(self.read(path), text.replace('old.md', 'deeper/new.md'))
        self.assertIn('docs/deeper/new.md', self.git('ls-files'))
        self.assertNotIn('docs/old.md', self.git('ls-files'))

    def test_asset_move_and_check_agree_on_three_link_forms(self):
        target = 'docs/assets/logo.png'
        new_target = 'docs/images/logo.png'
        rows = ['# Project', '', '![Logo](%s)' % target,
                '<p><IMG alt="src=other > text" SRC = "%s" width="80"></p>' % target,
                "<a title='image' href='%s'>view</a>" % target]
        examples = ('\n\n' + chr(96) + '<img src="missing">' + chr(96)
                    + '\n\n~~~html\n<a href="missing">\n~~~\n\n'
                    + '    <img src="missing">\n\n<!--\n'
                    + '<img src="missing"> [x](missing)\n-->\n')
        page = '\n'.join(rows) + examples
        self.write('README.md', page)
        support.wb(self.root / target, b'image')
        self.commit()

        def failures():
            _, report = support.check_json(self.root)
            return [(item['code'], item['line']) for item in report['errors']
                    if item['file'] == 'README.md']

        self.assertEqual(failures(), [])
        for index in (2, 3, 4):
            with self.subTest(line=index + 1):
                broken = rows.copy()
                broken[index] = broken[index].replace(target, 'missing.png')
                self.write('README.md', '\n'.join(broken) + examples)
                self.assertEqual(failures(), [('W6', index + 1)])
        self.write('README.md', page)
        plan = self.move('docs/assets', 'docs/images')
        self.assertNotIn('history/', plan)
        self.assertEqual(plan.count('README.md:'), 3, plan)
        self.assertEqual(self.read('README.md'), page)
        self.move('docs/assets', 'docs/images', '--apply')
        self.assertEqual(self.read('README.md'), page.replace(target, new_target))
        self.assertTrue((self.root / new_target).is_file())
        self.assertEqual(failures(), [])

    def test_moving_page_rebases_html_destinations_only(self):
        image = 'assets/a&amp;b.png'
        text = ('# Page\n\n<IMG data-copy="%s"\n Src = \'%s\' />\n'
                '<a href=%s>open</a>\n' % (image, image, image))
        self.write('docs/old.md', text)
        support.wb(self.root / 'docs/assets/a&b.png', b'image')
        self.commit()
        self.move('docs/old.md', 'docs/deeper/new.md', '--apply')
        self.assertEqual(self.read('docs/deeper/new.md'),
                         text.replace("Src = 'assets/", "Src = '../assets/")
                             .replace('href=assets/', 'href=../assets/'))
        _, report = support.check_json(self.root)
        self.assertFalse([item for item in report['errors'] if item['code'] == 'D1'], report)

    def test_outgoing_links_and_images_keep_targets_when_moved_deeper(self):
        page = ('# Page\n\n## Part <a id="part"></a>\n\n'
                '[Other](other.md#section) ![Picture](assets/pic.png)\n'
                '[Root](../README.md) [Self](old.md#part) [Here](#part)\n'
                '[Web](https://example.com/old.md)\n')
        self.write('docs/old.md', page)
        self.write('docs/other.md', '# Other\n')
        self.write('README.md', '# Project\n')
        support.wb(self.root / 'docs/assets/pic.png', b'picture')
        self.commit()
        self.move('docs/old.md', 'docs/deeper/new.md', '--apply')
        expected = (page.replace('(other.md#section)', '(../other.md#section)')
                    .replace('(assets/pic.png)', '(../assets/pic.png)')
                    .replace('(../README.md)', '(../../README.md)')
                    .replace('(old.md#part)', '(new.md#part)'))
        self.assertEqual(self.read('docs/deeper/new.md'), expected)

    # @trace docs/ru/commands.md#mv,docs/ru/move.md#plan,ADR-017
    def test_plan_lists_exact_replacements_and_changes_neither_tree_nor_index(self):
        self.write('docs/README.md', '# Docs\n\n[Part](old.md#part)\n')
        self.write('src/main.py', '# %s docs/old.md#part\n' % support.TAG)
        self.commit()
        self.write('local.txt', 'untracked local work\n')
        before = self.snapshot(self.root)
        out = self.move('docs/old.md', 'docs/deeper/new.md')
        self.assertEqual(self.snapshot(self.root), before)
        for value in ('docs/old.md', 'docs/deeper/new.md', 'docs/README.md:3',
                      'old.md#part', 'deeper/new.md#part', 'src/main.py:1'):
            self.assertIn(value, out)

    def test_paths_are_relative_to_current_directory(self):
        self.commit()
        self.move('old.md', 'nested/new.md', '--apply', cwd=self.root / 'docs')
        self.assertTrue((self.root / 'docs/nested/new.md').is_file())
        self.assertFalse((self.root / 'docs/old.md').exists())

    def test_refuses_untracked_non_markdown_existing_and_outside_paths(self):
        self.write('docs/existing.md', '# Existing\n')
        self.write('plain.txt', 'plain\n')
        self.commit()
        self.write('docs/untracked.md', '# Untracked\n')
        for old, new in (('docs/untracked.md', 'docs/new.md'),
                         ('plain.txt', 'docs/new.md'),
                         ('docs/old.md', 'docs/existing.md'),
                         ('docs/old.md', '../outside.md'),
                         ('docs/old.md', 'docs/new.txt')):
            with self.subTest(old=old, new=new):
                self.refused(old, new)
        self.assertFalse((self.base / 'outside.md').exists())

    def test_refuses_affected_git_conflict_before_any_file_is_changed(self):
        self.write('docs/README.md', '[Page](old.md)\n')
        self.commit()
        oid = self.git('rev-parse', 'HEAD:docs/README.md').strip()
        self.git('update-index', '--force-remove', 'docs/README.md')
        entries = ''.join('100644 %s %d\tdocs/README.md\n' % (oid, stage)
                          for stage in (1, 2, 3))
        result = subprocess.run(['git', '-C', str(self.root), 'update-index', '--index-info'],
                                input=entries.encode(), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.refused()

    def test_refuses_outside_source_and_symlink_source_or_destination_parent(self):
        outside = self.base / 'outside.md'
        support.w(outside, '# Outside\n')
        (self.root / 'docs/alias.md').symlink_to('old.md')
        (self.root / 'linked').symlink_to(self.base, target_is_directory=True)
        self.commit()
        for old, new in (('../outside.md', 'docs/new.md'),
                         ('docs/alias.md', 'docs/new.md'),
                         ('docs/old.md', 'linked/new.md')):
            with self.subTest(old=old, new=new):
                self.refused(old, new)
        self.assertEqual(outside.read_text(encoding='utf-8'), '# Outside\n')
        self.assertFalse((self.base / 'new.md').exists())

    def test_refuses_excluded_paths_and_tracked_destination_missing_from_worktree(self):
        for name in ('history/record.md', '.agents/lipi/rules.md', 'generated/page.md',
                     'docs/deleted.md'):
            self.write(name, '# Excluded or deleted\n')
        support.set_config(self.root, skip_dirs=['generated'])
        self.commit()
        (self.root / 'docs/deleted.md').unlink()
        for old, new in (('history/record.md', 'docs/new.md'),
                         ('.agents/lipi/rules.md', 'docs/new.md'),
                         ('generated/page.md', 'docs/new.md'),
                         ('docs/old.md', 'history/new.md'),
                         ('docs/old.md', 'docs/deleted.md')):
            with self.subTest(old=old, new=new):
                self.refused(old, new)

    def test_readonly_affected_file_refuses_before_rename(self):
        self.write('docs/README.md', '[Page](old.md)\n')
        self.commit()
        path = self.root / 'docs/README.md'
        path.chmod(0o444)
        try:
            self.refused()
        finally:
            path.chmod(0o644)

    def test_invalid_utf8_affected_reference_refuses_before_write(self):
        self.write('docs/README.md', '[Page](old.md)\n')
        support.wb(self.root / 'docs/broken.md', b'[Page](old.md)\n\xff')
        self.commit()
        self.refused()

    def test_unrelated_invalid_utf8_does_not_block_move(self):
        support.wb(self.root / 'docs/broken.md', b'unrelated\xff')
        self.commit()
        self.move('docs/old.md', 'docs/new.md', '--apply')
        self.assertEqual((self.root / 'docs/broken.md').read_bytes(), b'unrelated\xff')

    # @trace docs/ru/commands.md#mv,docs/ru/move.md#scope,docs/ru/move.md#links,ADR-017
    def test_archive_is_unchanged_and_report_names_excluded_history(self):
        archived = '# Old record\n\n[Part](../docs/old.md#part)\n'
        self.write('history/record.md', archived)
        self.commit()
        out = self.move('docs/old.md', 'docs/new.md', '--apply')
        self.assertEqual(self.read('history/record.md'), archived)
        self.assertRegex(out, support.localized('history/ was excluded', 'history/[^\\n]*(?:не обнов|исключ|пропущ)'))

    def test_examples_literals_settings_and_skipped_directories_stay_unchanged(self):
        examples = ('# Examples\n\n`[Page](old.md)`\n'
                    '```markdown\n[Page](old.md)\n<!-- covers: docs/old.md -->\n```\n')
        py = ('path = "docs/old.md"\n'
              'literal = "# %s docs/old.md#part"\n'
              'fixture = """\n# %s docs/old.md#part\n"""\n') % (support.TAG, support.TAG)
        js = 'const sample = "// %s docs/old.md#part";\n' % support.TAG
        preserved = {'docs/examples.md': examples, 'src/literals.py': py,
                     'src/literals.js': js, 'build.json': '{"path": "docs/old.md"}\n',
                     'tests/fixtures/sample.json': '{"path": "docs/old.md"}\n',
                     '.agents/lipi/example.md': '[Page](../../docs/old.md)\n',
                     'generated/page.md': '[Page](../docs/old.md)\n'}
        for path, text in preserved.items():
            self.write(path, text)
        support.set_config(self.root, skip_dirs=['generated'])
        self.write('src/real.js', '// %s docs/old.md#part\nconst value = 1;\n' % support.TAG)
        self.commit()
        self.move('docs/old.md', 'docs/new.md', '--apply')
        for path, text in preserved.items():
            with self.subTest(path=path):
                self.assertEqual(self.read(path), text)
        self.assertIn('docs/new.md#part', self.read('src/real.js'))

    # @trace docs/ru/commands.md#mv,docs/ru/move.md#plan,docs/ru/move.md#apply,ADR-017
    def test_local_dirty_work_and_preexisting_staged_content_survive(self):
        self.write('docs/README.md', '# Docs\n\n[Page](old.md)\n')
        self.write('src/unrelated.py', 'value = 1\n')
        self.commit()
        self.write('src/unrelated.py', 'value = 2\n')
        self.git('add', 'src/unrelated.py')
        self.write('src/unrelated.py', 'value = 3\n')
        self.write('local.txt', 'untracked\n')
        dirty = self.read('docs/README.md') + '\nUncommitted paragraph.\n'
        self.write('docs/README.md', dirty)
        self.write('docs/old.md', self.read('docs/old.md') + '\nUncommitted page.\n')
        page = self.read('docs/old.md')
        staged = self.git('show', ':src/unrelated.py')
        self.move('docs/old.md', 'docs/new.md', '--apply')
        self.assertEqual(self.read('docs/README.md'), dirty.replace('old.md', 'new.md'))
        self.assertEqual(self.read('docs/new.md'), page)
        self.assertEqual(self.read('src/unrelated.py'), 'value = 3\n')
        self.assertEqual(self.git('show', ':src/unrelated.py'), staged)
        self.assertEqual(self.read('local.txt'), 'untracked\n')

    # @trace docs/ru/commands.md#mv,docs/ru/move.md#links,ADR-017
    def test_neighbor_reverse_alias_report_respects_read_scope_and_never_writes(self):
        neighbor = self.base / 'neighbor'
        neighbor.mkdir()
        support.git_init(neighbor)
        support.w(neighbor / 'lipi.json', json.dumps({
            'repos': {'upstream': {'path': '../project', 'read': ['docs']}}}))
        support.w(neighbor / 'src/client.py', '# %s upstream::docs/old.md#part\n' % support.TAG)
        support.w(neighbor / 'tests/test_client.py', '# %s upstream::docs/old.md\n' % support.TAG)
        code, out = support.commit(neighbor)
        self.assertEqual(code, 0, out)
        before = self.snapshot(neighbor)
        for scopes, expected in ((['docs'], 0), (['code'], 1), (['tests'], 1),
                                 (['code', 'tests'], 2)):
            with self.subTest(scopes=scopes):
                support.set_config(self.root, repos={
                    'client': {'path': '../neighbor', 'read': scopes}})
                if not (self.root / '.git/index').exists():
                    self.commit()
                out = self.move('docs/old.md', 'docs/new.md')
                if expected:
                    self.assertRegex(out, r'client[^\n]*\b%d\b' % expected)
                else:
                    self.assertNotRegex(out, r'client[^\n]*\b[12]\b')
                self.assertEqual(self.snapshot(neighbor), before)
        self.move('docs/old.md', 'docs/new.md', '--apply')
        self.assertEqual(self.snapshot(neighbor), before)

    def test_neighbor_code_permission_cannot_read_tests_or_docs_through_symlink(self):
        neighbor = self.base / 'neighbor'
        neighbor.mkdir()
        support.git_init(neighbor)
        support.w(neighbor / 'lipi.json', json.dumps({
            'repos': {'upstream': {'path': '../project', 'read': ['docs']}}}))
        marker = '# %s upstream::docs/old.md#part\n' % support.TAG
        allowed = neighbor / 'src/client.py'
        denied = [neighbor / 'tests/test_secret.py', neighbor / 'docs/page.md']
        for path in [allowed, *denied]:
            support.w(path, marker)
        alias = neighbor / 'src/alias.py'
        alias.symlink_to('../tests/test_secret.py')
        code, out = support.commit(neighbor)
        self.assertEqual(code, 0, out)
        support.set_config(self.root, repos={
            'client': {'path': '../neighbor', 'read': ['code']}})
        read_bytes = Path.read_bytes
        for target in denied:
            with self.subTest(target=target.relative_to(neighbor)):
                alias.unlink()
                alias.symlink_to(target)
                reads = []

                def record_read(path):
                    reads.append(path.resolve())
                    return read_bytes(path)

                with patch.object(Path, 'read_bytes', record_read):
                    project = Project(self.root, load_config(self.root, None))
                    notices = neighbor_notices(project, {
                        self.root / 'docs/old.md': self.root / 'docs/new.md'})
                self.assertIn(allowed, reads)
                for path in denied:
                    self.assertNotIn(path, reads)
                self.assertRegex('\n'.join(notices), r'client[^\n]*\b1\b')


# @trace docs/ru/move.md#scope,docs/ru/commands.md#check,docs/ru/commands.md#audit,docs/ru/commands.md#slice,docs/ru/commands.md#map,docs/ru/commands.md#index
class SharedGitScope(support.Case):
    def test_all_commands_ignore_the_same_files_at_git_root_and_below(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                project = self.project()
                repository = project
                if nested:
                    repository = project.with_name(project.name + '-repository')
                    repository.mkdir()
                    project = project.rename(repository / 'app')
                    sibling = repository / 'sibling/README.md'
                    sibling_text = '[Guide](../app/docs/guide.md#max-discount)\n'
                    support.w(sibling, sibling_text)

                guide = 'docs/guide.md#max-discount'
                hidden = 'docs/hidden.md#private'
                escaped = 'docs/escape.md#private'
                hidden_issue = 'workflow/issue/2026/iss-058-hidden.md'
                support.set_config(project, entry=['^def .*_entry\\('])
                support.w(project / '.gitignore', '\n'.join('/' + name for name in
                          ('docs/hidden.md', 'docs/escape.md', 'src/hidden.py', hidden_issue)) + '\n')
                support.git_init(repository)
                code, output = support.commit(repository)
                self.assertEqual(code, 0, output)

                private_page = '# Private\n\n## Private <a id="private"></a>\n\n[Guide](guide.md)\n'
                private_code = '# %s %s\n\n\n\n\ndef private_entry():\n    pass\n' % (support.TAG, guide)
                outside = self.tmp / (repository.name + '-outside.md')
                support.w(outside, private_page)
                support.w(project / 'docs/hidden.md', private_page)
                (project / 'docs/escape.md').symlink_to(outside)
                support.w(project / 'src/hidden.py', private_code)
                support.w(project / hidden_issue, support.doc(project, 'iss').read_text(encoding='utf-8'))
                local_text = '# %s %s\nvalue = 1\n' % (support.TAG, guide)
                local_path = project / 'src/local.py'
                support.w(local_path, local_text)

                for command in ('check', 'audit', 'index'):
                    code, output = support.cli(project, command)
                    self.assertEqual(code, 0, output)
                    for name in ('hidden.md', 'escape.md', 'hidden.py', 'ISS-058'):
                        self.assertNotIn(name, output)
                self.assertNotIn('ISS-058', (project / 'workflow/index/issues.md').read_text(encoding='utf-8'))

                code, output = support.cli(project, 'map', '--format', 'json')
                self.assertEqual(code, 0, output)
                rows = {row['target']: row for row in json.loads(output)['rows']}
                self.assertEqual(rows[guide]['code'], {'src': 2})
                self.assertNotIn(hidden, rows)
                self.assertNotIn(escaped, rows)
                code, output = support.cli(project, 'slice', guide, '--format', 'json')
                self.assertEqual(code, 0, output)
                blocks = {block['kind']: block['items'] for block in json.loads(output)['blocks']}
                self.assertEqual({item['path'] for item in blocks['code']}, {'src/order.py', 'src/local.py'})

                probe = project / 'src/probe.py'
                support.w(probe, '# %s %s, %s\n' % (support.TAG, hidden, escaped))
                code, result = support.check_json(project)
                self.assertEqual(code, 1, result)
                errors = {item['subject'] for item in result['errors'] if item['code'] == 'T1'}
                self.assertEqual(errors, {hidden, escaped}, result)
                for target in (hidden, escaped):
                    code, output = support.cli(project, 'slice', target, '--format', 'json')
                    self.assertEqual(code, 1, output)
                    code, output = support.cli(project, 'mv', target.split('#')[0], 'docs/new.md')
                    self.assertEqual(code, 2, output)
                probe.unlink()

                outgoing = '\n[Private](hidden.md#private) [Escape](escape.md#private)\n'
                support.sub(project / 'docs/guide.md', 'Текст.', 'Текст.' + outgoing)
                code, output = support.cli(project, 'mv', 'docs/guide.md', 'docs/deep/guide.md', '--apply')
                self.assertEqual(code, 0, output)
                self.assertIn(outgoing, (project / 'docs/deep/guide.md').read_text(encoding='utf-8'))
                self.assertEqual(local_path.read_text(encoding='utf-8'),
                                 local_text.replace('docs/guide.md', 'docs/deep/guide.md'))
                self.assertEqual((project / 'docs/hidden.md').read_text(encoding='utf-8'), private_page)
                self.assertEqual((project / 'src/hidden.py').read_text(encoding='utf-8'), private_code)
                self.assertEqual(outside.read_text(encoding='utf-8'), private_page)
                self.assertTrue((project / 'docs/escape.md').is_symlink())
                if nested:
                    self.assertEqual(sibling.read_text(encoding='utf-8'), sibling_text)
