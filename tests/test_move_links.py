"""Границы точечных замен: примеры, лексика комментариев и синтаксис адресов."""

import sys
import unittest
from pathlib import Path
from types import MappingProxyType

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.move_links import replacements, trace_targets


# @trace docs/ru/commands.md#mv,docs/ru/move.md#links,ADR-017
class MoveLinks(unittest.TestCase):
    def rewrite(self, text, *, path='README.md', old='old.md', new='docs/new.md',
                moves=None, markdown=True):
        mapping = {old: new} if moves is None else moves
        mapping = MappingProxyType({support.LIPI / before: support.LIPI / after
                                    for before, after in mapping.items()})
        changes = replacements(text, path=support.LIPI / path, moves=mapping,
                               root=support.LIPI, markdown=markdown)
        previous_end = 0
        for change in changes:
            self.assertEqual(text[change.start:change.end], change.before)
            self.assertGreaterEqual(change.start, previous_end)
            previous_end = change.end
        for change in reversed(changes):
            text = text[:change.start] + change.after + text[change.end:]
        return text

    def test_indented_examples_and_nested_list_links(self):
        text = ('    [Example](old.md)\n\n'
                'Paragraph.\n\n'
                '    <!-- covers: old.md -->\n'
                '    [Example](old.md)\n\n'
                '- Item\n\n'
                '    [Continuation](old.md)\n\n'
                '    - Nested\n\n'
                '        [Nested continuation](old.md)\n\n'
                '          [Nested code](old.md)\n\n'
                '[Live](old.md)\n')
        expected = text
        for label in ('Continuation', 'Nested continuation', 'Live'):
            expected = expected.replace('[%s](old.md)' % label, '[%s](docs/new.md)' % label)
        self.assertEqual(self.rewrite(text), expected)

    def test_non_python_single_quotes_stop_at_newline(self):
        marker = '// %s old.md#part\n' % support.TAG
        for path, line in [('types.rs', "fn get<'a>(value: &'a str) {\n"),
                           ('script.js', "unfinished = 'value\n"),
                           ('script.js', 'unfinished = "value\n')]:
            with self.subTest(path=path, line=line):
                self.assertEqual(self.rewrite(line + marker, path=path, markdown=False),
                                 line + marker.replace('old.md', 'docs/new.md'))

    def test_multiline_strings_and_comment_lookalikes_are_untouched(self):
        tag = support.TAG
        text = ('const x = "// %s old.md";\n'
                'const template = `\n// %s old.md\n`;\n'
                "triple = '''\n# %s old.md\n'''\n"
                '// %s old.md#part\n') % (tag, tag, tag, tag)
        self.assertEqual(self.rewrite(text, path='script.js', markdown=False),
                         text.rsplit('old.md#part', 1)[0] + 'docs/new.md#part\n')
        python = "fixture = '''\n# %s old.md\n'''\n# %s old.md\n" % (tag, tag)
        self.assertEqual(self.rewrite(python, path='test.py', markdown=False),
                         python.rsplit('old.md', 1)[0] + 'docs/new.md\n')

    def test_fenced_offsets_and_query_anchor_titles_reference_definitions(self):
        text = ('```md\r\n[x](old%20page.md)\r\n```\r\n'
                '`[x](old%20page.md)`\r\n'
                '[x](<old%20page.md?q=x#part> "A title")\r\n'
                '[ref]: old%20page.md#part \'Reference title\'\r\n')
        result = self.rewrite(text, old='old page.md', new='docs/new page.md')
        self.assertEqual(result, text.replace('<old%20page.md?', '<docs/new%20page.md?')
                         .replace('[ref]: old%20page.md', '[ref]: docs/new%20page.md'))

    def test_new_parentheses_are_safe_and_escaped_old_urls_keep_style(self):
        for filename, encoded in [('new(.md', 'new%28.md'), ('new).md', 'new%29.md'),
                                  ('new(ok).md', 'new%28ok%29.md')]:
            with self.subTest(filename=filename):
                self.assertEqual(self.rewrite('[x](old.md#part)', new='docs/' + filename),
                                 '[x](docs/%s#part)' % encoded)
        self.assertEqual(self.rewrite(r'[x](old\(x\).md)', old='old(x).md', new='docs/new(y).md'),
                         r'[x](docs/new\(y\).md)')

    def test_trace_target_offsets_and_comment_forms(self):
        text = ('x = "// %s old.md";\n'
                '// %s old.md#part, neighbor::old.md#part\n'
                '/* %s old.md */\n'
                '-- %s old.md\n'
                '; %s old.md\n') % ((support.TAG,) * 5)
        found = list(trace_targets(text, Path('source.txt')))
        self.assertEqual([token for _, token in found],
                         ['old.md#part', 'neighbor::old.md#part', 'old.md', 'old.md', 'old.md'])
        for offset, token in found:
            self.assertEqual(text[offset:offset + len(token)], token)

    def test_trace_roles_and_adjacent_comments_preserve_exact_spelling(self):
        tag = support.TAG
        text = ('let sample = "/* %s old.md#example role=consumes*/";\r\n'
                '/* %s old.md#part, other.md#part  role=consumes,old.md#part*/ '
                '/* %s old.md#next role=produces*/\r\n'
                '// %s old.md#ignored role=reads lipi: ignore-trace\r\n') % (tag, tag, tag, tag)
        found = list(trace_targets(text, Path('source.js')))
        self.assertEqual([token for _, token in found],
                         ['old.md#part', 'other.md#part', 'old.md#next'])
        for offset, token in found:
            self.assertEqual(text[offset:offset + len(token)], token)
        expected = text.replace(tag + ' old.md#part,', tag + ' docs/new.md#part,')
        expected = expected.replace(tag + ' old.md#next', tag + ' docs/new.md#next')
        self.assertEqual(self.rewrite(text, path='source.js', markdown=False), expected)

    def test_mapping_uses_both_relocated_ends_and_original_targets(self):
        text = ('[Other](b.md#part) [Third](c.md?q=one#two)\n'
                '[Outside](../README.md) [Image](image.png)\n')
        moves = {'docs/a.md': 'pages/deep/a.md',
                 'docs/b.md': 'docs/c.md',
                 'docs/c.md': 'reference/c.md',
                 'docs/image.png': 'assets/image.png'}
        self.assertEqual(self.rewrite(text, path='docs/a.md', moves=moves),
                         '[Other](../../docs/c.md#part) '
                         '[Third](../../reference/c.md?q=one#two)\n'
                         '[Outside](../../README.md) '
                         '[Image](../../assets/image.png)\n')

    def test_whole_directory_preserves_internal_url_spelling(self):
        text = ('[Page](./%70age.md?q=one#part)\r\n'
                r'[Image](nested/../ima\(ge\).png)' + '\r\n'
                '[ref]: ./nested/../page.md "Title"\r\n'
                '[Root](/docs/page.md#part)\r\n'
                '[Outside](../README.md)\r\n')
        moves = {'docs/index.md': 'docs/ru/index.md',
                 'docs/page.md': 'docs/ru/page.md',
                 'docs/ima(ge).png': 'docs/ru/ima(ge).png'}
        expected = text.replace('(/docs/page.md', '(/docs/ru/page.md')
        expected = expected.replace('(../README.md)', '(../../README.md)')
        self.assertEqual(self.rewrite(text, path='docs/index.md', moves=moves), expected)

    def test_mapping_rewrites_root_covers_and_moving_code_markers(self):
        moves = {'docs/index.md': 'docs/ru/index.md',
                 'docs/page.md': 'docs/ru/page.md',
                 'docs/check.py': 'docs/ru/check.py'}
        markdown = ('<!-- covers: docs/page.md#part, docs/index.md -->\n'
                    '[Page](./page.md)\n')
        self.assertEqual(self.rewrite(markdown, path='docs/index.md', moves=moves),
                         '<!-- covers: docs/ru/page.md#part, docs/ru/index.md -->\n'
                         '[Page](./page.md)\n')
        code = '# %s docs/page.md#part, docs/index.md, README.md\n' % support.TAG
        self.assertEqual(self.rewrite(code, path='docs/check.py', moves=moves,
                                      markdown=False),
                         '# %s docs/ru/page.md#part, docs/ru/index.md, README.md\n'
                         % support.TAG)

    def test_inbound_images_and_reference_targets_use_same_mapping(self):
        text = ('![Image](docs/image.png) [Page](docs/page.md)\n'
                '[image-ref]: docs/image.png "Image"\n')
        moves = {'docs/page.md': 'guide/page.md',
                 'docs/image.png': 'guide/image.png'}
        self.assertEqual(self.rewrite(text, moves=moves), text.replace('docs/', 'guide/'))

    def test_escaped_and_incomplete_links_are_plain_text(self):
        text = r'\[escaped](old.md)' + '\n[incomplete](old.md\n'
        self.assertEqual(self.rewrite(text), text)


if __name__ == '__main__':
    unittest.main()
