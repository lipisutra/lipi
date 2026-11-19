"""Финальная проверка просмотров после адресных и прочих правок init."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from .checker.model import Project
from .checker.reviews import ReviewContext, fingerprint, pair_id, validate_reviews
from .i18n import tr
from .move_reviews import TransferError, _controlled, _selected


# @trace docs/ru/review.md#move,ADR-019,ADR-020
def validate_final_reviews(project, plan, changes):
    """Прежние отпечатки должны описывать итоговые области, включая сдвиг строк.

    Новый просмотр не создаётся: допустимые отпечатки берутся только из
    адресного плана, а добавление дат и прочие изменения проверяются против
    этих отпечатков через ReviewContext.matching. Исходные файлы не меняются.
    """
    transfer = plan.reviews
    if transfer is None or transfer.before is None:
        return
    root = project.root
    transfer.validate(project)
    original = ReviewContext(project)
    before = validate_reviews(json.loads(transfer.before.decode('utf-8')))
    if original.registry != before:
        raise TransferError(tr('layout_reviews.registry_changed'))
    after = validate_reviews(json.loads(transfer.after.decode('utf-8')))
    by_id = {entry['id']: entry for entry in after['entries']}
    changes = list(changes.values()) if isinstance(changes, dict) else list(changes)
    by_path = {change.path: change for change in changes}
    if len(by_path) != len(changes):
        raise TransferError(tr('layout_reviews.duplicate_path'))
    from .checker.reviews import REVIEWS_NAME
    registry_change = by_path.get(root / REVIEWS_NAME)
    if registry_change is not None and registry_change.after != transfer.after:
        raise TransferError(tr('layout_reviews.registry_mismatch'))
    files, affected, expected_ids = {}, [], set()

    def snapshot(path):
        if path not in files:
            for part in (path, *path.parents):
                if part == root:
                    break
                if part.is_symlink():
                    raise TransferError(tr('layout_reviews.region_symlink') % path)
            try:
                files[path] = path.read_bytes()
            except OSError as error:
                raise TransferError(tr('layout_reviews.region_unreadable') % path) from error
            change = by_path.get(path)
            if change is not None and change.before != files[path]:
                raise TransferError(tr('layout_reviews.region_changed_early') % path)
        return files[path]

    for entry in before['entries']:
        state, _ = original.classify(entry)
        if state != 'current':
            if by_id.get(entry['id']) != entry:
                raise TransferError(tr('layout_reviews.inactive_mark_changed') % entry['id'])
            expected_ids.add(entry['id'])
            continue
        touched = any(root / entry[side]['path'] in by_path or
                      root / entry[side]['path'] in plan.moves for side in ('source', 'target'))
        if not touched:
            if by_id.get(entry['id']) != entry:
                raise TransferError(tr('layout_reviews.unaffected_mark_changed') % entry['id'])
            expected_ids.add(entry['id'])
            continue
        pairs = original.matching(entry)
        if len(pairs) != 1:
            raise TransferError(tr('layout_reviews.ambiguous_mark') % entry['id'])
        pair = pairs[0]
        expected = dict(entry)
        for side in ('source', 'target'):
            descriptor = dict(entry[side])
            path = root / descriptor['path']
            data = snapshot(path)
            change = by_path.get(path)
            receipt = change.address_receipt if change is not None else None
            if receipt is not None:
                controlled = SimpleNamespace(path=path, before=receipt.before,
                                             after=receipt.after, edits=list(receipt.edits),
                                             address_receipt=receipt)
                _controlled(controlled, plan.moves, root)
                if receipt.before != data:
                    raise TransferError(tr('layout_reviews.original_bytes_changed') % path)
                data = receipt.after
            descriptor['path'] = plan.moves.get(path, path).relative_to(root).as_posix()
            descriptor['sha256'] = fingerprint(descriptor['kind'], _selected(data, pair[side + '_ranges']))
            expected[side] = descriptor
        expected['id'] = pair_id(expected['relation'], expected['source'], expected['target'])
        if by_id.get(expected['id']) != expected:
            raise TransferError(tr('layout_reviews.unverified_mark') % entry['id'])
        expected_ids.add(expected['id'])
        affected.append((entry, by_id[expected['id']]))
    if expected_ids != set(by_id):
        raise TransferError(tr('layout_reviews.new_mark'))
    if not affected:
        return

    with TemporaryDirectory(prefix='lipi-final-reviews-') as directory:
        projected_root = Path(directory).resolve()
        for path, data in files.items():
            change = by_path.get(path)
            data = change.after if change is not None else data
            if data is None:
                continue
            destination = projected_root / plan.moves.get(path, path).relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        projected = ReviewContext(Project(projected_root, project.cfg))
        for entry, expected in affected:
            if len(projected.matching(expected)) != 1:
                raise TransferError(tr('layout_reviews.region_changed_by_init') % entry['id'])
    for path, data in files.items():
        if path.read_bytes() != data:
            raise TransferError(tr('layout_reviews.region_changed') % path)
    # Эти стороны могут не участвовать в адресном переносе. Их CAS всё равно
    # обязателен перед применением всего плана, в том числе для untouched source.
    transfer.files.update(files)
    existing = {entry['id'] for entry in transfer.entries}
    transfer.entries.extend(entry for entry, _ in affected if entry['id'] not in existing)
