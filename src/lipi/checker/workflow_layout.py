"""Единая раскладка рабочих документов; приложения не становятся работами."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import os
import re

from lipi.i18n import tr
from .conventions import (FINAL, HISTORY_DIR, RE_DATE, RE_DECISION_NAME,
                          RE_DOC_NAME, STATUSES, TYPES)
from .model import feedback_dir, has_symlink, is_within

YEAR = re.compile(r"^[0-9]{4}$")
YEARLY = frozenset(TYPES) - {'adr'}


def is_year_directory(path, prefix, project=None):
    """Год не путается с разрешённой папкой ADR с голым номером."""
    if not YEAR.fullmatch(path.name) or not path.is_dir():
        return False
    main = path / (path.name + '-readme.md')
    if project is not None:
        main = project.file_path(main)
    return prefix != 'adr' or main is None or main.is_symlink() or not main.is_file()


def parse_date(value):
    """Календарная ISO-дата либо None; компактная форма ISO не допускается."""
    if not isinstance(value, str) or not RE_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def latest_closed_date():
    """Верхняя граница Даты закрытия: календарная дата UTC плюс день."""
    return datetime.now(timezone.utc).date() + timedelta(days=1)


def is_final(prefix, status):
    return status in STATUSES.get(prefix, ()) and status in FINAL


def document_directory(pr, prefix, created, feedback=False):
    if feedback:
        return feedback_dir(pr.root)
    if prefix == 'adr':
        return pr.decisions
    parsed = parse_date(created)
    if parsed is None:
        raise ValueError(tr('checker.workflow_layout.invalid_created_date') % created)
    return pr.wf / TYPES[prefix][0] / ('%04d' % parsed.year)


@dataclass(frozen=True)
class WorkEntry:
    prefix: str
    num: str
    slug: str
    path: Path
    container: Path
    year: str | None
    feedback: bool = False


@dataclass(frozen=True)
class LayoutProblem:
    code: str
    path: Path
    message: str
    subject: str


def discover_workflow(pr):
    """Главные файлы и ошибки раскладки без чтения содержимого.

    Узнаваемый документ в неверном месте остаётся доступен диагностике,
    но всегда сопровождается W10. Внутрь папки документа не спускаемся:
    даже приложение с именем PLN-номер не приобретает собственного ID.
    """
    entries, problems, seen = [], [], set()

    def allowed(path):
        return (not path.is_symlink() and not pr.in_connected_repo(path)
                and not pr.target_skip_dirs.excludes(path, directory=path.is_dir()))

    def problem(code, path, message):
        problems.append(LayoutProblem(code, path, message, path.name))

    def visit(base, prefix, type_root, feedback=False, children=None):
        if not allowed(base) or not base.is_dir():
            return
        if children is None and (pr.git_file_names(base) is not None
                                 or pr.git_root is not None and is_within(base, pr.root)):
            children = {}
            for eligible in pr.walk_md(base, exclusions=pr.target_skip_dirs):
                for path in (eligible, *eligible.parents):
                    if path == base:
                        break
                    children.setdefault(path.parent, set()).add(path)
        for path in sorted(base.iterdir() if children is None else children.get(base, ())):
            if path.name.startswith('.') or path.name in ('README.md', HISTORY_DIR) or not allowed(path):
                continue
            if path.is_file() and (path.suffix.lower() != '.md' or pr.file_path(path) is None):
                continue
            year_directory = is_year_directory(path, prefix, pr)
            if year_directory:
                if prefix == 'adr' or feedback or base != type_root:
                    problem('W10', path, tr('checker.workflow_layout.disallowed_year_directory'))
                visit(path, prefix, type_root, feedback, children)
                continue
            stem = path.stem if path.is_file() else path.name
            match = (RE_DECISION_NAME.fullmatch(stem) if prefix == 'adr'
                     else RE_DOC_NAME.fullmatch(stem))
            if not match or (prefix != 'adr' and match[1] != prefix):
                problem('W1', path, tr('checker.workflow_layout.invalid_document_name') %
                        (prefix, '.md' if path.is_file() else ''))
                # Неверная промежуточная папка не скрывает документы внутри.
                if path.is_dir():
                    visit(path, prefix, type_root, feedback, children)
                continue
            num, slug = ((match[1], match[2] or stem) if prefix == 'adr'
                         else (match[2], match[3]))
            year = base.name if base.parent == type_root and YEAR.fullmatch(base.name) else None
            valid = base == type_root if prefix == 'adr' or feedback else year is not None
            if not valid:
                problem('W10', path, tr('checker.workflow_layout.expected_flat_directory') if prefix == 'adr' or feedback
                        else tr('checker.workflow_layout.expected_created_year_directory') % TYPES[prefix][0])
            if feedback and path.is_dir():
                problem('W1', path, tr('checker.workflow_layout.invalid_feedback_name'))
                continue
            main = path
            if path.is_dir():
                lead = '' if prefix == 'adr' and not path.name.lower().startswith('adr-') else prefix + '-'
                main = path / (lead + num + '-readme.md')
                safe_main = pr.file_path(main)
                if safe_main is None or not safe_main.is_file():
                    problem('W1', path, tr('checker.workflow_layout.missing_container_document') % main.name)
                    continue
            real = pr.file_path(main)
            if real is None or not allowed(main) or real in seen:
                continue
            seen.add(real)
            entries.append(WorkEntry(prefix, num, slug, real, path,
                                     year if prefix in YEARLY and not feedback else None, feedback))

    if pr.wf is not None:
        for prefix, (dirname, _) in TYPES.items():
            if prefix != 'adr':
                visit(pr.wf / dirname, prefix, pr.wf / dirname)
    if pr.decisions is not None:
        visit(pr.decisions, 'adr', pr.decisions)
    feedback = feedback_dir(pr.root)
    if not has_symlink(feedback, pr.root):
        visit(feedback, 'iss', feedback, True)
    return entries, problems


def allows_work_names(pr, path):
    """Разрешает перечислять имена внутри рабочего корня без раскрытия ссылок."""
    if path is None or pr.in_connected_repo(path):
        return False
    boundary = next((root for root in (pr.root, pr.wf, pr.decisions) if is_within(path, root)), None)
    return boundary is not None and not boundary.is_symlink() and not has_symlink(path, boundary)


def reserved_numbers(pr, prefix):
    """Занятые номера по именам: годы, оба архива и feedback; без чтения текста."""
    roots = [pr.root / HISTORY_DIR]
    if pr.wf is not None:
        roots.append(pr.wf)
    if prefix == 'adr' and pr.decisions is not None:
        roots.append(pr.decisions)
    if prefix == 'iss':
        roots.append(feedback_dir(pr.root))
    numbers = set()
    decision_dirs = {'adr'} | ({pr.decisions.name} if pr.decisions is not None else set())
    for root in dict.fromkeys(roots):
        if not allows_work_names(pr, root):
            continue
        for directory, names, files in os.walk(root):
            base = Path(directory)
            names[:] = sorted(name for name in names if not (base / name).is_symlink()
                              and not pr.in_connected_repo(base / name))
            for name in names + files:
                path = base / name
                if path.is_symlink() or (path.is_file() and path.suffix.lower() != '.md'):
                    continue
                stem = path.stem if path.is_file() else name
                if prefix == 'adr':
                    match = RE_DECISION_NAME.fullmatch(stem)
                    bare_allowed = (base.name in decision_dirs or base == pr.decisions
                                    or (pr.decisions is not None and base == pr.decisions / HISTORY_DIR))
                    if (match and not is_year_directory(path, prefix)
                            and (stem.lower().startswith('adr-') or bare_allowed)):
                        numbers.add(int(match[1]))
                else:
                    match = re.match(r'^%s-(\d{3,})-' % prefix, stem)
                    if match:
                        numbers.add(int(match[1]))
            # Главный файл повторяет номер контейнера; приложения его не занимают.
            names[:] = [name for name in names
                        if not RE_DOC_NAME.fullmatch(name)
                        and not (base.name in decision_dirs and RE_DECISION_NAME.fullmatch(name)
                                 and not is_year_directory(base / name, 'adr'))]
    return numbers
