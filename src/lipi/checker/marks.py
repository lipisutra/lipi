"""Общий разбор меток физической строки и её явного исключения."""

from .conventions import RE_TRACE


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


def standalone_trace(line):
    """Отдельный комментарий с меткой; исключённый пример остаётся кодом."""
    if ignores_trace(line):
        return False
    rest = "".join(RE_TRACE.sub("", line).split())
    return rest in ("", "#", "//", "--", ";", "*", "/**/", "<!---->")


# @trace docs/ru/review.md#pair
def trace_groups(rows, resolve):
    """Общие физические группы: неразрешённая метка тоже ограничивает область."""
    groups = []
    for num, row in enumerate(rows, 1):
        matches = list(trace_matches(row))
        if not matches:
            continue
        targets = {}
        for match in matches:
            for token in match[1].split(','):
                target = resolve(token.strip())
                if target:
                    targets.setdefault(target, num)
        standalone = standalone_trace(row)
        if (groups and standalone and groups[-1]['standalone']
                and num == groups[-1]['end'] + 1):
            group = groups[-1]
            group['end'] = num
            for target, line in targets.items():
                group['targets'].setdefault(target, line)
        else:
            groups.append({'start': num, 'end': num, 'targets': targets,
                           'standalone': standalone})
    for pos, group in enumerate(groups):
        group['region_end'] = groups[pos + 1]['start'] - 1 if pos + 1 < len(groups) else len(rows)
    return groups
