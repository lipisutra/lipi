"""Combine code changes with references to the contracts changed in the same diff."""

from collections import Counter
from pathlib import Path

from .checker.model import Page
from .i18n import tr
from .slice_diff_places import contract_places
from .slice_index import anchor_title


def diff_target(base):
    return {'target': '--staged' if base is None else '--diff %s' % base,
            'title': tr('slice.diff.title'), 'kind': 'diff', 'found': 'exact', '_base': base}


def diff_checks(diff, base, places):
    checks = {'mode': 'staged' if base is None else 'diff', 'base': base,
              'files': diff['files'], 'unmarked': diff['unmarked']}
    if 'sections' in diff:
        checks['unanchored'] = diff['unanchored']
        checks['sections'] = []
        linked = {target for place in places for target in place['links']}
        for target, sides in sorted(diff['sections'].items()):
            section = {'target': target}
            for side, rows in sides.items():
                section[side] = '\n'.join(rows) if rows is not None else None
            if target not in linked:
                section['linked'] = False
            checks['sections'].append(section)
    return checks


def _location(place):
    return place.get('repo'), place['path'], place['line'], place.get('side', 'after')


def snapshot_title(target, sides):
    rows = sides['after'] if sides['after'] is not None else sides['before']
    page = Page(Path(target), '\n'.join(rows) + '\n')
    for line, anchor in page.anchor_order:
        if target.endswith('#' + anchor):
            return anchor_title(page, line) or anchor
    return target


def collect_contract_places(index, diff):
    """Use snapshot links for display and current, resolved places for A4 and T3."""
    sections = diff['sections']
    decisions = diff['decisions']
    contracts = sections.keys() | decisions
    places = contract_places(index, diff)
    snapshots = {_location(place): place for place in places}
    signals = {}
    counts = Counter()
    # Historical lines and unresolved markers must never be passed to blame.
    for target in contracts | diff['seeds']:
        for current in index.by_target.get(target, ()):
            key = _location(current)
            place = snapshots.get(key)
            if place and target in place['targets'] and place['links'].get(target) != 'removed':
                signals[key] = current

    for place in places:
        reasons = []
        links = place.get('links', {})
        for target in sorted(place['targets']):
            removed_section = target in sections and sections[target]['after'] is None
            if place['changed'] or (target in diff['seeds'] and not removed_section):
                reasons.append({'target': target, 'reason': 'code-change'})
            if target in links:
                if links[target] != 'removed' and not place['test']:
                    counts[target] += 1
                if target in decisions:
                    reason = 'decision-number'
                else:
                    reason = 'target-removed' if removed_section else 'contract-change'
                reasons.append({'target': target, 'reason': reason, 'link': links[target]})
        place['reasons'] = reasons
    return places, list(signals.values()), counts
