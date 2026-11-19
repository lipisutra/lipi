"""Общее разрешение целей меток кода и covers."""

import re
from pathlib import Path
from urllib.parse import unquote

from lipi.i18n import tr
from .conventions import (
    FINAL, HISTORY_DIR, K_REFINES, K_RESULT, K_STATUS, RE_DECISION_NAME, RE_DOC_NAME, RE_DOC_REF, RE_LINK,
    STATUSES, LIPI_DIR,
)
from .model import feedback_dir, is_within, mask_code, resolve_target
from .workflow_layout import discover_workflow


# @trace docs/ru/codes.md#t4
class TargetUnavailable(str):
    """Текст ошибки сохраняет API resolve_mark, но обозначает непроверенную связь."""


# @trace docs/ru/codes.md#t4
def target_error_code(error, default):
    return "T4" if isinstance(error, TargetUnavailable) else default


def target_excluded(pr, path):
    """Исключения целей не наследуют пропуск .agents при обходе кода."""
    if pr.in_connected_repo(path) or not is_within(path, pr.root):
        return True
    if pr.target_skip_dirs.excludes(path):
        return True
    if is_within(path, pr.root / LIPI_DIR):
        return True
    if is_within(path, pr.root / HISTORY_DIR):
        return True
    if pr.decisions is not None and is_within(path, pr.decisions / HISTORY_DIR):
        return True
    return bool(pr.wf and is_within(path, pr.wf / HISTORY_DIR))


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,ADR-015
def normalize_work_id(token):
    """Нули номера ADR не значимы; остальные номера сохраняют свой формат."""
    match = re.fullmatch(r"adr-(\d+)", token.strip(), re.I)
    if match:
        return "ADR-%03d" % int(match[1])
    match = RE_DOC_REF.fullmatch(token.strip())
    return token.strip().upper() if match else None


def decision_id(pr, path):
    """Номер главного файла в каталоге решений; вложения номера не получают."""
    path = pr.file_path(path)
    if path is None:
        return None
    if (not is_within(path, pr.decisions) or not path.is_file() or path.suffix.lower() != '.md'
            or (is_within(path, pr.root) and target_excluded(pr, path))):
        return None
    for parent in path.parents:
        if parent == pr.decisions:
            break
        owner = RE_DECISION_NAME.fullmatch(parent.name)
        if owner:
            stem = ('adr-' if parent.name.lower().startswith('adr-') else '') + owner[1]
            if (parent.parent != pr.decisions or path.parent != parent
                    or path.name.lower() != stem.lower() + '-readme.md'):
                return None
            return normalize_work_id('ADR-' + owner[1])
    if path.parent != pr.decisions:
        return None
    match = RE_DECISION_NAME.fullmatch(path.stem)
    return normalize_work_id('ADR-' + match[1]) if match else None


def work_targets(pr):
    """Номера рабочих документов и решений; физический файл учитывается один раз."""
    if pr.mark_work_index is None:
        pr.mark_work_index = {}
        entries, _ = discover_workflow(pr)
        for entry in entries:
            if entry.feedback or target_excluded(pr, entry.path):
                continue
            did = normalize_work_id('%s-%s' % (entry.prefix, entry.num))
            pr.mark_work_index.setdefault(did, []).append(entry.path)
    return pr.mark_work_index


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
def _decision_targets(pr):
    """Индекс внешних решений без обхода остальных рабочих материалов соседа."""
    if not hasattr(pr, "_external_decision_index"):
        index = {}
        if pr.decisions is not None:
            seen = set()
            for path in pr.walk_md(pr.decisions, exclusions=pr.target_skip_dirs):
                path = pr.file_path(path)
                if path in seen:
                    continue
                seen.add(path)
                did = decision_id(pr, path)
                if did:
                    index.setdefault(did, []).append(path)
        pr._external_decision_index = index
    return pr._external_decision_index


# @trace docs/ru/codes.md#w3,ADR-015
def decision_relations(pr):
    """Уточняющее решение -> уточняемые: только явные строки «Уточняет»."""
    paths = {targets[0]: did for did, targets in work_targets(pr).items()
             if did.startswith('ADR-') and len(targets) == 1}
    relations = {}
    for path, did in paths.items():
        page = pr.page(path)
        if page is None:
            continue
        parents = []
        for value in page.header_values(K_REFINES):
            for link in RE_LINK.finditer(mask_code(value)):
                target, _ = resolve_target(page, link[1], pr)
                if target in paths and paths[target] != did and paths[target] not in parents:
                    parents.append(paths[target])
        relations[did] = tuple(parents)
    return relations


# @trace docs/ru/codes.md#t3
def current_link_source(pr, path):
    """Обычные ссылки описания и правил проверяют актуальность решений."""
    path = pr.lexical_path(path)
    if (is_within(path, pr.wf) or is_within(path, pr.decisions)
            or is_within(path, feedback_dir(pr.root))):
        return False
    return (is_within(path, pr.docs) or path in (pr.root / 'README.md', pr.root / 'AGENTS.md')
            or is_within(path, pr.root / '.agents')
            or any(is_within(path, base) for base in pr.editions.values()))


# @trace docs/ru/codes.md#t3,ADR-013,ADR-015
def check_target_status(pr, rep, target_id, source, line, *, relation=None):
    """T3 для разрешённой цели метки кода или covers; разделы молчат."""
    page = pr.mark_work.get(target_id)
    if page is None:
        return
    external = pr.mark_external.get(target_id)
    if external and external["source"].unavailable_reason is not None:
        return
    owner = external["source"].project if external else pr
    local_id = external["target"] if external else target_id
    prefix = local_id.partition("-")[0].lower()
    header = page.header()
    status = header.get(K_STATUS, "").strip("* .").lower()
    if status not in STATUSES.get(prefix, ()) or status not in FINAL:
        return                     # неизвестный статус диагностирует W3

    subject = "%s %s" % (target_id, status)
    if relation == 'link':
        if prefix == 'adr':
            adjective = (tr('checker.targets.superseded_decision') if status == 'superseded'
                         else tr('checker.targets.rejected_decision'))
            rep.finding('T3', source, line,
                        tr('checker.targets.outdated_decision_link')
                        % (adjective, target_id), subject=subject)
        return
    message = subject
    if prefix == "adr" and status == "superseded":
        targets = _decision_targets(owner) if external else work_targets(pr)
        paths = {path: did for did, paths in targets.items() for path in paths}
        for link in RE_LINK.finditer(mask_code(header.get(K_RESULT, ""))):
            if external:
                relative = unquote(link.group(1).partition("#")[0])
                path = external["source"].resolve_path(page.path.parent / relative)
            else:
                path, _ = resolve_target(page, link.group(1), pr)
            if path in paths and owner.page(path) is not None:
                successor = paths[path]
                if external:
                    successor = external["source"].name + "::" + successor
                message += " " + successor
                break

    action = {
        ("adr", "superseded"): "checker.targets.align_code_with_decision",
        ("adr", "rejected"): "checker.targets.remove_rejected_decision_dependency",
        ("iss", "closed"): "checker.targets.check_issue_link",
        ("pln", "completed"): "checker.targets.check_completed_plan_link",
        ("pln", "canceled"): "checker.targets.remove_canceled_plan_dependency",
        ("dsc", "closed"): "checker.targets.check_discussion_outcome",
    }[(prefix, status)]
    rep.finding("T3", source, line, message + " — " + tr(action), subject=subject)


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,ADR-013
def _resolve_local_mark(pr, token):
    did = normalize_work_id(token)
    if did:
        if not did.startswith("ADR-") and not pr.cfg.get("workflow"):
            return None, tr("checker.targets.workflow_disabled")
        if not did.startswith("ADR-") and pr.wf is None:
            return None, tr("checker.targets.workflow_directory_missing")
        paths = work_targets(pr).get(did, [])
        if not paths:
            return None, tr("checker.targets.work_target_not_found") % did
        if len(paths) != 1:
            return None, tr("checker.targets.ambiguous_work_id") % (did, ", ".join(pr.rel(p) for p in paths))
        page = pr.page(paths[0])
        if page is None:
            return None, tr("checker.targets.unreadable_work_document") % did
        pr.mark_work[did] = page
        return did, None

    page_part, sep, anchor = token.partition("#")
    if not sep or not page_part or not anchor:
        return None, tr("checker.targets.invalid_target")
    path_part = Path(unquote(page_part))
    lexical = pr.lexical_path(path_part)
    path = pr.file_path(lexical) if not path_part.is_absolute() and not target_excluded(pr, lexical) else None
    if path is None or target_excluded(pr, path):
        return None, tr("checker.targets.excluded_target") % page_part
    if not path.is_file() or path.suffix.lower() != ".md":
        return None, tr("checker.targets.missing_target_page") % page_part
    page = pr.page(path)
    anchor = unquote(anchor)
    if page is None or anchor not in page.anchors:
        return None, tr("checker.targets.missing_target_anchor") % (page_part, anchor)
    if any(aid == anchor for _, aid in page.dup):
        return None, tr("checker.targets.ambiguous_target_anchor") % (anchor, page_part)
    aid = "%s#%s" % (pr.rel(path), anchor)
    pr.mark_anchors[aid] = (page, page.anchors[anchor])
    return aid, None


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
def _external_path_kind(source, path):
    """Возможность определяется типом документа, до чтения его текста."""
    pr = source.project
    if is_within(path, pr.decisions):
        return "decisions"
    parts = list(path.relative_to(pr.root).parts[:-1]) + [path.stem]
    if any(match and match[1] != "adr"
           for match in (RE_DOC_NAME.fullmatch(part.lower()) for part in parts)):
        return "work"
    if is_within(path, pr.wf) or is_within(path, feedback_dir(pr.root)):
        return "work"
    if path.name == "AGENTS.md":
        return None
    bases = (pr.docs, pr.descr, *pr.editions.values())
    matching = [base for base in bases if is_within(path, base)]
    if (is_within(path, pr.root / ".agents")
            and not any(is_within(base, pr.root / ".agents") for base in matching)):
        return None
    if path == pr.root / "README.md" or matching:
        return "docs"
    return None


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,docs/ru/codes.md#t4,ADR-016
def _resolve_external_mark(pr, alias, token):
    source = pr.sources.get(alias)
    if source is None:
        return None, tr("checker.targets.unknown_connection") % alias
    if not token or "::" in token:
        return None, tr("checker.targets.invalid_external_target") % alias
    if source.unavailable_reason is not None:
        return None, TargetUnavailable(tr("checker.targets.unchecked_external_target") % (
            alias, source.unavailable_reason))
    owner = source.project
    did = normalize_work_id(token)
    if did:
        if not did.startswith("ADR-"):
            return None, tr("checker.targets.unsupported_external_work_item") % (alias, did)
        if "decisions" not in source.read:
            return None, tr("checker.targets.decisions_not_allowed") % alias
        if not source.has_config:
            return None, tr("checker.targets.missing_external_config") % alias
        paths = _decision_targets(owner).get(did, [])
        if not paths:
            return None, tr("checker.targets.decision_target_not_found") % (alias, did)
        if len(paths) != 1:
            return None, tr("checker.targets.ambiguous_external_work_id") % (
                alias, did, ", ".join(alias + "::" + owner.rel(path) for path in paths))
        page = owner.page(paths[0])
        if page is None:
            source.mark_unavailable(tr("checker.targets.unreadable_external_decision") % did)
            return None, TargetUnavailable(tr("checker.targets.unchecked_external_target") % (
                alias, source.unavailable_reason))
        owner.mark_work[did] = page
        aid = alias + "::" + did
        pr.mark_work[aid] = page
        pr.mark_external[aid] = {"source": source, "target": did, "decision": did}
        return aid, None

    page_part, sep, anchor = token.partition("#")
    if not sep or not page_part or not anchor:
        return None, tr("checker.targets.malformed_external_target") % (alias, alias, alias)
    path_part = Path(unquote(page_part))
    path = owner.file_path(path_part)
    if path_part.is_absolute() or path is None:
        return None, tr("checker.targets.external_target_excluded") % (alias, page_part)
    kind = _external_path_kind(source, path)
    if kind == "work":
        return None, tr("checker.targets.unsupported_external_work_item") % (alias, page_part)
    if kind is None or kind not in source.read:
        return None, tr("checker.targets.external_target_not_allowed") % (
            alias, tr("checker.targets.required_capability") + kind if kind else "")
    if path.is_file() and path.suffix.lower() == ".md" and owner.page(path) is None:
        source.mark_unavailable(tr("checker.targets.unreadable_external_page") % page_part)
        return None, TargetUnavailable(tr("checker.targets.unchecked_external_target") % (
            alias, source.unavailable_reason))
    local_id, error = _resolve_local_mark(owner, token)
    if local_id is None:
        return None, tr("checker.targets.connection_error") % (alias, error)
    aid = alias + "::" + local_id
    pr.mark_anchors[aid] = owner.mark_anchors[local_id]
    pr.mark_external[aid] = {"source": source, "target": local_id,
                             "decision": decision_id(owner, path) if kind == "decisions" else None}
    return aid, None


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
def resolve_mark(pr, token):
    """Возвращает (id, ошибка); внешние цели сохраняют пространство имён."""
    token = token.strip()
    alias, separator, target = token.partition("::")
    if separator:
        return _resolve_external_mark(pr, alias, target)
    return _resolve_local_mark(pr, token)
