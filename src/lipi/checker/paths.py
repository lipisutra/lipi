"""Единые исключения каталогов: имена на любой глубине и пути от корня."""

from pathlib import Path, PureWindowsPath

from lipi.i18n import tr
from .conventions import SKIP_DIRS


# @trace docs/ru/settings.md#skip-dirs
def skip_entry(value):
    """Возвращает (путь от корня?, компоненты), не обращаясь к диску."""
    if not value or not value.strip() or '\x00' in value:
        raise ValueError(tr('checker.paths.empty_or_nul_directory'))
    if value.startswith('/') or PureWindowsPath(value).drive or value.startswith('\\'):
        raise ValueError(tr('checker.paths.relative_path_inside_root'))
    relative = '/' in value
    if relative and '\\' in value:
        raise ValueError(tr('checker.paths.path_separator'))
    parts = []
    for part in value.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise ValueError(tr('checker.paths.outside_project_root'))
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise ValueError(tr('checker.paths.exclude_project_root'))
    return relative, tuple(parts)


# @trace docs/ru/settings.md#skip-dirs
class SkipDirs:
    """Лексический фильтр каталогов одного проекта; шаблоны не раскрываются."""

    def __init__(self, root, configured=(), *, include_agents=False):
        self.root = Path(root)
        self.names = set(SKIP_DIRS)
        if include_agents:
            self.names.discard('.agents')
        self.paths = []
        for entry in configured:
            relative, parts = skip_entry(entry)
            if relative:
                self.paths.append(parts)
            else:
                self.names.add(parts[0])

    def excludes(self, path, *, directory=False, base=None):
        path = Path(path)
        try:
            parts = path.relative_to(self.root).parts
            rooted = True
        except ValueError:
            # Внешнее описание сохраняет исключения по имени; пути из
            # настройки всегда относятся только к корню этого проекта.
            rooted = False
            try:
                parts = path.relative_to(base).parts if base is not None else path.parts
            except ValueError:
                parts = path.parts
        directories = parts if directory else parts[:-1]
        return (bool(self.names.intersection(directories))
                or rooted and any(directories[:len(prefix)] == prefix
                                  for prefix in self.paths))
