"""Страницы, проект, разбор Markdown и обход файлов."""
import os
import re
import subprocess
from collections import deque
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote

from .markdown_links import markdown_links
from .conventions import (
    FEEDBACK, RE_ANCHOR, RE_HEADER, RE_SCHEME, RE_TEST_NAME,
    TEST_DIRS, LIPI_DIR,
)
from .paths import SkipDirs
from .marks import physical_lines


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def mask_code(text):
    """Затирает блоки кода и `инлайн-код`, сохраняя номера строк."""
    out, fence = [], None
    for line in text.split("\n"):
        st = line.lstrip()
        if fence:
            if st.startswith(fence):
                fence = None
            out.append("")
            continue
        m = re.match(r"(`{3,}|~{3,})", st)
        if m:
            fence = m.group(1)
            out.append("")
            continue
        out.append(re.sub(r"`[^`]*`", lambda mm: " " * len(mm.group(0)), line))
    return "\n".join(out)


def heading_slug(title):
    """Якорь заголовка, как его строит GitHub."""
    title = re.sub(r"<[^>]+>", "", title).strip().lower()
    title = re.sub(r"[^\w\- ]", "", title, flags=re.U)
    return title.replace(" ", "-")


def anchor_region(page, line):
    """Точные номера строк (с 1) элемента Markdown, содержащего якорь.

    Раздел включает вложенные заголовки, пункт — вложенные пункты и
    продолжения. Строка таблицы зависит также от шапки, но не от соседних
    строк: её область может быть разрывной.
    """
    raw, masked = physical_lines(page.text), page.masked.split("\n")
    start = line - 1
    if not 0 <= start < len(raw):
        return ()
    heading = re.compile(r"^(#{1,6})\s+")
    bullet = re.compile(r"^(\s*)(?:[-+*]|\d+[.)])\s+")

    def table(pos):
        return masked[pos].lstrip().startswith('|')

    def indent(pos):
        return len(raw[pos].expandtabs(4)) - len(raw[pos].expandtabs(4).lstrip())

    match = heading.match(masked[start])
    if match:
        end = next((pos for pos in range(start + 1, len(raw))
                    if (other := heading.match(masked[pos]))
                    and len(other[1]) <= len(match[1])), len(raw))
        return tuple(range(line, end + 1))
    if table(start):
        top = start
        while top and table(top - 1):
            top -= 1
        return tuple(sorted({top + 1, line}))

    def item_end(first):
        base, end = indent(first), first + 1
        while end < len(raw):
            if not raw[end].strip():
                following = end + 1
                while following < len(raw) and not raw[following].strip():
                    following += 1
                if following == len(raw) or indent(following) <= base:
                    break
                end = following
            if ((bullet.match(masked[end]) and indent(end) <= base)
                    or (heading.match(masked[end]) and indent(end) <= base)):
                break
            end += 1
        return end

    # Якорь может стоять на продолжении пункта, а не на строке с маркером.
    for first in range(start, -1, -1):
        if bullet.match(masked[first]):
            end = item_end(first)
            if start < end:
                return tuple(range(first + 1, end + 1))
        if heading.match(masked[first]):
            break

    def paragraph(pos):
        return (raw[pos].strip() and not heading.match(masked[pos])
                and not bullet.match(masked[pos]) and not table(pos)
                and not re.match(r"^\s*(`{3,}|~{3,})", raw[pos]))

    first, end = start, start + 1
    while first and paragraph(first - 1):
        first -= 1
    while end < len(raw) and paragraph(end):
        end += 1
    return tuple(range(first + 1, end + 1))


def section_lines(text, title):
    """Непустые строки раздела «title»; None, если раздела нет.

    Заголовок раздела — любой уровень (#+), совпадение по тексту заголовка;
    теги <a id> в строке заголовка игнорируются. Раздел идёт до следующего
    заголовка того же или более высокого уровня; строки под более глубокими
    подзаголовками не считаются текстом раздела. Заголовки ищутся по тексту
    с замаскированными блоками кода, сами строки берутся из текста.
    """
    masked = mask_code(text).split("\n")
    raw = text.split("\n")
    start = level = None
    for n, s in enumerate(masked, 1):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if m and re.sub(r"<[^>]+>", "", m.group(2)).strip() == title:
            start, level = n, len(m.group(1))
            break
    if start is None:
        return None
    out, deep = [], False
    for k in range(start, len(masked)):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", masked[k])
        if m:
            if len(m.group(1)) <= level:
                break
            deep = True
            continue
        if not deep and raw[k].strip():
            out.append(raw[k].strip())
    return out


def is_within(path, base):
    return path is not None and base is not None and (path == base or base in path.parents)


def feedback_dir(root):
    """Каталог замечаний к lipi: работает и без рабочих материалов проекта."""
    return Path(root) / FEEDBACK


def has_symlink(path, boundary):
    """Проверяет путь от границы к файлу, не раскрывая ссылки."""
    return any(part.is_symlink() for part in reversed((path, *path.parents))
               if part != boundary and is_within(part, boundary))


def is_test_file(rel):
    parts = [p.lower() for p in Path(rel).parts]
    return bool(TEST_DIRS.intersection(parts[:-1])) or bool(RE_TEST_NAME.search(Path(rel).name))


def _git_output(root, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
            check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def git_worktree_root(root):
    """Вершина рабочего дерева, которому принадлежит проект, или None."""
    top = _git_output(root, "rev-parse", "--show-toplevel")
    return Path(os.fsdecode(top.removesuffix(b"\n"))).resolve() if top else None


def list_project_files(root, path_filter=None):
    """Отслеживаемые и новые неигнорируемые файлы под root или None при сбое.

    Git возвращает имена относительно текущего подкаталога. Сохраняем
    исходные пути для проекции init. Пустое множество — успешный пустой список.
    """
    out = _git_output(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
    if out is None:
        return None
    paths = (root / name for name in os.fsdecode(out).split("\0") if name)
    return {path for path in paths if path_filter is None or path_filter(path)}


def _walk_files(base, skip, exclusions, onerror=None, directory_allowed=None):
    """Обход обычного каталога, если для него нет списка Git."""
    for dirpath, dirnames, filenames in os.walk(base, onerror=onerror):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if here / d not in skip
                             and not exclusions.excludes(here / d, directory=True, base=base)
                             and (directory_allowed is None or directory_allowed(here / d, True)))
        for name in sorted(filenames):
            yield here / name


def walk_md(base, skip=(), root=None, exclusions=None):
    """Обход Markdown вне проекта с его списком Git."""
    exclusions = exclusions or SkipDirs(root or base)
    if exclusions.excludes(base, directory=True, base=base):
        return
    for path in _walk_files(base, skip, exclusions):
        if (path.suffix.lower() == ".md"
                and not (path.is_symlink() and exclusions.excludes(path.resolve(), base=base))):
            yield path


class Page:
    def __init__(self, path, text):
        self.path, self.text = path, text
        self.masked = mask_code(text)
        self.lines = text.count("\n") + 1
        self.anchors, self.anchor_order, self.dup = {}, [], []
        for m in RE_ANCHOR.finditer(self.masked):
            line = line_of(self.masked, m.start())
            if m.group(1) in self.anchors:
                self.dup.append((line, m.group(1)))
            else:
                self.anchors[m.group(1)] = line
                self.anchor_order.append((line, m.group(1)))
        self.slugs, self.slug_dups, self.h1, self.h1_line = {}, [], None, 0
        for n, s in enumerate(self.masked.split("\n"), 1):
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
            if m:
                raw = text.split("\n")[n - 1]
                title = re.sub(r"^#{1,6}\s+", "", raw).strip()
                slug = heading_slug(title)
                if slug in self.slugs:
                    self.slug_dups.append((n, slug))
                else:
                    self.slugs[slug] = n
                if self.h1 is None and len(m.group(1)) == 1:
                    self.h1 = re.sub(r"\s*<a\s+id=[^>]*>\s*(</a>)?", "", title).strip()
                    self.h1_line = n

    @cached_property
    def links(self):
        return [(line_of(self.text, link.start), link.address) for link in markdown_links(self.text)]

    def header(self):
        """Шапка: строки «- Ключ: значение» сразу после H1."""
        return {key: values[-1] for key, values in self._header_values().items()}

    def header_values(self, key):
        """Все значения повторяемой строки шапки в порядке документа."""
        return self._header_values().get(key, [])

    def _header_values(self):
        res, key = {}, None
        if not self.h1_line:
            return res
        for s in self.text.split("\n")[self.h1_line:]:
            m = RE_HEADER.match(s)
            if m:
                key = m.group(1).strip()
                res.setdefault(key, []).append(m.group(2).strip())
            elif s.startswith("  ") and key and s.strip():
                res[key][-1] = (res[key][-1] + " " + s.strip()).strip()
            elif s.strip() or res:
                break
        return res


class Project:
    def __init__(self, root, cfg, *, git_file_filter=None):
        self.root, self.cfg = root, cfg
        self.skip_dirs = SkipDirs(root, cfg.get("skip_dirs", []))
        self.target_skip_dirs = SkipDirs(root, cfg.get("skip_dirs", []), include_agents=True)
        self.git_root = git_worktree_root(root)
        self.git_files = list_project_files(root, path_filter=git_file_filter) if self.git_root else None
        keys = ("docs", "description", "workflow", "decisions")
        catalogs = {key: self.catalog_path(cfg[key]) for key in keys if cfg.get(key)}
        self.editions = {language: self.catalog_path(base) for language, base in
                         cfg.get("languages", {}).get("editions", {}).items()}
        self.external_roots = tuple(base for base in (*catalogs.values(), *self.editions.values())
                                    if base is not None and not is_within(base, root))
        self.docs = catalogs.get("docs")
        self.descr = catalogs.get("description")
        self.wf = catalogs.get("workflow")
        self.decisions = (catalogs.get("decisions") if 'decisions' in cfg
                          else self.wf / 'adr' if self.wf else None)
        for name in ("docs", "descr", "wf"):
            d = getattr(self, name)
            if d is not None and not d.is_dir():
                setattr(self, name, None)
        self.pages = {}
        self.mark_anchors, self.mark_work = {}, {}
        self.mark_external = {}
        self.mark_work_index = None

    def lexical_path(self, path):
        return Path(os.path.abspath(self.root / path))

    def catalog_path(self, path):
        """Явно заданный каталог; локальные ссылки Git не раскрывают каталог."""
        path = self.lexical_path(path)
        if self.git_root is not None and is_within(path, self.root):
            return None if has_symlink(path, self.root) else path
        return path.resolve()

    @cached_property
    def sources(self):
        """Ленивый набор своего проекта и явно подключённых соседей."""
        from ..sources import SourceSet
        return SourceSet(self)

    @cached_property
    def connected_roots(self):
        """Физические корни прямых подключений для границы своего чтения."""
        roots = []
        for connection in self.cfg.get('repos', {}).values():
            try:
                roots.append((self.root / connection['path']).resolve())
            except (OSError, RuntimeError, ValueError):
                continue
        return tuple(roots)

    # @trace docs/ru/settings.md#repos
    def in_connected_repo(self, path):
        """Проверяет переданное имя; свой вложенный корень имеет приоритет."""
        return self._connected(self.lexical_path(path))

    def _connected(self, path):
        return any(is_within(path, root)
                   and not (is_within(self.root, root) and is_within(path, self.root))
                   for root in self.connected_roots)

    def in_git(self, p):
        """Проверка исходного имени файла по инвентарю Git."""
        return self._listed(self.lexical_path(p), False)

    def _listed(self, path, directory):
        scope = self._file_scope(path)
        git_root, names = self._git_listing(scope)
        if git_root is None:
            return True
        if names is None:
            return path not in self.git_ignored_paths((path,))
        return path in (self._directories(scope) if directory else names)

    @cached_property
    def _external_git(self):
        listings = {}
        if self.git_root is not None:
            for scope in self.external_roots:
                git_root = git_worktree_root(scope)
                listings[scope] = git_root, list_project_files(scope) if git_root else None
        return listings

    def _git_listing(self, scope):
        if scope == self.root:
            return self.git_root, self.git_files
        return self._external_git.get(scope, (None, None))

    def git_file_names(self, base):
        """Лексический инвентарь области, которой принадлежит каталог."""
        return self._git_listing(self._file_scope(self.lexical_path(base)))[1]

    @cached_property
    def _git_directories(self):
        return {}

    def _directories(self, scope):
        if scope not in self._git_directories:
            _, names = self._git_listing(scope)
            self._git_directories[scope] = {parent for path in names or () for parent in path.parents
                                           if is_within(parent, scope)}
        return self._git_directories[scope]

    def git_ignored_paths(self, paths):
        """Исключённые Git имена, включая ещё не созданные выходные файлы."""
        if self.git_root is None:
            return set()
        groups = {}
        for path in paths:
            scope = self._file_scope(path)
            git_root, listed = self._git_listing(scope)
            if git_root and path != scope and (listed is None or path not in listed):
                groups.setdefault(scope, set()).add(path)
        return {path for scope, candidates in groups.items()
                for path in self._git_ignored(scope, candidates)}

    def _git_ignored(self, scope, candidates):
        if not candidates:
            return set()
        names = b"".join(b"./" + os.fsencode(path.relative_to(scope)) + b"\0" for path in candidates)
        try:
            result = subprocess.run(
                ["git", "-C", str(scope), "check-ignore", "-z", "--stdin"], input=names,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"), check=False)
        except OSError:
            return candidates
        if result.returncode not in (0, 1):
            return candidates
        return {scope / os.fsdecode(name) for name in result.stdout.split(b"\0") if name}

    def file_path(self, path, *, directory=False):
        """Отбор по лексическому имени, затем раскрытие ссылки и границы чтения."""
        lexical = self.lexical_path(path)
        if not self._listed(lexical, directory):
            return None
        if not self._path_allowed(lexical, directory):
            return None
        try:
            if self.git_root is None:
                real = lexical.resolve()
            else:
                scope = self._file_scope(lexical)
                real = self._resolve_git_path(lexical, scope) if scope is not None else None
        except (OSError, RuntimeError, ValueError):
            return None
        if real is None or real != lexical and not self._path_allowed(real, directory):
            return None
        if real != lexical and not self._listed(real, directory):
            return None
        return real

    def _file_scope(self, path):
        if is_within(path, self.root):
            return self.root
        return next((root for root in self.external_roots if is_within(path, root)), None)

    def _resolve_git_path(self, lexical, scope):
        """Проверяет и промежуточные ссылки перед чтением их назначения."""
        parts = deque(lexical.relative_to(scope).parts)
        here = scope
        links = 0
        while parts:
            part = parts.popleft()
            if part == "..":
                here = here.parent
                if self._file_scope(here) != scope:
                    return None
                continue
            path = here / part
            if self._file_scope(path) != scope or not self._path_allowed(path, bool(parts)):
                return None
            if not path.is_symlink():
                here = path
                continue
            if links == 40 or not self._listed(path, False):
                return None
            links += 1
            target = path.readlink()
            if target.is_absolute():
                if self._file_scope(target) != scope:
                    return None
                target = target.relative_to(scope)
                here = scope
            parts.extendleft(reversed(target.parts))
        return here

    def _path_allowed(self, path, directory):
        return not self._connected(path)

    def _walk_selected(self, base=None, *, skip=(), exclusions=None, onerror=None, path_filter=None):
        base = self.lexical_path(base if base is not None else self.root)
        exclusions = exclusions or self.skip_dirs
        if exclusions.excludes(base, directory=True, base=base) or not self._path_allowed(base, True):
            return
        skip = {path for path in skip if path is not None and path != base}
        git_root, names = self._git_listing(self._file_scope(base))
        if names is None and self.file_path(base, directory=True) is None:
            return
        def directory_allowed(path, directory):
            return self._path_allowed(path, directory) and (git_root is None or self._listed(path, directory))

        candidates = (sorted(path for path in names if is_within(path, base))
                      if names is not None else _walk_files(base, skip, exclusions, onerror, directory_allowed))
        for path in candidates:
            if (exclusions.excludes(path, base=base) or any(is_within(path, d) for d in skip)
                    or path_filter is not None and not path_filter(path)):
                continue
            real = self.file_path(path)
            if (real is not None and not exclusions.excludes(real, base=base)
                    and not any(is_within(real, d) for d in skip)
                    and (names is None or real.is_file())):
                yield path, real

    def walk_files(self, base=None, *, resolved=False, **options):
        """Файлы проекта с учётом границ выбранного обхода."""
        return (real if resolved else path for path, real in self._walk_selected(base, **options))

    def walk_md(self, base, *, path_filter=None, **options):
        return self.walk_files(
            base, path_filter=lambda path: path.suffix.lower() == ".md"
            and (path_filter is None or path_filter(path)), **options)

    def refresh_git_files(self):
        if self.git_root is not None:
            self.git_files = list_project_files(self.root)
            self.__dict__.pop("_git_directories", None)
            self.__dict__.pop("_external_git", None)

    def rel(self, p):
        return Path(os.path.relpath(p, self.root)).as_posix()

    def page(self, path):
        path = self.file_path(path)
        if path is None:
            return None
        if path not in self.pages:
            text = read_text(path)
            self.pages[path] = Page(path, text) if text is not None else None
        return self.pages[path]

    def anchor_exists(self, page, anchor):
        return anchor in page.anchors

    def release_notes_path(self):
        """Путь страницы описания с записями о выпусках (release_notes) или None.

        Ключ называет страницу от каталога описания; D3 не проверяет её
        размер, остальные проверки описания действуют. Файла может не быть:
        тогда пропускать нечего.
        """
        rel = self.cfg.get("release_notes")
        if self.docs is None or not isinstance(rel, str) or not rel.strip():
            return None
        return self.file_path(self.docs / rel)


def resolve_target(page, target, project=None):
    """Куда ведёт ссылка внутри проекта: (абсолютный путь, якорь) или (None, None)."""
    if RE_SCHEME.match(target):
        return None, None
    path_part, _, anchor = target.partition("#")
    path = page.path.parent / unquote(path_part) if path_part else page.path
    if project is None:
        tpath = path.resolve()
    else:
        tpath = project.file_path(path)
        if tpath is None:
            directory = project.file_path(path, directory=True)
            tpath = directory if directory is not None and directory.is_dir() else None
    if tpath is None or not tpath.exists():
        return None, None
    return tpath, unquote(anchor) if anchor else None


def walk_md_agents(project):
    """Markdown-файлы правил проекта в .agents/ (кроме замечаний и файлов lipi)."""
    root = project.root
    return project.walk_md(root / ".agents", skip=(root / FEEDBACK, root / LIPI_DIR),
                           exclusions=project.target_skip_dirs)
