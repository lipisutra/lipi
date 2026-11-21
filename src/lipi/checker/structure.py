"""Граф связей проекта и цепочки устаревания."""

from .conventions import K_STATUS, MASTERPLAN, RE_DECISION_NAME, RE_DOC_NAME
from .model import resolve_target
from .trace import touched_anchors, touched_places


# --- Структура ---------------------------------------------------------------

def build_structure(pr, pages, anchor_ids, covers, docs, tag_lines, mp_refs, reachable, extra):
    """Граф связей проекта: узлы и рёбра, которые чекер уже вычислил.

    Узлы: doc (страница описания), work (рабочий документ), anchor (явный
    якорь Markdown-файла, id «путь/страница.md#якорь» от корня), code (файл кода с метками
    @trace), rules (файл правил), file (прочее: мастер-план, указатель).
    Рёбра: link (страница -> файл, с якорем в поле anchor), anchor (якорь ->
    страница), trace (код -> якорь или работа), covers (справка -> якорь или работа), ref
    (мастер-план -> работа). Граф — производное представление, источник
    истины не он.
    """
    nodes, edges = [], []
    node_ids = set()

    def target_path(target, page):
        external = pr.mark_external.get(target)
        if external is not None:
            source = external['source']
            return '%s::%s' % (source.name, source.project.rel(page.path))
        return pr.rel(page.path)

    def add(node):
        if node["id"] not in node_ids:
            node_ids.add(node["id"])
            nodes.append(node)

    def anchor_id(tpath, anchor):
        """id узла-якоря для ссылки: «путь/страница.md#якорь» от корня проекта."""
        if not anchor or tpath.suffix.lower() != ".md":
            return anchor
        tp = pr.page(tpath)
        if tp is not None and anchor in tp.anchors:
            rel = pr.rel(tpath)
            return "%s#%s" % (rel, anchor)
        return anchor

    def emit_links(page, source_id):
        for line, target in page.links:
            tpath, anchor = resolve_target(page, target, pr)
            if tpath is None:
                continue
            edge = {"from": source_id, "to": pr.rel(tpath), "type": "link", "line": line}
            if anchor:
                edge["anchor"] = anchor_id(tpath, anchor)
            edges.append(edge)

    for page in pages:
        r = pr.rel(page.path)
        add({"id": r, "type": "doc", "path": r, "h1": page.h1,
             "lines": page.lines, "anchors": list(page.anchors),
             "reachable": page.path in reachable})
        emit_links(page, r)

    for aid, (page, line) in anchor_ids.items():
        r = target_path(aid, page)
        add({"id": aid, "type": "anchor", "path": r, "line": line})
        edges.append({"from": aid, "to": r, "type": "anchor", "line": line})

    for did, d in sorted(docs.items()):
        add({"id": did.upper(), "type": "work", "path": pr.rel(d["page"].path),
             "prefix": d["prefix"], "status": d.get("status"), "title": d.get("title")})

    for did, page in sorted(pr.mark_work.items()):
        local_id = pr.mark_external.get(did, {}).get('target', did)
        add({"id": did, "type": "work", "path": target_path(did, page),
             "prefix": local_id.partition("-")[0].lower(),
             "status": page.header().get(K_STATUS), "title": page.h1})

    for cfile, places in sorted(tag_lines.items()):
        add({"id": cfile, "type": "code", "path": cfile})
        for line, ids in places:
            for aid in ids:
                edges.append({"from": cfile, "to": aid, "type": "trace", "line": line})

    for aid, help_pages in sorted(covers.items()):
        for page in help_pages:
            edges.append({"from": pr.rel(page.path), "to": aid, "type": "covers"})

    if mp_refs and pr.wf is not None:
        mp = pr.wf / MASTERPLAN
        if pr.file_path(mp) is not None and mp.is_file():
            mp_id = pr.rel(mp)
            add({"id": mp_id, "type": "file", "path": mp_id})
            for line, did in mp_refs:
                edges.append({"from": mp_id, "to": did.upper(), "type": "ref", "line": line})

    for item in extra:
        page, source, kind = item["page"], item["source"], item["type"]
        if page is None:
            continue
        if kind in ("file", "rules"):
            add({"id": source, "type": kind, "path": source})
        emit_links(page, source)

    # Раздел вне описания тоже имеет узел файла; известные правила и работы
    # уже добавлены выше под своими видами.
    for aid, (page, _) in anchor_ids.items():
        r = target_path(aid, page)
        if r not in node_ids:
            foreign = aid in pr.mark_external
            kind = ("rules" if not foreign and
                    (r == "AGENTS.md" or r.startswith(".agents/")) else "file")
            add({"id": r, "type": kind, "path": r})
            if not foreign:
                emit_links(page, r)

    node_types, edge_types = {}, {}
    for n in nodes:
        node_types[n["type"]] = node_types.get(n["type"], 0) + 1
    for e in edges:
        edge_types[e["type"]] = edge_types.get(e["type"], 0) + 1
    return {"nodes": nodes, "edges": edges,
            "counts": {"nodes": len(nodes), "edges": len(edges),
                       "nodeTypes": node_types, "edgeTypes": edge_types}}


# @trace docs/ru/codes.md#t2
def work_references(pr, docs):
    """Работа -> (страница, якорь|None): список id работ, которые на это ссылаются."""
    refs = {}

    def add(key, did):
        refs.setdefault(key, []).append(did)

    for did, d in docs.items():
        owner_pages = [(d["page"], did)]
        parent = d["page"].path.parent
        if parent != pr.decisions and (RE_DOC_NAME.match(parent.name)
                or (d['prefix'] == 'adr' and RE_DECISION_NAME.fullmatch(parent.name))):
            for p in pr.walk_md(parent):
                if pr.file_path(p) != d["page"].path:
                    page = pr.page(p)
                    if page is not None:
                        owner_pages.append((page, did))
        for page, owner in owner_pages:
            for _, target in page.links:
                tpath, anchor = resolve_target(page, target, pr)
                if tpath is None:
                    continue
                add((pr.rel(tpath), anchor if anchor else None), owner)
    return refs


def build_stale(pr, pages, anchor_ids, covers, tag_groups, docs, changed):
    """Цепочка устаревания: изменённый код под меткой -> якорь -> раздел -> справка -> работы."""
    # Даты из разных репозиториев не определяют согласованность их связи.
    anchor_ids = {aid: value for aid, value in anchor_ids.items()
                  if aid not in pr.mark_external}
    refs = work_references(pr, docs)
    code_touched = {}
    for f, ranges in changed.items():
        for i, line in touched_places(ranges, tag_groups.get(f, [])):
            code_touched.setdefault(i, []).append((f, line))
    docs_touched = set()
    for page in {page for page, _ in anchor_ids.values()}:
        ranges = changed.get(pr.rel(page.path))
        if ranges:
            rel = pr.rel(page.path)
            docs_touched.update("%s#%s" % (rel, aid)
                                for aid in touched_anchors(ranges, page))
    stale = []
    for i, places in sorted(code_touched.items()):
        if i not in anchor_ids or i in docs_touched:
            continue
        page, _ = anchor_ids[i]
        page_rel = pr.rel(page.path)
        name = i.rpartition("#")[2]
        covers_list = [pr.rel(cp.path) for cp in covers.get(i, [])]
        works = set(refs.get((page_rel, name), [])) | set(refs.get((page_rel, None), []))
        for cp in covers_list:
            works |= set(refs.get((cp, None), []))
        works = [{"id": w.upper(), "status": docs[w].get("status")}
                 for w in sorted(works) if w in docs]
        for f, fline in places:
            stale.append({"file": f, "line": fline, "anchor": i,
                          "page": page_rel, "covers": covers_list, "works": works})
    return stale
