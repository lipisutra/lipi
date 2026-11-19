"""Полный комплект указателей: чистое построение, план и обратимая запись."""

import os
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from urllib.parse import quote

from lipi.i18n import tr
from .conventions import K_CLOSED, K_CREATED, K_KIND, K_RESULT, K_STATUS, K_UPDATED, STATUSES
from .workflow_layout import is_final, latest_closed_date, parse_date


MARKER = "<!-- lipi:generated:workflow-index -->"
FIXED = ("INDEX.md", "index/plans.md", "index/issues.md",
         "index/discussions.md", "index/decisions.md", "index/audits.md")
YEAR_PATH = re.compile(r"index/done/[0-9]{4}\.md\Z")


class IndexErrorBase(ValueError):
    def __init__(self, path, message):
        self.path, self.message = Path(path), message
        super().__init__("%s: %s" % (path, message))


class IndexHeaderError(IndexErrorBase):
    """Ошибка шапки; W3/W4 сообщает обычная проверка рабочего документа."""


@dataclass
class IndexPlan:
    files: dict
    changes: dict
    before: dict


def index_path(wf, path):
    """Только точные производные пути, без произвольных файлов в index/."""
    try:
        relative = Path(path).relative_to(wf).as_posix()
    except ValueError:
        return False
    return relative in FIXED or bool(YEAR_PATH.fullmatch(relative))


def _owned(data):
    return data is not None and data.startswith((MARKER + "\n").encode("utf-8"))


def _safe_path(path, boundary):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise IndexErrorBase(part, tr("checker.workflow_index.index_path_symlink"))
        if part != path and part.exists() and not part.is_dir():
            raise IndexErrorBase(part, tr("checker.workflow_index.non_directory_at_index_path"))
        if part == boundary:
            break
    if path.exists() and not path.is_file():
        raise IndexErrorBase(path, tr("checker.workflow_index.non_file_at_index_path"))


def _safe_root(pr):
    configured = pr.cfg.get("workflow")
    if configured:
        configured_path = pr.root / configured
        boundary = pr.root if configured_path.is_relative_to(pr.root) else configured_path
        _safe_path(configured_path / ".lipi-index-root", boundary)


def read_index_files(pr):
    """Снимок точных путей; чужие файлы не читаются и не удаляются."""
    if pr.wf is None:
        return {}
    _safe_root(pr)
    paths = [pr.wf / name for name in FIXED]
    done = pr.wf / "index/done"
    names = pr.git_file_names(done)
    if names is not None:
        for path in (done.parent, done):
            if path in names and path.is_symlink():
                raise IndexErrorBase(path, tr("checker.workflow_index.index_path_symlink"))
        paths.extend(path for path in names if path.parent == done and index_path(pr.wf, path))
    else:
        _safe_path(done / "0000.md", pr.wf)
        if done.is_dir():
            paths.extend(path for path in done.iterdir() if index_path(pr.wf, path))
    previous = {}
    for path in sorted(set(paths) - pr.git_ignored_paths(paths)):
        _safe_path(path, pr.wf)
        if pr.file_path(path) is not None and path.is_file():
            try:
                previous[path] = path.read_bytes()
            except OSError as error:
                raise IndexErrorBase(path, str(error)) from error
    return previous


# @trace docs/ru/workflow.md#files,docs/ru/workflow.md#closure
def build_index_files(pr, docs, *, previous=None, latest_date=None, ignored=()):
    """Возвращает конечные абсолютные пути/байты без чтения файлов или Git.

    previous — снимок прежних указателей, в том числе в проекции init.
    Только помеченные страницы годов сохраняются после опустошения.
    """
    from .workflow import _index_result

    if pr.wf is None:
        return {}
    if latest_date is None:
        latest_date = latest_closed_date()
    previous = previous or {}
    documents = [doc for doc in docs.values() if not doc.get("feedback")]
    finals, live = {}, {prefix: [] for prefix in ("pln", "iss", "dsc", "adr", "aud")}
    for doc in documents:
        header, prefix = doc["header"], doc["prefix"]
        status = header.get(K_STATUS, "").strip("* .").lower()
        if is_final(prefix, status):
            closed = parse_date(header.get(K_CLOSED, ""))
            created = parse_date(header.get(K_CREATED, ""))
            if (closed is None or closed > latest_date
                    or (created is not None and closed < created)):
                raise IndexHeaderError(doc["page"].path,
                                       tr("checker.workflow_index.invalid_closed_date"))
            finals.setdefault("%04d" % closed.year, []).append(doc)
        elif prefix == "aud" or status in STATUSES.get(prefix, ()):
            live[prefix].append(doc)
    for path, content in previous.items():
        if (index_path(pr.wf, path) and _owned(content)
                and YEAR_PATH.fullmatch(Path(path).relative_to(pr.wf).as_posix())):
            finals.setdefault(Path(path).stem, [])

    def ordered(items, closed=False):
        return sorted(items, key=lambda doc: (doc["header"].get(K_CLOSED if closed else K_UPDATED, ""),
                                              doc["num"], doc["id"]), reverse=True)

    def row(doc, destination, closed=False):
        header = doc["header"]
        address = quote(os.path.relpath(doc["page"].path, destination.parent).replace(os.sep, "/"),
                        safe="/!$&'*+,-.:;=@_~")
        result = "- [%s](%s) %s" % (doc["id"].upper(), address, doc["title"])
        if doc["prefix"] == "iss" and header.get(K_KIND):
            result += " · %s" % header[K_KIND].lower()
        if closed and header.get(K_RESULT):
            result += " — %s" % _index_result(header[K_RESULT], doc["page"], destination.parent)
        return result + " (%s)" % header.get(K_CLOSED if closed else K_UPDATED, "?")

    # Указатель входит в проект и не меняется при смене личного языка.
    label = partial(tr, language="en")

    def page(title, content):
        return ("\n".join([MARKER, "# " + title, "",
                          label("checker.workflow_index.generated_notice"),
                          "", *content]).rstrip("\n") + "\n").encode("utf-8")

    files = {}
    lists = (("pln", "plans", label("checker.workflow_index.plans")),
             ("iss", "issues", label("checker.workflow_index.issues")),
             ("dsc", "discussions", label("checker.workflow_index.discussions")),
             ("adr", "decisions", label("checker.workflow_index.decisions")),
             ("aud", "audits", label("checker.workflow_index.audits")))
    root_content = []
    for title, status in ((label("checker.workflow_index.in_progress"), "in progress"),
                          (label("checker.workflow_index.pending_acceptance"), "pending acceptance")):
        items = [doc for prefix in ("pln", "iss") for doc in live[prefix]
                 if doc["header"].get(K_STATUS, "").strip("* .").lower() == status]
        rows = [row(doc, pr.wf / "INDEX.md") for doc in ordered(items)]
        root_content.extend(["## " + title, "", *(rows or [label("checker.workflow_index.no_work_items")]), ""])
    root_content.extend([label("checker.workflow_index.all_documents"), "",
                         label("checker.workflow_index.total_documents") % len(documents), ""])
    for prefix, name, title in lists:
        destination = pr.wf / ("index/%s.md" % name)
        if destination in ignored:
            continue
        files[destination] = page(title, [row(doc, destination) for doc in ordered(live[prefix])]
                                 or [label("checker.workflow_index.no_work_items")])
        root_content.append("- [%s](index/%s.md): %d" % (title, name, len(live[prefix])))
    root_content.extend(["", label("checker.workflow_index.closed_work_items"), ""])
    for year, items in sorted(finals.items(), reverse=True):
        destination = pr.wf / ("index/done/%s.md" % year)
        if destination in ignored:
            continue
        files[destination] = page(label("checker.workflow_index.closed_year") + year,
                                 [row(doc, destination, True) for doc in ordered(items, True)]
                                 or [label("checker.workflow_index.no_closed_work_items")])
        root_content.append("- [%s](index/done/%s.md): %d" % (year, year, len(items)))
    if not finals:
        root_content.append(label("checker.workflow_index.no_closed_work_items"))
    root_index = pr.wf / "INDEX.md"
    if root_index not in ignored:
        files[root_index] = page(label("checker.workflow_index.index_title"), root_content)
    return dict(sorted(files.items()))


def build_project_index(pr, docs, *, previous=None, latest_date=None):
    files = build_index_files(pr, docs, previous=previous, latest_date=latest_date)
    ignored = pr.git_ignored_paths(files)
    if ignored:
        files = build_index_files(pr, docs, previous=previous, latest_date=latest_date, ignored=ignored)
    return files


# @trace docs/ru/workflow.md#ownership
def plan_index(pr, files, *, previous=None):
    """Проверяет владение всем набором до записи; пригоден для композиции init."""
    _safe_root(pr)
    previous = read_index_files(pr) if previous is None else previous
    changes, before = {}, {}
    for path, content in files.items():
        if pr.wf is None or not index_path(pr.wf, path) or not _owned(content):
            raise IndexErrorBase(path, tr("checker.workflow_index.invalid_index_path_or_marker"))
        _safe_path(path, pr.wf)
        old = previous.get(path)
        if old is not None and not _owned(old):
            raise IndexErrorBase(path, tr("checker.workflow_index.user_file_at_index_path"))
        if old != content:
            changes[path], before[path] = content, old
    return IndexPlan(dict(files), changes, before)


def _write_file(path, content):
    path.write_bytes(content)


# @trace docs/ru/workflow.md#refresh
def apply_index(pr, plan):
    """Записывает план с откатом файлов и новых каталогов, не меняя индекс Git."""
    _safe_root(pr)
    for path, old in plan.before.items():
        _safe_path(path, pr.wf)
        current = path.read_bytes() if path.exists() else None
        if current != old:
            raise IndexErrorBase(path, tr("checker.workflow_index.changed_after_plan"))
    touched, created_dirs = [], []
    try:
        for path, content in plan.changes.items():
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
            touched.append(path)
            _write_file(path, content)
    except BaseException:
        for path in reversed(touched):
            old = plan.before[path]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old)
        for directory in reversed(created_dirs):
            directory.rmdir()
        raise
    for path in plan.files:
        pr.pages.pop(path, None)
    if plan.changes:
        pr.refresh_git_files()
    return plan


def refresh_index(pr, docs):
    previous = read_index_files(pr)
    files = build_project_index(pr, docs, previous=previous)
    return apply_index(pr, plan_index(pr, files, previous=previous))
