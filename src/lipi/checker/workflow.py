"""Рабочие документы, проверки и указатель."""

import os
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote

from lipi.i18n import quoted, tr
from .conventions import (
    FINAL,
    HISTORY_DIR,
    ISSUE_KINDS,
    K_CREATED,
    K_CLOSED,
    K_KIND,
    K_REFINES,
    K_RESULT,
    K_STATUS,
    K_UPDATED,
    MASTERPLAN,
    NEED_RESULT,
    REQUIRED_SECTIONS,
    RE_DECISION_NAME,
    RE_DOC_NAME,
    RE_DOC_REF,
    RE_LINK,
    RE_SCHEME,
    STATUSES,
    TYPES,
)
from .docs import check_anchors, check_links
from .model import is_within, mask_code, resolve_target, section_lines
from .targets import decision_id, normalize_work_id, target_excluded
from .workflow_layout import (allows_work_names, discover_workflow, is_final, is_year_directory,
                              latest_closed_date, parse_date, reserved_numbers)


TRANSLIT = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m",
                     "n", "o", "p", "r", "s", "t", "u", "f", "h", "c", "ch", "sh",
                     "sch", "", "y", "", "e", "yu", "ya"]))
TRANSLIT["ё"] = "e"


def slugify(title):
    s = "".join(TRANSLIT.get(ch, ch) for ch in title.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return "-".join(s.split("-")[:6]) or "doc"


# @trace docs/ru/commands.md#new-decision
def decision_names(pr, include_archived=False):
    """Имена ADR для создания: архив резервирует номера без чтения страниц."""
    result = []
    seen = set()

    def add(path, allow_bare):
        if path in seen or path.is_symlink() or pr.in_connected_repo(path):
            return
        seen.add(path)
        if is_year_directory(path, 'adr'):
            return
        if path.is_file() and path.suffix.lower() != '.md':
            return
        match = RE_DECISION_NAME.fullmatch(path.stem if path.is_file() else path.name)
        bare = not path.name.lower().startswith('adr-')
        if match and (allow_bare or not bare):
            result.append((int(match[1]), len(match[1]), bare))

    if allows_work_names(pr, pr.decisions) and pr.decisions.is_dir():
        for path in sorted(pr.decisions.iterdir()):
            add(path, True)
    if not include_archived:
        return result

    # Префикс определяет ADR сам; голые номера — только в каталогах решений.
    # Вложенные приложения с числовыми именами номерами решений не становятся.
    decision_dirs = {'adr'}
    if pr.decisions is not None:
        decision_dirs.add(pr.decisions.name)
    roots = [pr.root / HISTORY_DIR]
    if pr.wf is not None:
        roots.append(pr.wf)
    if pr.decisions is not None:
        roots.append(pr.decisions / HISTORY_DIR)
    for root in dict.fromkeys(roots):
        if not allows_work_names(pr, root):
            continue
        for directory, names, files in os.walk(root):
            base = Path(directory)
            names[:] = sorted(name for name in names
                              if not (base / name).is_symlink()
                              and not pr.in_connected_repo(base / name))
            allow_bare = (base.name in decision_dirs
                          or (pr.decisions is not None
                              and base == pr.decisions / HISTORY_DIR))
            for name in sorted(names + files):
                add(base / name, allow_bare)
    return result


def next_number(pr, prefix):
    """Следующий номер документа: у замечаний он общий с .agents/lipi-feedback/."""
    return "%03d" % (max(reserved_numbers(pr, prefix), default=0) + 1)


# --- Рабочие материалы -------------------------------------------------------

# @trace docs/ru/codes.md#w1,docs/ru/codes.md#w2
def register_doc(pr, rep, docs, prefix, num, slug, main, feedback=False):
    """Добавляет документ в словарь проверки: W1 — не читается, W2 — номер занят."""
    did = normalize_work_id("%s-%s" % (prefix, num)).lower()
    page = pr.page(main)
    if page is None:
        rep.finding("W1", pr.rel(main), 0, tr("checker.workflow.unreadable_utf8"))
        return
    doc = {"id": did, "prefix": prefix, "num": int(num), "page": page,
           "header": page.header(), "title": page.h1 or slug, "feedback": feedback}
    if did in docs:
        if docs[did]["page"].path == page.path:
            return docs[did]
        rep.finding("W2", pr.rel(main), 0, tr("checker.workflow.duplicate_work_id")
                    % (did.upper(), pr.rel(docs[did]["page"].path)), subject=did)
        docs[did]["ambiguous"] = True
        docs[did].setdefault("duplicates", []).append(doc)
    else:
        docs[did] = doc
    return doc


# @trace docs/ru/codes.md#w1,docs/ru/codes.md#w9,docs/ru/codes.md#w10,ADR-020
def scan_workflow(pr, rep):
    """Общая раскладка: главные файлы проверяются отдельно от приложений."""
    docs, others = {}, []
    entries, problems = discover_workflow(pr)
    for problem in problems:
        rep.finding(problem.code, pr.rel(problem.path), 0, problem.message,
                    subject=problem.subject)
    visited = set()
    for entry in entries:
        doc = register_doc(pr, rep, docs, entry.prefix, entry.num, entry.slug,
                           entry.path, feedback=entry.feedback)
        if doc is not None:
            doc["year"] = entry.year
            doc["container"] = entry.container
        visited.add(entry.path)
    history = [pr.root / HISTORY_DIR]
    if pr.wf is not None:
        history.append(pr.wf / HISTORY_DIR)
    if pr.decisions is not None:
        history.append(pr.decisions / HISTORY_DIR)
    type_dirs = [pr.wf / directory for prefix, (directory, _) in TYPES.items()
                 if pr.wf is not None and prefix != 'adr']
    if pr.decisions is not None:
        type_dirs.append(pr.decisions)
    for base in dict.fromkeys(path for path in (pr.wf, pr.decisions) if path):
        for path in pr.walk_md(base, skip=history, resolved=True):
            if path in visited or (is_within(path, pr.root) and target_excluded(pr, path)):
                continue
            match = RE_DOC_NAME.fullmatch(path.stem)
            if (match and path.parent != pr.wf
                    and not any(is_within(path, directory) for directory in type_dirs)):
                rep.finding('W1', pr.rel(path), 0, tr('checker.workflow.wrong_document_directory')
                            % (tr(TYPES[match[1]][1]).lower(), TYPES[match[1]][0]),
                            subject=path.stem)
            others.append(path)
            visited.add(path)
    return docs, others


# @trace docs/ru/codes.md#w3
def check_workflow(pr, rep, docs, others, *, latest_date=None):
    if latest_date is None:
        latest_date = latest_closed_date()
    mp_refs = []
    all_docs = [(did, item) for did, doc in sorted(docs.items())
                for item in [doc] + doc.get("duplicates", [])]
    for did, d in all_docs:
        page, h, prefix = d["page"], d["header"], d["prefix"]
        r = pr.rel(page.path)
        if not page.h1:
            rep.finding("W3", r, 1, tr("checker.workflow.missing_h1"))
        for key in (K_CREATED, K_UPDATED):
            v = h.get(key)
            if not v:
                rep.finding("W3", r, page.h1_line, tr("checker.workflow.missing_date_header") % key,
                        subject=key)
            elif parse_date(v) is None:
                rep.finding("W3", r, page.h1_line, tr("checker.workflow.invalid_date_header") % (key, v),
                        subject=key)
        if parse_date(h.get(K_CREATED)) and parse_date(h.get(K_UPDATED)) \
                and h[K_UPDATED] < h[K_CREATED]:
            rep.finding("W3", r, page.h1_line, tr("checker.workflow.updated_before_created"),
                    subject=K_UPDATED)
        status = h.get(K_STATUS, "").strip("* .").lower()
        d["status"] = status
        if prefix in STATUSES:
            if not status:
                rep.finding("W3", r, page.h1_line, tr("checker.workflow.missing_required_header")
                        % (K_STATUS, ", ".join(STATUSES[prefix])), subject=K_STATUS)
            elif status not in STATUSES[prefix]:
                rep.finding("W3", r, page.h1_line,
                        tr("checker.workflow.invalid_status")
                        % (h[K_STATUS], ", ".join(STATUSES[prefix]), K_RESULT), subject=K_STATUS)
        if prefix == "iss":
            kind = h.get(K_KIND, "").strip().lower()
            if kind not in ISSUE_KINDS:
                rep.finding("W3", r, page.h1_line, tr("checker.workflow.missing_kind_header")
                        % (K_KIND, ", ".join(ISSUE_KINDS)), subject=K_KIND)
        if prefix == 'adr':
            for value in page.header_values(K_REFINES):
                links = list(RE_LINK.finditer(mask_code(value)))
                invalid = not links
                for link in links:
                    target, _ = resolve_target(page, link[1], pr)
                    if RE_SCHEME.match(link[1]) or (target is not None and decision_id(pr, target) is None):
                        invalid = True
                if invalid:
                    rep.finding('W3', r, page.h1_line,
                                tr('checker.workflow.refines_needs_decision_link') % K_REFINES,
                                subject=K_REFINES)
        # @trace docs/ru/codes.md#w4
        if (prefix, status) in NEED_RESULT and not h.get(K_RESULT):
            rep.finding("W4", r, page.h1_line,
                    tr("checker.workflow.missing_result")
                    % (status, K_RESULT), subject=did)
        # @trace docs/ru/codes.md#w3,docs/ru/codes.md#w4,docs/ru/codes.md#w11,ADR-020
        closed = h.get(K_CLOSED)
        if is_final(prefix, status) and not closed:
            rep.finding("W4", r, page.h1_line,
                        tr("checker.workflow.missing_closed_date") % (status, K_CLOSED),
                        subject=K_CLOSED)
        if closed:
            created_date, closed_date = parse_date(h.get(K_CREATED)), parse_date(closed)
            if closed_date is None:
                message = tr("checker.workflow.invalid_closed_date") % K_CLOSED
            elif created_date and closed_date < created_date:
                message = tr("checker.workflow.closed_before_created")
            elif closed_date > latest_date:
                message = tr("checker.workflow.closed_after_latest_date") % latest_date
            else:
                message = None
            if message:
                rep.finding("W3", r, page.h1_line, message, subject=K_CLOSED)
        created_date = parse_date(h.get(K_CREATED))
        if d.get("year") and created_date and int(d["year"]) != created_date.year:
            container = d["container"]
            destination = container.parent.parent / ("%04d" % created_date.year) / container.name
            rep.finding("W11", r, page.h1_line,
                        tr('checker.workflow.incorrect_directory_year')
                        % (pr.rel(container), pr.rel(destination)), subject=K_CREATED)
        # @trace docs/ru/codes.md#w8
        required = REQUIRED_SECTIONS.get((prefix, status))
        if required:
            need = tr("checker.workflow.section_conjunction").join(map(quoted, required))
            for title in required:
                lines = section_lines(page.text, title)
                if lines is None:
                    rep.finding("W8", r, page.h1_line,
                            tr("checker.workflow.missing_required_section") % (title, status, need),
                            subject=title)
                elif not lines:
                    rep.finding("W8", r, page.h1_line,
                            tr("checker.workflow.empty_required_section") % (title, status, need),
                            subject=title)
        check_anchors(pr, rep, page)
        check_links(pr, rep, page, "W6")
    for p in others:
        page = pr.page(p)
        if page is not None:
            check_links(pr, rep, page, "W6")

    # W5: мастер-план
    # @trace docs/ru/codes.md#w5
    if pr.wf is None:
        return mp_refs
    mp = pr.wf / MASTERPLAN
    if pr.file_path(mp) is not None and mp.is_file() and not pr.target_skip_dirs.excludes(mp, base=pr.wf):
        page = pr.page(mp)
        r = pr.rel(mp)
        lim = pr.cfg["limits"]["masterplan_lines"]
        if lim and page.lines > lim:
            rep.finding("W5", r, 0, tr("checker.workflow.masterplan_too_large") % (page.lines, lim))
        for n, s in enumerate(page.masked.split("\n"), 1):
            seen = set()
            for m in RE_DOC_REF.finditer(page.text.split("\n")[n - 1]):
                did = normalize_work_id("%s-%s" % (m.group(1), m.group(2))).lower()
                if did in seen:
                    continue
                seen.add(did)
                mp_refs.append((n, did))
                if did not in docs:
                    rep.finding("W5", r, n, tr("checker.workflow.nonexistent_masterplan_document") % did.upper(),
                                subject=did)
                elif docs[did].get("ambiguous"):
                    rep.finding("W5", r, n, tr("checker.workflow.ambiguous_masterplan_document") % did.upper(),
                                subject=did)
                elif docs[did]["prefix"] in ("pln", "iss") and docs[did].get("status") in FINAL:
                    rep.finding("W5", r, n, tr("checker.workflow.closed_masterplan_document")
                            % (did.upper(), docs[did]["status"]), subject=did)
    return mp_refs


# @trace docs/ru/commands.md#index
def _index_result(value, page, index_dir):
    """Переносит адреса итога в указатель, сохраняя остальной Markdown."""
    def relative(path):
        return quote(os.path.relpath(path, index_dir).replace(os.sep, "/"),
                     safe="/!$&'*+,-.:;=@_~")

    result = value
    for match in reversed(list(RE_LINK.finditer(mask_code(value)))):
        address = value[match.start(1):match.end(1)]
        path, marker, anchor = address.partition("#")
        if RE_SCHEME.match(address) or unquote(path).startswith("/"):
            continue
        if path:
            prefix = relative(page.path.parent)
            # Сокращаем только начальные буквальные ./ и ../: нормализация
            # всего адреса исказила бы глубину сегментов вроде «a%2Fb/..».
            while path.startswith(("./", "../")):
                part, _, path = path.partition("/")
                path = path.lstrip("/")
                prefix = posixpath.normpath(posixpath.join(prefix, part))
            rewritten = posixpath.join(prefix, path)
            if rewritten.startswith("./"):
                rewritten = rewritten[2:]
        else:
            rewritten = relative(page.path)
        if RE_SCHEME.match(rewritten):
            rewritten = "./" + rewritten
        start, end = match.span(1)
        result = result[:start] + rewritten + marker + anchor + result[end:]
    return result


# @trace docs/ru/commands.md#index
def build_index(pr, docs, *, previous=None):
    """Построение комплекта указателей с учётом исключений Git."""
    from .workflow_index import build_project_index
    return build_project_index(pr, docs, previous=previous)
