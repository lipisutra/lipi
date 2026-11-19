"""test_gitfiles.py — перечень файлов из Git: игнорируемые файлы не проверяются.

Когда корень проекта находится в рабочем дереве Git, страницы описания, рабочие
документы и код с метками берутся из `git ls-files --cached --others
--exclude-standard`: файлы из `.gitignore` не проверяются, новые
неигнорируемые проверяются сразу, до `git add`. Вне git и для каталогов вне
корня (рабочие материалы или описание в отдельном репозитории) — прежний
обход каталогов.

Запуск: python3 -m unittest discover -s tests -p "test_gitfiles.py" -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support


class GitFilesTests(support.Case):
    """Проект в git-репозитории: перечень файлов берётся из git."""

    def test_ignored_dir_not_checked(self):
        """Каталог из .gitignore не проверяется: ни D4 за страницу описания, ни
        T1 за метку; при этом обычные страницы проверяются (D1 срабатывает)."""
        root = self.project()
        support.w(root / ".gitignore", "ignored/\n")
        support.w(root / "docs" / "ignored" / "orphan.md",
                  "# Игнор\n\n## Раздел <a id=\"s\"></a>\n")
        support.w(root / "ignored" / "ignored.py",
                  "# %s docs/guide.md#nope\n" % support.TAG)
        support.git_init(root)
        support.commit(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "D4"), out)
        self.assertFalse(support.found(out, "T1"), out)
        self.assertNotIn("ignored", out)
        support.sub(root / "docs" / "guide.md", "Текст.", "Текст.\n\n[битая](nope.md)")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_untracked_files_checked(self):
        """Новые неигнорируемые файлы без git add проверяются: D4 и T1 срабатывают."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        support.w(root / "docs" / "orphan.md", "# Сирота\n")
        support.w(root / "src" / "extra.py", "# %s docs/guide.md#nope\n" % support.TAG)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn("docs/orphan.md", out)
        self.assertTrue(support.found(out, "T1"), out)
        self.assertIn("src/extra.py", out)

    def test_committed_project_clean(self):
        """Закоммиченный правильный проект в git-режиме проходит без ошибок."""
        root = self.project()
        support.git_init(root)
        support.commit(root)
        code, out = support.check(root)
        self.assertEqual(code, 0, out)

    def test_nested_commands_use_same_project_files_as_at_git_root(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                root = self.project()
                repository = root
                if nested:
                    repository = root.with_name(root.name + '-repo')
                    repository.mkdir()
                    root = root.rename(repository / 'project')
                    support.w(repository / 'sibling/src/code.py',
                              '# %s docs/guide.md#max-discount\n' % support.TAG)
                target = 'docs/guide.md#max-discount'
                support.w(root / 'src/ignored/tracked.py', '# %s %s\n' % (support.TAG, target))
                support.git_init(repository)
                self.assertEqual(support.commit(repository)[0], 0)
                prefix = '/project/' if nested else '/'
                support.w(repository / '.gitignore', '\n'.join(prefix + name for name in (
                    'docs/hidden.md', 'src/ignored/', 'workflow/issue/2026/iss-010-hidden.md')) + '\n')
                support.w(root / 'docs/hidden.md', '# Скрытая страница\n\n[Битая ссылка](missing.md)\n')
                support.w(root / 'src/ignored/ignored.py', '# %s docs/guide.md#missing\n' % support.TAG)
                support.w(root / 'src/untracked.py', '# %s %s\n' % (support.TAG, target))
                support.w(root / 'workflow/issue/2026/iss-010-hidden.md',
                          support.doc(root, 'iss').read_text(encoding='utf-8'))
                for command in ('check', 'audit', 'index'):
                    code, out = support.cli(root, command)
                    self.assertEqual(code, 0, out)
                    self.assertNotIn('iss-010', out)
                issues = root / 'workflow/index/issues.md'
                self.assertNotIn('ISS-010', issues.read_text(encoding='utf-8'))
                code, out = support.cli(root, 'map', '--format', 'json')
                self.assertEqual(code, 0, out)
                rows = {row['target']: row for row in json.loads(out)['rows']}
                self.assertEqual(rows[target]['code'], {'src': 3})
                self.assertNotIn('docs/hidden.md', rows)
                code, out = support.cli(root, 'slice', target, '--format', 'json')
                self.assertEqual(code, 0, out)
                sections = {block['kind']: block['items'] for block in json.loads(out)['blocks']}
                self.assertEqual({item['path'] for item in sections['code']},
                                 {'src/order.py', 'src/ignored/tracked.py', 'src/untracked.py'})
                code, out = support.cli(root, 'new', 'iss', 'Первое замечание', 'bug', '--format', 'json')
                self.assertEqual(code, 0, out)
                created = json.loads(out)
                self.assertEqual(created['id'], 'ISS-011')
                self.assertEqual([issue['id'] for issue in created['similar']], ['ISS-001'])
                self.assertTrue((root / created['path']).is_file())
                self.assertIn('ISS-011', issues.read_text(encoding='utf-8'))

    def test_nested_audit_a5_ignores_commits_only_in_sibling(self):
        repository = self.tmp / 'a5-repo'
        repository.mkdir()
        root = self.project().rename(repository / 'project')
        support.git_init(repository)
        support.header_set(root, 'pln', {'Created': '2026-01-01',
                                         'Updated': '2026-01-01'})
        self.assertEqual(support.commit(repository, date='2026-01-01T10:00:00+00:00')[0], 0)
        support.w(root / 'src/local.py', 'value = 1\n')
        self.assertEqual(support.commit(repository, 'PLN-001 local', '2026-01-02T10:00:00+00:00')[0], 0)
        support.w(repository / 'sibling/src/other.py', 'value = 2\n')
        self.assertEqual(support.commit(repository, 'PLN-001 sibling', '2026-01-03T10:00:00+00:00')[0], 0)
        code, out = support.cli(root, 'audit', '--format', 'json')
        self.assertEqual(code, 0, out)
        a5 = [item for item in json.loads(out)['warnings'] if item['code'] == 'A5']
        self.assertEqual(len(a5), 1, out)
        self.assertIn('commits after 2026-01-01: 1', a5[0]['message'])


class ExternalCatalogsTests(unittest.TestCase):
    """Каталоги вне корня проекта: обход каталогов, git-список не годится."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-gitfiles-"))
        self.root = self.tmp / "root"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_external_workflow_checked_by_walk(self):
        """Рабочие материалы вне корня в настройках обходятся каталогами:
        документ с битой ссылкой даёт W6 и в git-репозитории."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        support.set_config(self.root, workflow='../wf')
        support.git_init(self.root)
        support.commit(self.root)
        support.w(self.tmp / "wf" / "plan" / "2026" / "pln-010-vneshniy.md",
                  "# Внешний план\n\n- Created: 2026-01-01\n"
                  "- Updated: 2026-01-01\n- Status: new\n\n"
                  "## Purpose\n\n[x](../net.md)\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "W6"), out)
        self.assertIn("pln-010-vneshniy.md", out)

    def test_default_decisions_in_external_workflow_keep_workflow_checks(self):
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        support.set_config(self.root, workflow='../wf')
        support.git_init(self.root)
        support.commit(self.root)
        support.w(self.tmp / 'wf/adr/adr-001-rule.md',
                  '# External decision\n\n- Created: 2026-01-01\n'
                  '- Updated: 2026-01-01\n- Status: неизвестно\n\n'
                  '## Decision\n\n[Missing](missing.md)\n')
        code, result = support.check_json(self.root, '--structure')
        self.assertEqual(code, 1, result)
        errors = result['errors'] + result['warnings']
        self.assertEqual({item['code'] for item in errors
                          if item['file'] == '../wf/adr/adr-001-rule.md'}, {'W3', 'W6'})
        self.assertTrue(any(node['id'] == 'ADR-001' and node['type'] == 'work'
                            for node in result['structure']['nodes']), result)
        # Классификация для проверок не расширяет разрешённые цели вне root.
        support.w(self.root / 'src/main.py', '# %s ADR-001\nvalue = 1\n' % support.TAG)
        _, result = support.check_json(self.root)
        self.assertTrue(any(item['code'] == 'T1' for item in result['errors']), result)

    def test_external_docs_checked_by_walk(self):
        """Описание вне корня (--docs ../documentation) обходится каталогами:
        сирота даёт D4 и в git-репозитории."""
        code, out = support.init(self.root, "--docs", "../documentation")
        self.assertEqual(code, 0, out)
        support.git_init(self.root)
        support.commit(self.root)
        support.w(self.tmp / "documentation" / "orphan.md", "# Сирота\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D4"), out)
        self.assertIn("orphan.md", out)


if __name__ == "__main__":
    unittest.main()
