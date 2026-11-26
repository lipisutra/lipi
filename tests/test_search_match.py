"""Search matching and excerpt selection over a single document scope."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import support

from lipi.checker.model import Project
from lipi.search_match import rank_documents
from lipi.slice_index import SliceIndex


class SearchMatching(unittest.TestCase):
    def index(self, pages):
        folder = tempfile.TemporaryDirectory(prefix='lipi-search-match-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        for name, markdown in pages.items():
            support.w(root / 'docs' / f'{name}.md', markdown)
        return SliceIndex(Project(root, {'docs': 'docs'}), links=False)

    def targets(self, index, query):
        return [item['target'] for item in rank_documents(index, query)]

    def test_terminal_letter_forms_and_whole_short_words(self):
        index = self.index({
            'backup': '# Хранение\n\nКопия хранится 30 дней.\n',
            'exact': '# Output\n\nGenerates reports.\n',
            'variant': '# Results\n\nGenerates a report.\n',
            'tax': '# Расчёт\n\nСумма включает НДС.\n',
            'server': '# Устройство\n\nAPI доступен.\n',
            'near': '# Terms\n\nпортал portal полёт платформа APIS.\n',
            'letters': '# Endpoint\n\nShows ports.\n',
            'copy': '# Duplication\n\nKeep a copy.\n',
        })
        cases = {
            'Как долго хранят копию?': ['docs/backup.md'],
            'reports': ['docs/exact.md', 'docs/variant.md'],
            'report': ['docs/variant.md', 'docs/exact.md'],
            'ндс': ['docs/tax.md'],
            'api': ['docs/server.md'],
            'порт': [],
            'port': ['docs/letters.md'],
            'платёж': [],
            'copies': [],
        }
        for query, targets in cases.items():
            with self.subTest(query=query):
                self.assertEqual(self.targets(index, query), targets)

    def test_combining_marks_remain_part_of_a_word(self):
        index = self.index({'words': '# A\n\nभाषा and café.\n'})
        self.assertEqual(self.targets(index, 'भाषा'), ['docs/words.md'])
        self.assertEqual(self.targets(index, 'भाषि'), [])
        self.assertEqual(self.targets(index, 'cafe\u0301'), ['docs/words.md'])

    def test_rare_word_outranks_common_question_words(self):
        for query, common in (
                ('что если API недоступен', 'Что если'),
                ('what if the API is unavailable', 'What if the result is empty')):
            with self.subTest(query=query):
                repeated = ' '.join([common] * 100)
                pages = {'b': '# B\n\nAPI.\n', 'c': '# C\n\n' + common,
                         'd': '# D\n\n' + common, 'a': '# A\n\n' + common}
                base = self.targets(self.index(pages), query)
                self.assertEqual(base, ['docs/b.md', 'docs/a.md', 'docs/c.md', 'docs/d.md'])
                pages['c'] = '# C\n\n' + repeated
                self.assertEqual(self.targets(self.index(pages), query), base)

    # @trace docs/ru/slice-search.md#match
    def test_receipt_answer_outranks_rare_question_word(self):
        for query, heading, recurring, answer, copy, pack in (
                ('сколько хранится квитанция', 'Сроки', 'Квитанция выдаётся после применения.',
                 'Квитанция хранится 30 дней.', 'Копия хранится до очистки.',
                 'Сколько единиц входит в пакет.'),
                ('How long are receipts stored?', 'Retention policy',
                 'Receipts follow every transaction.', 'Receipts remain stored for 30 days.',
                 'Backups stay stored until cleanup.', 'How many units fit inside the pack?')):
            with self.subTest(query=query):
                pages = {f'issued-{number}': f'# Guide\n\n{recurring}\n' for number in range(6)}
                pages.update({
                    'retention': f'# Guide\n\n## {heading} <a id="receipts"></a>\n\n{recurring}\n\n{answer}\n',
                    'copy': f'# Guide\n\n{copy}\n',
                    'pack': f'# Guide\n\n{pack}\n',
                })
                results = rank_documents(self.index(pages), query)
                self.assertIn('docs/pack.md', [result['target'] for result in results])
                first = results[0]
                self.assertEqual((first['target'], first['excerpt'], first['line']),
                                 ('docs/retention.md#receipts', answer, 7))

    def test_exact_word_keeps_positive_weight_in_one_document(self):
        index = self.index({'one': '# Overview\n\nThe API is available.\n'})
        self.assertEqual(self.targets(index, 'api api'), ['docs/one.md'])
        self.assertEqual(self.targets(index, '...'), [])

    def test_matching_words_in_one_paragraph_win_and_target_is_unique(self):
        index = self.index({
            'combined': '# Правила\n\nСрок хранения\nкопии определён.\n\nСрок.\n',
            'separate': '# Правила\n\nСрок.\n\nХранения.\n\nКопии.\n',
            'partial': '# Правила\n\nСрок.\n',
        })
        results = rank_documents(index, 'срок хранения копии')
        self.assertEqual([item['target'] for item in results],
                         ['docs/combined.md', 'docs/separate.md', 'docs/partial.md'])
        self.assertEqual(results[0]['excerpt'], 'Срок хранения копии определён.')
        self.assertEqual(results[0]['line'], 3)
        self.assertEqual(results[1]['line'], 5)

    def test_heading_and_body_use_narrowest_anchor_and_physical_line(self):
        index = self.index({'storage': (
            '# Хранение\n\n'
            'Введение.\n\n'
            '## Архив <a id="archive"></a>\n\n'
            'Архив доступен.\n\n'
            '### Политика очистки <a id="cleanup"></a>\n\n'
            'Запись описывает это правило.\n'
            'Копия хранится 30 дней.\n\n'
            '## Ограничения\n\n'
            'Это исключение.\n'
        )})
        result, = rank_documents(index, 'Сколько дней хранится копия?')
        self.assertEqual(result, {
            'target': 'docs/storage.md#cleanup',
            'title': 'Политика очистки',
            'excerpt': 'Запись описывает это правило. Копия хранится 30 дней.',
            'line': 12,
            'path': index.pr.root / 'docs/storage.md',
        })
        for query, target, line in (
                ('очистки', 'docs/storage.md#cleanup', 9),
                ('доступен', 'docs/storage.md#archive', 7),
                ('исключение', 'docs/storage.md', 16)):
            with self.subTest(query=query):
                result, = rank_documents(index, query)
                self.assertEqual((result['target'], result['line']), (target, line))
                node, error = index.resolve(result['target'])
                self.assertIsNone(error)
                self.assertEqual(node['page'].path, result['path'])

    def test_list_table_and_paragraph_anchors(self):
        index = self.index({'items': (
            '# Reference\n\n'
            '## Outer <a id="outer"></a>\n\n'
            '- <a id="list"></a> Parent.\n'
            '  - <a id="nested"></a> Subitem.\n'
            '    The continuation is visible.\n\n'
            '| Key | Detail |\n'
            '| --- | --- |\n'
            '| First | Nearby |\n'
            '| <a id="row"></a> Next | Inside |\n\n'
            'Paragraph starts.\n'
            '<a id="paragraph"></a> And ends.\n'
        )})
        cases = {
            'continuation': ('docs/items.md#nested', 7),
            'Parent': ('docs/items.md#list', 5),
            'Nearby': ('docs/items.md#outer', 11),
            'Inside': ('docs/items.md#row', 12),
            'Detail': ('docs/items.md#row', 9),
            'starts': ('docs/items.md#paragraph', 14),
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                item, = rank_documents(index, query)
                self.assertEqual((item['target'], item['line']), expected)

    def test_visible_markdown_text_and_hidden_syntax(self):
        index = self.index({'formatting': (
            '# **Heading** [handbook](secrethandbook.md)\n\n'
            'Follow [**the API**](secret(destination).md "secretcaption") '
            'and run `example_call`.\n\n'
            '> See [**Troubleshooting**][internalref] and <https://example.test/address>.\n\n'
            '<!-- commentword\n'
            '```\n'
            'stillcomment\n'
            '-->\n\n'
            '````python\n'
            'fencedword\n'
            '```\n'
            'stillfenced\n'
            '````\n\n'
            '    indentedword\n\n'
            '[internalref]: ../secretroute.md\n\n'
            '<span class="secretclass">Visible</span> &amp; ready.\n'
        )})
        for query in ('secrethandbook', 'secret', 'destination', 'secretcaption',
                      'internalref', 'secretroute', 'commentword', 'stillcomment',
                      'fencedword', 'stillfenced', 'indentedword', 'secretclass'):
            with self.subTest(query=query):
                self.assertEqual(self.targets(index, query), [])
        for query, expected in (
                ('handbook', (1, 'Heading handbook')),
                ('API', (3, 'Follow the API and run example_call.')),
                ('example_call', (3, 'Follow the API and run example_call.')),
                ('Troubleshooting', (5, 'See Troubleshooting and https://example.test/address.')),
                ('Visible', (22, 'Visible & ready.'))):
            with self.subTest(query=query):
                item, = rank_documents(index, query)
                self.assertEqual((item['line'], item['excerpt']), expected)
                self.assertEqual(item['title'], 'Heading handbook')

    def test_long_excerpt_stays_near_matching_text_and_reports_original_line(self):
        index = self.index({'span': (
            '# Title\n\n' + 'Common filler ' * 90 +
            '\n' + 'More filler ' * 100 + 'Unique signal. ' + 'Later filler ' * 90 + '\n'
        )})
        item, = rank_documents(index, 'signal')
        self.assertEqual(item['line'], 4)
        self.assertIn('Unique signal.', item['excerpt'])
        self.assertLessEqual(len(item['excerpt']), 180)

    def test_literal_filename_address_round_trips(self):
        index = self.index({
            'file#part': '# Guide\n\nBeforeword.\n\n## Hash <a id="x"></a>\n\nHashword.\n',
            'file%20': ('# Guide\n\n## Percent <a id="x"></a>\n\nPercentword.\n\n'
                        '## Fragment <a id="x%20"></a>\n\nFragmentword.\n'),
            'file ': '# Other\n\n## Space <a id="x"></a>\n\nDecoyword.\n',
        })
        root = index.pr.root
        support.w(root / 'lipi.json', '{}\n')
        for query, address, filename, title in (
                ('Beforeword', 'docs/file%23part.md', 'file#part.md', 'Guide'),
                ('Hashword', 'docs/file%23part.md#x', 'file#part.md', 'Hash'),
                ('Percentword', 'docs/file%2520.md#x', 'file%20.md', 'Percent'),
                ('Fragmentword', 'docs/file%2520.md#x%2520', 'file%20.md', 'Fragment'),
                ('Decoyword', 'docs/file .md#x', 'file .md', 'Space')):
            with self.subTest(query=query):
                item, = rank_documents(index, query)
                self.assertEqual(item['target'], address)
                self.assertEqual(item['path'], root / 'docs' / filename)
                node, error = index.resolve(address)
                self.assertIsNone(error)
                self.assertEqual(node['page'].path, item['path'])
                self.assertEqual(node['title'], title)
                code, output = support.cli(root, 'slice', '--search', query, '--format', 'json')
                self.assertEqual(code, 0, output)
                candidate, = json.loads(output)['candidates']
                self.assertEqual(candidate['target'], address)
                self.assertEqual(root / candidate['file'], item['path'])
                code, output = support.cli(root, 'slice', candidate['target'], '--format', 'json')
                self.assertEqual(code, 0, output)
                target = json.loads(output)['target']
                self.assertEqual(target['title'], title)
                self.assertEqual(target['kind'], 'section' if '#' in address else 'page')
