"""Доказуемый перенос отметок вместе с адресными заменами общего плана."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from .i18n import tr
from .checker.model import Project
from .checker.reviews import (REVIEWS_NAME, ReviewContext, fingerprint,
                             load_reviews, pair_id, raw_lines, serialize_reviews)


class TransferError(ValueError):
    """Перенос не доказан; исходный реестр может быть корректным."""


@dataclass(frozen=True)
class AddressReceipt:
    """Неизменяемый результат единственного разбора адресов в планировщике."""
    root: Path
    path: Path
    before: bytes
    after: bytes
    moves: frozenset
    edits: tuple


def _lines(data):
    return raw_lines(data.decode('utf-8'))


def _selected(data, ranges):
    rows = _lines(data)
    return [row for first, last in ranges for row in rows[first - 1:last]]


def _controlled(change, moves, root):
    """План разрешает только объявленные замены адресов, без новых строк."""
    text = change.before.decode('utf-8')
    receipt = change.address_receipt
    if (receipt is None or receipt.root != root or receipt.path != change.path or
            receipt.before != change.before or receipt.after != change.after or
            receipt.moves != frozenset(moves.items()) or receipt.edits != tuple(change.edits)):
        raise TransferError(tr('move.review.address_only'))
    end = 0
    for edit in change.edits:
        if (edit.start < end or text[edit.start:edit.end] != edit.before
                or any(char in edit.before + edit.after for char in '\r\n')):
            raise TransferError(tr('move.review.cannot_verify_address'))
        end = edit.end
    for edit in reversed(change.edits):
        text = text[:edit.start] + edit.after + text[edit.end:]
    if text.encode('utf-8') != change.after:
        raise TransferError(tr('move.review.address_only'))


@dataclass
class ReviewTransfer:
    before: bytes | None
    after: bytes | None
    files: dict
    entries: list
    notices: list

    def validate(self, project):
        """CAS всех прочитанных сторон и повторная проверка однозначности."""
        path = project.root / REVIEWS_NAME
        current = path.read_bytes() if path.exists() else None
        if current != self.before:
            raise TransferError(tr('move.review.registry_changed'))
        for path, data in self.files.items():
            if path.read_bytes() != data:
                raise TransferError(tr('move.review.region_changed') % path)
        if self.entries:
            context = ReviewContext(project)
            for entry in self.entries:
                if len(context.matching(entry)) != 1:
                    raise TransferError(tr('move.review.region_ambiguous') % entry['id'])


# @trace docs/ru/review.md#move,ADR-019
def prepare_transfer(project, moves, changes):
    """Общий участник переноса: без blame, записи и нового просмотра.

    moves и changes описывают только переносы и адресные замены. Такой же
    участник может использовать перевод раскладки, до прочих правок init.
    """
    root = project.root
    path = root / REVIEWS_NAME
    registry = load_reviews(root)
    before = path.read_bytes() if registry is not None else None
    result = ReviewTransfer(before, before, {}, [], [])
    if registry is None:
        return result
    context = ReviewContext(project)
    if context.registry != registry:
        raise TransferError(tr('move.review.registry_changed_during'))
    by_path = {change.path: change for change in changes}
    affected = []
    for entry in registry['entries']:
        status, reason = context.classify(entry)
        if status != 'current':
            label = tr('move.review.obsolete') if status == 'obsolete' else tr('move.review.unchecked')
            result.notices.append(tr('move.review.kept') %
                                  (label, entry['id'], reason))
            continue
        if not any(root / entry[side]['path'] in by_path or
                   root / entry[side]['path'] in moves for side in ('source', 'target')):
            continue
        matches = context.matching(entry)
        if len(matches) != 1:
            raise TransferError(tr('move.review.mark_ambiguous') % entry['id'])
        affected.append((entry, matches[0]))
        result.entries.append(entry)
        for side in ('source', 'target'):
            filename = root / entry[side]['path']
            if any(part.is_symlink() for part in (filename, *filename.parents) if root in part.parents):
                raise TransferError(tr('move.review.symlink') % filename)
            data = filename.read_bytes()
            change = by_path.get(filename)
            if change:
                _controlled(change, moves, root)
                if data != change.before:
                    raise TransferError(tr('move.review.region_changed_during') % filename)
            if _selected(data, matches[0][side + '_ranges']) != matches[0][side + '_lines']:
                raise TransferError(tr('move.review.region_changed_read') % filename)
            result.files[filename] = data
    if not affected:
        result.validate(project)
        return result
    replacements = {}
    with tempfile.TemporaryDirectory(prefix='lipi-review-move-') as directory:
        projected_root = Path(directory).resolve()
        for filename, data in result.files.items():
            destination = projected_root / moves.get(filename, filename).relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(by_path[filename].after if filename in by_path else data)
        projected = ReviewContext(Project(projected_root, project.cfg))
        for entry, old_pair in affected:
            updated = dict(entry)
            expected = {}
            for side in ('source', 'target'):
                descriptor = dict(entry[side])
                filename = root / descriptor['path']
                descriptor['path'] = moves.get(filename, filename).relative_to(root).as_posix()
                data = by_path[filename].after if filename in by_path else result.files[filename]
                expected[side] = _selected(data, old_pair[side + '_ranges'])
                descriptor['sha256'] = fingerprint(descriptor['kind'], expected[side])
                updated[side] = descriptor
            updated['id'] = pair_id(updated['relation'], updated['source'], updated['target'])
            matches = projected.matching(updated)
            if (len(matches) != 1 or
                    matches[0]['boundaries'] != old_pair['boundaries'] or
                    matches[0]['history_line'] != old_pair['history_line'] or any(
                    matches[0][side + '_ranges'] != old_pair[side + '_ranges'] or
                    matches[0][side + '_lines'] != expected[side]
                    for side in ('source', 'target'))):
                raise TransferError(tr('move.review.cannot_verify_region') % entry['id'])
            if updated != entry:
                replacements[entry['id']] = updated
                sides = ', '.join(side for side in ('source', 'target') if entry[side] != updated[side])
                result.notices.append(tr('move.review.transferred') % (
                    entry['id'], updated['id'], sides,
                    entry['source']['path'], updated['source']['path'],
                    entry['target']['path'], entry['target']['anchor'],
                    updated['target']['path'], updated['target']['anchor']))
    entries = [replacements.get(entry['id'], entry) for entry in registry['entries']]
    if len({entry['id'] for entry in entries}) != len(entries):
        raise TransferError(tr('move.review.collision'))
    if replacements:
        result.after = serialize_reviews(dict(registry, entries=entries))
    result.validate(project)
    return result
