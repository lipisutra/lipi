"""Find code and test places linked to contracts changed in a Git diff."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from functools import lru_cache
from urllib.parse import unquote

from .checker.conventions import RE_TRACE
from .checker.marks import physical_lines, trace_groups
from .checker.model import is_within
from .checker.targets import normalize_work_id
from .slice_diff import _staged_worktree, _unchanged
from .slice_diff_sections import local_section_address
from .slice_index import declaration_line


def _contract_resolver(pr, contracts):
    @lru_cache(maxsize=None)
    def resolve(token):
        # The diff has already checked these addresses against the project's
        # boundaries. Match lexically so a removed page need not exist.
        parts = local_section_address(pr, token)
        address = '#'.join(parts) if parts else normalize_work_id(token)
        return address if address in contracts else None

    return resolve


def _neighbor_resolver(source, local_resolve):
    @lru_cache(maxsize=None)
    def resolve(token):
        alias, separator, target = token.partition('::')
        if separator and points_to_local(alias):
            return local_resolve(target)
        return None

    points_to_local = lru_cache(maxsize=None)(source.points_to_local)
    return resolve


def _with_current_targets(resolve_contract, mark, seeds, *, pr=None, sections=(), dirty=()):
    @lru_cache(maxsize=None)
    def resolve(token):
        contract = resolve_contract(token)
        if contract:
            return contract
        target = mark(token)
        if target in seeds:
            return target
        if target in sections:
            page = unquote(token.rpartition('::')[2].partition('#')[0])
            path = pr.lexical_path(page)
            if all(pr.rel(part) not in dirty for part in (path, *path.parents) if is_within(part, pr.root)):
                return target
        return None

    return resolve if seeds or sections else resolve_contract


def _anchors(rows, groups):
    for group in groups.values():
        start = group['start']
        for line in range(start, group['end'] + 1):
            yield line, start
        declaration = declaration_line(rows, group)
        if declaration is not None and declaration != start:
            yield declaration, start


def _intervals(hunks, side):
    spans = [(hunk[side], hunk[side] + hunk[side + 1] - 1, position)
             for position, hunk in enumerate(hunks) if hunk[side + 1]]
    return tuple(zip(*spans)) if spans else ((), (), ())


def _inline_marks(rows, groups, intervals):
    starts, ends, positions = intervals
    signatures = defaultdict(list)
    for line, group in groups.items():
        if group['standalone']:
            continue
        span = bisect_right(starts, line) - 1
        if span >= 0 and line <= ends[span]:
            declaration = RE_TRACE.sub('', rows[line - 1]).strip()
            signatures[positions[span], declaration].append(line)
    return signatures


def _paired_groups(before, after, hunks, old, new, old_intervals, new_intervals):
    """Use exact Git line matches for markers and their declarations."""
    if not old or not new:
        return {}
    blocks = _unchanged(before, hunks)
    starts = [block[0] + 1 for block in blocks]
    candidates, origins = defaultdict(set), defaultdict(set)
    new_anchors = dict(_anchors(after, new))

    def match(old_group, new_group):
        candidates[old_group].add(new_group)
        origins[new_group].add(old_group)

    for line, group in _anchors(before, old):
        pos = bisect_right(starts, line) - 1
        if pos < 0:
            continue
        start, destination, length = blocks[pos]
        offset = line - 1 - start
        if offset < length and (mapped := new_anchors.get(destination + offset + 1)):
            match(group, mapped)

    # An inline marker changes its declaration's Git row even when all the
    # code on that row is unchanged. Require a unique signature in the hunk.
    old_inline = _inline_marks(before, old, old_intervals)
    new_inline = _inline_marks(after, new, new_intervals)
    for signature in old_inline.keys() & new_inline.keys():
        if len(old_inline[signature]) == len(new_inline[signature]) == 1:
            match(old_inline[signature][0], new_inline[signature][0])

    # A split or merge can map to several groups and has no one-to-one pair.
    return {dest: src for dest, sources in origins.items() if len(sources) == 1
            for src in sources if len(candidates[src]) == 1}


def _touched(group, intervals):
    if group is None:
        return False
    starts, ends, _ = intervals
    span = bisect_left(ends, group['start'])
    return span < len(starts) and starts[span] <= group['region_end']


def _place(index, path, rows, old, new, contracts, *, repo=None, changed=False):
    previous = old['targets'] if old else {}
    current = new['targets'] if new else {}
    links = {target: ('retained' if target in previous else 'added')
             if target in current else 'removed'
             for target in sorted((previous.keys() | current.keys()) & contracts)}
    if links:
        targets = {**previous, **current}
    elif current and not changed:
        targets = current
    else:
        return None
    # The current marker can keep the link while dropping its role.
    roles = {}
    if old:
        roles.update((target, values) for target, values in old['target_roles'].items()
                     if target not in current)
    if new:
        roles.update(new['target_roles'])
    return dict(index.code_place(path, rows, new or old), repo=repo, targets=targets,
                target_roles=roles, links=links, side='after' if new else 'before', changed=changed)


def _snapshot_places(index, snapshot, resolve, contracts):
    before, after = snapshot['before'] or (), snapshot['after'] or ()
    hunks = snapshot['hunks']
    old = {group['start']: group for group in trace_groups(before, resolve)}
    new = {group['start']: group for group in trace_groups(after, resolve)}
    if not any(group['targets'] for group in (*old.values(), *new.values())):
        return
    old_intervals, new_intervals = _intervals(hunks, 0), _intervals(hunks, 2)
    pairs = _paired_groups(before, after, hunks, old, new, old_intervals, new_intervals)
    for line, group in new.items():
        previous = old.get(pairs.get(line))
        place = _place(index, snapshot['new_path'], after, previous, group, contracts,
                       changed=_touched(previous, old_intervals) or _touched(group, new_intervals))
        if place:
            yield place
    for line in old.keys() - pairs.values():
        group = old[line]
        place = _place(index, snapshot['old_path'], before, group, None, contracts,
                       changed=_touched(group, old_intervals))
        if place:
            yield place


# @trace docs/ru/slice-diff.md#response,docs/ru/slice.md#repos
def contract_places(index, diff):
    """Return contract links on both sides and unchanged places linked to code changes."""
    sections = diff.get('sections', {})
    contracts = sections.keys() | diff.get('decisions', set())
    seeds = diff['seeds'] - contracts
    if not (contracts or seeds):
        return []
    # An unchanged section on a changed page can also be selected by a code
    # edit. Its address was resolved in Git and may be absent in the worktree.
    document_paths = diff['document_paths']
    snapshot_targets = {seed for seed in seeds if seed.partition('#')[0] in document_paths}
    resolve = _contract_resolver(index.pr, contracts | snapshot_targets)
    indices = getattr(index, 'indices', {None: index})
    snapshots = diff.get('code_snapshots', [])
    dirty = diff.get('worktree_only_paths', ())
    covered = {snapshot[key] for snapshot in snapshots for key in ('old_path', 'new_path')}
    covered.update(dirty)
    active_sections = {target for target, sides in sections.items() if sides['after'] is not None}
    local_index = indices[None]
    places = []
    historical_resolve = _with_current_targets(resolve, local_index.mark, seeds)
    for snapshot in snapshots:
        places.extend(_snapshot_places(local_index, snapshot, historical_resolve, contracts))
    for repo, source_index in indices.items():
        source_resolve = _with_current_targets(
            resolve if repo is None else _neighbor_resolver(source_index.source, resolve),
            source_index.mark, seeds, pr=index.pr, sections=active_sections, dirty=dirty)
        for path, text in source_index.code_texts.items():
            if repo is None and path in covered:
                continue
            rows = physical_lines(text)
            for group in trace_groups(rows, source_resolve):
                place = _place(source_index, path, rows, group, group, contracts, repo=repo)
                if place:
                    places.append(place)
    return sorted(places, key=index.place_order)


# @trace docs/ru/slice-diff.md#selection
def staged_code_role_places(index, diff, places, role=None):
    """Use index locations with role information on a code-only staged diff."""
    seeds = diff['seeds']
    anchors = {target for target in seeds if '#' in target}
    if not anchors:
        return places
    local = getattr(index, 'local', index)
    snapshots = []
    dirty = _staged_worktree(local.pr, (), snapshots)
    if not dirty:
        return places
    changed = diff.get('changed_index', ())
    indexed_places = []
    for snapshot in snapshots:
        path, rows = snapshot['new_path'], snapshot['after']
        for group in trace_groups(rows, local.mark):
            if group['targets'].keys().isdisjoint(seeds) or (path, group['start']) in changed:
                continue
            place = local.code_place(path, rows, group)
            if not place['test']:
                indexed_places.append(dict(place, repo=None))
    if role is None:
        # Keep the legacy working-tree view for files without roles on either side.
        dirty &= {place['path'] for place in (*places, *indexed_places)
                  if place.get('repo') is None and not place['test']
                  and not place['target_roles'].keys().isdisjoint(anchors)}
    current_places = [place for place in places if place.get('repo') is not None
                      or place['test'] or place['path'] not in dirty]
    return current_places + [place for place in indexed_places if place['path'] in dirty]
