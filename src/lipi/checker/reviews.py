"""Точные состояния местных пар A4 и строгий реестр просмотра."""

import datetime
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from lipi.i18n import tr
from .conventions import MAX_CODE_FILE
from .model import anchor_region, has_symlink, is_within
from .targets import target_excluded

REVIEWS_NAME = '.agents/lipi/reviews.json'
ALGORITHM = 'sha256-lines-v1'
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_OID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z', re.ASCII)


class ReviewError(ValueError):
    """Повреждённый реестр: C1, без пропуска отдельных записей."""


# @trace docs/ru/review.md#state
def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def raw_lines(text):
    """Нормализованные физические строки с точным признаком последнего LF."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    parts = text.split('\n')
    return [part + '\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def fingerprint(kind, lines):
    return hashlib.sha256(canonical_json([ALGORITHM, kind, list(lines)])).hexdigest()


def pair_id(relation, source, target):
    return hashlib.sha256(canonical_json(['review-pair-v1', relation, source, target])).hexdigest()


def _fields(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ReviewError(tr('checker.reviews.unexpected_fields') % (where, ', '.join(fields)))


def _string(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(tr('checker.reviews.empty_string') % where)
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ReviewError(tr('checker.reviews.unpaired_surrogate') % where) from error


def _descriptor(value, kind):
    fields = ['kind', 'path', 'sha256'] + (['anchor'] if kind == 'anchor' else [])
    _fields(value, fields, kind)
    if value['kind'] != kind:
        raise ReviewError(tr('checker.reviews.wrong_kind') % kind)
    path = value['path']
    _string(path, 'path')
    if (path.startswith('/') or PureWindowsPath(path).drive or '\\' in path
            or '\0' in path or any(part in ('', '.', '..') for part in path.split('/'))):
        raise ReviewError(tr('checker.reviews.invalid_path'))
    digest = value['sha256']
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ReviewError(tr('checker.reviews.invalid_digest'))
    if kind == 'anchor':
        _string(value['anchor'], 'anchor')
        if '#' in value['anchor'] or '\0' in value['anchor']:
            raise ReviewError(tr('checker.reviews.invalid_anchor'))


# @trace docs/ru/review.md#state
def validate_reviews(data):
    """Проверяет весь объект; возвращает его без нормализации пользовательских полей."""
    _fields(data, ['schema', 'algorithm', 'entries'], tr('checker.reviews.registry'))
    if type(data['schema']) is not int or data['schema'] != 1:
        raise ReviewError(tr('checker.reviews.invalid_schema'))
    if data['algorithm'] != ALGORITHM:
        raise ReviewError(tr('checker.reviews.invalid_algorithm') % ALGORITHM)
    if not isinstance(data['entries'], list):
        raise ReviewError(tr('checker.reviews.invalid_entries'))
    ids = set()
    for entry in data['entries']:
        _fields(entry, ['id', 'relation', 'source', 'target', 'reviewer',
                        'reviewed_at', 'reason', 'head'], tr('checker.reviews.entry'))
        if entry['relation'] != 'trace':
            raise ReviewError(tr('checker.reviews.invalid_relation'))
        _descriptor(entry['source'], 'trace')
        _descriptor(entry['target'], 'anchor')
        wanted = pair_id(entry['relation'], entry['source'], entry['target'])
        if not isinstance(entry['id'], str) or entry['id'] != wanted:
            raise ReviewError(tr('checker.reviews.invalid_id'))
        if wanted in ids:
            raise ReviewError(tr('checker.reviews.repeated_id') % wanted)
        ids.add(wanted)
        _string(entry['reviewer'], 'reviewer')
        _string(entry['reason'], 'reason')
        date = entry['reviewed_at']
        if not isinstance(date, str) or not _DATE.fullmatch(date):
            raise ReviewError(tr('checker.reviews.timestamp_format'))
        try:
            datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError as error:
            raise ReviewError(tr('checker.reviews.invalid_timestamp')) from error
        head = entry['head']
        if head is not None and (not isinstance(head, str) or not _OID.fullmatch(head)):
            raise ReviewError(tr('checker.reviews.invalid_head'))
    return data


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReviewError(tr('checker.reviews.duplicate_json_key') % key)
        result[key] = value
    return result


def load_reviews(root):
    path = Path(root) / REVIEWS_NAME
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        if path.is_symlink():
            raise ReviewError(tr('checker.reviews.unreadable_registry')) from error
        return None
    except OSError as error:
        raise ReviewError(tr('checker.reviews.unreadable_registry_detail') % error) from error
    return parse_reviews(raw)


def parse_reviews(raw):
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ReviewError(tr('checker.reviews.invalid_json_value') % value)))
        return validate_reviews(data)
    except (ValueError, RecursionError) as error:
        raise ReviewError(str(error)) from error


def serialize_reviews(data):
    validate_reviews(data)
    data = dict(data, entries=sorted(data['entries'], key=lambda entry: entry['id']))
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def ranges(numbers):
    result = []
    for num in numbers:
        if result and result[-1][1] == num - 1:
            result[-1][1] = num
        else:
            result.append([num, num])
    return result


# @trace docs/ru/review.md#pair,docs/ru/review.md#state
class ReviewContext:
    """Структура текущего дерева; история не читается и A4 не подразумевается."""

    def __init__(self, pr, index=None):
        from ..slice_index import SliceIndex
        self.pr = pr
        self.registry = load_reviews(pr.root)
        self.index = index if index is not None else SliceIndex(pr, links=False)
        self.texts = {}
        self.missing_paths = set()
        self.pairs = []
        self._pairs = {}
        self._places = {}
        self._relations = {}
        self._availability = {}
        self._entries = {entry['id']: entry for entry in self.registry['entries']} if self.registry else {}
        self._rows = {}
        targets = {}
        for place in self.index.places:
            path = place['path']
            if path not in self._rows:
                text = getattr(self.index, 'code_texts', {}).get(path)
                if text is None:
                    try:
                        selected = pr.file_path(path)
                        if selected is None:
                            continue
                        text = selected.read_text(encoding='utf-8')
                    except (OSError, UnicodeError):
                        continue
                self.texts[path] = text
                self._rows[path] = raw_lines(text)
            rows = self._rows[path]
            boundaries = self.index.boundaries.get(path, [])
            start = place['line']
            stop = min((num - 1 for num in boundaries if num > start), default=len(rows))
            lines = rows[start - 1:stop]
            source = {'kind': 'trace', 'path': path, 'sha256': fingerprint('trace', lines)}
            for aid in place['targets']:
                if (path, start, aid) in self._places:
                    continue  # Два имени одного физического файла не создают две группы.
                node = self.index.nodes.get(aid)
                if not node or node['kind'] != 'section' or aid in pr.mark_external:
                    continue
                if aid not in targets:
                    page = node['page']
                    target_path = pr.rel(page.path)
                    self.texts[target_path] = page.text
                    if target_path not in self._rows:
                        self._rows[target_path] = raw_lines(page.text)
                    target_rows = self._rows[target_path]
                    numbers = list(anchor_region(page, node['line']))
                    if not numbers or any(num > len(target_rows) for num in numbers):
                        continue
                    selected = [target_rows[num - 1] for num in numbers]
                    target = {'kind': 'anchor', 'path': target_path,
                              'anchor': aid.partition('#')[2], 'sha256': fingerprint('anchor', selected)}
                    targets[aid] = (target, numbers, selected)
                target, numbers, selected = targets[aid]
                pair = {'id': pair_id('trace', source, target), 'relation': 'trace',
                        'source': source, 'target': target,
                        'source_ranges': [[start, stop]], 'source_lines': lines,
                        'target_ranges': ranges(numbers), 'target_lines': selected,
                        'target_numbers': numbers, 'history_line': place.get('history_line', start),
                        'boundaries': boundaries, 'place': place, 'target_id': aid,
                        'target_line': node['line']}
                self.pairs.append(pair)
                self._pairs.setdefault(pair['id'], []).append(pair)
                self._places[(path, start, aid)] = pair
                self._relations.setdefault((path, aid), []).append(pair)

    def matching(self, entry):
        """Совпадения состояния; несколько физически разных групп запрещают отметку."""
        key = pair_id(entry['relation'], entry['source'], entry['target'])
        return self._pairs.get(key, [])

    def existing(self, pair):
        return self._entries.get(pair['id']) if len(self.matching(pair)) == 1 else None

    def acknowledges(self, pair):
        return self.existing(pair) is not None

    def pair_for(self, path, line, target):
        return self._places.get((path, line, target))

    def _available(self, descriptor):
        key = descriptor['kind'], descriptor['path']
        if key not in self._availability:
            self._availability[key] = self._read_available(descriptor)
        return self._availability[key]

    def _read_available(self, descriptor):
        pr = self.pr
        path = pr.root / descriptor['path']
        source = descriptor['kind'] == 'trace'
        try:
            excluded = (pr.skip_dirs.excludes(path) if source else target_excluded(pr, path))
            if source:
                excluded = excluded or path.suffix.lower() == '.md' or any(
                    base != pr.root and is_within(path, base)
                    for base in (pr.docs, pr.wf, pr.decisions) if base)
            if excluded:
                return 'unchecked', 'excluded', None
            real = pr.file_path(path)
            if real is None:
                if not has_symlink(path.parent, pr.root):
                    path.lstat()  # Доказать отсутствие без чтения исключённого файла.
                return 'unchecked', 'excluded', None
            if not is_within(real, pr.root) or (
                    pr.skip_dirs.excludes(real) if source else target_excluded(pr, real)):
                return 'unchecked', 'excluded', None
            status = real.stat()
            if not real.is_file():
                return 'unchecked', 'unreadable', None
            if source and status.st_size > MAX_CODE_FILE:
                return 'unchecked', 'excluded', None
            text = real.read_text(encoding='utf-8')
            return None, None, text
        except FileNotFoundError:
            if path.is_symlink():
                return 'unchecked', 'unreadable', None
            self.missing_paths.add(descriptor['path'])
            return 'obsolete', 'missing-source' if source else 'missing-target', None
        except (OSError, UnicodeError, RuntimeError, ValueError):
            return 'unchecked', 'unreadable', None

    # @trace docs/ru/review.md#prune
    def classify(self, entry):
        """Удаление требует доказательства; ошибки и исключения сохраняют запись."""
        available = [self._available(entry[side]) for side in ('source', 'target')]
        for side, (_, _, text) in zip(('source', 'target'), available):
            if text is not None:
                path = entry[side]['path']
                if path in self.texts and self.texts[path] != text:
                    return 'unchecked', 'unreadable'
                self.texts[path] = text
        for state, reason, _ in available:
            if state == 'unchecked':
                return state, reason
        for state, reason, _ in available:
            if state:
                return state, reason
        source_text, target_text = available[0][2], available[1][2]
        target_path = self.pr.root / entry['target']['path']
        page = self.pr.page(target_path)
        if page is None or page.text != target_text:
            return 'unchecked', 'unreadable'
        anchor = entry['target']['anchor']
        if any(aid == anchor for _, aid in page.dup):
            return 'unchecked', 'ambiguous'
        if anchor not in page.anchors:
            return 'obsolete', 'missing-target'
        source_path = entry['source']['path']
        if source_path in self.texts and source_text != self.texts[source_path]:
            return 'unchecked', 'unreadable'
        matches = self.matching(entry)
        if len(matches) > 1:
            return 'unchecked', 'ambiguous'
        if matches:
            return 'current', None
        target_id = entry['target']['path'] + '#' + anchor
        candidates = self._relations.get((source_path, target_id), [])
        if sum(pair['source'] == entry['source'] for pair in candidates) > 1:
            return 'unchecked', 'ambiguous'
        if candidates:
            return 'obsolete', 'changed'
        # A readable file absent from a partial/custom index is not proof of removal.
        from .marks import physical_lines, trace_groups
        from .targets import resolve_mark
        groups = trace_groups(physical_lines(source_text), lambda token: resolve_mark(self.pr, token)[0])
        if any(target_id in group['targets'] for group in groups):
            return 'unchecked', 'excluded'
        return 'obsolete', 'missing-relation'

    def lifecycle(self):
        remove, unchecked = [], []
        for entry in self.registry['entries'] if self.registry else []:
            state, reason = self.classify(entry)
            if state == 'current':
                continue
            item = {key: entry[key] for key in ('id', 'source', 'target')}
            item['reason'] = reason
            (remove if state == 'obsolete' else unchecked).append(item)
        return sorted(remove, key=lambda item: item['id']), sorted(unchecked, key=lambda item: item['id'])
