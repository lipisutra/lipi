"""Источники из своего проекта и прямых подключений, без перехода к третьим."""

import json
import os
import re
import subprocess
from functools import cached_property
from pathlib import Path

from lipi.i18n import tr
from . import __version__
from .checker.config import check_lock, load_config, resolve_page_dir, validate_settings
from .checker.conventions import CONFIG_NAME, HISTORY_DIR, LOCK_NAME, LIPI_DIR
from .checker.model import Project, git_worktree_root, has_symlink, is_within
from .checker.paths import SkipDirs


# @trace docs/ru/settings.md#repos,ADR-016
def _confined(root, path):
    """Путь внутри root и до, и после раскрытия символических ссылок."""
    try:
        path = Path(path)
        lexical = Path(os.path.abspath(root / path))
        if not is_within(lexical, root):
            return None
        resolved = lexical.resolve()
        return resolved if is_within(resolved, root) else None
    except (OSError, RuntimeError, ValueError):
        return None


# @trace docs/ru/settings.md#repos,ADR-016
class _SourceProject(Project):
    """Project соседа защищает также прямое чтение страницы."""

    def __init__(self, source):
        self.source = source
        super().__init__(source.root, source.cfg,
                         git_file_filter=source._outside_child_repos)

    def _connected(self, path):
        # Пути подключений соседа нельзя раскрывать: это уже третьи источники.
        return not self.source._outside_child_repos(path)

    def _path_allowed(self, path, directory):
        return self.source._path_allowed(path, directory)

    @cached_property
    def sources(self):
        return SourceSet(self, neighbors=False)


# @trace docs/ru/settings.md#repos,ADR-016
class Source:
    """Один корень, его настройки, возможности чтения и состояние дерева.

    У своего проекта name=None. Метаданные Git читаются при первом запросе
    state/head/dirty/reason; получение Source не запускает проверки проекта.
    """

    def __init__(self, owner, name=None, connection=None):
        self.name = name
        self._owner = owner
        self._reason = None
        self._has_config = None
        self._page_dirs = ()
        if name is None:
            self.root = owner.root
            self.cfg = owner.cfg
            self.project = owner
            self.read = ('docs', 'decisions', 'code', 'tests')
            return
        self.read = tuple(connection['read'])
        if 'docs' in self.read:
            self._page_dirs = tuple(connection.get('page_dirs', ()))
        self.cfg = None
        self.project = None
        self._has_config = False
        path = owner.root / connection['path']
        self.root = Path(os.path.abspath(path))
        try:
            self.root = path.resolve()
            self._load()
        except (OSError, RuntimeError, ValueError) as error:
            self._reason = str(error)

    @property
    def has_config(self):
        if self._has_config is None:
            self._has_config = (self.root / CONFIG_NAME).is_file()
        return self._has_config

    @property
    def unavailable_reason(self):
        """Уже известная причина недоступности, без чтения состояния Git."""
        return self._reason

    def mark_unavailable(self, reason):
        """Ошибка чтения цели делает источник недоступным, сохраняя его проект."""
        self._reason = reason
        self.__dict__.pop('_metadata', None)

    def _load(self):
        if not self.root.is_dir():
            raise ValueError(tr('checker.sources.missing_connected_directory'))
        config = _confined(self.root, CONFIG_NAME)
        if config is None:
            raise ValueError(tr('checker.sources.config_outside_connected_root'))
        # lstat отличает отсутствующий файл от битой символической ссылки.
        try:
            (self.root / CONFIG_NAME).lstat()
            self._has_config = True
        except FileNotFoundError:
            pass
        if self.has_config and not config.is_file():
            raise ValueError(tr('checker.sources.unreadable_connected_config'))
        try:
            cfg = load_config(self.root, str(config) if self.has_config else None)
        except (OSError, ValueError) as error:
            raise ValueError('lipi.json: %s' % error) from error
        if not self.has_config:
            cfg.update(docs='.', workflow=None)
        problems = validate_settings(self.root, cfg, repo_roots=False)
        if problems:
            raise ValueError('; '.join('%s: %s' % item for item in problems))
        if any('::' in layer for layer in cfg.get('layers', {}).values()):
            raise ValueError(tr('checker.sources.reserved_layer_separator'))
        directories = {key: cfg.get(key) for key in
                       ('docs', 'description', 'workflow', 'decisions')}
        if 'decisions' not in cfg and cfg.get('workflow'):
            directories['decisions'] = str(Path(cfg['workflow']) / 'adr')
        directories.update({'languages.' + name: path for name, path in
                            cfg.get('languages', {}).get('editions', {}).items()})
        for key, path in directories.items():
            if path is None:
                continue
            lexical = Path(os.path.abspath(self.root / path))
            if (not is_within(lexical, self.root)
                    or has_symlink(lexical, self.root) and (
                        git_worktree_root(self.root) is not None or _confined(self.root, lexical) is None)):
                raise ValueError(tr('checker.sources.invalid_connected_directory') % key)
        self._check_version()
        self.cfg = cfg
        self.project = _SourceProject(self)

    def _check_version(self):
        lock = _confined(self.root, LOCK_NAME)
        if lock is None:
            raise ValueError(tr('checker.sources.lock_outside_connected_root'))
        try:
            (self.root / LOCK_NAME).lstat()
        except FileNotFoundError:
            return
        if not lock.is_file():
            raise ValueError(tr('checker.sources.unreadable_connected_lock'))
        problems = check_lock(self.root)
        if problems:
            raise ValueError('; '.join('%s: %s' % item for item in problems))
        # Схема уже проверена; неизвестная версия не доказывает несовместимость.
        version = json.loads(lock.read_text(encoding='utf-8'))['lipi']
        major = re.match(r'^(\d+)(?:\.|$)', version)
        if major and int(major[1]) != int(__version__.split('.')[0]):
            raise ValueError(tr('checker.sources.incompatible_major_version') % (
                version, __version__.split('.')[0]))

    def _outside_child_repos(self, path):
        """Лексический фильтр дочерних подключений, без resolve/stat их корней."""
        return not any(is_within(path, child) for child in self._child_roots)

    @cached_property
    def _child_roots(self):
        candidates = (Path(os.path.abspath(self.root / item['path']))
                      for item in self.cfg.get('repos', {}).values())
        return tuple(path for path in candidates if path != self.root and is_within(path, self.root))

    @cached_property
    def skip_dirs(self):
        return SkipDirs(self.root, self.cfg.get('skip_dirs', []), include_agents=True)

    @cached_property
    def documentation_roots(self):
        pr = self.project
        return tuple(base for base in (pr.docs, pr.descr, *pr.editions.values()) if base is not None)

    @cached_property
    def page_dirs(self):
        roots = []
        for entry in self._page_dirs:
            try:
                path = resolve_page_dir(self.root, entry, path_allowed=self._path_allowed,
                                        follow_symlinks=self.project.git_root is None)
                if path is not None:
                    path = self.resolve_path(path, directory=True)
                if path is not None and path.is_dir():
                    roots.append(path)
            except (OSError, RuntimeError, ValueError):
                continue
        return tuple(roots)

    @cached_property
    def _archive_roots(self):
        workflow = self.cfg.get('workflow')
        decisions = self.cfg.get('decisions', str(Path(workflow) / 'adr') if workflow else None)
        bases = (self.project.wf, self.project.decisions,
                 *(self.project.lexical_path(base) for base in (workflow, decisions) if base))
        return (self.root / HISTORY_DIR, *(base / HISTORY_DIR for base in bases if base))

    def is_archived(self, path):
        """Путь архива, в том числе отсутствующий в рабочем дереве."""
        return any(is_within(path, root) for root in self._archive_roots)

    def _path_allowed(self, path, directory=False):
        return (is_within(path, self.root) and self._outside_child_repos(path)
                and not self.skip_dirs.excludes(path, directory=directory)
                and not is_within(path, self.root / LIPI_DIR)
                and not self.is_archived(path))

    def resolve_path(self, path, *, directory=False):
        """Разрешённый путь или None; существование файла не проверяется."""
        if self.project is None:
            return None
        if self.name is None:
            lexical = self.project.lexical_path(path)
            if not self._path_allowed(lexical, directory):
                return None
            real = self.project.file_path(lexical, directory=directory)
            return real if real is not None and self._path_allowed(real, directory) else None
        return self.project.file_path(path, directory=directory)

    def points_to_local(self, alias):
        """Ссылка соседа ведёт в свой проект; прочие источники не открываются."""
        if self.cfg is None:
            return False
        connection = self.cfg.get('repos', {}).get(alias)
        if connection is None:
            return False
        try:
            path = self.root / connection['path']
            lexical = Path(os.path.abspath(path))
            if lexical == self._owner.root or path.resolve() == self._owner.root:
                return True
            return path.samefile(self._owner.root)
        except (OSError, RuntimeError, ValueError):
            return False

    def _git(self, *args):
        return subprocess.run(
            ['git', '-C', str(self.root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'), check=False)

    @cached_property
    def _metadata(self):
        if self._reason is not None:
            return ('unavailable', None, None, self._reason)
        try:
            if self.project.git_root is None:
                return ('no-git', None, None, tr('checker.sources.outside_git_worktree'))
            head = self._git('rev-parse', '--verify', 'HEAD')
            status = self._git('status', '--porcelain=v1', '--untracked-files=normal')
            if status.returncode:
                return ('unavailable', None, None, tr('checker.sources.git_state_unavailable'))
            return ('ok', head.stdout.decode().strip() if not head.returncode else None,
                    bool(status.stdout), None)
        except (OSError, RuntimeError, ValueError) as error:
            return ('no-git', None, None, str(error))

    @property
    def state(self):
        return self._metadata[0]

    @property
    def head(self):
        return self._metadata[1]

    @property
    def dirty(self):
        return self._metadata[2]

    @property
    def reason(self):
        return self._metadata[3]

    @property
    def reproducible(self):
        return self.state == 'ok' and self.head is not None and self.dirty is False


# @trace docs/ru/settings.md#repos,ADR-016
class SourceSet:
    """Ленивые прямые подключения; порядок: свой источник, затем ключи repos."""

    def __init__(self, project, *, neighbors=True):
        self.project = project
        self.local = Source(project)
        self._sources = {None: self.local}
        self._connections = project.cfg.get('repos', {}) if neighbors else {}

    def get(self, name):
        if name not in self._sources:
            connection = self._connections.get(name)
            if connection is None:
                return None
            self._sources[name] = Source(self.project, name, connection)
        return self._sources[name]

    @property
    def all(self):
        """Все источники, включая свой; загружает ещё не открытых соседей."""
        return (self.local, *(self.get(name) for name in self._connections))

    def items(self):
        """Пары (имя, источник), начиная со своего (None, local)."""
        return ((source.name, source) for source in self.all)

    @property
    def reproducible(self):
        return all(source.reproducible for source in self.all)
