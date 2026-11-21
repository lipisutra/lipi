"""Срез подключений: общий индекс, локальная история, явные адреса ответа."""

import os
import re
from shlex import quote
from urllib.parse import unquote

from .i18n import plural_form, tr
from .repo_output import repository_status
from .slice_index import document_order


def _split(target):
    repo, separator, local = target.partition('::')
    return (repo, local) if separator else (None, target)


# @trace docs/ru/slice-output.md#repo-search
def _suggestions(index, query):
    path = unquote(query)
    if (not query.strip() or path in ('.', '..')
            or any(separator in path for separator in ('#', '/', '\\'))
            or re.fullmatch(r'\S+\.[a-zA-Z][\w-]*', path)):
        return []
    suggestions = []
    for source in index.sources.all:
        if source.name is None or 'docs' not in source.read or not source.has_config:
            continue
        if source.state == 'unavailable':
            continue
        target = source.name + '::' + query
        if os.name == 'nt':
            # PowerShell распознаёт и типографские одинарные кавычки.
            quoted = "'%s'" % re.sub(r"['‘’‚‛]", r'\g<0>\g<0>', target)
        else:
            quoted = quote(target)
        command = 'lipi slice -- ' if target.startswith('-') else 'lipi slice '
        suggestions.append({'repo': source.name, 'command': command + quoted})
    return suggestions


def _empty(target, role=None):
    from .slice_query import SUMMARY
    from .slice_roles import role_counts
    summary = dict.fromkeys(SUMMARY, 0)
    if role:
        summary['roles'] = role_counts(role)
    return {'schema': 1,
            'target': {key: value for key, value in target.items()
                       if key not in ('page', 'line', 'unavailable') and not key.startswith('_')},
            'summary': summary, 'blocks': [], 'incomplete': True,
            'notes': [], 'checks': {'staleness': {'state': 'full', 'checked': 0, 'total': 0}}}


def _build_stable(index, target, depth, layers, diff=None, role=None):
    """Новый сбой чтения убирает источник и пересобирает зависящие от него связи."""
    from .slice_query import _build_slice
    while True:
        before = {source.name for source in index.sources.all if source.state == 'unavailable'}
        if target.get('repo') in before:
            return _empty(target, role), 0
        if diff is not None and before:
            diff['seeds'] = {aid for aid in diff['seeds'] if _split(aid)[0] not in before}
        try:
            response = _build_slice(index, target, depth, layers, diff=diff, role=role)
        except KeyError:
            after = {source.name for source in index.sources.all if source.state == 'unavailable'}
            if after == before:
                raise
        else:
            after = {source.name for source in index.sources.all if source.state == 'unavailable'}
            if after == before:
                return response
        index.prune_unavailable()


# @trace docs/ru/slice.md#repos
def _finish(index, response, *, contract_counts=()):
    """После всех чтений исключает недоступные источники до подсчёта и обрезки."""
    from .slice_query import SUMMARY
    index.prune_unavailable()
    status = repository_status(index.pr)
    unavailable = {record['repo'] for record in status['checks']['repos']
                   if record['state'] == 'unavailable'}
    order = {record['repo']: number for number, record in enumerate(status['checks']['repos'])}
    response.setdefault('checks', {}).update(status['checks'])
    response['reproducible'] = status['reproducible']
    response['incomplete'] = response.get('incomplete', False) or status['incomplete']
    response.setdefault('notes', []).extend(status['notes'])
    cross_locations = response.pop('_cross_repo_locations', None)
    target_repo = response.get('target', {}).get('repo')
    if (cross_locations is not None and target_repo not in unavailable
            and (cross_locations or not unavailable)):
        cross_note = tr('repo.note.cross_staleness.' + plural_form(cross_locations)) % cross_locations
    else:
        cross_note = tr('repo.note.cross_staleness')
    response['notes'].append({'code': 'cross-repo-staleness', 'text': cross_note})
    if 'error' in response:
        for candidate in response.get('candidates', []):
            repo, target = _split(candidate['target'])
            candidate.update(repo=repo or candidate.get('repo'), target=target)
        if response.pop('_local_title_miss', False):
            suggestions = _suggestions(index, response['query'])
            if suggestions:
                response['suggestions'] = suggestions
        return response

    target = response['target']
    target_repo, target_id = _split(target['target'])
    target.update(repo=target_repo, target=target_id)
    target.pop('unavailable', None)
    if target_repo in unavailable:
        target.update(title='')
        target.pop('found', None)
        response['blocks'] = []
        response['notes'] = [note for note in response['notes'] if note['code'].startswith('repos-')
                             or note['code'] == 'cross-repo-staleness']
        response['checks']['staleness'] = {'state': 'full', 'checked': 0, 'total': 0}
    response['checks']['staleness']['scope'] = 'local'

    blocks = []
    summary = dict.fromkeys(SUMMARY, 0)
    non_tests = []
    for block in response['blocks']:
        kind = block['kind']
        items = []
        for item in block['items']:
            if kind == 'excerpt':
                items.append(item)
                continue
            raw_target = item.get('target')
            item_repo, local_target = _split(raw_target) if raw_target else (item.get('repo'), None)
            source_repo = item.get('repo', item_repo)
            via = item.get('via')
            origins = [via] if isinstance(via, str) else via or []
            if (source_repo in unavailable or item_repo in unavailable
                    or (origins and all(_split(origin)[0] in unavailable for origin in origins))):
                continue
            if isinstance(via, list):
                item['via'] = [origin for origin in via if _split(origin)[0] not in unavailable]
            if kind == 'signals':
                item.update(repo=source_repo, target_repo=item_repo, target=local_target)
            elif raw_target is not None:
                item.update(repo=item_repo, target=local_target)
                if 'code_count' in item and raw_target not in contract_counts:
                    item['code_count'] = index.count(raw_target)
            else:
                item['repo'] = source_repo
            if kind == 'obey':
                summary['decisions' if index.nodes[raw_target]['kind'] == 'decision' else 'rules'] += 1
            if kind in ('entry', 'code', 'tests'):
                if item.pop('_test', kind == 'tests'):
                    summary['tests'] += 1
                else:
                    non_tests.append(item)
            items.append(item)
        if kind not in ('excerpt', 'signals'):
            if kind in ('entry', 'code', 'tests'):
                items.sort(key=lambda item: (order[item['repo']],
                           index.indices[item['repo']].layer_order.index(item['layer'])
                           if item['layer'] in index.indices[item['repo']].layer_order else
                           len(index.indices[item['repo']].layer_order),
                           item['layer'], item['path'], item['line']))
            else:
                items.sort(key=lambda item: (order[item['repo']], document_order(item['target'])))
        if items:
            blocks.append({**block, 'items': items})

    signal_block = next((block for block in blocks if block['kind'] == 'signals'), None)
    if signal_block is None and status['signals']:
        signal_block = {'kind': 'signals', 'items': [], 'omitted': 0, 'hint': []}
        blocks.insert(0, signal_block)
    if signal_block:
        signal_block['items'].extend(status['signals'])
        signal_block['items'].sort(key=lambda item: (
            0 if (item.get('code') == 'T3' and not item.get('path')
                  and item['target_repo'] == target_repo and item['target'] == target_id) else 1,
            {'error': 0, 'warning': 1, 'info': 2}[item['level']],
            order[item['repo']], item.get('path', item['target']), item.get('line', 0)))
        for item in signal_block['items']:
            if item['level'] in ('error', 'warning'):
                summary[item['level'] + 's'] += 1
            elif item['code'] is None:
                summary['open_work'] += 1
    for kind in ('concepts', 'entry', 'targets'):
        summary[kind] = sum(len(block['items']) for block in blocks if block['kind'] == kind)
    summary.update(code=len(non_tests), layers=len({(item['repo'], item['layer']) for item in non_tests}),
                   repos=len({item['repo'] for item in non_tests}))
    if 'roles' in response['summary']:
        summary['roles'] = response['summary']['roles']
    from .checker.reviews import load_reviews
    if load_reviews(index.pr.root) is not None:
        summary['reviewed_pairs'] = (0 if target_repo in unavailable
                                     else response['summary'].get('reviewed_pairs', 0))
    response.update(blocks=blocks, summary=summary)
    return response


# @trace docs/ru/slice.md#repos
def build_repo_slice(pr, query, depth=1, layers=None, role=None):
    from .repo_index import RepoIndex
    index = RepoIndex(pr)
    target, error = index.resolve(query)
    if error:
        return _finish(index, error), 1
    if target.get('unavailable'):
        return _finish(index, _empty(target, role)), 0
    response, code = _build_stable(index, target, depth, layers, role=role)
    return _finish(index, response), code


# @trace docs/ru/slice.md#repos,docs/ru/slice-diff.md#response
def build_repo_diff_slice(pr, base=None, staged=False, depth=1, layers=None, role=None):
    from .repo_index import RepoIndex
    from .slice_diff_response import diff_target
    from .slice_diff import collect_diff
    index = RepoIndex(pr)
    diff = collect_diff(index, base=base, staged=staged)
    index.prune_unavailable()
    index._review_explicit_decisions = {aid for aid in diff['seeds']
                                       if index.nodes.get(aid, {}).get('kind') == 'decision'}
    response, code = _build_stable(index, diff_target(base), depth, layers, diff=diff, role=role)
    return _finish(index, response, contract_counts=diff.get('sections', {}).keys()
                   | diff.get('decisions', set())), code
