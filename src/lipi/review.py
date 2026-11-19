#!/usr/bin/env python3
"""lipi review — просмотр одной пары A4 и уборка устаревших отметок."""
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (OSError, ValueError):
            pass
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lipi.i18n import ArgumentParser, cli_output, output_format, tr
from lipi.checker.config import load_config, validate_config
from lipi.checker.conventions import CONFIG_NAME
from lipi.checker.history import GitBlame
from lipi.checker.model import Project
from lipi.checker.report import CODE_LEVELS
from lipi.map import _config_errors
from lipi.checker.reviews import (REVIEWS_NAME, ReviewContext, ReviewError, canonical_json,
                                  serialize_reviews)


class ReviewFailure(Exception):
    def __init__(self, error, message, **details):
        super().__init__(message)
        self.error, self.details = error, details


class ConfigFailure(Exception):
    def __init__(self, errors):
        self.errors = errors


class Parser(ArgumentParser):
    def error(self, message):
        raise ReviewFailure('invalid-arguments', message)


# @trace docs/ru/commands.md#review,docs/ru/review.md#confirm
def parser():
    ap = Parser(prog='lipi review', description=tr('review.help.description'))
    ap.add_argument('target', nargs='?', metavar='TARGET', help=tr('review.help.target'))
    ap.add_argument('--at', metavar='PATH[:LINE]', help=tr('review.help.at'))
    ap.add_argument('--full', action='store_true', help=tr('review.help.full'))
    ap.add_argument('--format', choices=('text', 'json'), default='text')
    ap.add_argument('--confirm', metavar='TOKEN', help=tr('review.help.confirm'))
    ap.add_argument('--by', metavar='ACTOR', help=tr('review.help.by'))
    ap.add_argument('--reason', metavar='TEXT', help=tr('review.help.reason'))
    ap.add_argument('--prune', action='store_true', help=tr('review.help.prune'))
    return ap


def _path(value):
    if (not value or value.startswith('/') or '\\' in value or '\0' in value
            or re.match(r'^[A-Za-z]:', value)
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ReviewFailure('invalid-arguments', tr('review.arguments.path'))
    return value


def _arguments(args):
    if args.confirm is not None and not re.fullmatch('[0-9a-f]{64}', args.confirm):
        raise ReviewFailure('invalid-arguments', tr('review.arguments.token'))
    if args.prune:
        if any((args.target, args.at, args.full, args.by is not None, args.reason is not None)):
            raise ReviewFailure('invalid-arguments', tr('review.arguments.prune'))
        return
    if args.target is None or args.at is None:
        raise ReviewFailure('invalid-arguments', tr('review.arguments.missing'))
    if args.target.count('#') != 1 or '::' in args.target:
        raise ReviewFailure('invalid-arguments', tr('review.arguments.target'))
    path, anchor = args.target.split('#')
    _path(path)
    if not anchor or '\0' in anchor or any(c.isspace() for c in anchor):
        raise ReviewFailure('invalid-arguments', tr('review.arguments.anchor'))
    args.source_path, args.source_line = args.at, None
    if ':' in args.at:
        args.source_path, suffix = args.at.rsplit(':', 1)
        if not suffix.isascii() or not suffix.isdigit() or int(suffix) < 1:
            raise ReviewFailure('invalid-arguments', tr('review.arguments.line'))
        args.source_line = int(suffix)
    _path(args.source_path)
    if args.confirm is None and (args.by is not None or args.reason is not None):
        raise ReviewFailure('invalid-arguments', tr('review.arguments.confirm'))
    if args.confirm is not None and (not args.by or not args.by.strip()
                                     or not args.reason or not args.reason.strip()):
        raise ReviewFailure('invalid-arguments', tr('review.arguments.confirm_details'))


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


# @trace docs/ru/review.md#confirm
def _read(path):
    """Отсутствие — отдельное состояние; замена во время чтения — отказ."""
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    data = path.read_bytes()
    try:
        after = path.stat()
    except FileNotFoundError:
        raise ReviewFailure('changed-preview', tr('review.read.changed') % path.name)
    if _stamp(before) != _stamp(after):
        raise ReviewFailure('changed-preview', tr('review.read.changed') % path.name)
    return data


def _digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _head(root):
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
        head = result.stdout.decode('ascii').strip()
        return head if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head) else None
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return None


def _candidate(pair):
    return {key: pair[key] for key in ('relation', 'source', 'target',
                                      'source_ranges', 'target_ranges')}


def _pair(pair):
    return {key: pair[key] for key in ('id', 'relation', 'source', 'target')}


# @trace docs/ru/review.md#pair
def _select(context, args):
    path, anchor = args.target.split('#')
    candidates = [p for p in context.pairs if p['source']['path'] == args.source_path
                  and p['target']['path'] == path and p['target']['anchor'] == anchor]
    if args.source_line is not None:
        candidates = [p for p in candidates if any(first <= args.source_line <= last
                                                   for first, last in p['source_ranges'])]
    if not candidates:
        raise ReviewFailure('no-candidate', tr('review.pair.missing'))
    if len(candidates) > 1:
        raise ReviewFailure('ambiguous', tr('review.pair.line'),
                            candidates=[_candidate(p) for p in candidates])
    selected = candidates[0]
    identical = [p for p in context.pairs if p['id'] == selected['id']]
    if len(identical) > 1:
        raise ReviewFailure('ambiguous', tr('review.pair.identical'),
                            candidates=[_candidate(p) for p in identical])
    return selected


def _view(pair, side, full):
    lines = pair[side + '_lines']
    shown = lines if full else lines[:20]
    return {'ranges': pair[side + '_ranges'], 'lines': shown, 'omitted': len(lines) - len(shown)}


# @trace docs/ru/review.md#worktree,docs/ru/review.md#confirm
def _prepare(root, args):
    try:
        config_bytes = _read(root / CONFIG_NAME)
        cfg = load_config(root, None)
    except (ValueError, OSError) as error:
        raise ConfigFailure([(CONFIG_NAME, tr('config.read.query') % error)])
    errors = validate_config(root, cfg)
    if errors:
        raise ConfigFailure(errors)
    try:
        registry_bytes = _read(root / REVIEWS_NAME)
    except OSError as error:
        raise ReviewError(tr('review.registry.unreadable') % error)
    head = _head(root)
    context = ReviewContext(Project(root, cfg))
    lifecycle = context.lifecycle() if args.prune else None
    # Сопоставляем прочитанные индексом тексты с устойчивым чтением тех же файлов.
    snapshots = {}
    for path, text in context.texts.items():
        raw = _read(root / path)
        if raw is None or raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n') != text:
            raise ReviewFailure('changed-preview', tr('review.read.region_changed') % path)
        snapshots[path] = _digest(raw)
    basis = {'head': head, 'config': cfg, 'config_bytes': _digest(config_bytes),
             'registry': _digest(registry_bytes), 'files': snapshots}
    if args.prune:
        remove, unchecked = lifecycle
        response = {'schema': 1, 'operation': 'prune', 'result': 'preview',
                    'file': REVIEWS_NAME, 'basis': 'worktree',
                    'remove': remove, 'unchecked': unchecked, 'token': None}
        # В план входят и отсутствующие/непроверяемые стороны, не только текущие пары.
        basis['plan'] = [remove, unchecked, [_pair(p) for p in context.pairs]]
        if remove:
            response['token'] = hashlib.sha256(canonical_json(['review-prune-v1', basis])).hexdigest()
    else:
        selected = _select(context, args)
        level = cfg.get('codes', {}).get('A4', CODE_LEVELS['A4'])
        if level == 'off':
            raise ReviewFailure('no-candidate', tr('review.pair.disabled'))
        history = GitBlame(root)
        numbers = [n for first, last in selected['target_ranges'] for n in range(first, last + 1)]
        doc_time = history.lines_time(selected['target']['path'], numbers)
        if not doc_time:
            raise ReviewFailure('unavailable', tr('review.pair.no_history'))
        code_time = history.stale_region_time(selected['source']['path'], selected['history_line'],
                                               selected['boundaries'], since=doc_time)
        if not code_time:
            raise ReviewFailure('no-candidate', tr('review.pair.no_staleness'))
        basis['pair'] = _pair(selected)
        # Другие файлы не влияют на выбор этой группы; тот же файл — влияет.
        basis['files'] = {p: snapshots[p] for p in
                          (selected['source']['path'], selected['target']['path'])}
        basis['candidates'] = [_pair(p) for p in context.pairs
                               if p['source']['path'] == selected['source']['path']]
        existing = context.existing(selected)
        response = {'schema': 1, 'operation': 'review', 'result': 'preview',
                    'pair': _pair(selected), 'code': 'A4', 'level': level,
                    'source_view': _view(selected, 'source', args.full),
                    'target_view': _view(selected, 'target', args.full),
                    'head': head, 'existing': existing['id'] if existing else None,
                    'token': hashlib.sha256(canonical_json(['review-preview-v1', basis])).hexdigest()}
    if (_read(root / CONFIG_NAME) != config_bytes or _head(root) != head
            or _read(root / REVIEWS_NAME) != registry_bytes
            or any(_digest(_read(root / p)) != digest for p, digest in snapshots.items())
            or any((root / p).exists() for p in getattr(context, 'missing_paths', set()))):
        raise ReviewFailure('changed-preview', tr('review.worktree.changed'))
    return response, context, registry_bytes


# @trace docs/ru/review.md#confirm,docs/ru/review.md#move
@contextmanager
def registry_lock(root, timeout=10):
    """Один писатель реестра; mkdir атомарен и на POSIX, и на Windows."""
    path = root / (REVIEWS_NAME + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise OSError(tr('review.registry.locked') % path.name)
            time.sleep(.05)
    try:
        yield
    finally:
        path.rmdir()


def _write(root, registry, expected):
    path = root / REVIEWS_NAME
    if _read(path) != expected:
        raise ReviewFailure('changed-preview', tr('review.registry.changed'))
    data = serialize_reviews(registry)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.reviews-', delete=False) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None:
            os.chmod(temporary, path.stat().st_mode & 0o777)
        if _read(path) != expected:
            raise ReviewFailure('changed-preview', tr('review.registry.changed_before_write'))
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


# @trace docs/ru/review.md#confirm,docs/ru/review.md#prune
def _confirm(root, args, preview, context, expected):
    if preview['token'] != args.confirm:
        raise ReviewFailure('changed-preview', tr('review.confirm.changed'))
    with registry_lock(root):
        fresh, context, raw = _prepare(root, args)
        if fresh['token'] != args.confirm or raw != expected:
            raise ReviewFailure('changed-preview', tr('review.confirm.changed_before_write'))
        registry = context.registry
        if args.prune:
            removed = {item['id'] for item in fresh['remove']}
            entries = registry['entries'] if registry else []
            kept = [entry for entry in entries if entry['id'] not in removed]
            if removed:
                _write(root, dict(registry, entries=kept), raw)
            return {'schema': 1, 'operation': 'prune', 'result': 'written' if removed else 'unchanged',
                    'file': REVIEWS_NAME, 'removed': len(removed), 'remaining': len(kept),
                    'unchecked': len(fresh['unchecked'])}
        existing = next((e for e in (registry or {}).get('entries', [])
                         if e['id'] == fresh['pair']['id']), None)
        if existing:
            return {'schema': 1, 'operation': 'review', 'result': 'unchanged',
                    'file': REVIEWS_NAME, 'entry': existing}
        entry = dict(fresh['pair'], reviewer=args.by.strip(), reason=args.reason.strip(),
                     reviewed_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                     head=fresh['head'])
        if registry is None:
            registry = {'schema': 1, 'algorithm': 'sha256-lines-v1', 'entries': []}
        _write(root, dict(registry, entries=[*registry['entries'], entry]), raw)
        return {'schema': 1, 'operation': 'review', 'result': 'written', 'file': REVIEWS_NAME, 'entry': entry}


# @trace docs/ru/review.md#json
def render_text(response):
    if 'error' in response:
        lines = ['%s: %s' % (response['error'], response['message'])]
        lines.extend('%s %s → %s#%s' % (p['source']['path'], p['source_ranges'],
                      p['target']['path'], p['target']['anchor']) for p in response.get('candidates', []))
        return '\n'.join(lines)
    if response['operation'] == 'prune':
        if response['result'] != 'preview':
            return tr('review.render.prune.result') % (
                response['result'], response['removed'], response['remaining'], response['unchecked'])
        lines = [tr('review.render.prune.preview') % response['file']]
        for kind, label in (('remove', tr('review.render.prune.remove')), ('unchecked', tr('review.render.prune.unchecked'))):
            for item in response[kind]:
                lines.append('%s %s: %s → %s#%s (%s)' % (label, item['id'], item['source']['path'],
                             item['target']['path'], item['target']['anchor'], item['reason']))
        lines.append('token: %s' % response['token'])
        return '\n'.join(lines)
    if response['result'] != 'preview':
        return '%s: %s (%s)' % (response['result'], response['entry']['id'], response['file'])
    lines = ['%s %s; %s' % (response['code'], response['level'], response['pair']['relation'])]
    for side in ('source', 'target'):
        desc, view = response['pair'][side], response[side + '_view']
        lines.extend(['%s: %s%s %s' % (side, desc['path'], '#' + desc['anchor'] if 'anchor' in desc else '',
                                      view['ranges']), 'sha256: ' + desc['sha256'], ''.join(view['lines'])])
        if view['omitted']:
            lines.append(tr('review.render.omitted') % view['omitted'])
    lines.extend(['HEAD: %s' % response['head'], 'existing: %s' % response['existing'],
                  'token: ' + response['token']])
    return '\n'.join(lines)


@cli_output
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fmt = output_format(argv)
    operation = 'prune' if '--prune' in argv else 'review'
    args = None
    try:
        args = parser().parse_args(argv)
        _arguments(args)
        root = Path.cwd().resolve()
        response, context, raw = _prepare(root, args)
        if args.confirm is not None:
            response = _confirm(root, args, response, context, raw)
    except ConfigFailure as error:
        _config_errors(error.errors, fmt)
        return 2
    except ReviewError as error:
        _config_errors([(REVIEWS_NAME, str(error))], fmt)
        return 2
    except ReviewFailure as error:
        if args and args.confirm and error.error in ('no-candidate', 'ambiguous', 'unavailable'):
            error = ReviewFailure('changed-preview', tr('review.confirm.pair_changed'))
        response = {'schema': 1, 'operation': operation, 'error': error.error,
                    'message': str(error), **error.details}
    except (OSError, UnicodeError) as error:
        response = {'schema': 1, 'operation': operation,
                    'error': 'write-failed' if args and args.confirm else 'unavailable', 'message': str(error)}
    print(json.dumps(response, ensure_ascii=False) if fmt == 'json' else render_text(response))
    return 2 if 'error' in response else 0


if __name__ == '__main__':
    sys.exit(main())
