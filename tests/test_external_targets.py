"""External trace/covers targets, status and local-only drift (ADR-016)."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / 'src'))
from lipi.checker.config import load_config
from lipi.checker.audit import audit
from lipi.checker.docs import check_docs
from lipi.checker.history import GitBlame
from lipi.checker.model import Project
from lipi.checker.report import Report, level_of_project
from lipi.checker.structure import build_structure
from lipi.checker.targets import resolve_mark
from lipi.checker.trace import scan_code


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,docs/ru/codes.md#t4,ADR-016
class ExternalTargets(support.Case):
    seed_project = False

    def setUp(self):
        self.root = self.project().resolve()
        self.neighbor = self.root.parent / (self.root.name + '-engine')
        self.neighbor.mkdir()
        self.configure_neighbor()
        support.w(self.neighbor / 'docs/guide.md',
                  '# Guide\n\n## Request <a id="request"></a>\n\nContract.\n')
        self.connect()

    def connect(self, read=('docs', 'decisions'), **extra):
        repos = {'engine': {'path': '../' + self.neighbor.name, 'read': list(read)}}
        repos.update(extra)
        support.set_config(self.root, repos=repos)

    def configure_neighbor(self, **config):
        support.w(self.neighbor / 'lipi.json', json.dumps(config) + '\n')

    def targets(self, *targets):
        support.w(self.root / 'src/consumer.py', ''.join(
            '# %s %s\ndef consumer_%d():\n    return 1\n\n'
            % (support.TAG, target, number) for number, target in enumerate(targets)))
        support.w(self.root / 'docs/README.md',
                  '# Guide\n\n<!-- covers: %s -->\n' % ', '.join(targets))

    def decision(self, status='accepted', number=1, directory='workflow/adr', root=None):
        root = root or self.neighbor
        path = root / directory / ('adr-%03d-choice.md' % number)
        result = ('- Result: [ADR-002](adr-002-choice.md)\n'
                  if status == 'superseded' else '')
        support.w(path, '# Choice\n\n- Created: 2026-01-01\n'
                  '- Updated: 2026-01-01\n- Status: ' + status + '\n' + result +
                  '\n## Decision <a id="decision"></a>\n\nRule.\n')
        return path

    def inspect(self):
        project = Project(self.root, load_config(self.root, None))
        report = Report(level_of_project(project.cfg))
        tags, lines = scan_code(project, report)
        pages, anchors, covers, reachable = check_docs(project, report)
        return project, report, tags, lines, pages, anchors, covers, reachable

    @staticmethod
    def findings(report, code):
        return [item for item in report.items if item[3] == code]

    def assert_target_errors(self, targets, text=None):
        self.targets(*targets)
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(tags, {}, report.items)
        self.assertEqual(covers, {}, report.items)
        for code in ('T1', 'D6'):
            items = self.findings(report, code)
            self.assertEqual(len(items), len(targets), report.items)
            self.assertEqual({item[5] for item in items}, set(targets))
            if text:
                self.assertTrue(all(text in item[4] for item in items), report.items)
        self.assertFalse(self.findings(report, 'T4'), report.items)

    def checked(self, *args):
        code, data = support.check_json(self.root, *args)
        self.assertIsNotNone(data)
        self.assertNotEqual(code, 2, data)
        return code, data

    def commit(self, root, date):
        code, output = support.commit(root, date=date)
        self.assertEqual(code, 0, output)

    def test_trace_and_covers_share_canonical_external_targets_and_cached_page(self):
        self.decision()
        self.targets('engine::docs/guide.md#request', 'engine::ADR-0001', 'engine::adr-1')
        project, report, tags, _, _, anchors, covers, _ = self.inspect()
        expected = {'engine::docs/guide.md#request', 'engine::ADR-001'}
        self.assertEqual(set(tags), expected, report.items)
        self.assertEqual(set(covers), expected, report.items)
        self.assertFalse(report.items, report.items)
        page = anchors['engine::docs/guide.md#request'][0]
        self.assertIs(page, project.sources.get('engine').project.page(page.path))
        with patch.object(Path, 'read_text', side_effect=AssertionError('uncached target read')):
            self.assertEqual(resolve_mark(project, 'engine::ADR-0001'), ('engine::ADR-001', None))
            self.assertEqual(resolve_mark(project, 'engine::docs/guide.md#request'),
                             ('engine::docs/guide.md#request', None))

    def test_unknown_alias_and_known_missing_target_keep_callsite_codes(self):
        self.assert_target_errors(('unknown::docs/guide.md#request',
                                   'engine::docs/missing.md#request',
                                   'engine::docs/guide.md#missing', 'engine::ADR-999'))

    def test_unprefixed_missing_targets_do_not_search_neighbors(self):
        self.decision()
        self.assert_target_errors(('ADR-001', 'docs/guide.md#request'))

    def test_local_targets_and_default_error_levels_are_unchanged(self):
        self.targets('docs/README.md#local', 'docs/missing.md#missing')
        with (self.root / 'docs/README.md').open('a') as stream:
            stream.write('\n## Local <a id="local"></a>\n')
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {'docs/README.md#local'})
        self.assertEqual(set(covers), set(tags))
        for code in ('T1', 'D6'):
            findings = self.findings(report, code)
            self.assertEqual(len(findings), 1, report.items)
            self.assertEqual(findings[0][2], 'E')
            self.assertEqual(findings[0][5], 'docs/missing.md#missing')

    def test_missing_neighbor_reports_t4_for_both_relations_with_levels(self):
        support.set_config(self.root, repos={
            'engine': {'path': '../absent-repository', 'read': ['docs', 'decisions']}})
        self.targets('engine::ADR-001')
        for level, expected_code, expected_count in ((None, 0, 2), ('error', 1, 2), ('off', 0, 0)):
            with self.subTest(level=level):
                support.set_config(self.root, codes={} if level is None else {'T4': level})
                code, data = self.checked()
                self.assertEqual(code, expected_code, data)
                items = data['errors'] + data['warnings']
                self.assertEqual(len([i for i in items if i['code'] == 'T4']), expected_count, data)
                self.assertFalse([i for i in items if i['code'] in ('T1', 'D6', 'T3')], data)
                if level is None:
                    self.assertEqual(len(data['warnings']), 2, data)
                    self.assertTrue(all('engine' in i['message'] and 'The link was not checked' in i['message']
                                        for i in data['warnings']), data)
                project, _, tags, _, _, _, covers, _ = self.inspect()
                self.assertEqual(project.sources.get('engine').state, 'unavailable')
                self.assertEqual(tags, {})
                self.assertEqual(covers, {})

    def test_bad_config_and_other_major_are_unavailable_not_missing_targets(self):
        self.targets('engine::ADR-001')
        for failure in ('config', 'major'):
            with self.subTest(failure=failure):
                self.configure_neighbor()
                if failure == 'config':
                    support.w(self.neighbor / 'lipi.json', '{invalid')
                else:
                    major = int(support.VERSION.split('.')[0]) + 1
                    support.w(self.neighbor / support.LOCK_REL,
                              json.dumps({'lipi': '%d.0.0' % major, 'files': {}}))
                _, report, _, _, _, _, _, _ = self.inspect()
                self.assertEqual(len(self.findings(report, 'T4')), 2, report.items)
                self.assertFalse(any(self.findings(report, code) for code in ('T1', 'D6', 'T3')))

    def test_unreadable_target_content_is_t4_for_both_relations(self):
        support.wb(self.neighbor / 'docs/guide.md', b'\xff\xfeinvalid')
        self.targets('engine::docs/guide.md#request')
        project, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(len(self.findings(report, 'T4')), 2, report.items)
        self.assertFalse(any(self.findings(report, code) for code in ('T1', 'D6', 'T3')))
        self.assertEqual(tags, {})
        self.assertEqual(covers, {})
        source = project.sources.get('engine')
        self.assertEqual(source.state, 'unavailable')
        self.assertIsNone(source.head)
        self.assertIsNone(source.dirty)
        self.assertFalse(project.sources.reproducible)

    def test_unreadable_target_invalidates_previous_source_metadata_even_with_t4_off(self):
        support.wb(self.neighbor / 'docs/guide.md', b'\xffinvalid')
        support.set_config(self.root, codes={'T4': 'off'})
        project = Project(self.root, load_config(self.root, None))
        source = project.sources.get('engine')
        self.assertEqual(source.state, 'no-git')
        owner = source.project
        with patch.object(source, '_git', side_effect=AssertionError('unexpected Git refresh')):
            target, error = resolve_mark(project, 'engine::docs/guide.md#request')
            self.assertIsNone(target)
            self.assertTrue(error)
            self.assertEqual(source.state, 'unavailable')
            self.assertIsNone(source.head)
            self.assertIsNone(source.dirty)
            self.assertIs(source.project, owner)
        self.assertFalse(project.sources.reproducible)

    def test_capabilities_follow_target_kind_including_decisions_under_docs(self):
        self.configure_neighbor(decisions='docs/adr')
        self.decision(directory='docs/adr')
        choices = ('engine::docs/guide.md#request', 'engine::ADR-001',
                   'engine::docs/adr/adr-001-choice.md#decision')
        for read, allowed in ((('docs',), {choices[0]}),
                              (('decisions',), set(choices[1:])),
                              (('code', 'tests'), set()),
                              (('docs', 'decisions'), set(choices))):
            with self.subTest(read=read):
                self.connect(read)
                self.targets(*choices)
                _, report, tags, _, _, _, covers, _ = self.inspect()
                self.assertEqual(set(tags), allowed, report.items)
                self.assertEqual(set(covers), allowed, report.items)
                for code in ('T1', 'D6'):
                    denied = self.findings(report, code)
                    self.assertEqual({item[5] for item in denied}, set(choices) - allowed)
                    self.assertTrue(all('read' in item[4] or support.localized('allowed reads', 'разреш') in item[4] for item in denied))

    def test_page_dirs_extend_trace_and_covers_with_matching_boundaries(self):
        self.configure_neighbor(workflow=None, decisions='notes/drafts/decisions')
        support.set_config(self.root, repos={'engine': {
            'path': '../' + self.neighbor.name, 'read': ['docs'], 'page_dirs': ['notes/drafts']}})
        allowed = 'notes/drafts/guide.md'
        denied = ('notes/private/guide.md', 'notes/drafts/decisions/adr-001-choice.md',
                  'notes/drafts/iss-001-work.md', 'notes/drafts/AGENTS.md')
        for path in (allowed, *denied):
            support.w(self.neighbor / path, '# Guide <a id="request"></a>\n')
        expected = 'engine::' + allowed + '#request'
        denied_targets = {'engine::' + path + '#request' for path in denied}
        self.targets(expected, *sorted(denied_targets))
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {expected}, report.items)
        self.assertEqual(set(covers), {expected}, report.items)
        for code in ('T1', 'D6'):
            self.assertEqual({item[5] for item in self.findings(report, code)}, denied_targets)
        self.assertFalse(self.findings(report, 'T4'), report.items)

    def test_denied_capabilities_are_checked_before_reading_target_contents(self):
        self.connect(('code', 'tests'))
        self.decision()
        project = Project(self.root, load_config(self.root, None))
        source = project.sources.get('engine')
        with patch.object(source.project, 'page', side_effect=AssertionError('denied content read')):
            for target in ('engine::docs/guide.md#request', 'engine::ADR-001',
                           'engine::workflow/adr/adr-001-choice.md#decision'):
                with self.subTest(target=target):
                    identity, error = resolve_mark(project, target)
                    self.assertIsNone(identity)
                    self.assertTrue(error)

    def test_decision_attachment_kind_comes_from_explicit_directory(self):
        self.configure_neighbor(decisions='docs/decisions')
        relative = 'docs/decisions/adr-001-choice/iss-001-evidence.md'
        support.w(self.neighbor / relative, '# Evidence <a id="evidence"></a>\n')
        target = 'engine::' + relative + '#evidence'
        self.connect(('decisions',))
        self.targets(target)
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {target}, report.items)
        self.assertEqual(set(covers), {target})
        self.assertFalse(report.items, report.items)
        self.connect(('docs',))
        self.assert_target_errors((target,))

    def test_external_work_is_unsupported_by_number_and_path(self):
        targets = []
        for prefix, directory in (('PLN', 'plan'), ('ISS', 'issue'),
                                  ('DSC', 'discussion'), ('AUD', 'audit')):
            relative = 'workflow/%s/%s-001-work.md' % (directory, prefix.lower())
            support.w(self.neighbor / relative, '# Work <a id="work"></a>\n')
            targets.extend(('engine::' + prefix + '-001', 'engine::' + relative + '#work'))
        self.assert_target_errors(targets, support.localized('unsupported', 'не поддерж'))

    def test_foreign_executor_rules_are_not_targets_even_when_docs_is_root(self):
        self.configure_neighbor(docs='.')
        paths = ('AGENTS.md', '.agents/local.md', '.agents/lipi/README.md')
        for relative in paths:
            support.w(self.neighbor / relative, '# Rules <a id="rule"></a>\n')
        self.assert_target_errors(tuple('engine::' + p + '#rule' for p in paths))

    def test_explicit_docs_directory_under_agents_is_description(self):
        self.configure_neighbor(docs='.agents/manual')
        support.w(self.neighbor / '.agents/manual/guide.md', '# Manual <a id="manual"></a>\n')
        self.targets('engine::.agents/manual/guide.md#manual')
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {'engine::.agents/manual/guide.md#manual'})
        self.assertEqual(set(covers), set(tags))
        self.assertFalse(report.items, report.items)

    def test_without_config_explicit_paths_work_but_adr_numbers_do_not(self):
        (self.neighbor / 'lipi.json').unlink()
        self.decision()
        self.targets('engine::docs/guide.md#request', 'engine::ADR-001')
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {'engine::docs/guide.md#request'}, report.items)
        self.assertEqual(set(covers), set(tags))
        for code in ('T1', 'D6'):
            self.assertEqual([item[5] for item in self.findings(report, code)], ['engine::ADR-001'])
        self.assertFalse(self.findings(report, 'T4'))

    def test_symlink_escape_and_transitive_alias_never_read_third_repository(self):
        third = self.root.parent / (self.root.name + '-third')
        support.w(third / 'docs/secret.md', '# Secret <a id="secret"></a>\n')
        self.configure_neighbor(repos={'third': {'path': '../' + third.name, 'read': ['docs']}})
        (self.neighbor / 'docs/escape.md').symlink_to(third / 'docs/secret.md')
        self.targets('engine::docs/escape.md#secret', 'third::docs/secret.md#secret',
                     'engine::third::docs/secret.md#secret')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(third), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(tags, {})
        self.assertEqual(covers, {})
        self.assertEqual(len(self.findings(report, 'T1')), 3, report.items)
        self.assertEqual(len(self.findings(report, 'D6')), 3, report.items)

    # @trace docs/ru/codes.md#t3,ADR-016
    def test_external_replaced_decision_t3_has_alias_and_successor(self):
        self.decision('superseded')
        self.decision(number=2)
        self.targets('engine::ADR-1')
        _, report, _, _, _, _, _, _ = self.inspect()
        findings = self.findings(report, 'T3')
        self.assertEqual(len(findings), 2, report.items)
        self.assertEqual({item[5] for item in findings}, {'engine::ADR-001 superseded'})
        self.assertTrue(all('engine::ADR-002' in item[4] for item in findings), findings)
        self.assertTrue(all(item[2] == 'W' for item in findings), findings)

    def test_external_decision_sections_do_not_inherit_t3_status(self):
        self.decision('rejected')
        self.targets('engine::workflow/adr/adr-001-choice.md#decision')
        _, report, tags, _, _, _, covers, _ = self.inspect()
        self.assertEqual(set(tags), {'engine::workflow/adr/adr-001-choice.md#decision'})
        self.assertEqual(set(covers), set(tags))
        self.assertFalse(self.findings(report, 'T3'), report.items)

    def test_t3_error_off_and_baseline_identity_do_not_collide_across_aliases(self):
        second = self.root.parent / (self.root.name + '-second')
        support.w(second / 'lipi.json', '{}\n')
        self.decision('rejected')
        self.decision('rejected', root=second)
        self.connect(other={'path': '../' + second.name, 'read': ['decisions']})
        self.targets('engine::ADR-001', 'other::ADR-001')
        support.set_config(self.root, codes={'T3': 'error'})
        code, data = self.checked()
        self.assertEqual(code, 1, data)
        self.assertEqual({i['subject'] for i in data['errors'] if i['code'] == 'T3'},
                         {'engine::ADR-001 rejected', 'other::ADR-001 rejected'})
        code, output = support.check(self.root, 'baseline')
        self.assertEqual(code, 0, output)
        entries = json.loads((self.root / support.BASE_REL).read_text())['entries']
        self.assertEqual(len(entries), 4, entries)
        self.assertEqual({item['subject'] for item in entries},
                         {'engine::ADR-001 rejected', 'other::ADR-001 rejected'})
        self.assertEqual(self.checked()[0], 0)
        self.decision('superseded')
        self.decision(number=2)
        code, data = self.checked()
        self.assertEqual(code, 1, data)
        self.assertEqual({i['subject'] for i in data['errors']}, {'engine::ADR-001 superseded'})
        self.assertEqual(data['baseline'], {'known': 2, 'fixed': 2})
        support.set_config(self.root, codes={'T3': 'off'})
        code, data = self.checked()
        self.assertEqual(code, 0, data)
        self.assertFalse([i for i in data['errors'] + data['warnings'] if i['code'] == 'T3'])

    # @trace ADR-016
    def test_structure_preserves_aliases_without_following_foreign_page_links(self):
        third = self.root.parent / (self.root.name + '-third')
        support.w(third / 'secret.md', '# Secret <a id="secret"></a>\n')
        page = self.neighbor / 'docs/guide.md'
        support.w(page, page.read_text() + '\n[Third](../../%s/secret.md#secret)\n' % third.name)
        self.targets('engine::docs/guide.md#request')
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(third), str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            project, report, _, lines, pages, anchors, covers, reachable = self.inspect()
            structure = build_structure(project, pages, anchors, covers, {}, lines, {}, reachable, [])
        self.assertFalse(report.items, report.items)
        self.assertEqual({edge['to'] for edge in structure['edges']
                          if edge['type'] in ('trace', 'covers')},
                         {'engine::docs/guide.md#request'})
        self.assertFalse([edge for edge in structure['edges'] if third.name in str(edge)])
        nodes = [node for node in structure['nodes'] if node['id'] == 'engine::docs/guide.md#request']
        self.assertEqual([node['path'] for node in nodes], ['engine::docs/guide.md'])

    def test_t2_a4_and_structure_stale_stay_local_with_dated_commits(self):
        self.targets('engine::docs/guide.md#request')
        support.w(self.root / 'docs/local.md', '# Local <a id="local"></a>\n\nLocal rule.\n')
        with (self.root / 'docs/README.md').open('a') as stream:
            stream.write('\n[Local](local.md)\n')
        support.w(self.root / 'src/local.py',
                  '# %s docs/local.md#local\ndef local():\n    return 1\n' % support.TAG)
        for root in (self.root, self.neighbor):
            support.git_init(root)
            self.commit(root, '2026-01-01T10:00:00')
        for path in ('src/consumer.py', 'src/local.py'):
            support.sub(self.root / path, 'return 1', 'return 2')
        support.git(self.root, 'add', 'src')
        code, data = self.checked('--staged', '--structure')
        self.assertEqual(code, 0, data)
        t2 = [item for item in data['warnings'] if item['code'] == 'T2']
        self.assertEqual({item['subject'] for item in t2}, {'docs/local.md#local'}, data)
        self.assertEqual({item['anchor'] for item in data['structure']['stale']}, {'docs/local.md#local'})
        self.commit(self.root, '2026-01-03T10:00:00')
        code, data = self.checked('--audit')
        self.assertEqual(code, 0, data)
        a4 = [item for item in data['warnings'] if item['code'] == 'A4']
        self.assertEqual({item['subject'] for item in a4}, {'docs/local.md#local'}, data)
        self.assertTrue(all('2026-01-03' in item['message'] for item in a4), a4)
        project, report, tags, lines, _, anchors, _, _ = self.inspect()
        original = GitBlame.lines_time

        def lines_time(history, relative, numbers):
            self.assertNotIn('..', Path(relative).parts, relative)
            self.assertNotIn('::', relative)
            return original(history, relative, numbers)

        with patch.object(GitBlame, 'lines_time', lines_time):
            audit(project, report, {}, anchors, tags, lines)
        self.assertEqual({item[5] for item in self.findings(report, 'A4')}, {'docs/local.md#local'})
        support.sub(self.neighbor / 'docs/guide.md', 'Contract.', 'Changed contract.')
        self.commit(self.neighbor, '2026-01-05T10:00:00')
        code, data = self.checked('--staged', '--structure')
        self.assertEqual(code, 0, data)
        self.assertFalse([item for item in data['warnings'] if item['code'] == 'T2'], data)
        self.assertEqual(data['structure']['stale'], [])
