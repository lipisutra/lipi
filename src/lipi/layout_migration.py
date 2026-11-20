"""Применение каркаса и перенос плоских рабочих материалов по годам."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import subprocess

from .i18n import tr
from .checker.conventions import K_CLOSED
from .checker.model import Page
from .checker.workflow_layout import is_final, latest_closed_date, parse_date
from .legacy_format import historical_status


def _git(root, *args, missing=False):
    try:
        proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                              env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    except OSError as error:
        raise ValueError(tr('layout_migration.git_history') % error) from error
    if proc.returncode and not missing:
        raise ValueError(tr('layout_migration.git_history') % proc.stderr.decode('utf-8', 'replace').strip())
    return None if proc.returncode else proc.stdout


# @trace ADR-020
def infer_closed_date(top, path, prefix, created, updated, latest_date):
    """Дата последнего закрытия либо явный fallback; только для перевода."""
    path = Path(path).resolve()
    first, last = parse_date(str(created)), parse_date(str(latest_date))
    if first is None or last is None:
        raise ValueError(tr('layout_migration.invalid_date_bounds'))

    def result(value, origin):
        parsed = parse_date(value)
        if parsed is None or not first <= parsed <= last:
            raise ValueError(tr('layout_migration.closed_range') %
                             (value, first, last, origin))
        return value, origin

    if top is None:
        return result(updated, tr('layout_migration.updated_without_git'))
    top = Path(top).resolve()
    if not path.is_relative_to(top):
        raise ValueError(tr('layout_migration.outside_repository') % path)
    relative = path.relative_to(top).as_posix()
    if any(char in relative for char in '\0\n\x1e'):
        raise ValueError(tr('layout_migration.unsupported_git_path') % relative)
    head = _git(top, 'rev-parse', '--verify', 'HEAD', missing=True)
    if head is None:
        if _git(top, 'rev-list', '--all', '--count').strip() != b'0':
            raise ValueError(tr('layout_migration.unreadable_head'))
        return result(updated, tr('layout_migration.updated_without_file_history'))
    shallow_name = _git(top, 'rev-parse', '--git-path', 'shallow').decode().strip()
    shallow = Path(shallow_name)
    if not shallow.is_absolute():
        shallow = top / shallow
    boundaries = set(shallow.read_text().splitlines()) if shallow.is_file() else set()
    histories, pages, episodes = {}, {}, {}

    def records(revision, filename):
        key = revision, filename
        if key not in histories:
            history = _git(top, 'log', '--first-parent', '--full-history', '--follow',
                           '--format=%x1e%H%x00%cI%x00%P%x00', '--name-status', '-z',
                           revision, '--', filename)
            parsed = []
            for record in history.split(b'\x1e')[1:]:
                fields = record.split(b'\0')
                commit, stamp, parents = (value.decode('utf-8') for value in fields[:3])
                names = [field.lstrip(b'\n') for field in fields[3:] if field.lstrip(b'\n')]
                if not names:
                    continue
                # --follow даёт новый путь в коммите rename, далее — старые имена.
                parsed.append((commit, stamp, parents.split(), names[-1].decode('utf-8')))
            histories[key] = parsed
        return histories[key]

    def final_at(revision, filename):
        key = revision, filename
        if key not in pages:
            exists = _git(top, 'ls-tree', '-z', '--name-only', revision, '--', filename)
            if not exists:
                pages[key] = False
            else:
                text = _git(top, 'show', revision + ':' + filename).decode('utf-8')
                header = Page(top / filename, text).header()
                pages[key] = is_final(prefix, historical_status(header))
        return pages[key]

    def commit_date(stamp):
        try:
            value = datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if value.tzinfo is None:
                raise ValueError(tr('layout_migration.commit_timezone'))
            # Дата — сутки, записанные самим коммитом, без смены его зоны.
            return value.date().isoformat()
        except ValueError as error:
            raise ValueError(tr('layout_migration.commit_date') % stamp) from error

    def parent_path(parent, commit, filename):
        if _git(top, 'ls-tree', '-z', '--name-only', parent, '--', filename):
            return filename
        fields = _git(top, 'diff-tree', '--no-commit-id', '--name-status', '-r', '-M',
                      '-z', parent, commit).split(b'\0')
        pos, matches = 0, []
        while pos < len(fields) and fields[pos]:
            status = fields[pos].decode('ascii')
            before = fields[pos + 1].decode('utf-8')
            pos += 2
            if status.startswith(('R', 'C')):
                after = fields[pos].decode('utf-8')
                pos += 1
                if after == filename:
                    matches.append(before)
        if len(matches) > 1:
            raise ValueError(tr('layout_migration.ambiguous_merge_path') % filename)
        return matches[0] if matches else filename

    def episode(revision, filename):
        key = revision, filename
        if key in episodes:
            return episodes[key]
        if not final_at(revision, filename):
            episodes[key] = None
            return None
        candidate = None
        for commit, stamp, parents, historical_path in records(revision, filename):
            if not final_at(commit, historical_path):
                break
            if commit in boundaries:
                raise ValueError(tr('layout_migration.shallow_history') % filename)
            if len(parents) > 1:
                origins = {episode(parent, parent_path(parent, commit, historical_path))
                           for parent in parents}
                if len(origins) != 1:
                    raise ValueError(tr('layout_migration.ambiguous_merge_closure') % (commit, filename))
                inherited = origins.pop()
                candidate = inherited or (commit_date(stamp), commit)
                break
            candidate = commit_date(stamp), commit
        if candidate is None:
            raise ValueError(tr('layout_migration.unknown_closure_commit') % filename)
        episodes[key] = candidate
        return candidate

    revision = head.decode().strip()
    if not records(revision, relative):
        return result(updated, tr('layout_migration.updated_without_file_history'))
    candidate = episode(revision, relative)
    if candidate is None:
        raise ValueError(tr('layout_migration.no_git_closure') % relative)
    return result(candidate[0], 'Git ' + candidate[1])


_UNSET = object()


def _put(changes, path, data, *, mode=None, expected_before=_UNSET):
    from .move import FileChange, _stamp
    before = path.read_bytes() if path.is_file() else None
    if expected_before is not _UNSET and before != expected_before:
        raise ValueError(tr('layout_migration.changed_file') % path)
    if path in changes:
        if expected_before is not _UNSET and changes[path].before != expected_before:
            raise ValueError(tr('layout_migration.inconsistent_snapshots') % path)
        changes[path].after = data
        if mode is not None:
            changes[path].mode = mode
    else:
        if before != data or mode is not None:
            changes[path] = FileChange(path, before, data,
                                       _stamp(path) if before is not None else None, [], mode=mode)


def _closed_text(text, value):
    rows = text.splitlines(keepends=True)
    positions = [i for i, row in enumerate(rows) if row.startswith('- ') and ': ' in row]
    if not positions:
        raise ValueError(tr('layout_migration.header_missing'))
    position = positions[0]
    while position < len(rows) and (rows[position].startswith('- ') and ': ' in rows[position]
                                    or rows[position].startswith((' ', '\t')) and rows[position].strip()):
        position += 1
    newline = '\r\n' if rows[positions[0]].endswith('\r\n') else '\n'
    rows.insert(position, '- %s: %s%s' % (K_CLOSED, value, newline))
    return ''.join(rows)


# @trace ADR-020,docs/ru/workflow.md#upgrade
def prepare_layout(root, cfg, updates, *, hook=None, external_creates=()):
    """Полный план init: реальные файлы до записи и проекция конечных страниц.

    История нужна для восстановления дат закрытия при переносе по годам.
    Правила, lock, указатель, состояние и hook меняются в той же транзакции.
    """
    from .checker.config import load_config, validate_config
    from .checker.conventions import BASE_NAME, K_CREATED, K_UPDATED, K_STATUS, TYPES
    from .checker.model import Project, is_within
    from .checker.report import Report
    from .checker.workflow import scan_workflow
    from .checker.workflow_layout import discover_workflow, YEARLY
    from .checker.workflow_index import build_project_index, plan_index, read_index_files
    from .move import (MovePlan, archive_present, make_plan, _index_path, _clean_affected,
                       _git as move_git)
    from .move_reviews import prepare_transfer
    from .layout_state import transfer_baseline

    config_path = root / 'lipi.json'
    config_before = config_path.read_bytes() if config_path.is_file() else None
    cfg = dict(load_config(root, None), **cfg)
    errors = validate_config(root, cfg)
    if errors:
        raise ValueError('; '.join('%s: %s' % item for item in errors))
    project = Project(root, cfg)
    wf_name = cfg.get('workflow')
    if wf_name and project.wf is None:
        project.wf = (root / wf_name).resolve()
    if wf_name and not is_within((root / wf_name).resolve(), root):
        raise ValueError(tr('layout_migration.external_workflow'))
    entries, problems = discover_workflow(project)
    pairs, dates, notices, source_bytes = [], {}, [], {}
    seen = set()
    latest_date = latest_closed_date()
    git_root_bytes = _git(root, 'rev-parse', '--show-toplevel', missing=True)
    top = Path(os.fsdecode(git_root_bytes).strip()).resolve() if git_root_bytes else None
    for entry in entries:
        identity = (entry.prefix, int(entry.num))
        if identity in seen:
            raise ValueError(tr('layout_migration.ambiguous_number') % identity)
        seen.add(identity)
        try:
            source_bytes[entry.path] = entry.path.read_bytes()
            page = Page(entry.path, source_bytes[entry.path].decode('utf-8'))
        except (OSError, UnicodeError) as error:
            raise ValueError(tr('layout_migration.unreadable_document') % entry.path) from error
        project.pages[entry.path.resolve()] = page
        header = page.header()
        created = parse_date(header.get(K_CREATED))
        updated = parse_date(header.get(K_UPDATED))
        if created is None or updated is None or updated < created:
            raise ValueError(tr('layout_migration.invalid_header_dates') % entry.path)
        if entry.prefix in YEARLY and not entry.feedback:
            type_root = project.wf / TYPES[entry.prefix][0]
            if entry.year is None:
                if entry.container.parent != type_root:
                    raise ValueError(tr('layout_migration.ambiguous_layout') % entry.container)
                destination = type_root / str(created.year).zfill(4) / entry.container.name
                pairs.append((entry.container, destination))
            elif int(entry.year) != created.year:
                raise ValueError(tr('layout_migration.year_mismatch') % entry.path)
    allowed_flat = {path for path, _ in pairs}
    for problem in problems:
        if problem.code != 'W10' or problem.path not in allowed_flat:
            raise ValueError('%s: %s' % (problem.path, problem.message))
    if pairs and top is None:
        raise ValueError(tr('layout_migration.flat_without_git'))
    if pairs and top != root:
        raise ValueError(tr('layout_migration.requires_git_root'))
    for entry in entries:
        header = project.page(entry.path).header()
        closed = header.get(K_CLOSED)
        if closed:
            date = parse_date(closed)
            if date is None or not parse_date(header[K_CREATED]) <= date <= latest_date:
                raise ValueError(tr('layout_migration.invalid_closed') % entry.path)
        elif pairs and is_final(entry.prefix, header.get(K_STATUS, '').strip('* .').lower()):
            value, origin = infer_closed_date(top, entry.path, entry.prefix,
                                             header[K_CREATED], header[K_UPDATED], latest_date)
            dates[entry.path] = value
            notices.append(tr('layout_migration.closed_notice') % (project.rel(entry.path), value, origin))

    if pairs:
        plan = make_plan(root, pairs=pairs, config=cfg)
    else:
        index = _index_path(root) if top == root else None
        before = index.read_bytes() if index is not None and index.exists() else None
        if before is None:
            index = None
        reviews = prepare_transfer(project, {}, [])
        plan = MovePlan(root, {}, [], [], index, before, False, [], reviews, cfg)
    plan.external_creates = frozenset(external_creates)
    plan.notices.extend(notices)
    changes = {change.path: change for change in plan.changes}
    # Baseline uses the same receipts, before header/managed changes are added.
    baseline_before, baseline_after, baseline_notices = transfer_baseline(root, plan.moves, plan.changes)
    if baseline_before != baseline_after:
        _put(changes, root / BASE_NAME, baseline_after, expected_before=baseline_before)
    plan.guards = dict(source_bytes)
    plan.guards[root / BASE_NAME] = baseline_before
    plan.guards[config_path] = config_before
    plan.notices.extend(baseline_notices)
    for path, value in dates.items():
        data = changes[path].after if path in changes else source_bytes[path]
        _put(changes, path, _closed_text(data.decode('utf-8'), value).encode('utf-8'),
             expected_before=source_bytes[path])
    for path, text in updates:
        data = text.encode('utf-8')
        if os.linesep != '\n':
            data = data.replace(b'\n', os.linesep.encode())
        _put(changes, path, data)
    if hook is not None:
        path, data, mode = hook
        _put(changes, path, data, mode=mode)

    rep = Report()
    docs, _ = scan_workflow(project, rep)
    projected_docs = {}
    for identity, document in docs.items():
        path = document['page'].path
        data = changes[path].after if path in changes else source_bytes[path]
        projected = dict(document)
        projected['page'] = Page(plan.moves.get(path, path), data.decode('utf-8'))
        projected['header'] = projected['page'].header()
        projected['status'] = projected['header'].get(K_STATUS, '').strip('* .').lower()
        projected_docs[identity] = projected
    previous = read_index_files(project)
    index_files = build_project_index(project, projected_docs, previous=previous, latest_date=latest_date)
    index_plan = plan_index(project, index_files, previous=previous)
    for path, data in index_plan.changes.items():
        _put(changes, path, data, expected_before=index_plan.before[path])
    plan.changes = list(changes.values())
    from .layout_reviews import validate_final_reviews
    validate_final_reviews(project, plan, changes)
    from .move_transaction import _file_scope
    for change in plan.changes:
        _file_scope(plan, change.path)
    if pairs:
        tracked = {root / os.fsdecode(name) for name in
                   move_git(root, 'ls-files', '--cached', '-z').split(b'\0') if name}
        # New outputs are allowed; existing untracked files are user changes.
        _clean_affected(root, [change for change in plan.changes
                              if change.before is not None and '.git' not in change.path.relative_to(root).parts], tracked)
    if archive_present(project):
        plan.notices.append(tr('layout_migration.archive_excluded'))
    return plan


def initial_baseline(root):
    """Calculate the first baseline against the files and Git index just installed."""
    from .checker.commands import run_project_checks
    from .checker.config import load_config, validate_config
    from .checker.model import Project
    from .checker.report import Report, level_of_project
    from .checker.runner import check_project_content
    from .checker.state import baseline_counts, baseline_text

    cfg = load_config(root, None)
    errors = validate_config(root, cfg)
    if errors:
        raise ValueError("\n".join("%s: %s" % item for item in errors))
    project = Project(root, cfg)
    report = Report(level_of_project(cfg))
    if project.docs is not None or project.wf is not None:
        check_project_content(project, report, deployment_cfg=cfg)
    run_project_checks(project, report, False)
    return baseline_text(baseline_counts(report)).encode("utf-8")


def apply_layout(plan, *, create_baseline=False):
    from .checker.conventions import BASE_NAME
    from contextlib import nullcontext
    from .review import registry_lock
    from .move_transaction import apply_transaction
    with registry_lock(plan.root) if plan.reviews.before is not None else nullcontext():
        final_file = (plan.root / BASE_NAME, initial_baseline) if create_baseline else None
        apply_transaction(plan, final_file=final_file)
