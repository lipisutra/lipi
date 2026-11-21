"""Срез прямых подключений: области чтения, адреса, неполнота и общий отбор."""
import json
import os
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.slice_query import build_slice


# @trace docs/ru/slice.md#repos
class RepositorySlices(support.Case):
    seed_project = False

    def setUp(self):
        self.root = self.project().resolve()
        self.neighbor = self.root.parent / (self.root.name + '-core')
        self.neighbor.mkdir()
        support.w(self.neighbor / 'lipi.json', json.dumps({
            'workflow': None, 'decisions': 'decisions',
            'repos': {'consumer': {'path': '../' + self.root.name, 'read': ['docs']}},
            'layers': {'src/*': 'engine'}}))
        support.set_config(self.root, workflow=None,
                           repos={'core': {'path': '../' + self.neighbor.name,
                                           'read': ['docs', 'decisions', 'code', 'tests']}},
                           layers={'src/*': 'api'})
        support.w(self.root / 'docs/README.md', '# Local\n\n## Local <a id="local"></a>\n\nLocal rule.\n')
        support.w(self.neighbor / 'docs/api.md',
                  '# Protocol\n\n## Request <a id="request"></a>\n\nA request has an identifier.\n')

    def code(self, path='src/client.py', targets=('core::docs/api.md#request',), root=None):
        support.w((root or self.root) / path,
                  '# %s %s\ndef request():\n    return 1\n' % (support.TAG, ', '.join(targets)))

    def decision(self, number, *, status='accepted', refines=None):
        text = '# Decision %s\n\n- Status: %s\n' % (number, status)
        if refines:
            text += '- Refines: [Parent](adr-%03d-choice.md)\n' % refines
        support.w(self.neighbor / ('decisions/adr-%03d-choice.md' % number),
                  text + '\n## Decision\n\nA rule.\n')

    def response(self, query, *args, expected=0):
        code, text = support.cli(self.root, 'slice', query, '--format', 'json', *args)
        self.assertEqual(code, expected, text)
        return json.loads(text)

    @staticmethod
    def items(response, kind):
        return [item for block in response.get('blocks', []) if block['kind'] == kind
                for item in block['items']]

    def note(self, response, code):
        notes = [note['text'] for note in response['notes'] if note['code'] == code]
        self.assertEqual(len(notes), 1, response['notes'])
        return notes[0]

    def test_external_excerpt_and_only_local_consumers_with_clean_metadata(self):
        self.code()
        self.code('tests/test_client.py')
        self.code(root=self.neighbor, targets=('docs/api.md#request',))
        for root in (self.root, self.neighbor):
            support.git_init(root)
            self.assertEqual(support.commit(root)[0], 0)
        result = self.response('core::docs/api.md#request', '--full')
        self.assertEqual(result['target']['repo'], 'core')
        self.assertEqual(result['target']['target'], 'docs/api.md#request')
        self.assertIn('identifier', self.items(result, 'excerpt')[0]['text'])
        self.assertEqual({item['repo'] for item in self.items(result, 'code')}, {None})
        self.assertEqual(result['summary']['tests'], 1)
        self.assertEqual(result['summary']['repos'], 1)
        self.assertEqual([item['repo'] for item in result['checks']['repos']], [None, 'core'])
        self.assertTrue(result['reproducible'])
        self.assertFalse(result['incomplete'])
        self.assertEqual(result['checks']['staleness'],
                         {'state': 'full', 'checked': 0, 'total': 0, 'scope': 'local'})
        self.assertEqual(self.note(result, 'cross-repo-staleness'),
                         '2 locations with cross-repository links. Staleness of these links was not checked')

    def test_external_without_consumers_still_returns_excerpt(self):
        result = self.response('core::docs/api.md#request')
        self.assertTrue(self.items(result, 'excerpt'))
        self.assertFalse(self.items(result, 'code'))
        self.assertEqual(self.note(result, 'cross-repo-staleness'),
                         '0 locations with cross-repository links. Staleness of these links was not checked')

    # @trace docs/ru/slice-output.md#repo-search
    def test_title_search_suggestions_preserve_order_and_shell_arguments(self):
        another = self.root.parent / 'another'
        support.w(another / 'lipi.json', '{"workflow": null}')
        decisions = self.root.parent / 'decisions'
        support.w(decisions / 'lipi.json', '{"workflow": null}')
        unconfigured = self.root.parent / 'unconfigured'
        unconfigured.mkdir()
        support.set_config(self.root, repos={
            'z-core': {'path': '../' + self.neighbor.name, 'read': ['docs']},
            'decisions': {'path': '../decisions', 'read': ['decisions']},
            'missing': {'path': '../absent', 'read': ['docs']},
            'unconfigured': {'path': '../unconfigured', 'read': ['docs']},
            '-another': {'path': '../another', 'read': ['docs']},
        })
        phrase = '  writer\'s "$REPORT" & editor’s preview  '
        project = Project(self.root, load_config(self.root, None))
        with patch('lipi.repo_index._NeighborIndex._search_candidates',
                   side_effect=AssertionError('suggestions must not search titles')):
            result, status = build_slice(project, phrase)
        self.assertEqual(status, 1)
        self.assertEqual(result['error'], 'not-found')
        self.assertEqual(result['candidates'], [])
        self.assertEqual([item['repo'] for item in result['suggestions']], ['z-core', '-another'])
        for item in result['suggestions']:
            target = item['repo'] + '::' + phrase
            args = ['lipi', 'slice'] + (['--'] if target.startswith('-') else [])
            if os.name == 'nt':
                quoted = "'" + target.replace("'", "''").replace('’', '’’') + "'"
                self.assertEqual(item['command'], ' '.join([*args, quoted]))
            else:
                self.assertEqual(shlex.split(item['command']), [*args, target])
        self.assertEqual(self.response(phrase, expected=1)['suggestions'], result['suggestions'])
        code, output = support.cli(self.root, 'slice', phrase)
        self.assertEqual(code, 1, output)
        self.assertEqual([line.strip() for line in output.splitlines() if line.startswith('  lipi slice ')],
                         [item['command'] for item in result['suggestions']])

    # @trace docs/ru/slice-output.md#repo-search
    def test_suggestions_only_for_local_text_misses_with_eligible_connections(self):
        for query, status in (
                ('Local', 0), ('core::word missing', 1), ('missing.md', 1), ('missing.py', 1),
                ('docs%2Fmissing', 1), ('docs/README.md#absent', 1), ('ADR-099', 1)):
            with self.subTest(query=query):
                self.assertNotIn('suggestions', self.response(query, expected=status))
        for name in ('first', 'second'):
            support.w(self.root / ('docs/' + name + '.md'), '# Shared report\n')
        result = self.response('shared report', expected=1)
        self.assertEqual(result['error'], 'ambiguous')
        self.assertNotIn('suggestions', result)
        result = self.response('Working with Node.js', expected=1)
        self.assertEqual([item['repo'] for item in result['suggestions']], ['core'])
        support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
                                                     'read': ['decisions']}})
        result = self.response('word missing', expected=1)
        self.assertNotIn('suggestions', result)

    # @trace docs/ru/slice-output.md#repo-search
    def test_neighbor_title_lookup_from_root_and_subdirectory(self):
        file = self.neighbor / 'notes/drafts/export.md'
        title = 'Повторная выгрузка отчёта'
        phrase = 'выгрузка отчёта'
        support.w(file, '# ' + title + '\n\nКарточка.\n')
        support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
            'read': ['docs'], 'page_dirs': ['notes/drafts']}})
        src = self.root / 'src'
        src.mkdir()
        support.git_init(self.root)
        expected = self.response('core::' + phrase)
        self.assertEqual(expected['target'], {'repo': 'core', 'target': 'notes/drafts/export.md',
                                              'title': title, 'found': 'title', 'kind': 'page'})
        for cwd, language, match, opening in (
                (self.root, 'en', '(found: title)', 'Open '),
                (src, 'ru', '(найдено: title)', 'Открыть ')):
            with self.subTest(cwd=cwd, language=language):
                env = support.language_env(self.root.parent / ('profile-' + language), language)
                cli = support.PY + [str(support.CLI), 'slice']
                code, output = support.run(cli + [phrase, '--format', 'json'], cwd=cwd, env=env)
                self.assertEqual(code, 1, output)
                suggestion, = json.loads(output)['suggestions']
                self.assertEqual(suggestion, {'repo': 'core', 'command': "lipi slice 'core::" + phrase + "'"})
                code, output = support.run(cli + [phrase], cwd=cwd, env=env)
                self.assertEqual(code, 1, output)
                self.assertIn(suggestion['command'], output)
                query = shlex.split(suggestion['command'])[-1]
                code, output = support.run(cli + [query, '--format', 'json'], cwd=cwd, env=env)
                self.assertEqual(code, 0, output)
                self.assertEqual(json.loads(output), expected)
                code, output = support.run(cli + [query], cwd=cwd, env=env)
                self.assertEqual(code, 0, output)
                self.assertIn('core::notes/drafts/export.md — ' + title, output)
                self.assertIn(match, output)
                opened = next(line[len(opening):] for line in output.splitlines() if line.startswith(opening))
                self.assertEqual(opened, os.path.relpath(file, cwd))
                self.assertEqual((cwd / opened).read_text(encoding='utf-8'), file.read_text(encoding='utf-8'))

    # @trace docs/ru/slice.md#target
    def test_project_discovery_stops_at_nested_git_boundary(self):
        support.git_init(self.root)
        nested = self.root / 'nested'
        cwd = nested / 'src'
        cwd.mkdir(parents=True)
        support.git_init(nested)
        code, output = support.cli(cwd, 'slice', 'Local', '--format', 'json')
        self.assertEqual(code, 1, output)
        self.assertNotIn('checks', json.loads(output))
        support.w(nested / 'lipi.json', '{"workflow": null}')
        support.w(nested / 'docs/local.md', '# Local\n')
        code, output = support.cli(cwd, 'slice', 'Local', '--format', 'json')
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)['target']['target'], 'docs/local.md')

    def test_reverse_places_use_physical_backlink_and_qualified_layer(self):
        self.code(targets=('docs/README.md#local',))
        self.code(root=self.neighbor, targets=('consumer::docs/README.md#local',))
        self.code(root=self.neighbor, path='tests/test_request.py',
                  targets=('consumer::docs/README.md#local',))
        result = self.response('docs/README.md#local')
        self.assertEqual([item['repo'] for item in self.items(result, 'code')], [None, 'core'])
        self.assertEqual(self.items(result, 'tests')[0]['repo'], 'core')
        self.assertEqual(result['summary']['repos'], 2)
        narrowed = self.response('docs/README.md#local', '--layer', 'core::engine')
        self.assertEqual([item['repo'] for item in self.items(narrowed, 'code')], ['core'])
        self.assertEqual(narrowed['summary']['code'], 1)
        self.assertFalse([note for note in narrowed['notes'] if note['code'] == 'layers-no-marks'])
        self.assertEqual(result['checks']['staleness'], narrowed['checks']['staleness'])
        code, text = support.cli(self.root, 'slice', 'docs/README.md#local', '--layer', 'core::engine')
        self.assertEqual(code, 0, text)
        self.assertIn('core::src/client.py:1', text)
        self.assertIn('[core::engine]', text)

    def test_staleness_counts_mixed_locations_once_before_filters_and_budget(self):
        target = 'docs/README.md#local'
        test_path = 'tests/test_request.py'
        support.w(self.neighbor / 'docs/detail.md', '# Detail <a id="detail"></a>\n\nDetails.\n')
        self.code(targets=(target,))
        self.code(test_path, targets=(target, 'core::docs/api.md#request',
                                      'core::docs/detail.md#detail'))
        self.code(root=self.neighbor, targets=('consumer::' + target,))
        self.code(test_path, root=self.neighbor, targets=('consumer::' + target,))
        for root in (self.root, self.neighbor):
            support.git_init(root)
            self.assertEqual(support.commit(root)[0], 0)

        result = self.response(target)
        coverage = {'state': 'full', 'checked': 2, 'total': 2, 'scope': 'local'}
        cross_note = '3 locations with cross-repository links. Staleness of these links was not checked'
        local_note = 'checked 2 of 2 local locations for staleness'
        self.assertEqual(result['checks']['staleness'], coverage)
        self.assertEqual(self.note(result, 'cross-repo-staleness'), cross_note)
        self.assertEqual(self.note(result, 'staleness-full'), local_note)
        self.assertEqual(result['summary']['tests'], 2)
        self.assertEqual([(item['repo'], item['path'], item['line']) for item in self.items(result, 'tests')],
                         [(None, test_path, 1), ('core', test_path, 1)])
        self.assertFalse(result['incomplete'])

        for language, summary, heading, local, cross in (
                ('en', '2 test locations', 'Test locations', local_note, cross_note),
                ('ru', '2 места в тестах', 'Места в тестах',
                 'Устаревание проверено для 2 из 2 локальных мест',
                 '3 места с межрепозиторными связями. Устаревание этих связей не проверялось')):
            with self.subTest(language=language):
                env = support.language_env(self.root.parent / ('profile-' + language), language)
                command = support.PY + [str(support.CLI), 'slice', target]
                code, text = support.run(command, cwd=self.root, env=env)
                self.assertEqual(code, 0, text)
                self.assertIn(summary, text.splitlines()[1])
                self.assertIn(heading, text.splitlines())
                self.assertIn(local, text.splitlines())
                self.assertIn(cross, text.splitlines())
                code, output = support.run(command + ['--format', 'json'], cwd=self.root, env=env)
                self.assertEqual(code, 0, output)
                self.assertEqual(json.loads(output), result)

        support.set_config(self.root, slice_budget=1)
        filtered = self.response(target, '--only', 'code', '--layer', 'api', '--layer', 'core::engine')
        self.assertEqual([item['repo'] for item in self.items(filtered, 'code')], [None])
        self.assertFalse(self.items(filtered, 'tests'))
        self.assertEqual(next(block['omitted'] for block in filtered['blocks'] if block['kind'] == 'code'), 1)
        self.assertEqual(filtered['checks']['staleness'], coverage)
        self.assertEqual(self.note(filtered, 'cross-repo-staleness'), cross_note)
        self.assertEqual(self.note(filtered, 'staleness-full'), local_note)

    def test_code_file_counts_its_own_cross_repo_location_with_partial_local_history(self):
        path = 'src/client.py'
        target = 'docs/README.md#local'
        self.code(path, targets=(target,))
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        support.w(self.root / 'docs/untracked.md', '# New <a id="new"></a>\n\nNew rule.\n')
        self.code(path, targets=(target, 'docs/untracked.md#new', 'core::docs/api.md#request'))

        result = self.response(path)
        self.assertFalse(self.items(result, 'code'))
        self.assertEqual(result['checks']['staleness'],
                         {'state': 'partial', 'checked': 0, 'total': 1, 'scope': 'local'})
        self.assertEqual(self.note(result, 'staleness-partial'),
                         'checked 0 of 1 local locations for staleness. Run lipi audit for a full local check')
        self.assertEqual(self.note(result, 'cross-repo-staleness'),
                         '1 location with cross-repository links. Staleness of these links was not checked')

    def test_missing_source_has_exit_zero_even_t4_error_and_off_preserves_state(self):
        support.set_config(self.root, repos={'core': {'path': '../missing-neighbor', 'read': ['docs']}})
        for level in ('warning', 'error', 'off'):
            with self.subTest(level=level):
                support.set_config(self.root, codes={'T4': level})
                result = self.response('core::docs/api.md#request')
                self.assertTrue(result['incomplete'])
                self.assertFalse(result['reproducible'])
                self.assertNotIn('found', result['target'])
                self.assertEqual(result['target']['title'], '')
                self.assertEqual(result['checks']['repos'][1]['state'], 'unavailable')
                signals = self.items(result, 'signals')
                self.assertEqual(len(signals), 0 if level == 'off' else 1)
                if signals:
                    self.assertEqual(signals[0]['target_repo'], 'core')
                    self.assertEqual(signals[0]['level'], level)
        result = self.response('core::request')
        self.assertIsNone(result['target']['kind'])

    def test_unknown_missing_and_ambiguous_targets_return_one_with_addresses(self):
        for query in ('unknown::docs/api.md#request', 'core::docs/missing.md#request'):
            with self.subTest(query=query):
                result = self.response(query, expected=1)
                self.assertEqual(result['error'], 'not-found')
                self.assertTrue(result['message'])
                self.assertIn('checks', result)
        support.w(self.neighbor / 'docs/extra.md', '# Other\n\n## Request <a id="request"></a>\n')
        result = self.response('core::request', expected=1)
        self.assertEqual(result['error'], 'ambiguous')
        self.assertEqual({item['repo'] for item in result['candidates']}, {'core'})
        self.assertTrue(all('::' not in item['target'] for item in result['candidates']))

    # @trace docs/ru/slice-output.md#repo-search
    def test_explicit_page_address_explains_the_action_in_text_and_json(self):
        self.decision(1)
        support.w(self.neighbor / 'notes/export.md', '# Export\n')
        cases = (
            ('notes/export.md', ['docs'], 'outside-scope', 'repos.core.page_dirs'),
            ('notes/absent.md#x', ['docs'], 'outside-scope', 'repos.core.page_dirs'),
            ('docs/api.md#request', ['decisions'], 'scope-not-enabled', 'docs'),
            ('decisions/adr-001-choice.md', ['docs'], 'scope-not-enabled', 'decisions'),
            ('docs/missing.md', ['docs'], 'page-not-found', 'file path'),
            ('docs/api.md#absent', ['docs'], 'anchor-not-found', '#absent'),
        )
        for address, read, reason, hint in cases:
            with self.subTest(address=address):
                support.set_config(self.root, repos={'core': {
                    'path': '../' + self.neighbor.name, 'read': read}})
                query = 'core::' + address
                result = self.response(query, expected=1)
                self.assertEqual((result['schema'], result['error'], result['reason']),
                                 (1, 'not-found', reason))
                self.assertIn(hint, result['message'])
                if reason == 'scope-not-enabled':
                    self.assertIn('repos.core.read', result['message'])
                status, text = support.cli(self.root, 'slice', query)
                self.assertEqual(status, 1)
                self.assertIn(support.localized(hint, 'путь' if hint == 'file path' else hint), text)

        support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
                                                     'read': ['docs'], 'page_dirs': ['notes', 'future']}})
        self.assertEqual(self.response('core::notes/export.md')['target']['found'], 'exact')
        self.assertEqual(self.response('core::future/export.md', expected=1)['reason'], 'page-not-found')

    def test_configured_decision_directory_keeps_its_scope_through_an_internal_symlink(self):
        self.decision(1)
        directory = self.neighbor / 'decisions'
        directory.rename(self.neighbor / 'policies')
        try:
            directory.symlink_to('policies', target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        page = 'decisions/adr-001-choice.md'
        support.w(self.neighbor / page, '# Choice\n\n## Rule <a id="rule"></a>\n')
        for read in (['docs', 'decisions'], ['docs']):
            support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
                                                         'read': read}})
            for suffix in ('', '#rule'):
                with self.subTest(read=read, suffix=suffix):
                    query = 'core::' + page + suffix
                    if 'decisions' in read:
                        self.assertEqual(self.response(query)['target']['found'], 'exact')
                    else:
                        result = self.response(query, expected=1)
                        self.assertEqual(result['reason'], 'scope-not-enabled')
                        self.assertIn('decisions', result['message'])

    def test_outside_scope_does_not_probe_the_requested_file(self):
        from lipi.repo_index import RepoIndex
        pr = Project(self.root, load_config(self.root, None))
        index = RepoIndex(pr)
        source = index.sources.get('core')
        with patch.object(source, 'resolve_path', side_effect=AssertionError('out-of-scope probe')), \
                patch.object(source.project, 'file_path', side_effect=AssertionError('out-of-scope probe')):
            for suffix in ('', '#row'):
                _, error = index.resolve('core::notes/private.md' + suffix)
                self.assertEqual(error['reason'], 'outside-scope')

    def test_external_not_found_explains_work_ids_bare_names_and_denied_decisions(self):
        self.decision(1)
        for query in ('core::ADR-999', 'core::absent', 'core::ISS-001', 'core::ADR-001'):
            with self.subTest(query=query):
                read = ['docs'] if query == 'core::ADR-001' else ['docs', 'decisions']
                support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
                                                            'read': read}})
                result = self.response(query, expected=1)
                self.assertEqual(result['error'], 'not-found')
                self.assertEqual(result['query'], query)
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['message'],
                                 'target is missing or outside the allowed read scope')
                self.assertEqual([item['repo'] for item in result['checks']['repos']],
                                 [None, 'core'])
                self.assertEqual(result['checks']['repos'][1]['read'], read)

    def test_ambiguous_external_decision_keeps_candidate_paths(self):
        self.decision(1)
        support.w(self.neighbor / 'decisions/0001-other.md', '# Other decision\n')
        result = self.response('core::ADR-001', expected=1)
        self.assertEqual(result['error'], 'ambiguous')
        self.assertEqual(result['query'], 'core::ADR-001')
        self.assertNotIn('message', result)
        self.assertEqual({(item['repo'], item['target']) for item in result['candidates']},
                         {('core', 'decisions/adr-001-choice.md'),
                          ('core', 'decisions/0001-other.md')})
        self.assertEqual([item['repo'] for item in result['checks']['repos']], [None, 'core'])

    def test_without_config_only_explicit_section_is_supported(self):
        (self.neighbor / 'lipi.json').unlink()
        self.assertTrue(self.items(self.response('core::docs/api.md#request'), 'excerpt'))
        for query in ('core::docs/api.md', 'core::request', 'core::ADR-001'):
            with self.subTest(query=query):
                response = self.response(query, expected=1)
                self.assertEqual(response['error'], 'not-found')
                self.assertEqual(response['reason'], 'no-config')
                self.assertIn('path#anchor', response['message'])

    def test_explicit_external_adr_brings_accepted_refinements_but_not_foreign_rules(self):
        self.decision(1)
        self.decision(2, refines=1)
        self.decision(3, refines=2)
        support.w(self.neighbor / 'AGENTS.md', '# Rules\n\n## Hidden <a id="hidden"></a>\n')
        self.assertFalse(self.items(self.response('core::ADR-001'), 'obey'))
        self.code(targets=('core::ADR-001',))
        for query in ('src/client.py', 'core::ADR-001'):
            with self.subTest(query=query):
                result = self.response(query)
                self.assertEqual({(item['repo'], item['target']) for item in self.items(result, 'obey')},
                                 {('core', 'ADR-001'), ('core', 'ADR-002'), ('core', 'ADR-003')})
                self.assertFalse(any('AGENTS' in item['target'] for item in self.items(result, 'context')))

    def test_t3_separates_local_source_and_external_target(self):
        self.decision(1, status='rejected')
        self.code(targets=('docs/README.md#local', 'core::ADR-001'))
        result = self.response('docs/README.md#local')
        signal = next(item for item in self.items(result, 'signals') if item['code'] == 'T3')
        self.assertEqual((signal['repo'], signal['path'], signal['target_repo'], signal['target']),
                         (None, 'src/client.py', 'core', 'ADR-001'))
        self.assertIn('core::ADR-001', signal['message'])

    def test_unreadable_source_discards_all_its_data_and_keeps_own_places(self):
        self.code(targets=('docs/README.md#local',))
        self.code(root=self.neighbor, targets=('consumer::docs/README.md#local',))
        (self.neighbor / 'docs/broken.md').write_bytes(b'\xff')
        result = self.response('docs/README.md#local')
        self.assertEqual([item['repo'] for item in self.items(result, 'code')], [None])
        self.assertEqual(result['summary']['code'], 1)
        self.assertEqual(result['checks']['repos'][1]['state'], 'unavailable')
        self.assertTrue(result['incomplete'])

    def test_failed_covers_read_discards_already_indexed_source(self):
        (self.neighbor / 'lipi.json').unlink()
        self.code(targets=('docs/README.md#local', 'core::docs/api.md#request'))
        (self.neighbor / 'docs/broken.md').write_bytes(b'\xff')
        with (self.root / 'docs/README.md').open('a') as stream:
            stream.write('\n<!-- covers: core::docs/broken.md#missing -->\n')
        result = self.response('docs/README.md#local')
        self.assertEqual(result['checks']['repos'][1]['state'], 'unavailable')
        self.assertEqual(result['summary']['code'], 1)
        self.assertFalse([item for item in self.items(result, 'context') if item['repo'] == 'core'])
        self.assertEqual(len([item for item in self.items(result, 'signals') if item['code'] == 'T4']), 1)

    def test_same_file_and_line_in_different_sources_keep_both_status_signals(self):
        support.set_config(self.root, decisions='decisions')
        support.w(self.root / 'decisions/adr-001-rule.md', '# Rule\n\n- Status: rejected\n')
        self.code(targets=('docs/README.md#local', 'ADR-001'))
        self.code(root=self.neighbor, targets=('consumer::docs/README.md#local', 'consumer::ADR-001'))
        result = self.response('docs/README.md#local')
        statuses = [item for item in self.items(result, 'signals') if item['code'] == 'T3']
        self.assertEqual({(item['repo'], item['path'], item['target_repo']) for item in statuses},
                         {(None, 'src/client.py', None), ('core', 'src/client.py', None)})

    def test_read_only_and_dirty_metadata_do_not_claim_incomplete(self):
        self.code()
        for root in (self.root, self.neighbor):
            support.git_init(root)
            self.assertEqual(support.commit(root)[0], 0)
        support.w(self.neighbor / 'untracked.txt', 'Uncommitted.\n')
        before = {str(path): path.read_bytes() for root in (self.root, self.neighbor)
                  for path in root.rglob('*') if path.is_file()}
        result = self.response('core::docs/api.md#request')
        self.assertFalse(result['reproducible'])
        self.assertFalse(result['incomplete'])
        self.assertTrue(result['checks']['repos'][1]['dirty'])
        after = {str(path): path.read_bytes() for root in (self.root, self.neighbor)
                 for path in root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_local_work_gets_explicit_foreign_obligations_via_own_goal(self):
        support.set_config(self.root, workflow='workflow')
        self.decision(1)
        self.decision(2, refines=1)
        self.code(targets=('docs/README.md#local', 'core::ADR-001'))
        support.w(self.root / 'workflow/plan/2026/pln-001-change.md',
                  '# Change\n\n- Status: new\n\n[Goal](../../../docs/README.md#local)\n')
        result = self.response('PLN-001')
        obligations = self.items(result, 'obey')
        self.assertEqual({item['target'] for item in obligations}, {'ADR-001', 'ADR-002'})
        self.assertTrue(all(item['repo'] == 'core' for item in obligations))
        self.assertTrue(all(item['via'] == ['docs/README.md#local'] for item in obligations))

    def test_staleness_never_asks_git_about_external_targets_or_code(self):
        self.code()
        project = Project(self.root, load_config(self.root, None))
        with patch('lipi.slice_query.GitBlame', side_effect=AssertionError('foreign blame')):
            result, code = build_slice(project, 'core::docs/api.md#request')
        self.assertEqual(code, 0)
        self.assertEqual(result['checks']['staleness']['total'], 0)

    def test_read_permissions_apply_to_search_and_reverse_place_categories(self):
        self.decision(1)
        self.code(root=self.neighbor, targets=('consumer::docs/README.md#local',))
        self.code(root=self.neighbor, path='tests/test_request.py',
                  targets=('consumer::docs/README.md#local',))
        support.set_config(self.root, repos={'core': {'path': '../' + self.neighbor.name,
                                                     'read': ['docs', 'tests']}})
        self.response('core::ADR-001', expected=1)
        result = self.response('docs/README.md#local')
        self.assertFalse(self.items(result, 'code'))
        self.assertEqual(len(self.items(result, 'tests')), 1)
        self.assertEqual(self.note(result, 'cross-repo-staleness'),
                         '1 location with cross-repository links. Staleness of these links was not checked')

    def test_only_and_budget_preserve_metadata_and_common_selection(self):
        for number in range(8):
            self.code('src/client%d.py' % number)
        support.set_config(self.root, slice_budget=3)
        result = self.response('core::docs/api.md#request', '--only', 'code')
        self.assertEqual(result['summary']['code'], 8)
        self.assertEqual(len(self.items(result, 'code')), 3)
        self.assertTrue(result['incomplete'])
        self.assertTrue(result['checks']['repos'])
        code, text = support.cli(self.root, 'slice', 'core::docs/api.md#request', '--only', 'code')
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized('sources:', 'источники:'), text)
        self.assertIn(support.localized('local staleness was not checked (Git unavailable)',
                                        'Устаревание локальных связей не проверено (Git недоступен)'), text)
        self.assertIn(support.localized(
            '8 locations with cross-repository links. Staleness of these links was not checked',
            '8 мест с межрепозиторными связями. Устаревание этих связей не проверялось'), text)
        for item in self.items(result, 'code'):
            self.assertIn(item['path'] + ':1', text)

    def test_diff_reads_only_own_changes_but_includes_external_targets(self):
        self.code()
        self.code('tests/test_request.py')
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        support.sub(self.root / 'src/client.py', 'return 1', 'return 2')
        code, text = support.cli(self.root, 'slice', '--diff', 'HEAD', '--format', 'json')
        self.assertEqual(code, 0, text)
        result = json.loads(text)
        self.assertEqual([(item['repo'], item['target']) for item in self.items(result, 'concepts')],
                         [('core', 'docs/api.md#request')])
        self.assertEqual([item['path'] for item in self.items(result, 'tests')], ['tests/test_request.py'])
        self.assertEqual(self.note(result, 'cross-repo-staleness'),
                         '1 location with cross-repository links. Staleness of these links was not checked')
        self.assertEqual(result['checks']['diff']['files'], 1)

    def test_deleted_external_decision_mark_retains_diff_obligations(self):
        self.decision(1)
        self.decision(2, refines=1)
        self.code(targets=('core::ADR-001',))
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        (self.root / 'src/client.py').unlink()
        code, text = support.cli(self.root, 'slice', '--diff', 'HEAD', '--format', 'json')
        self.assertEqual(code, 0, text)
        result = json.loads(text)
        self.assertEqual({item['target'] for item in self.items(result, 'obey')}, {'ADR-001', 'ADR-002'})
