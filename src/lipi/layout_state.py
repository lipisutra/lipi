"""Доказуемый перенос ключей базовой линии в общем плане init."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .checker.config import check_baseline
from .i18n import tr
from .checker.conventions import BASE_NAME
from .move_links import _address
from .move_reviews import TransferError, _controlled


RELATIVE_SUBJECTS = frozenset({'D1', 'W6', 'W9', 'D7', 'D5'})
ROOTED_SUBJECTS = frozenset({'T1', 'D6'})


class BaselineTransferError(ValueError):
    """Ключ долга нельзя безопасно перенести; исходные байты не изменены."""


def _safe_registry(path, root):
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise BaselineTransferError(tr('layout_state.registry_symlink') % part)
    if path.exists() and not path.is_file():
        raise BaselineTransferError(tr('layout_state.registry_not_file') % path)


def _key(entry):
    return entry['code'], entry['file'], entry['subject']


# @trace docs/ru/commands.md#baseline,ADR-020
def transfer_baseline(root, moves, changes):
    """Вернуть (прежние байты, новые байты, пояснения), ничего не записывая.

    Содержание находок заново не собирается. Изменяем только file и адресный
    subject, подтверждённый AddressReceipt общего адресного прохода. changes
    должны предшествовать добавлению дат закрытия и прочим правкам init.
    """
    root = Path(root).resolve()
    path = root / BASE_NAME
    _safe_registry(path, root)
    if not os.path.lexists(path):
        return None, None, []
    try:
        before = path.read_bytes()
        problems = check_baseline(root)
        if problems:
            raise BaselineTransferError(tr('layout_state.invalid_baseline') % '; '.join(
                '%s: %s' % problem for problem in problems))
        registry = json.loads(before.decode('utf-8'))
        if path.read_bytes() != before:
            raise BaselineTransferError(tr('layout_state.registry_changed_while_reading'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineTransferError(tr('layout_state.registry_unreadable') % error) from error

    by_path = {}
    for change in changes:
        if change.path in by_path:
            raise BaselineTransferError(tr('layout_state.duplicate_path') % change.path)
        by_path[change.path] = change
    checked = set()

    def proof(source):
        change = by_path.get(source)
        if change is None:
            raise BaselineTransferError(tr('layout_state.missing_path_change') % source)
        if source not in checked:
            try:
                _safe_registry(source, root)
                _controlled(change, moves, root)
                if source.read_bytes() != change.before:
                    raise BaselineTransferError(tr('layout_state.file_changed') % source)
            except (OSError, UnicodeError, TransferError) as error:
                raise BaselineTransferError(tr('layout_state.unverified_transfer') % (source, error)) from error
            checked.add(source)
        return change

    entries, notices, destinations = [], [], {}
    for entry in registry['entries']:
        updated = dict(entry)
        source = root / entry['file']
        destination = moves.get(source, source)
        if destination != source:
            updated['file'] = destination.relative_to(root).as_posix()
        code, subject = entry['code'], entry['subject']
        if code in RELATIVE_SUBJECTS | ROOTED_SUBJECTS:
            rooted = code in ROOTED_SUBJECTS
            expected = _address(subject, base=root if rooted else source.parent,
                                after_base=root if rooted else destination.parent,
                                moves=moves, root=root)
            if expected != subject:
                change = proof(source)
                candidates = {edit.after for edit in change.edits if edit.before == subject}
                if candidates != {expected}:
                    raise BaselineTransferError(
                        tr('layout_state.unverified_subject') %
                        (code, entry['file'], subject))
                updated['subject'] = expected
        old_key, new_key = _key(entry), _key(updated)
        if new_key in destinations and destinations[new_key] != old_key:
            raise BaselineTransferError(tr('layout_state.key_collision') % new_key)
        destinations[new_key] = old_key
        entries.append(updated)
        if updated != entry:
            notices.append(tr('layout_state.transfer_notice') % (
                code, entry['file'], subject, updated['file'], updated['subject'], entry['count']))
    if path.read_bytes() != before:
        raise BaselineTransferError(tr('layout_state.registry_changed_while_planning'))
    if not notices:
        return before, before, []
    after = json.dumps(dict(registry, entries=entries), ensure_ascii=False, indent=2,
                       sort_keys=True).encode('utf-8') + b'\n'
    return before, after, notices
