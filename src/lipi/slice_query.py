"""Полный срез без обрезки, записи файлов и запуска проверок проекта."""

import datetime
import re
import time

from .i18n import tr
from .checker.conventions import DECISION_HEADING, K_REFINES, RE_COVERS
from .checker.history import GitBlame
from .checker.model import anchor_region, line_of, resolve_target
from .checker.report import CODE_LEVELS, Report, level_of_project
from .checker.targets import check_target_status, current_link_source, decision_id
from .checker.workflow_index import index_path
from .slice_index import HEADING, SliceIndex, clean_title, document_order
from .slice_output import count_text
from .slice_roles import (
    file_role_locations, has_explicit_roles, matching_roles, role_counts, role_entries, role_states,
)

OPEN = {'iss': {'open', 'in progress'}, 'pln': {'new', 'in progress', 'pending acceptance'},
        'dsc': {'open'}, 'adr': {'proposed'}}
ORDERS = {
    'section': ('signals', 'obey', 'excerpt', 'entry', 'code', 'tests', 'context'),
    'decision': ('signals', 'obey', 'excerpt', 'entry', 'code', 'tests', 'context'),
    'page': ('signals', 'obey', 'concepts', 'entry', 'code', 'tests', 'context'),
    'code': ('signals', 'obey', 'concepts', 'tests', 'code', 'context'),
    'work': ('signals', 'obey', 'code', 'targets', 'context'),
    'diff': ('signals', 'obey', 'concepts', 'entry', 'code', 'tests', 'context'),
}
SUMMARY = ('errors', 'warnings', 'decisions', 'rules', 'concepts', 'entry',
           'code', 'layers', 'tests', 'open_work', 'targets')
STALENESS_CHEAP_FILE_LIMIT = 64
STALENESS_PRECISE_FILE_LIMIT = 16


def _document(index, target, relation='link', **extra):
    node = index.nodes[target]
    item = {'target': target, 'title': node['title'], 'relation': relation}
    if 'status' in node:
        item['status'] = node['status']
    item.update(extra)
    return item


def _is_rule(index, node):
    if node.get('repo') is not None:
        return False
    path = index.pr.rel(node['page'].path)
    return node['kind'] == 'section' and (path == 'AGENTS.md' or path.startswith('.agents/'))


def _excerpt(node):
    page = node['page']
    if node['kind'] == 'decision':
        line = next((num for num, text in enumerate(page.masked.splitlines(), 1)
                     if HEADING.match(text) and clean_title(text) == DECISION_HEADING), None)
        if line is None:
            return []
    else:
        line = node['line']
    rows = page.text.splitlines()
    selected = [rows[num - 1] for num in anchor_region(page, line)]
    text = re.sub(r'<a\s+id=[^>]*>\s*(?:</a>)?', '', '\n'.join(selected)).strip()
    return [{'text': text, 'lines': len(text.splitlines()), 'cut': False}] if text else []


def _status(index, target, place=None, own=False, relation='mark'):
    report = Report(level_of_project(index.pr.cfg))
    check_target_status(index.pr, report, target,
                        place['path'] if place else '',
                        place['targets'].get(target, place['line']) if place else 0,
                        relation=relation)
    result = []
    for path, line, level, code, message, _ in report.items:
        if own:
            local_target = target.partition('::')[2] if '::' in target else target
            current = (tr('slice.history.decision') if local_target.startswith('ADR-') else
                       tr('slice.history.plan') if target.startswith('PLN-') else tr('slice.history.work'))
            message = tr('slice.history.note') % (message.partition(' — ')[0], current)
        item = {'code': code, 'level': 'error' if level == 'E' else 'warning',
                'message': message, 'target': target}
        if path:
            item.update(path=path, line=line)
        if hasattr(index, 'sources'):
            item['repo'] = place.get('repo') if place else index.nodes.get(target, {}).get('repo')
        result.append(item)
    return result


def _covers(index, target):
    page = target.get('page')
    if page is None:
        return []
    allowed = (set(anchor_region(page, target['line']))
               if target['kind'] == 'section' else None)
    targets = []
    for match in RE_COVERS.finditer(page.masked):
        line = line_of(page.masked, match.start())
        if allowed is not None and line not in allowed:
            continue
        for token in match[1].split(','):
            repo = target.get('repo')
            aid = (index.mark(token.strip(), repo=repo) if hasattr(index, 'sources')
                   else index.mark(token.strip()))
            if aid:
                owner = index.sources.get(repo).project if repo is not None else index.pr
                place = {'path': owner.rel(page.path), 'line': line, 'targets': {aid: line}}
                if hasattr(index, 'sources'):
                    place['repo'] = repo
                targets.append((aid, place))
    return targets


def _link_status(index, target):
    if target.get('repo') is not None:
        # Чужие обычные ссылки дают контекст, а не импорт чужих проверок.
        return []
    page = target.get('page')
    if page is None or not current_link_source(index.pr, page.path):
        return []
    allowed = (set(anchor_region(page, target['line']))
               if target['kind'] == 'section' else None)
    signals = []
    for line, link in page.links:
        if allowed is not None and line not in allowed:
            continue
        path, _ = resolve_target(page, link, index.pr)
        aid = decision_id(index.pr, path) if path else None
        linked = index.pr.page(path) if aid else None
        if linked is not None:
            # Ссылка на конкретный файл однозначна даже при дубле номера.
            previous = index.pr.mark_work.get(aid)
            index.pr.mark_work[aid] = linked
            try:
                signals.extend(_status(index, aid, {
                    'path': index.pr.rel(page.path), 'line': line,
                    'targets': {aid: line}}, relation='link'))
            finally:
                if previous is None:
                    index.pr.mark_work.pop(aid, None)
                else:
                    index.pr.mark_work[aid] = previous
    return signals


def _decision_family(index, seeds, bases=False):
    """Направленные цепочки: уточнения вниз, основания отдельно вверх.

    Ветка останавливается на неактивном решении, но возвращает его для
    сигнала. Поворот через предка к соседним уточнениям не разрешён.
    """
    found = dict(seeds)
    graphs = [index.refinements]
    if bases:
        graphs.append(index.refines)
    for graph in graphs:
        seen, frontier = set(), set(seeds)
        while frontier:
            following = set()
            for aid in sorted(frontier, key=document_order):
                if aid in seen:
                    continue
                seen.add(aid)
                if index.nodes[aid].get('status') != 'accepted':
                    continue
                for other in sorted(graph.get(aid, ()), key=document_order):
                    found.setdefault(other, 'link')
                    if other not in seen:
                        following.add(other)
            frontier = following
    return found


# @trace docs/ru/slice.md#staleness
def _staleness(index, concepts, places):
    from .checker.reviews import ReviewContext, load_reviews
    registry = load_reviews(index.pr.root)
    index._reviews_present = registry is not None
    index._reviewed_pairs = set()
    if hasattr(index, 'sources'):
        concepts = {aid for aid in concepts if index.nodes.get(aid, {}).get('repo') is None}
        places = [place for place in places if place.get('repo') is None]
    cfg = index.pr.cfg
    level = cfg.get('codes', {}).get('A4', CODE_LEVELS['A4'])
    eligible = sorted({id(place): place for place in places
                       if level != 'off' and concepts.intersection(place['targets'])}.values(),
                      key=lambda place: (2 if place['test'] else 0 if place['entry'] else 1,
                                         place['path'], place['line']))
    check = {'state': 'full', 'checked': 0, 'total': len(eligible)}
    if index.pr.git_root is None:
        check['state'] = 'no-git'
        return [], check
    if not eligible:
        return [], check
    reviews = None
    reviewed_places = {}
    if registry and registry['entries']:
        local_index = index.indices[None] if hasattr(index, 'sources') else index
        reviews = ReviewContext(index.pr, index=local_index)
        reviewed_places = {(pair['source']['path'], pair['place']['line'], pair['target_id']): pair
                           for pair in reviews.pairs}
    # Повторная сборка после потери соседа сохраняет время запуска, но
    # получает свежие кэши и лимиты истории.
    if not hasattr(index, '_uncommitted_time'):
        index._uncommitted_time = time.time()
    history = GitBlame(index.pr.root, uncommitted_time=index._uncommitted_time)
    doc_times = {}
    for aid in sorted(concepts):
        node = index.nodes.get(aid)
        if node and node['kind'] == 'section':
            page = node['page']
            timestamp = history.lines_time(index.pr.rel(page.path),
                                           anchor_region(page, node['line']))
            if timestamp:
                doc_times[aid] = timestamp
    history.preload_staleness([
        (place['path'], place['history_line'], index.boundaries[place['path']], doc_times[aid])
        for place in eligible for aid in sorted(doc_times.keys() & place['targets'].keys())
    ], max_cheap_files=STALENESS_CHEAP_FILE_LIMIT,
       max_precise_files=STALENESS_PRECISE_FILE_LIMIT)
    signals = []
    for place in eligible:
        checked = True
        for aid in sorted(concepts.intersection(place['targets'])):
            doc_time = doc_times.get(aid)
            if doc_time is None or not history.region_checked(
                    place['path'], place['history_line'], index.boundaries[place['path']],
                    since=doc_time):
                checked = False
                continue
            line = place['targets'][aid]
            code_time = history.stale_region_time(place['path'], place['history_line'],
                                                  index.boundaries[place['path']], since=doc_time)
            if code_time and code_time > doc_time:
                pair = reviewed_places.get((place['path'], place['line'], aid))
                if pair is not None and reviews.acknowledges(pair):
                    index._reviewed_pairs.add(pair['id'])
                    continue
                def stamp(value):
                    pattern = '%Y-%m-%d %H:%M:%S.%f UTC' if isinstance(value, float) else '%Y-%m-%d %H:%M:%S UTC'
                    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).strftime(pattern)
                signals.append({'code': 'A4', 'level': level,
                                'message': tr('slice.signal.stale') % (stamp(code_time), stamp(doc_time)),
                                'target': aid, 'path': place['path'], 'line': line})
        check['checked'] += checked
    if check['checked'] < check['total']:
        check['state'] = 'partial'
    return signals, check


def _neighbors(index, seeds, depth, incoming_only=False):
    seen, frontier, result = set(seeds), set(seeds), {}
    if index.pr.wf:
        seen.update(aid for aid, node in index.nodes.items()
                    if node['page'].path == index.pr.wf / 'masterplan.md'
                    or index_path(index.pr.wf, node['page'].path))
    for distance in range(1, depth + 1):
        following = set()
        for aid in frontier:
            adjacent = set(index.incoming.get(aid, ()))
            if not (incoming_only and distance == 1):
                adjacent.update(index.outgoing.get(aid, ()))
            for other in adjacent - seen:
                result[other] = distance
                following.add(other)
        seen.update(following)
        frontier = following
    return result


def _explicit_decisions(index):
    return index.local_explicit_decisions | getattr(index, '_review_explicit_decisions', set())


def _related(index, seeds, places, include_seeds=False):
    """Прямые ссылки и совместные метки, без обхода соседних срезов."""
    related = {}
    for item in sorted(seeds, key=document_order):
        for source in sorted(index.incoming.get(item, ()), key=document_order):
            owner = index.nodes.get(item)
            if (owner and index.nodes[source]['kind'] == 'decision'
                    and index.nodes[index.page_ids[owner['page'].path]]['kind'] == 'decision'):
                continue
            related[source] = 'link'
    for place in places:
        for item in place['targets']:
            if item not in seeds:
                related.setdefault(item, 'mark')
    if include_seeds:
        for item in sorted(seeds, key=document_order):
            related.setdefault(item, 'mark')
    if hasattr(index, 'sources'):
        related = {item: relation for item, relation in related.items()
                   if index.nodes[item].get('repo') is None
                   or item in _explicit_decisions(index)}
    return related


def _with_refinements(index, related, own_decisions=()):
    if hasattr(index, 'sources'):
        for item in list(related):
            if (index.nodes[item].get('repo') is not None
                    and item not in _explicit_decisions(index)):
                del related[item]
    decision_seeds = {item: relation for item, relation in related.items()
                      if index.nodes[item]['kind'] == 'decision'}
    family = _decision_family(index, decision_seeds)
    refinements = family.keys() - decision_seeds.keys()
    related.update(family)
    for item in sorted(own_decisions, key=document_order):
        if (hasattr(index, 'sources') and index.nodes[item].get('repo') is not None
                and item not in _explicit_decisions(index)):
            continue
        family = _decision_family(index, {item: 'link'}, bases=True)
        refinements.update(family.keys() - {item})
        related.update(family)
    return refinements


def _seeds_for_target(index, aid):
    node = index.nodes[aid]
    if node['kind'] == 'page':
        return {aid, *index.anchors[node['page'].path]}
    return {aid}


def _work_obligations(index, work):
    """Обязательства прямых целей работы; места их кода не раскрываются."""
    related, via, refinements, signals = {}, {}, set(), []
    for goal in sorted(index.outgoing.get(work, ()), key=document_order):
        seeds = _seeds_for_target(index, goal)
        places = {id(place): place for item in seeds for place in index.by_target.get(item, [])}
        found = _related(index, seeds, places.values())
        # Прямо названное решение или правило также нужно соблюдать.
        found.setdefault(goal, 'link')
        signals.extend(_link_status(index, index.nodes[goal]))
        for covered, place in _covers(index, index.nodes[goal]):
            signals.extend(_status(index, covered, place))
            if index.nodes[covered]['kind'] == 'decision':
                found.setdefault(covered, 'mark')
        decisions = {goal} if index.nodes[goal]['kind'] == 'decision' else set()
        refinements.update(_with_refinements(index, found, decisions))
        for item, relation in found.items():
            if index.nodes[item]['kind'] != 'decision' and not _is_rule(index, index.nodes[item]):
                continue
            related.setdefault(item, relation)
            via.setdefault(item, set()).add(goal)
    return related, via, refinements, signals


# @trace docs/ru/slice.md#blocks,docs/ru/slice.md#summary,docs/ru/slice.md#json
def build_slice(pr, query, depth=1, layers=None, role=None):
    """Возвращает полный JSON-договор и код выхода; слой применяется до сводки."""
    if pr.cfg.get('repos'):
        from .repo_slice import build_repo_slice
        return build_repo_slice(pr, query, depth, layers, role=role)
    index = SliceIndex(pr)
    target, error = index.resolve(query)
    if error:
        return error, 1
    return _build_slice(index, target, depth, layers, role=role)


# @trace docs/ru/slice-diff.md#response,docs/ru/slice-diff.md#json
def build_diff_slice(pr, base=None, staged=False, depth=1, layers=None):
    """Связи изменённых мест; один индекс и общий ограниченный проход A4."""
    from .slice_diff import collect_diff
    from .slice_diff_response import diff_target

    if pr.cfg.get('repos'):
        from .repo_slice import build_repo_diff_slice
        return build_repo_diff_slice(pr, base, staged, depth, layers)
    index = SliceIndex(pr)
    diff = collect_diff(index, base=base, staged=staged)
    return _build_slice(index, diff_target(base), depth, layers, diff=diff)


def _qualified_layer(place):
    return (place['repo'] + '::' if place.get('repo') else '') + place['layer']


def _build_slice(index, target, depth, layers, diff=None, role=None):
    pr = index.pr
    connected = hasattr(index, 'sources')
    kind, aid = target['kind'], target['target']
    own_work = target.get('_work_id', aid if kind in ('work', 'decision') else None)
    own_places = index.by_file.get(aid, []) if kind == 'code' else []
    contract_targets = set()
    if kind == 'diff':
        seeds = diff['seeds'] & index.nodes.keys()
        contract_targets = diff.get('sections', {}).keys() | diff.get('decisions', set())
        seeds.update(target for target in contract_targets if target in index.nodes
                     and diff['sections'].get(target, {}).get('after', True) is not None)
    elif kind == 'page':
        seeds = {aid, *index.anchors[target['page'].path]}
        if own_work:
            seeds.add(own_work)
    elif kind == 'code':
        seeds = {item for place in own_places for item in place['targets']}
    else:
        seeds = {aid}
    concepts = {item for item in seeds if index.nodes.get(item, {}).get('kind') == 'section'}
    contract_counts = {}
    document_diff = diff is not None and 'sections' in diff
    if document_diff:
        from .slice_diff_response import collect_contract_places
        all_places, signal_places, contract_counts = collect_contract_places(index, diff)
    elif kind == 'code':
        selected = {id(place): place for item in concepts for place in index.by_target.get(item, [])
                    if place.get('repo') is not None or place['path'] != aid}
        # Метки на работы самого файла дают сигналы, но не соседние места кода.
        signal_places = list(own_places) + list(selected.values())
        all_places = list(selected.values())
    else:
        marker_targets = diff['seeds'] if diff is not None else seeds
        selected = {id(place): place for item in marker_targets for place in index.by_target.get(item, [])}
        if diff is not None:
            selected = {key: place for key, place in selected.items()
                        if place.get('repo') is not None
                        or (place['path'], place['line']) not in diff['changed']}
        signal_places = list(selected.values())
        all_places = list(selected.values())
    all_places.sort(key=index.place_order)
    places = [place for place in all_places if not layers or _qualified_layer(place) in layers]
    blocks = {name: [] for name in ORDERS[kind]}
    notes = []

    related_places = signal_places if document_diff else all_places
    related = _related(index, seeds, own_places if kind == 'code' else related_places,
                       include_seeds=kind in ('code', 'diff'))
    own_signals = _status(index, own_work, own=True) if own_work else []
    signals = _link_status(index, target)
    for item, place in _covers(index, target):
        signals.extend(_status(index, item, place))
        if index.nodes[item]['kind'] == 'decision':
            related.setdefault(item, 'mark')
    own_decisions = {own_work} if own_work and index.nodes[own_work]['kind'] == 'decision' else set()
    if kind == 'diff':
        own_decisions.update(item for item in seeds if index.nodes[item]['kind'] == 'decision')
        for item in sorted(seeds, key=document_order):
            signals.extend(_link_status(index, index.nodes[item]))
            for covered, place in _covers(index, index.nodes[item]):
                signals.extend(_status(index, covered, place))
                if index.nodes[covered]['kind'] == 'decision':
                    related.setdefault(covered, 'mark')
    refinement_targets = _with_refinements(index, related, own_decisions)
    via = {item: {aid} for item in related} if kind == 'work' else {}
    works = {aid} if kind == 'work' else {
        item for item in seeds if kind == 'diff' and index.nodes[item]['kind'] == 'work'}
    for work in sorted(works, key=document_order):
        found, origins, refinements, statuses = _work_obligations(index, work)
        refinement_targets.update(refinements)
        signals.extend(statuses)
        for item, relation in found.items():
            related.setdefault(item, relation)
            via.setdefault(item, set()).update(origins[item])
    # T3 относится и к другим основаниям того же объявления.
    for place in signal_places:
        for item in place['targets']:
            if item not in (aid, own_work):
                signals.extend(_status(index, item, place))
    if kind == 'diff':
        # У удалённой метки может уже не быть текущего места, но её статус
        # остаётся частью проверки связанных целей.
        for item in sorted(seeds, key=document_order):
            if not any(signal['code'] == 'T3' and signal['target'] == item for signal in signals):
                signals.extend(_status(index, item))
    for item, relation in related.items():
        if item in (aid, own_work):
            if ('obey' in blocks and index.nodes[item]['kind'] == 'decision'
                    and index.nodes[item].get('status') == 'accepted'):
                blocks['obey'].append(_document(index, item, relation))
            continue
        node = index.nodes[item]
        status = node.get('status')
        prefix = item.rpartition('::')[2].partition('-')[0].lower()
        if status in OPEN.get(prefix, set()):
            signals.append({'code': None, 'level': 'info',
                            'message': '%s %s — %s (%s)' % (item, status, node['title'],
                                tr('slice.relation.refines') % K_REFINES if item in refinement_targets else
                                tr('slice.relation.mark') if relation == 'mark' else
                                (tr('slice.relation.section') if kind == 'section' else tr('slice.relation.target'))),
                            'target': item})
        elif status in ('superseded', 'rejected'):
            # Сигнал с местом уже добавлен для совместной метки.
            if not any(signal['code'] == 'T3' and signal['target'] == item for signal in signals):
                signals.extend(_status(index, item))
        elif 'obey' in blocks:
            is_rule = _is_rule(index, node)
            if (node['kind'] == 'decision' and status == 'accepted') or is_rule:
                extra = {'via': sorted(via[item], key=document_order)} if kind == 'work' else {}
                blocks['obey'].append(_document(index, item, relation, **extra))
    stale_signals, staleness = _staleness(index, concepts, signal_places)
    signals.extend(stale_signals)
    unique = {}
    for signal in signals:
        key = (signal['code'], signal['target'], signal.get('repo'),
               signal.get('path', ''), signal.get('line', 0))
        unique[key] = signal
    signals = sorted(unique.values(), key=lambda item: (
        {'error': 0, 'warning': 1, 'info': 2}[item['level']],
        item.get('path', item['target']), item.get('line', 0), item['target']))
    blocks['signals'] = own_signals + signals

    display_targets = diff['seeds'] | contract_targets if kind == 'diff' else seeds
    own_locations = {}
    if own_places:
        layered_own_places = (place for place in own_places
                              if not layers or _qualified_layer(place) in layers)
        own_locations = file_role_locations(layered_own_places, concepts, role)
    if 'concepts' in blocks:
        for item in sorted(display_targets if kind == 'diff' else concepts, key=document_order):
            node = index.nodes.get(item)
            title = node['title'] if node else item
            if diff and item in diff.get('sections', {}):
                from .slice_diff_response import snapshot_title
                title = snapshot_title(item, diff['sections'][item])
            concept = {'target': item, 'title': title,
                       'code_count': (contract_counts.get(item, 0) if item in contract_targets
                                      else index.count(item))}
            if item in own_locations:
                concept['locations'] = own_locations[item]
            blocks['concepts'].append(concept)
    has_roles = bool(own_locations)
    states_by_location = {}
    visible_places = []
    for place in places:
        matched_targets = sorted(place['targets'].keys() & display_targets)
        links = matching_roles(place, matched_targets) if kind != 'diff' else {}
        if links:
            states = role_states(links, role)
            if role is not None and not states:
                continue
            address = (place.get('repo'), place['path'], place['line'])
            states_by_location.setdefault(address, set()).update(states)
            show_roles = role is not None or states != {'unassigned'}
        else:
            show_roles = False
        visible_places.append(place)
        via = matched_targets[0]
        item = {key: place[key] for key in ('path', 'line', 'symbol', 'layer')}
        if connected:
            item['repo'] = place.get('repo')
            item['_test'] = place['test']
        if (kind == 'diff' or place['test']
                or (role is None and not has_explicit_roles(place.get('target_roles', {})))):
            item['line'] = place['targets'][via]
        if 'reasons' in place:
            item['reasons'] = place['reasons']
            if place.get('side') == 'before':
                item['side'] = 'before'
            elif place.get('links', {}).get(via) == 'removed':
                item['line'] = place['line']
        if kind == 'work':
            destination = 'code'
        elif place['test']:
            destination = 'tests'
        elif place['entry'] and 'entry' in blocks:
            destination = 'entry'
        else:
            destination = 'code'
        if destination != 'tests':
            item['via'] = via
        if kind == 'diff':
            item['matched_targets'] = matched_targets
        if show_roles:
            item['target_roles'] = role_entries(links)
            has_roles = True
        blocks[destination].append(item)
    if 'targets' in blocks:
        for item in sorted(index.outgoing.get(aid, ()), key=document_order):
            blocks['targets'].append(_document(index, item, code_count=index.count(item)))
    neighbors = _neighbors(index, seeds, depth, incoming_only=kind == 'work')
    represented = {item['target'] for name in ('obey', 'targets', 'concepts')
                   for item in blocks.get(name, [])}
    represented.update(signal['target'] for signal in blocks['signals'])
    for item in sorted(neighbors, key=document_order):
        if item not in represented:
            blocks['context'].append(_document(index, item, depth=neighbors[item]))
    if 'obey' in blocks:
        blocks['obey'].sort(key=lambda item: document_order(item['target']))
    if 'excerpt' in blocks and (target.get('repo') is not None or
                               all_places or related or neighbors or blocks['signals']):
        blocks['excerpt'] = _excerpt(target)

    if kind == 'diff':
        count = diff['unmarked']
        notes.extend([{'code': 'diff-review', 'text': tr('slice.note.diff_review')},
                      {'code': 'diff-unmarked',
                       'text': tr('slice.note.diff_unmarked') % count_text(count, 'diff_locations')}])
        if diff.get('unanchored'):
            notes.append({'code': 'diff-unanchored',
                          'text': tr('slice.note.diff_unanchored') % diff['unanchored']})
    elif not (own_places if kind == 'code' else all_places):
        messages = {
            'section': ('no-marks', tr('slice.note.no_marks')),
            'page': ('no-marks', tr('slice.note.no_marks')),
            'decision': ('no-code', tr('slice.note.decision_no_code')),
            'code': ('file-no-marks', tr('slice.note.file_no_marks')),
            'work': ('work-empty', tr('slice.note.work_empty')),
        }
        if kind != 'work' or not blocks.get('targets'):
            code, text = messages[kind]
            notes.append({'code': code, 'text': text})
    configured = list(dict.fromkeys(pr.cfg.get('layers', {}).values()))
    expected_layers = list(dict.fromkeys(layers or configured))
    if connected:
        expected_layers = [layer for layer in expected_layers if '::' not in layer or
                           (index.sources.get(layer.partition('::')[0]) is not None
                            and index.sources.get(layer.partition('::')[0]).state != 'unavailable')]
    missing = [layer for layer in expected_layers
               if not any(_qualified_layer(place) == layer for place in places)]
    if missing:
        notes.append({'code': 'layers-no-marks', 'text': tr('slice.note.layers_no_marks') % ', '.join(missing)})
    state = staleness['state']
    if state == 'no-git':
        key = 'repo.note.local_staleness_no_git' if connected else 'slice.note.no_git'
        notes.append({'code': 'no-git', 'text': tr(key)})
    elif staleness['total']:
        coverage_key = 'repo.note.local_staleness_' if connected else 'slice.note.staleness_'
        notes.append({'code': 'staleness-' + state,
                      'text': tr(coverage_key + state)
                              % (staleness['checked'], staleness['total'])})
    summary = dict.fromkeys(SUMMARY, 0)
    for signal in blocks['signals']:
        if signal['level'] in ('error', 'warning'):
            summary[signal['level'] + 's'] += 1
        elif signal['code'] is None:
            summary['open_work'] += 1
    for item in blocks.get('obey', []):
        summary['decisions' if index.nodes[item['target']]['kind'] == 'decision' else 'rules'] += 1
    for key in ('concepts', 'entry', 'tests', 'targets'):
        summary[key] = len(blocks.get(key, []))
    non_tests = [place for place in visible_places if not place['test']]
    summary['tests'] = len(visible_places) - len(non_tests)
    summary['code'] = len(non_tests)
    summary['layers'] = len({place['layer'] for place in non_tests})
    if kind != 'diff' and (role is not None or has_roles):
        summary['roles'] = role_counts(role, states_by_location.values())
    if index._reviews_present:
        summary['reviewed_pairs'] = len(index._reviewed_pairs)
    public_target = {key: value for key, value in target.items() if key not in ('page', 'line') and not key.startswith('_')}
    response = {'schema': 1, 'target': public_target, 'summary': summary,
                'blocks': [{'kind': name, 'items': blocks[name], 'omitted': 0, 'hint': []}
                           for name in ORDERS[kind] if blocks[name]],
                'incomplete': state == 'partial',
                'notes': notes, 'checks': {'staleness': staleness}}
    if kind == 'diff':
        from .slice_diff_response import diff_checks
        response['checks']['diff'] = diff_checks(diff, target['_base'], all_places)
    if connected:
        cross_locations = {(place['repo'], place['path'], place['line']) for place in signal_places
                           if any(index.nodes[aid]['repo'] != place['repo']
                                  for aid in place['targets'])}
        cross_locations.update((place['repo'], place['path'], place['line']) for place in all_places
                               if place.get('repo') and place.get('links'))
        response['_cross_repo_locations'] = len(cross_locations)
    return response, 0
