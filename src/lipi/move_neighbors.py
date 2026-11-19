"""Потребители переносимой страницы в прямых подключениях: только чтение."""

import fnmatch
from urllib.parse import unquote

from .i18n import plural_form, tr
from .checker.conventions import CODE_EXT, MAX_CODE_FILE
from .move_links import trace_targets


# @trace docs/ru/move.md#links
def neighbor_notices(pr, moves):
    notices = []
    for name, connection in pr.cfg.get('repos', {}).items():
        if not {'code', 'tests'}.intersection(connection['read']):
            continue
        source = pr.sources.get(name)
        if source.unavailable_reason or not source.has_config:
            notices.append(tr('move.neighbor.unchecked') % (
                name, source.unavailable_reason or tr('move.neighbor.no_config')))
            continue
        aliases = {alias for alias in source.cfg.get('repos', {})
                   if source.points_to_local(alias)}
        if not aliases:
            continue
        counts, unread = _count(source, moves, pr, aliases)
        if unread:
            notices.append(tr('move.neighbor.partial') % (name, '; '.join(unread)))
        for old, count in sorted(counts.items()):
            page = (tr('move.neighbor.this_page') if len(moves) == 1 else
                    old.relative_to(pr.root).as_posix())
            form = plural_form(count)
            notices.append(tr('move.neighbor.marks.' + form) % (name, count, page))
    return notices


def _count(source, moves, owner, aliases):
    """Один обход соседа; для каждой цели строка считается один раз."""
    pr, found, unread = source.project, {}, []
    extensions = {'.' + ext for ext in CODE_EXT.split('|')}
    skip_paths = {p for p in (pr.docs, pr.wf, pr.decisions) if p and p != pr.root}
    for path in pr.walk_files(skip=skip_paths, onerror=lambda e: unread.append(str(e))):
        if path.is_symlink() or path.suffix.lower() not in extensions:
            continue
        path = source.resolve_path(path)
        if path is None:
            continue
        rel = pr.rel(path)
        layer = next((layer for pattern, layer in pr.cfg.get('layers', {}).items()
                      if fnmatch.fnmatchcase(rel, pattern)), '')
        is_test = layer == 'tests' or any(fnmatch.fnmatchcase(path.name, pattern)
                                         for pattern in pr.cfg.get('tests', []))
        if ('tests' if is_test else 'code') not in source.read:
            continue
        try:
            if path.stat().st_size > MAX_CODE_FILE:
                unread.append(tr('move.neighbor.read_limit') % rel)
                continue
            data = path.read_bytes()
            if b'@trace' not in data:
                continue
            text = data.decode('utf-8')
        except (OSError, UnicodeError) as error:
            unread.append('%s: %s' % (rel, error))
            continue
        previous_offset, line = 0, 1
        for offset, token in trace_targets(text, path):
            line += text.count('\n', previous_offset, offset)
            previous_offset = offset
            alias, sep, target = token.partition('::')
            if not sep or alias not in aliases or '::' in target:
                continue
            part = unquote(target.partition('#')[0])
            if not part or part.startswith('/'):
                continue
            target_path = owner.file_path(part)
            if target_path in moves:
                found.setdefault(target_path, set()).add((rel, line))
    return {path: len(rows) for path, rows in found.items()}, unread
