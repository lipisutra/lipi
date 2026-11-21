"""Общий разбор меток физической строки и её явного исключения."""

from .conventions import RE_TRACE, TRACE_ROLES


def physical_lines(text):
    """LF-строки без фиктивной строки после EOF; Unicode-разделители — данные."""
    rows = text.split("\n")
    return rows[:-1] if rows[-1] == "" else rows


# @trace ADR-018
def ignores_trace(line):
    """Точный признак отключает все метки только на этой физической строке."""
    return "lipi: ignore-trace" in line


def trace_matches(line):
    """Метки, создающие связи и границы областей кода."""
    return () if ignores_trace(line) else RE_TRACE.finditer(line)


# @trace docs/ru/rules.md#trace-roles
def trace_roles(match):
    """Распознанные и ошибочные значения; явно пустое значение — ошибка."""
    value = match['roles']
    if value is None:
        return (), ()
    tokens = dict.fromkeys(token.strip() for token in value.split(','))
    return (tuple(token for token in tokens if token in TRACE_ROLES),
            tuple(token for token in tokens if token not in TRACE_ROLES))


# @trace docs/ru/review.md#pair
def standalone_trace(line):
    """Отдельный комментарий с меткой; исключённый пример остаётся кодом."""
    if ignores_trace(line):
        return False
    rest = "".join(RE_TRACE.sub("", line).split())
    return rest in ("", "#", "//", "--", ";", "*", "/**/", "<!---->")


# @trace docs/ru/review.md#pair
def trace_groups(rows, resolve):
    """Границы групп, первая строка каждой цели и множества явно заданных ролей."""
    groups = []
    for num, row in enumerate(rows, 1):
        matches = list(trace_matches(row))
        if not matches:
            continue
        standalone = standalone_trace(row)
        if (groups and standalone and groups[-1]['standalone']
                and num == groups[-1]['end'] + 1):
            group = groups[-1]
            group['end'] = num
        else:
            group = {'start': num, 'end': num, 'targets': {}, 'target_roles': {},
                     'standalone': standalone}
            groups.append(group)
        for match in matches:
            roles, invalid_roles = trace_roles(match)
            for token in match[1].split(','):
                target = resolve(token.strip())
                if not target:
                    continue
                group['targets'].setdefault(target, num)
                if roles or invalid_roles:
                    valid, invalid = group['target_roles'].setdefault(target, (set(), set()))
                    valid.update(roles)
                    invalid.update(invalid_roles)
    for pos, group in enumerate(groups):
        group['region_end'] = groups[pos + 1]['start'] - 1 if pos + 1 < len(groups) else len(rows)
    return groups
