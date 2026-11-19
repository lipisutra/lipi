"""Preview, explicit confirmation, races and conservative prune."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import support


# @trace docs/ru/review.md#confirm,docs/ru/review.md#json,docs/ru/review.md#prune
class ReviewCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lipi-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / '.agents/lipi/reviews.json'
        self.write('lipi.json', '{}\n')
        self.write('docs/api.md', '# API\n\n## Rule <a id="rule"></a>\n\nLimit 3.\n')
        self.source = '# %s docs/api.md#rule\nvalue = 2\n' % support.TAG
        self.write('src/a.py', self.source)
        support.git_init(self.root)
        support.commit(self.root, date='2026-01-01T10:00:00+00:00')
        self.write('src/a.py', self.source.replace('2', '3'))
        support.commit(self.root, date='2026-01-02T10:00:00+00:00')

    def write(self, path, text):
        support.w(self.root / path, text)

    def command(self, *args, expected=0):
        code, out = support.cli(self.root, 'review', *args, '--format', 'json')
        self.assertEqual(code, expected, out)
        return json.loads(out)

    def preview(self, *args, expected=0):
        return self.command('docs/api.md#rule', '--at', 'src/a.py', *args, expected=expected)

    def confirm(self, token, *args, expected=0):
        return self.preview('--confirm', token, '--by', 'agent:test', '--reason',
                            'Limit remains three after the refactor.', *args, expected=expected)

    def save(self):
        return self.confirm(self.preview()['token'])

    def local(self, *args):
        from lipi import review
        before = Path.cwd()
        output = io.StringIO()
        try:
            os.chdir(self.root)
            with contextlib.redirect_stdout(output):
                code = review.main([*args, '--format', 'json'])
        finally:
            os.chdir(before)
        return code, json.loads(output.getvalue())

    def test_preview_confirm_noop_and_no_git_add(self):
        preview = self.preview()
        self.assertFalse(self.state.exists())
        self.assertEqual(preview['code'], 'A4')
        self.assertEqual(preview['level'], 'warning')
        self.assertEqual(preview['source_view']['ranges'], [[1, 2]])
        full = self.preview('--full')
        self.assertEqual(full['token'], preview['token'])
        saved = self.confirm(preview['token'])
        self.assertEqual(saved['result'], 'written')
        original = self.state.read_bytes()
        self.assertEqual(json.loads(original)['entries'], [saved['entry']])
        self.assertEqual(original[-1:], b'\n')
        self.assertEqual(support.git(self.root, 'diff', '--cached', '--name-only')[1], '')
        second = self.preview()
        self.assertEqual(second['existing'], saved['entry']['id'])
        repeated = self.confirm(second['token'])
        self.assertEqual(repeated['result'], 'unchanged')
        self.assertEqual(repeated['entry'], saved['entry'])
        self.assertEqual(self.state.read_bytes(), original)

    def test_preview_limits_views_and_full_keeps_token(self):
        self.write('src/a.py', self.source + '\n'.join('value_%s = %s' % (i, i) for i in range(30)))
        preview, full = self.preview(), self.preview('--full')
        self.assertEqual(len(preview['source_view']['lines']), 20)
        self.assertEqual(preview['source_view']['omitted'], 12)
        self.assertEqual(full['source_view']['omitted'], 0)
        self.assertEqual(full['token'], preview['token'])

    def test_selection_precedes_staleness_and_duplicate_identity_refused(self):
        self.write('src/a.py', self.source + self.source.replace('2', '3'))
        from lipi import review
        with patch.object(review, 'GitBlame') as history:
            code, result = self.local('docs/api.md#rule', '--at', 'src/a.py')
        self.assertEqual(code, 2)
        history.assert_not_called()
        self.assertEqual(result['error'], 'ambiguous')
        self.assertEqual(len(result['candidates']), 2)
        self.command('docs/api.md#rule', '--at', 'src/a.py:3')
        self.write('src/a.py', self.source * 2)
        result = self.command('docs/api.md#rule', '--at', 'src/a.py:3', expected=2)
        self.assertEqual(result['error'], 'ambiguous')
        self.assertEqual(len(result['candidates']), 2)
        self.assertFalse(self.state.exists())

    def test_token_rejects_source_target_head_config_and_registry_changes(self):
        preview = self.preview()
        mutations = [('src/a.py', self.source.replace('2', '4')),
                     ('docs/api.md', '# API\n\n## Rule <a id="rule"></a>\n\nLimit 4.\n'),
                     ('lipi.json', '{"codes":{"A4":"error"}}\n'),
                     ('.agents/lipi/reviews.json', '{"schema":1,"algorithm":"sha256-lines-v1","entries":[]}\n')]
        for path, changed in mutations:
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_bytes() if target.exists() else None
                self.write(path, changed)
                self.assertEqual(self.confirm(preview['token'], expected=2)['error'], 'changed-preview')
                if original is None:
                    target.unlink()
                else:
                    target.write_bytes(original)
        support.git(self.root, 'commit', '--allow-empty', '-m', 'unrelated')
        self.assertEqual(self.confirm(preview['token'], expected=2)['error'], 'changed-preview')
        self.assertFalse(self.state.exists())

    def test_confirmation_requires_explicit_nonempty_fields(self):
        token = self.preview()['token']
        for extra in ([], ['--by', 'actor'], ['--by', ' ', '--reason', 'reason'],
                      ['--by', 'actor', '--reason', '\t']):
            result = self.preview('--confirm', token, *extra, expected=2)
            self.assertEqual(result['error'], 'invalid-arguments')
        self.assertFalse(self.state.exists())

    def test_bad_arguments_have_json_contract(self):
        for args in [[], ['docs/api.md#rule'], ['--prune', '--full'], ['--prune', '--reason', 'why'],
                     ['--staged'], ['--diff', 'HEAD'], ['--from', 'list.json'],
                     ['docs/api.md#rule', '--at', 'src/a.py:0'],
                     ['docs/api.md#rule', '--at', '../src/a.py'],
                     ['other::docs/api.md#rule', '--at', 'src/a.py'],
                     ['docs/api.md#rule', '--at', 'src/a.py', '--by', 'actor']]:
            with self.subTest(args=args):
                result = self.command(*args, expected=2)
                self.assertEqual(result['error'], 'invalid-arguments')
                self.assertEqual(result['schema'], 1)
        with tempfile.TemporaryDirectory(prefix='lipi-review-profile-') as profile:
            env = support.language_env(Path(profile), 'ru')
            command = support.PY + [str(support.CLI), 'review']
            code, out = support.run(command + ['--format=json'], cwd=self.root, env=env)
            self.assertEqual(code, 2, out)
            self.assertEqual(json.loads(out), self.command(expected=2))
            self.assertEqual(json.loads(out)['message'], 'specify TARGET and --at PATH[:LINE]')
            code, text = support.run(command, cwd=self.root, env=env)
            self.assertEqual(code, 2, text)
            self.assertIn('укажите TARGET и --at PATH[:LINE]', text)
        self.assertFalse(self.state.exists())

    def test_disabled_code_and_missing_history_are_not_reviewable(self):
        self.write('lipi.json', '{"codes":{"A4":"off"}}\n')
        self.assertEqual(self.preview(expected=2)['error'], 'no-candidate')
        self.write('lipi.json', '{"codes":{"A4":"error"}}\n')
        self.assertEqual(self.preview()['level'], 'error')
        self.write('docs/new.md', '## New <a id="new"></a>\nNew\n')
        self.write('src/new.py', '# %s docs/new.md#new\nvalue = 3\n' % support.TAG)
        self.assertEqual(self.command('docs/new.md#new', '--at', 'src/new.py', expected=2)['error'],
                         'unavailable')

    def test_corrupt_registry_is_c1_before_selection(self):
        self.write('.agents/lipi/reviews.json', '{"schema":1,"schema":1}')
        result = self.preview(expected=2)
        self.assertEqual(result['errors'][0]['code'], 'C1')
        self.assertNotIn('token', result)
        self.assertEqual(self.state.read_text(), '{"schema":1,"schema":1}')

    def test_prune_changed_only_after_confirmation_and_empty_noop(self):
        empty = self.command('--prune')
        self.assertIsNone(empty['token'])
        self.assertFalse(self.state.exists())
        saved = self.save()
        unchanged = self.command('--prune')
        self.assertEqual(unchanged['remove'], [])
        self.assertIsNone(unchanged['token'])
        before = self.state.read_bytes()
        self.write('src/a.py', self.source.replace('2', '4'))
        plan = self.command('--prune')
        self.assertEqual(plan['remove'][0]['id'], saved['entry']['id'])
        self.assertEqual(plan['remove'][0]['reason'], 'changed')
        self.assertEqual(self.state.read_bytes(), before)
        done = self.command('--prune', '--confirm', plan['token'])
        self.assertEqual(done['result'], 'written')
        self.assertEqual(done['removed'], 1)
        self.assertEqual(done['remaining'], 0)
        self.assertEqual(json.loads(self.state.read_bytes())['entries'], [])

    def test_prune_missing_endpoint_and_live_reappearance_race(self):
        from lipi import review
        self.save()
        (self.root / 'src/a.py').unlink()
        plan = self.command('--prune')
        self.assertEqual(plan['remove'][0]['reason'], 'missing-source')
        original = review.ReviewContext.lifecycle
        def racing(context):
            result = original(context)
            self.write('src/a.py', self.source.replace('2', '3'))
            return result
        with patch.object(review.ReviewContext, 'lifecycle', racing):
            code, result = self.local('--prune')
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'changed-preview')
        self.assertEqual(len(json.loads(self.state.read_bytes())['entries']), 1)

    def test_prune_preserves_excluded_and_ambiguous(self):
        self.save()
        self.write('lipi.json', '{"skip_dirs":["src"]}\n')
        plan = self.command('--prune')
        self.assertEqual(plan['remove'], [])
        self.assertEqual(plan['unchecked'][0]['reason'], 'excluded')
        self.write('lipi.json', '{}\n')
        self.write('src/a.py', self.source.replace('2', '3') * 2)
        plan = self.command('--prune')
        self.assertEqual(plan['remove'], [])
        self.assertEqual(plan['unchecked'][0]['reason'], 'ambiguous')

    def test_prune_revalidates_plan(self):
        self.save()
        self.write('src/a.py', self.source.replace('2', '4'))
        plan = self.command('--prune')
        self.write('src/a.py', self.source.replace('2', '3'))
        result = self.command('--prune', '--confirm', plan['token'], expected=2)
        self.assertEqual(result['error'], 'changed-preview')
        self.assertEqual(len(json.loads(self.state.read_bytes())['entries']), 1)

    def test_selected_pair_only_uses_blame_and_unstable_read_refused(self):
        from lipi import review
        calls = []
        original = review.GitBlame.lines_time
        def reading(history, path, numbers):
            calls.append(path)
            return original(history, path, numbers)
        with patch.object(review.GitBlame, 'lines_time', reading):
            code, response = self.local('docs/api.md#rule', '--at', 'src/a.py')
        self.assertEqual(code, 0, response)
        self.assertEqual(calls, ['docs/api.md'])
        def racing(history, path, numbers):
            result = original(history, path, numbers)
            self.write('src/a.py', self.source.replace('2', '5'))
            return result
        with patch.object(review.GitBlame, 'lines_time', racing):
            code, response = self.local('docs/api.md#rule', '--at', 'src/a.py')
        self.assertEqual(code, 2)
        self.assertEqual(response['error'], 'changed-preview')
        self.assertFalse(self.state.exists())

    def test_atomic_write_failure_preserves_bytes_and_releases_lock(self):
        from lipi import review
        self.save()
        self.write('src/a.py', self.source.replace('2', '4'))
        preview = self.preview()
        before = self.state.read_bytes()
        with patch.object(review.os, 'replace', side_effect=OSError('synthetic write failure')):
            code, response = self.local('docs/api.md#rule', '--at', 'src/a.py',
                                        '--confirm', preview['token'], '--by', 'actor', '--reason', 'reason')
        self.assertEqual(code, 2)
        self.assertEqual(response['error'], 'write-failed')
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(self.state.with_name('reviews.json.lock').exists())
        self.assertEqual(list(self.state.parent.glob('.reviews-*')), [])

    def test_registry_cas_refuses_concurrent_writer(self):
        from lipi import review
        token = self.preview()['token']
        original = review.registry_lock
        @contextlib.contextmanager
        def racing(root):
            with original(root):
                self.write('.agents/lipi/reviews.json',
                           '{"schema":1,"algorithm":"sha256-lines-v1","entries":[]}\n')
                yield
        with patch.object(review, 'registry_lock', racing):
            code, response = self.local('docs/api.md#rule', '--at', 'src/a.py', '--confirm', token,
                                        '--by', 'actor', '--reason', 'reason')
        self.assertEqual(code, 2)
        self.assertEqual(response['error'], 'changed-preview')
        self.assertEqual(json.loads(self.state.read_bytes())['entries'], [])

    def test_help_routing_and_text_preview(self):
        for args in [('help', 'review'), ('review', '--help')]:
            code, out = support.cli(self.root, *args)
            self.assertEqual(code, 0, out)
            self.assertIn('--confirm', out)
        code, out = support.cli(self.root, 'review', 'docs/api.md#rule', '--at', 'src/a.py')
        self.assertEqual(code, 0, out)
        for text in ('A4 warning', 'sha256:', 'token:', 'src/a.py', 'docs/api.md#rule'):
            self.assertIn(text, out)


if __name__ == '__main__':
    unittest.main()
