#!/usr/bin/env python3
"""lipi map — карта явных меток проекта по целям, слоям и тестам."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lipi.i18n import ArgumentParser, cli_output, tr
from lipi.checker.config import load_config, validate_config
from lipi.checker.conventions import CONFIG_NAME, K_STATUS
from lipi.checker.model import Project, feedback_dir, is_within
from lipi.checker.report import Report, finding_item, json_output
from lipi.checker.targets import decision_id, work_targets
from lipi.slice_index import SliceIndex, document_order


def _work_paths(pr):
    return {path for did, paths in work_targets(pr).items() if not did.startswith('ADR-')
            for path in paths}


def _document_group(pr, node, work_paths):
    path = node['page'].path
    rel = pr.rel(path)
    did = decision_id(pr, path) if is_within(path, pr.decisions) else None
    if node['kind'] == 'page' and (did or path in work_paths):
        node = dict(node, kind='decision' if did else 'work',
                    status=node['page'].header().get(K_STATUS, '').strip('* .').lower())
    order = document_order(did) if did else (1, 0, rel)
    return order, rel, node


# @trace docs/ru/map.md#rows
def _unmarked_page(pr, node):
    """Описание и собственные правила остаются видны даже без меток."""
    path = node['page'].path
    if node['kind'] == 'decision':
        return True
    if node['kind'] != 'page' or any(is_within(path, base) for base in
                                    (pr.wf, pr.decisions, feedback_dir(pr.root))):
        return False
    directories = (pr.docs, pr.descr, pr.root / '.agents', *pr.editions.values())
    return (path in (pr.root / 'README.md', pr.root / 'AGENTS.md')
            or any(is_within(path, base) for base in directories))


# @trace docs/ru/map.md#counts
def _row(index, target, layers, owner):
    node = owner if target == owner['target'] else index.nodes[target]
    code = dict.fromkeys(layers, 0)
    tests = 0
    seen = set()
    for place in index.by_target.get(target, []):
        key = place['path'], place['line']
        if key in seen:
            continue
        seen.add(key)
        if place['test']:
            tests += 1
        else:
            code[place['layer']] += 1
    row = {'target': target, 'title': node['title'], 'kind': node['kind'],
           'code': code, 'tests': tests}
    if 'status' in owner:
        row['status'] = owner['status']
    return row


# @trace docs/ru/map.md#rows,docs/ru/map.md#counts
def build_map(pr):
    if pr.cfg.get('repos'):
        return _repo_map(pr)
    index = SliceIndex(pr, links=False)
    layers = [layer for layer in index.layer_order if layer != 'tests']
    layers.extend(sorted({place['layer'] for place in index.places
                          if not place['test']} - set(layers)))
    work_paths = _work_paths(pr)
    groups = [_document_group(pr, index.nodes[target], work_paths)
              for target in index.page_ids.values()]
    rows = []
    for _, _, node in sorted(groups):
        target = node['target']
        anchors = index.anchors[node['page'].path]
        marked = any(index.by_target.get(aid) for aid in [target, *anchors])
        if not marked and not _unmarked_page(pr, node):
            continue
        if not marked:
            targets = [target]
        elif node['kind'] in ('decision', 'work'):
            targets = [target, *anchors]
        else:
            targets = anchors
        rows.extend(_row(index, aid, layers, node) for aid in targets)
    return {'schema': 1, 'layers': layers, 'rows': rows, 'note': tr('map.zero')}


# @trace docs/ru/map.md#repos
def _repo_map(pr):
    from lipi.repo_index import RepoIndex, split_id
    from lipi.repo_output import repository_status

    index = RepoIndex(pr, links=False)
    # A failed metadata read also excludes the source before counting cells.
    for source in index.sources.all:
        _ = source.state
    index.prune_unavailable()
    layers, test_repos = [], [None]
    for repo, source_index in index.indices.items():
        source = index.sources.get(repo)
        if source.state == 'unavailable' or (repo is not None and not source.has_config):
            continue
        if repo is None or 'code' in source.read:
            names = [name for name in source_index.layer_order if name != 'tests']
            names.extend(sorted({place['layer'] for place in index.places
                                 if place.get('repo') == repo and not place['test']} - set(names)))
            layers.extend(name if repo is None else repo + '::' + name for name in names)
        if repo is not None and 'tests' in source.read:
            test_repos.append(repo)

    groups = []
    work_paths = _work_paths(pr)
    ranks = {source.name: rank for rank, source in enumerate(index.sources.all)}
    for target in index.page_ids.values():
        node = index.nodes[target]
        repo = node.get('repo')
        source = index.sources.get(repo)
        if source.state == 'unavailable':
            continue
        groups.append((ranks[repo], *_document_group(source.project, node, work_paths)))

    rows = []
    for _, _, _, node in sorted(groups, key=lambda item: item[:3]):
        target, repo = node['target'], node.get('repo')
        source = index.sources.get(repo)
        anchors = index.anchors[node['page'].path]
        group_targets = [target, *anchors]
        marked = any(index.by_target.get(aid) for aid in group_targets)
        if repo is not None:
            if not any(aid in index.local_marked for aid in group_targets):
                continue
        elif not marked and not _unmarked_page(pr, node):
            continue
        if repo is not None and not source.has_config:
            targets = anchors
        elif not marked:
            targets = [target]
        elif node['kind'] in ('decision', 'work'):
            targets = group_targets
        else:
            targets = anchors
        for aid in targets:
            item = node if aid == target else index.nodes[aid]
            code = dict.fromkeys(layers, 0)
            tests = dict.fromkeys(test_repos, 0)
            seen = set()
            for place in index.by_target.get(aid, []):
                place_repo = place.get('repo')
                identity = place_repo, place['path'], place['line']
                if identity in seen:
                    continue
                seen.add(identity)
                if place['test']:
                    if place_repo in tests:
                        tests[place_repo] += 1
                else:
                    layer = (place['layer'] if place_repo is None
                             else place_repo + '::' + place['layer'])
                    if layer in code:
                        code[layer] += 1
            row = {'repo': repo, 'target': split_id(aid)[1], 'title': item['title'],
                   'kind': item['kind'], 'code': code, 'tests': sum(tests.values()),
                   'test_counts': [{'repo': name, 'count': count} for name, count in tests.items()]}
            if 'status' in node:
                row['status'] = node['status']
            rows.append(row)
    return {'schema': 1, 'layers': layers, 'rows': rows, 'note': tr('map.zero'),
            **repository_status(pr)}


# @trace docs/ru/map.md#output
def render_text(response):
    if 'checks' in response and 'repos' in response['checks']:
        return _render_repo_text(response)
    layers = response['layers']
    table = [[tr('map.column.target'), tr('map.column.title'), tr('map.column.status'),
              *layers, tr('map.column.tests')]]
    for row in response['rows']:
        title = row['title']
        if row['kind'] != 'section' and not (sum(row['code'].values()) + row['tests']):
            title += tr('map.unmarked')
        table.append([row['target'], title, row.get('status', ''),
                      *(str(row['code'][layer]) for layer in layers), str(row['tests'])])
    table = [[' '.join(cell.split()).replace('|', '\\|') for cell in row] for row in table]
    widths = [max(len(row[column]) for row in table) for column in range(len(table[0]))]
    lines = [' | '.join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
             for row in table]
    lines.insert(1, '-+-'.join('-' * width for width in widths))
    if not response['rows']:
        lines.append(tr('map.empty'))
    return '\n'.join([*lines, '', response['note']])


# @trace docs/ru/map.md#repos
def _render_repo_text(response):
    from lipi.repo_output import render_repository_status

    columns = []
    test_repos = {item['repo'] for row in response['rows'] for item in row['test_counts']}
    if not response['rows']:
        test_repos = {source['repo'] for source in response['checks']['repos']
                      if source['repo'] is None or (source['state'] != 'unavailable'
                                                    and 'tests' in source['read'])}
    for source in response['checks']['repos']:
        repo = source['repo']
        for layer in response['layers']:
            owner = layer.partition('::')[0] if '::' in layer else None
            if owner == repo:
                columns.append((layer, 'code', layer))
        if repo in test_repos:
            label = tr('map.column.tests')
            columns.append((repo + '::' + label if repo is not None else label, 'tests', repo))
    table = [[tr('map.column.target'), tr('map.column.title'), tr('map.column.status'),
              *(column[0] for column in columns)]]
    for row in response['rows']:
        title = row['title']
        if row['kind'] != 'section' and not (sum(row['code'].values()) + row['tests']):
            title += tr('map.unmarked')
        target = row['target'] if row['repo'] is None else row['repo'] + '::' + row['target']
        counts = {item['repo']: item['count'] for item in row['test_counts']}
        values = [row['code'][key] if kind == 'code' else counts.get(key, 0)
                  for _, kind, key in columns]
        table.append([target, title, row.get('status', ''), *(str(value) for value in values)])
    table = [[' '.join(cell.split()).replace('|', '\\|') for cell in row] for row in table]
    widths = [max(len(row[column]) for row in table) for column in range(len(table[0]))]
    lines = [' | '.join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
             for row in table]
    lines.insert(1, '-+-'.join('-' * width for width in widths))
    if not response['rows']:
        lines.append(tr('map.empty'))
    lines.extend(['', response['note'], *render_repository_status(response)])
    lines.extend(note['text'] for note in response['notes'])
    lines.extend('[%s T4] %s' % (tr('map.signal.' + signal['level']), signal['message'])
                 for signal in response['signals'])
    return '\n'.join(lines)


# @trace docs/ru/commands.md#map
def parser():
    ap = ArgumentParser(prog='lipi map', description=tr('map.help.description'),
                        epilog=tr('map.help.epilog'))
    ap.add_argument('--format', choices=('text', 'json'), default='text', help=tr('output.help.format'))
    return ap


def _config_errors(errors, fmt):
    if fmt == 'json':
        items = [finding_item((path, 0, 'E', 'C1', message, '')) for path, message in errors]
        print(json.dumps(json_output(items, []), ensure_ascii=False))
    else:
        report = Report()
        for path, message in errors:
            report.finding('C1', path, 0, message)
        report.dump()


# @trace docs/ru/map.md#exit
@cli_output
def main(argv=None):
    args = parser().parse_args(argv)
    root = Path.cwd().resolve()
    try:
        cfg = load_config(root, None)
    except (ValueError, OSError) as error:
        _config_errors([(CONFIG_NAME, tr('config.read.query') % error)], args.format)
        return 2
    errors = validate_config(root, cfg)
    if errors:
        _config_errors(errors, args.format)
        return 2
    try:
        response = build_map(Project(root, cfg))
    except ValueError as error:
        _config_errors([(CONFIG_NAME, str(error))], args.format)
        return 2
    print(json.dumps(response, ensure_ascii=False) if args.format == 'json' else render_text(response))
    return 0


if __name__ == '__main__':
    sys.exit(main())
