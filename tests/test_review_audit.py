"""Авторы учтённых отметок и сравнение реестра с Git-ревизией."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from tests import support


EARLY = '2026-01-05T08:00:00Z'
LATE = '2026-01-06T09:00:00Z'
LATEST = '2026-01-07T10:00:00Z'


# @trace docs/ru/review.md#summary,docs/ru/checking.md#review-authors
class ReviewAudit(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lipi-review-audit-')
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        project = self.workspace / 'project'
        self.prepare_project(project, project)

    def prepare_project(self, root, repository):
        self.root = root
        self.repository = repository
        self.registry = self.root / '.agents/lipi/reviews.json'
        support.w(self.root / 'lipi.json', '{"workflow": null}\n')
        support.w(self.root / 'docs/README.md', '# Описание\n\n[Правило](api.md#rule)\n')
        support.w(self.root / 'docs/api.md', '# Договор\n\n## Правило <a id="rule"></a>\n\nВерно.\n')
        for name in 'abcd':
            self.write_source(name, 0)
        support.git_init(self.repository)
        self.initial = self.commit(1)
        for name in 'abcd':
            self.write_source(name, 1)
        self.before_registry = self.commit(2)

    def write_source(self, name, value):
        support.w(self.root / f'src/{name}.py',
                  f'# {support.TAG} docs/api.md#rule\ndef {name}():\n    return {value}\n')

    def commit(self, day):
        code, output = support.commit(self.repository, date=f'2026-01-{day:02}T00:00:00+00:00')
        self.assertEqual(code, 0, output)
        code, output = support.git(self.repository, 'rev-parse', 'HEAD')
        self.assertEqual(code, 0, output)
        return output.strip()

    def command(self, *args, expected=0, cwd=None):
        code, output = support.cli(cwd or self.root, *args)
        self.assertEqual(code, expected, output)
        return output

    def json_command(self, *args, expected=0, cwd=None):
        return json.loads(self.command(*args, '--format', 'json', expected=expected, cwd=cwd))

    def entry(self, name, reviewer, reviewed_at):
        preview = self.json_command('review', 'docs/api.md#rule', '--at', f'src/{name}.py')
        return dict(preview['pair'], reviewer=reviewer, reviewed_at=reviewed_at,
                    reason='Смысл раздела сохраняется.', head=preview['head'])

    def write_reviews(self, *entries):
        support.w(self.registry, json.dumps({'schema': 1, 'algorithm': 'sha256-lines-v1',
                                             'entries': entries}) + '\n')

    def add_check_that_writes_file(self):
        marker = self.root / 'check-ran'
        support.set_config(self.root, checks=[{
            'name': 'marker', 'mode': 'audit',
            'run': [support.PY[0], '-c', 'from pathlib import Path; Path("check-ran").touch()'],
        }])
        return marker

    def test_authors_count_only_applied_reviews_and_use_latest_date(self):
        self.write_reviews(self.entry('b', 'анна', EARLY), self.entry('a', 'Анна', LATE),
                           self.entry('c', 'Анна', EARLY), self.entry('d', 'Анна', LATEST))
        self.write_source('d', 2)
        self.commit(3)

        result = self.json_command('audit')
        self.assertEqual(self.json_command('check', '--audit'), result)
        self.assertEqual(result['schema'], 1)
        self.assertEqual(result['errors'], [])
        self.assertEqual([row['code'] for row in result['warnings']], ['A4'])
        summary = result['summary']
        self.assertEqual(summary['reviewed_obsolete'], 1)
        self.assertEqual(summary['reviewed_pairs'], 3)
        self.assertEqual(summary['reviewed_by'], [
            {'reviewer': 'Анна', 'count': 2, 'last_reviewed_at': LATE},
            {'reviewer': 'анна', 'count': 1, 'last_reviewed_at': EARLY},
        ])
        self.assertEqual(sum(row['count'] for row in summary['reviewed_by']), summary['reviewed_pairs'])
        self.assertNotIn('reviews_since', summary)

    def test_audit_with_empty_and_absent_registry(self):
        absent = self.json_command('audit')['summary']
        self.assertNotIn('reviewed_by', absent)
        self.assertNotIn('reviews_since', absent)

        self.write_reviews()
        empty = self.json_command('audit')['summary']
        self.assertEqual(empty['reviewed_pairs'], 0)
        self.assertEqual(empty['reviewed_by'], [])
        self.assertNotIn('reviews_since', empty)

    def test_since_compares_pair_ids_including_obsolete_entries(self):
        unchanged = self.entry('a', 'старый автор', EARLY)
        replaced = self.entry('b', 'старый автор', EARLY)
        self.write_reviews(unchanged, replaced)
        previous = self.commit(3)
        self.write_source('b', 2)
        self.commit(4)
        updated = dict(unchanged, reviewer='новый автор', reviewed_at=LATEST, reason='Другая причина.')
        new_fingerprint = self.entry('b', 'Ли', LATE)
        new_obsolete = self.entry('c', 'Ли', EARLY)
        self.assertNotEqual(replaced['id'], new_fingerprint['id'])
        self.write_reviews(updated, replaced, new_fingerprint, new_obsolete)
        self.write_source('c', 2)
        self.commit(5)

        result = self.json_command('audit', '--reviews-since', previous)
        self.assertEqual(self.json_command('check', '--audit', '--reviews-since', previous), result)
        summary = result['summary']
        self.assertEqual(summary['reviewed_pairs'], 2)
        self.assertEqual(summary['reviewed_obsolete'], 2)
        self.assertEqual(summary['reviews_since'], {
            'revision': previous, 'commit': previous, 'count': 2,
            'by_reviewer': [{'reviewer': 'Ли', 'count': 2, 'last_reviewed_at': LATE}],
        })

    def test_since_without_historical_registry_includes_entries_when_a4_is_off(self):
        self.write_reviews(self.entry('a', 'Ли', EARLY), self.entry('b', 'Ада', LATE))
        support.set_config(self.root, codes={'A4': 'off'})
        result = self.json_command('audit', '--reviews-since', 'HEAD', '--strict')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])
        summary = result['summary']
        self.assertEqual(summary['reviewed_pairs'], 0)
        self.assertEqual(summary['reviewed_by'], [])
        self.assertEqual(summary['reviews_since'], {
            'revision': 'HEAD', 'commit': self.before_registry, 'count': 2,
            'by_reviewer': [
                {'reviewer': 'Ада', 'count': 1, 'last_reviewed_at': LATE},
                {'reviewer': 'Ли', 'count': 1, 'last_reviewed_at': EARLY},
            ],
        })

    def test_since_with_absent_current_registry_does_not_create_file(self):
        self.write_reviews(self.entry('a', 'Ли', EARLY))
        previous = self.commit(3)
        self.registry.unlink()
        summary = self.json_command('audit', '--reviews-since', 'HEAD')['summary']
        self.assertNotIn('reviewed_by', summary)
        self.assertEqual(summary['reviews_since'], {
            'revision': 'HEAD', 'commit': previous, 'count': 0, 'by_reviewer': [],
        })
        self.assertFalse(self.registry.exists())

    def test_since_uses_project_path_at_annotated_tag(self):
        outer = self.workspace / 'repo'
        self.prepare_project(outer / 'project', outer)
        old = self.entry('a', 'Ли', EARLY)
        self.write_reviews(old)
        previous = self.commit(3)
        env = dict(os.environ, GIT_COMMITTER_DATE='2026-01-03T00:00:00+00:00')
        code, output = support.git(self.repository, 'tag', '-a', 'start', '-m', 'Start', env=env)
        self.assertEqual(code, 0, output)
        self.write_reviews(old, self.entry('b', 'Ада', LATE))

        result = self.json_command('audit', '--root', str(self.root), '--reviews-since', 'start',
                                   cwd=self.repository)
        self.assertEqual(result['summary']['reviews_since'], {
            'revision': 'start', 'commit': previous, 'count': 1,
            'by_reviewer': [{'reviewer': 'Ада', 'count': 1, 'last_reviewed_at': LATE}],
        })

    def test_since_accepts_revisions_named_like_subcommands(self):
        for revision in ('new', 'baseline'):
            with self.subTest(revision=revision):
                code, output = support.git(self.repository, 'branch', revision)
                self.assertEqual(code, 0, output)
                result = self.json_command('audit', '--reviews-since', revision)
                self.assertEqual(result['summary']['reviews_since'], {
                    'revision': revision, 'commit': self.before_registry, 'count': 0, 'by_reviewer': [],
                })

    def test_invalid_revision_is_rejected_before_project_checks(self):
        marker = self.add_check_that_writes_file()
        output = self.command('audit', '--reviews-since', 'missing-ref', expected=2)
        self.assertIn('--reviews-since:', output)
        self.assertIn('missing-ref', output)
        self.assertFalse(marker.exists())
        self.assertFalse(self.registry.exists())
        self.command('audit')
        self.assertTrue(marker.exists())

    def test_since_requires_git_history(self):
        detached = self.repository.parent / 'detached'
        support.w(detached / 'lipi.json', '{"workflow": null}\n')
        support.w(detached / 'docs/README.md', '# Описание\n')
        output = self.command('audit', '--reviews-since', 'HEAD', expected=2, cwd=detached)
        self.assertIn('--reviews-since:', output)
        self.assertIn('HEAD', output)

    def test_corrupt_historical_registry_is_a_c1_before_project_checks(self):
        support.w(self.registry, '{"schema": 1, "schema": 1, '
                  '"algorithm": "sha256-lines-v1", "entries": []}\n')
        self.commit(3)
        self.registry.unlink()
        self.write_reviews(self.entry('a', 'Ли', EARLY))
        marker = self.add_check_that_writes_file()
        original = self.registry.read_bytes()

        result = self.json_command('audit', '--reviews-since', 'HEAD', expected=2)
        self.assertEqual([row['code'] for row in result['errors']], ['C1'])
        self.assertEqual(result['errors'][0]['file'], '.agents/lipi/reviews.json')
        self.assertIn('duplicate JSON key', result['errors'][0]['message'])
        self.assertFalse(marker.exists())
        self.assertEqual(self.registry.read_bytes(), original)

    def test_non_file_historical_registry_is_a_c1(self):
        child = self.registry / 'entry'
        support.w(child, 'registry directory\n')
        directory = self.commit(3)
        child.unlink()
        self.registry.rmdir()
        self.registry.symlink_to('missing.json')
        symlink = self.commit(4)
        self.registry.unlink()
        self.write_reviews()

        for revision in (directory, symlink):
            with self.subTest(revision=revision):
                result = self.json_command('audit', '--reviews-since', revision, expected=2)
                self.assertEqual([row['code'] for row in result['errors']], ['C1'])
                self.assertEqual(result['errors'][0]['file'], '.agents/lipi/reviews.json')

    def test_since_is_audit_only_and_plain_check_and_slice_keep_their_summary(self):
        self.write_reviews(self.entry('a', 'Ли', EARLY))
        check = self.json_command('check', '--diff', self.initial)
        sliced = self.json_command('slice', 'docs/api.md#rule')
        for result, reviewed in ((check, 0), (sliced, 1)):
            self.assertEqual(result['summary']['reviewed_pairs'], reviewed)
            self.assertNotIn('reviewed_by', result['summary'])
            self.assertNotIn('reviews_since', result['summary'])
        self.assertIn('T2', [row['code'] for row in check['warnings']])
        for args in (('check',), ('slice', 'docs/api.md#rule')):
            with self.subTest(args=args):
                self.command(*args, '--reviews-since', 'HEAD', expected=2)

    # @trace docs/ru/commands.md#new
    def test_new_preserves_titles_that_start_with_the_audit_flag(self):
        root = self.workspace / 'workflow-project'
        root.mkdir()
        self.command('init', cwd=root)
        for title in ('--reviews-since', '--reviews-since=HEAD'):
            with self.subTest(title=title):
                result = self.json_command('new', 'pln', title, cwd=root)
                first_line = (root / result['path']).read_text(encoding='utf-8').splitlines()[0]
                self.assertEqual(first_line, f'# {title}')

        output = self.command('new', 'pln', 'Обычный план', '--reviews-since', 'HEAD',
                              expected=2, cwd=root)
        self.assertIn('--reviews-since', output)
        self.assertEqual(len(list((root / 'workflow/plan').rglob('pln-*.md'))), 2)

    # @trace docs/ru/review.md#summary,docs/ru/checking.md#review-authors
    def test_text_and_github_report_review_metadata_without_extra_findings(self):
        reviewer = 'Ли\n::error::ложная аннотация'
        self.write_reviews(self.entry('a', reviewer, EARLY))
        for fmt in ('text', 'github'):
            with self.subTest(fmt=fmt):
                current = self.command('audit', '--format', fmt)
                compared = self.command('audit', '--format', fmt, '--reviews-since', 'HEAD')
                strict = self.command('audit', '--format', fmt, '--reviews-since', 'HEAD',
                                      '--strict', expected=1)
                self.assertIn(json.dumps(reviewer, ensure_ascii=False), current)
                self.assertIn(EARLY, current)
                self.assertGreater(compared.count(EARLY), current.count(EARLY))
                self.assertNotIn('\n::error::ложная аннотация', compared)
                self.assertEqual(compared, strict)
                if fmt == 'github':
                    annotations = [line for line in compared.splitlines() if line.startswith('::')]
                    self.assertEqual(annotations, [line for line in current.splitlines()
                                                   if line.startswith('::')])
                    self.assertEqual(len(annotations), 3)
