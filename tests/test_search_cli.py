"""CLI contract for explicit document text search."""
import io
import json
import os
import shlex
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import support
from lipi.checker.model import Project
from lipi.slice import main


QUESTION = 'Сколько дней хранится копия?'
EXCERPT = 'Копия хранится 30 дней.'
TITLE = 'Политика очистки'
PAGE = 'docs/storage.md'
TARGET = PAGE + '#cleanup'


class SearchCLI(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='lipi-search-cli-')
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name).resolve()
        self.root = self.workspace / 'local'
        support.w(self.root / 'lipi.json', '{}\n')

    def cli(self, *args, cwd=None, language='en'):
        env = support.language_env(self.workspace / ('profile-' + language), language)
        return support.run(support.PY + [str(support.CLI), 'slice', *args],
                           cwd=cwd or self.root, env=env)

    def storage(self, path):
        support.w(path, '# Хранение\n\n## %s <a id="cleanup"></a>\n' % TITLE
                  + '\n' * 8 + EXCERPT + '\n')

    def response(self, *args, expected=0, **kwargs):
        code, text = self.cli(*args, **kwargs)
        self.assertEqual(code, expected, text)
        return json.loads(text)

    # @trace docs/ru/slice-search.md#command,docs/ru/slice-search.md#output
    def test_prompt_search_and_open_matching_line_in_both_languages(self):
        self.storage(self.root / PAGE)
        command = "lipi slice --search '" + QUESTION + "'"
        miss = self.response(QUESTION, '--format', 'json', expected=1)
        self.assertEqual(miss, {'schema': 1, 'error': 'not-found', 'query': QUESTION,
                                'candidates': [], 'search_command': command})
        language_cases = [
            ('en', ['--format', 'json', '--search', QUESTION], 'Found 1. Showing 1.'),
            ('ru', ['--search', QUESTION, '--format=json'], 'Найдено 1. Показано 1.'),
        ]
        expected_candidate = {'repo': None, 'target': TARGET, 'title': TITLE, 'excerpt': EXCERPT,
                              'file': os.path.join('docs', 'storage.md'), 'line': 12}
        for language, args, count in language_cases:
            with self.subTest(language=language):
                status, text = self.cli(QUESTION, language=language)
                self.assertEqual(status, 1, text)
                self.assertIn(command, text)
                result = self.response(*args, language=language)
                self.assertEqual(result, {'schema': 1, 'query': QUESTION, 'total': 1,
                                          'candidates': [expected_candidate]})
                candidate, = result['candidates']
                editor_path = self.root / candidate['file']
                self.assertEqual(editor_path.read_text(encoding='utf-8').splitlines()[candidate['line'] - 1],
                                 candidate['excerpt'])
                status, text = self.cli('--search', QUESTION, language=language)
                self.assertEqual(status, 0, text)
                self.assertEqual(text.splitlines(), [
                    count, '  ' + TARGET + ' — ' + TITLE,
                    '    ' + candidate['file'] + ':12', '    ' + EXCERPT,
                ])
                target = self.response(candidate['target'], '--format', 'json')['target']
                self.assertEqual(target['target'], TARGET)

    # @trace docs/ru/slice-search.md#command
    def test_search_is_a_separate_call_and_keeps_shell_arguments(self):
        self.storage(self.root / PAGE)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)
        with patch('lipi.search_sources.search_documents',
                   side_effect=AssertionError('an ordinary slice cannot start document text search')):
            with redirect_stdout(io.StringIO()) as output:
                status = main([QUESTION, '--format', 'json'])
        self.assertEqual(status, 1, output.getvalue())
        self.assertIn('search_command', json.loads(output.getvalue()))
        query = '-writer\'s "$REPORT" & editor’s preview'
        result = self.response('--format', 'json', '--', query, expected=1)
        command = result['search_command']
        if os.name == 'nt':
            self.assertEqual(command, """lipi slice '--search=-writer''s "$REPORT" & editor’’s preview'""")
        else:
            parts = shlex.split(command)
            self.assertEqual(parts, ['lipi', 'slice', '--search=' + query])
            response = self.response(*parts[2:], '--format=json', expected=1)
            self.assertEqual(response['query'], query)

    # @trace docs/ru/slice-search.md#command
    def test_usage_rejects_empty_queries_and_other_slice_options(self):
        for args in (
            ('--search', ''), ('--search', '   '), ('--search', 'core::  '), ('--search',),
            ('--search', 'word', 'target'), ('--search', 'word', '--diff', 'HEAD'),
            ('--search', 'word', '--staged'), ('--search', 'word', '--role', 'unassigned'),
            ('--search', 'word', '--depth', '2'), ('--search', 'word', '--only', 'excerpt'),
            ('--search', 'word', '--full'), ('--search', 'word', '--layer', 'core'),
        ):
            with self.subTest(args=args):
                code, text = self.cli(*args)
                self.assertEqual(code, 2, text)
                self.assertIn('error:', text)
        for language, syntax in [('en', 'name::phrase'), ('ru', 'имя::фраза')]:
            with self.subTest(language=language):
                code, text = self.cli('--help', language=language)
                self.assertEqual(code, 0, text)
                self.assertIn(syntax, text)

    # @trace docs/ru/slice-search.md#command,docs/ru/slice-search.md#output
    def test_local_result_suggests_one_connection_and_its_result_opens_from_subdirectory(self):
        neighbor = self.workspace / 'neighbor'
        support.w(neighbor / 'lipi.json', '{}\n')
        path = neighbor / 'notes/handbook/storage.md'
        self.storage(path)
        support.w(neighbor / 'private/outside.md', '# Outside\n\nOutsideword\n')
        support.w(self.workspace / 'unconfigured/docs/storage.md', '# Omitted\n\n' + EXCERPT)
        support.w(self.root / 'docs/logs.md', '# Журнал\n\nЖурнал хранится 7 дней.\n')
        src = self.root / 'src'
        src.mkdir()
        support.set_config(self.root, repos={
            'missing': {'path': '../missing', 'read': ['docs']},
            '-core': {'path': '../neighbor', 'read': ['docs'], 'page_dirs': ['notes/handbook']},
            'unconfigured': {'path': '../unconfigured', 'read': ['docs']},
        })
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)
        page = Project.page

        def local_page(project, filename):
            self.assertEqual(project.root, self.root, 'a local suggestion must not read another page')
            return page(project, filename)

        with patch.object(Project, 'page', local_page), redirect_stdout(io.StringIO()) as output:
            status = main(['--search', QUESTION, '--format=json'])
        self.assertEqual(status, 0, output.getvalue())
        local = json.loads(output.getvalue())
        self.assertEqual([item['target'] for item in local['candidates']], ['docs/logs.md'])
        suggest, = local['suggestions']
        self.assertEqual(suggest['repo'], '-core')
        qualified = '-core::' + QUESTION
        self.assertEqual(suggest['command'], "lipi slice '--search=" + qualified + "'")
        status, text = self.cli('--search', QUESTION)
        self.assertEqual(status, 0, text)
        self.assertIn(suggest['command'], text)
        expected_target = 'notes/handbook/storage.md#cleanup'
        for cwd in (self.root, src):
            with self.subTest(cwd=cwd):
                result = self.response('--search=' + qualified, '--format=json', cwd=cwd)
                self.assertEqual(result['total'], 1)
                self.assertNotIn('suggestions', result)
                candidate, = result['candidates']
                self.assertEqual(candidate, {
                    'repo': '-core', 'target': expected_target, 'title': TITLE, 'excerpt': EXCERPT,
                    'file': os.path.relpath(path, cwd), 'line': 12,
                })
                reopened = self.response('--format=json', '--', '-core::' + candidate['target'],
                                         cwd=cwd)['target']
                self.assertEqual((reopened['repo'], reopened['target']), ('-core', expected_target))
        result = self.response('--search=-core::Outsideword', '--format=json', expected=1)
        self.assertEqual((result['error'], result['total'], result['candidates']), ('not-found', 0, []))

    # @trace docs/ru/slice-search.md#output
    def test_empty_search_and_unread_source_have_distinct_outcomes(self):
        support.w(self.workspace / 'plain/docs/page.md', '# Any\n\nAPI\n')
        support.w(self.workspace / 'code/lipi.json', '{}\n')
        support.w(self.workspace / 'code/docs/page.md', '# Any\n\nAPI\n')
        support.set_config(self.root, repos={
            'missing': {'path': '../missing', 'read': ['docs']},
            'plain': {'path': '../plain', 'read': ['docs']},
            'code': {'path': '../code', 'read': ['code']},
        })
        empty = self.response('--search', 'unicorn', '--format=json', expected=1)
        self.assertEqual(empty, {'schema': 1, 'query': 'unicorn', 'candidates': [], 'total': 0,
                                'error': 'not-found'})
        status, text = self.cli('--search', 'unicorn')
        self.assertEqual((status, text.strip()), (1, 'Found 0. Showing 0.'))
        incomplete = self.response('--search', 'missing::api', '--format=json')
        self.assertEqual(incomplete, self.response('--format=json', '--search', 'missing::api', language='ru'))
        self.assertEqual(incomplete['candidates'], [])
        self.assertTrue(incomplete['incomplete'])
        self.assertNotIn('error', incomplete)
        status, text = self.cli('--search', 'missing::api')
        self.assertEqual(status, 0, text)
        self.assertEqual(text.strip(), incomplete['message'])
        for query, reason, message in (
            ('unknown::api', None, 'unknown connected repository'),
            ('plain::api', 'no-config', 'lipi.json'),
            ('code::api', 'scope-not-enabled', 'docs'),
        ):
            with self.subTest(query=query):
                result = self.response('--search', query, '--format=json', expected=1)
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['error'], 'not-found')
                self.assertEqual(result.get('reason'), reason)
                self.assertIn(message, result['message'])

    # @trace docs/ru/slice-search.md#output
    def test_limited_list_keeps_total_and_candidate_order(self):
        for name in 'gbcafde':
            support.w(self.root / ('docs/' + name + '.md'), '# Node\n\nAPI\n')
        result = self.response('--search', 'api', '--format=json')
        targets = ['docs/' + name + '.md' for name in 'abcde']
        self.assertEqual(result['total'], 7)
        self.assertEqual([item['target'] for item in result['candidates']], targets)
        code, text = self.cli('--search', 'api')
        self.assertEqual(code, 0, text)
        self.assertIn('Found 7. Showing 5.', text)
        self.assertEqual([line.strip().split(' — ')[0] for line in text.splitlines()
                          if line.startswith('  docs/')], targets)
