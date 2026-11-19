"""Ссылки, якоря и проверки страниц описания."""

import os
import re

from lipi.i18n import quoted, tr
from .conventions import RE_COVERS, RE_SCHEME
from .model import is_within, line_of, resolve_target
from .targets import (
    check_target_status, current_link_source, decision_id, resolve_mark, target_error_code,
)


# @trace docs/ru/codes.md#d1,docs/ru/codes.md#w6
def check_links(pr, rep, page, code, forbid=None, forbid_msg=""):
    r = pr.rel(page.path)
    for line, target in page.links:
        tpath, anchor = resolve_target(page, target, pr)
        if tpath is None:
            if not RE_SCHEME.match(target):
                rep.finding(code, r, line, tr("checker.docs.missing_link_file") % target,
                        subject=target)
            continue
        # @trace docs/ru/codes.md#d5,ADR-015
        decision = decision_id(pr, tpath)
        if forbid is not None and is_within(tpath, forbid) and decision is None:
            rep.finding("D5", r, line, forbid_msg + ": %s" % target, subject=target)
        # @trace docs/ru/codes.md#t3,ADR-015
        if decision and current_link_source(pr, page.path):
            target_page = pr.page(tpath)
            if target_page is not None:
                pr.mark_work[decision] = target_page
                check_target_status(pr, rep, decision, r, line, relation='link')
        # @trace docs/ru/codes.md#d1,docs/ru/codes.md#w6
        if anchor and tpath.is_file() and tpath.suffix.lower() == ".md":
            tp = pr.page(tpath)
            if tp is not None and not pr.anchor_exists(tp, anchor):
                # @trace docs/ru/codes.md#d7,docs/ru/codes.md#w9
                if anchor in tp.slugs:
                    heading_code = "D7" if code == "D1" else "W9"
                    rep.finding(heading_code, r, line,
                            tr("checker.docs.heading_without_explicit_anchor") % target,
                            subject=target)
                else:
                    rep.finding(code, r, line, tr("checker.docs.missing_anchor") % target,
                            subject=target)


# @trace docs/ru/codes.md#d2
def check_anchors(pr, rep, page):
    r = pr.rel(page.path)
    for line, aid in page.dup:
        rep.finding("D2", r, line, tr("checker.docs.duplicate_anchor") % aid, subject=aid)
    for aid, line in page.anchors.items():
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", aid):
            rep.finding("D2", r, line, tr("checker.docs.invalid_anchor") % aid,
                    subject=aid)


def reachable_pages(pr, rep, base, scope, boundary):
    index = base / "README.md"
    if pr.skip_dirs.excludes(index, base=base):
        return set()
    safe_index = pr.file_path(index)
    if safe_index is None or not safe_index.is_file():
        rep.finding("D4", pr.rel(base), 0, tr("checker.docs.missing_readme_index"))
        return set()
    seen, queue = {safe_index}, [safe_index]
    while queue:
        page = pr.page(queue.pop())
        if page is None:
            continue
        for _, target in page.links:
            if not target.partition("#")[0]:
                continue
            path, _ = resolve_target(page, target, pr)
            if path is not None and path.is_dir():
                path = pr.file_path(path / "README.md")
            if (path is not None and path.suffix.lower() == ".md" and path not in seen
                    and is_within(path, boundary) and not pr.skip_dirs.excludes(path, base=base)):
                seen.add(path)
                queue.append(path)
    for page in scope:
        if page.path not in seen:
            rep.finding("D4", pr.rel(page.path), 0,
                        tr("checker.docs.unreachable_page") % pr.rel(index))
    return seen


# --- Описание ----------------------------------------------------------------

# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
def check_docs(pr, rep):
    """Возвращает (страницы, якоря id -> (page, line),
    covers id -> [страницы справки], достижимые страницы).

    D3 не проверяет размер страницы release_notes: это записи о выпусках, они
    растут с каждым выпуском, а не описывают текущее устройство. Ссылки,
    якоря и достижимость у неё проверяются как у обычной страницы.
    """
    pages, anchor_ids, covers, reachable = [], pr.mark_anchors, {}, set()
    if pr.docs is None or is_within(pr.docs, pr.decisions):
        return pages, anchor_ids, covers, reachable
    lim = pr.cfg["limits"]
    release_notes = pr.release_notes_path()
    agents = pr.file_path(pr.root / "AGENTS.md")
    for p in pr.walk_md(pr.docs, skip=(pr.wf, pr.decisions)):
        if pr.file_path(p) == agents and agents is not None:
            continue                      # это правила исполнителя, а не описание
        page = pr.page(p)
        # @trace docs/ru/codes.md#d1
        if page is None:
            rep.finding("D1", pr.rel(p), 0, tr("checker.docs.unreadable_utf8"))
            continue
        pages.append(page)
        r = pr.rel(p)
        check_anchors(pr, rep, page)
        check_links(pr, rep, page, "D1", forbid=pr.wf,
                    forbid_msg=tr("checker.docs.workflow_link"))
        # @trace docs/ru/codes.md#d3
        size = len(page.text.encode("utf-8"))
        if page.path != release_notes and (
                (lim["docs_lines"] and page.lines > lim["docs_lines"]) or
                (lim["docs_bytes"] and size > lim["docs_bytes"])):
            rep.finding("D3", r, 0, tr("checker.docs.page_too_large")
                    % (page.lines, size, lim["docs_lines"], lim["docs_bytes"]))
        # @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
        docs_rel = pr.rel(page.path)
        for aid, line in page.anchors.items():
            anchor_ids["%s#%s" % (docs_rel, aid)] = (page, line)
        # @trace docs/ru/codes.md#d2
        for line, slug in page.slug_dups:
            rep.finding("D2", r, line, tr("checker.docs.duplicate_heading_slug") % slug,
                     subject=slug, level="W")

    # D4: достижимость из указателя; у описания системы свой указатель
    # @trace docs/ru/codes.md#d4
    descr_pages = [p for p in pages if is_within(p.path, pr.descr)]
    reachable |= reachable_pages(pr, rep, pr.docs,
                                 [p for p in pages if not is_within(p.path, pr.descr)], pr.docs)
    if pr.descr is not None:
        reachable |= reachable_pages(pr, rep, pr.descr, descr_pages, pr.docs)

    # @trace docs/ru/codes.md#d6
    # covers в справке используют те же цели, что метки кода, и работают
    # также без отдельного каталога описания системы.
    for page in pages:
        if is_within(page.path, pr.descr):
            continue
        for m in RE_COVERS.finditer(page.masked):
            for target in [x.strip() for x in m.group(1).split(",") if x.strip()]:
                cid, err = resolve_mark(pr, target)
                if cid is None:
                    # @trace docs/ru/codes.md#d6,docs/ru/codes.md#t4
                    rep.finding(target_error_code(err, "D6"), pr.rel(page.path),
                                line_of(page.masked, m.start()),
                                "covers: %s" % err, subject=target)
                else:
                    # @trace docs/ru/codes.md#t3
                    check_target_status(pr, rep, cid, pr.rel(page.path),
                                        line_of(page.masked, m.start()))
                    # @trace docs/ru/codes.md#d6
                    covers.setdefault(cid, []).append(page)
    return pages, anchor_ids, covers, reachable


# @trace docs/ru/codes.md#l1,docs/ru/codes.md#l2
def check_edition_docs(pr, rep):
    """D1–D5 и D4 каждой дополнительной редакции; пары страниц: L1 и L2.

    Ключ languages включает редакции описания. Редакция по умолчанию (её
    каталог — docs) проверяется как обычное описание в check_docs; здесь —
    остальные: у каждой свои D1–D3, D5 и D4 от своего README.md, а пары
    страниц всех редакций сверяются по относительному пути: L1 — страницы
    нет в обязательной редакции (required), L2 — у пары разные наборы явных
    якорей. Без ключа languages проверка молчит.
    """
    langs = pr.cfg.get("languages")
    if not isinstance(langs, dict):
        return {}
    dirs = pr.editions
    default = langs["default"]
    lim = pr.cfg["limits"]

    def lang_of(path):
        """Язык редакции файла (самый глубокий каталог) или None."""
        best = None
        for lang, base in dirs.items():
            if is_within(path, base) and (
                    best is None or len(base.parts) > len(dirs[best].parts)):
                best = lang
        return best

    pages = {}
    for lang in [default] + sorted(x for x in dirs if x != default):
        base = dirs[lang]
        found = {}
        pages[lang] = found
        if base is None:
            continue
        for p in pr.walk_md(base, skip=(pr.wf, pr.decisions)):
            if lang_of(pr.file_path(p)) != lang:
                continue          # страница вложенной редакции: её проверит свой проход
            page = pr.page(p)
            if page is None:
                rep.finding("D1", pr.rel(p), 0, tr("checker.docs.unreadable_utf8"))
                continue
            found[os.path.relpath(str(p), str(base)).replace(os.sep, "/")] = page

    # D1–D5 дополнительных редакций: обычные ссылки остаются внутри редакции.
    for lang in sorted(x for x in dirs if x != default):
        base = dirs[lang]
        if base is None:
            continue
        for rel, page in sorted(pages[lang].items()):
            check_anchors(pr, rep, page)
            check_links(pr, rep, page, "D1", forbid=pr.wf,
                        forbid_msg=tr("checker.docs.workflow_link"))
            size = len(page.text.encode("utf-8"))
            if (lim["docs_lines"] and page.lines > lim["docs_lines"]) or \
                    (lim["docs_bytes"] and size > lim["docs_bytes"]):
                rep.finding("D3", pr.rel(page.path), 0,
                        tr("checker.docs.page_too_large")
                        % (page.lines, size, lim["docs_lines"], lim["docs_bytes"]))
            for line, slug in page.slug_dups:
                rep.finding("D2", pr.rel(page.path), line,
                         tr("checker.docs.duplicate_heading_slug") % slug,
                         subject=slug, level="W")
        # D4: достижимость из указателя своей редакции.
        reachable_pages(pr, rep, base, pages[lang].values(), base)

    # L1, L2: пары страниц по относительному пути внутри редакций.
    required = list(langs.get("required") or ())
    order = [default] + sorted(x for x in dirs if x != default)
    for rel in sorted({r for table in pages.values() for r in table}):
        present = [lang for lang in order if rel in pages[lang]]
        if not present:
            continue
        ref_lang = default if rel in pages[default] else present[0]
        ref = pages[ref_lang][rel]
        for lang in required:
            if lang in present or lang not in dirs:
                continue
            if dirs[lang] is None or not dirs[lang].is_dir():
                continue          # каталога нет: об этом скажет D4
            rep.finding("L1", pr.rel(ref.path), 0,
                    tr("checker.docs.missing_edition_page")
                    % (lang, pr.rel(dirs[lang] / rel)), subject=rel)
        ref_anchors = set(ref.anchors)
        for lang in present:
            if lang == ref_lang:
                continue
            anchors = set(pages[lang][rel].anchors)
            if anchors == ref_anchors:
                continue
            missing = sorted(ref_anchors - anchors)
            extra = sorted(anchors - ref_anchors)
            parts = []
            if missing:
                parts.append(tr("checker.docs.missing_anchors") + ", ".join(map(quoted, missing)))
            if extra:
                word = tr("checker.docs.extra_anchor") if len(extra) == 1 else tr("checker.docs.extra_anchors")
                parts.append("%s %s" % (word, ", ".join(map(quoted, extra))))
            rep.finding("L2", pr.rel(pages[lang][rel].path), 0,
                    tr("checker.docs.edition_anchor_mismatch")
                    % (ref_lang, "; ".join(parts)), subject=rel)
    return pages


# @trace docs/ru/codes.md#l3
def check_edition_links(pr, rep, pages):
    """L3: между редакциями переходят только на парную страницу другого языка.

    pages — {язык: {относительный путь: Page}} из check_edition_docs. Ссылка
    внутри своей редакции — обычная проверка D1; ссылка в другую редакцию
    годится, только если ведёт на страницу пары (тот же относительный путь).
    Внешние ссылки, якоря на своей странице и файлы вне редакций не
    проверяются.
    """
    langs = pr.cfg.get("languages")
    if not isinstance(langs, dict) or not pages:
        return
    dirs = pr.editions

    def lang_of(path):
        best = None
        for lang, base in dirs.items():
            if is_within(path, base) and (
                    best is None or len(base.parts) > len(dirs[best].parts)):
                best = lang
        return best

    for src in sorted(pages):
        for rel, page in sorted(pages[src].items()):
            for line, target in page.links:
                tpath, _ = resolve_target(page, target, pr)
                if tpath is None or is_within(tpath, pr.decisions):
                    continue
                dst = lang_of(tpath)
                if dst is None or dst == src:
                    continue
                pair = pr.file_path(dirs[dst] / rel) or dirs[dst] / rel
                if tpath != pair:
                    rep.finding("L3", pr.rel(page.path), line,
                            tr("checker.docs.edition_link_to_nonmatching_page")
                            % (src, dst, target, pr.rel(pair)), subject=rel)
