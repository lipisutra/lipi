"""Роли совпавших связей и подсчёт мест в обычном срезе."""

from .checker.conventions import TRACE_ROLES


def matching_roles(place, targets):
    if place['test']:
        return {}
    explicit = place.get('target_roles', {})
    return {target: explicit.get(target, ((), ())) for target in targets if '#' in target}


def has_explicit_roles(links):
    return any(valid or invalid for valid, invalid in links.values())


def role_entries(links):
    items = []
    for target, (valid, invalid) in sorted(links.items()):
        item = {'target': target, 'roles': [role for role in TRACE_ROLES if role in valid]}
        if invalid:
            item['invalid_roles'] = sorted(invalid)
        items.append(item)
    return items


# @trace docs/ru/slice-output.md#roles
def role_states(links, role):
    """Без фильтра совпадением считается любая распознанная роль."""
    states = set()
    for valid, invalid in links.values():
        if valid and (role is None or role in valid):
            states.add('matched')
        if invalid:
            states.add('unrecognized')
        elif not valid:
            states.add('unassigned')
    return states


def role_counts(role=None, places=()):
    """Нераспознанная и запрошенная роли могут относиться к одному месту."""
    counts = {} if role is None else {'role': role, 'matched': 0}
    counts.update(unassigned=0, unrecognized=0)
    for states in places:
        if role is not None and 'matched' in states:
            counts['matched'] += 1
        if 'unrecognized' in states:
            counts['unrecognized'] += 1
        elif states == {'unassigned'}:
            counts['unassigned'] += 1
    return counts


# @trace docs/ru/slice-output.md#roles
def file_role_locations(places, concepts, role):
    """Собственные объявления файла по целям с адресом начала группы меток."""
    matches = [(place, matching_roles(place, place['targets'].keys() & concepts))
               for place in places]
    if role is None and not any(has_explicit_roles(links) for _, links in matches):
        return {}
    result = {}
    for place, matched in matches:
        for target, values in matched.items():
            links = {target: values}
            if role is not None and not role_states(links, role):
                continue
            location = {'path': place['path'], 'line': place['line'],
                        'symbol': place['symbol'], 'target_roles': role_entries(links)}
            if 'repo' in place:
                location['repo'] = place['repo']
            result.setdefault(target, []).append(location)
    return result
