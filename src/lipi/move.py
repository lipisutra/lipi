#!/usr/bin/env python3
"""lipi mv — план и безопасный перенос файлов и каталогов внутри Git-проекта."""
import json
import os
import shlex
import stat
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (OSError, ValueError):
            pass
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lipi.i18n import ArgumentParser, cli_output, tr
from lipi.checker.config import load_config, validate_settings
from lipi.checker.conventions import CODE_EXT, CONFIG_NAME, HISTORY_DIR, LOCK_NAME, LIPI_DIR
from lipi.checker.model import Project, is_within
from lipi.checker.paths import SkipDirs
from lipi.move_links import replacements
from lipi.move_neighbors import neighbor_notices
from lipi.move_reviews import AddressReceipt, prepare_transfer
from lipi.checker.reviews import REVIEWS_NAME, ReviewError


class MoveError(ValueError):
    """Отказ до записи или объяснение неудачного переноса."""


def _git(root, *args, index=None):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    if index is not None:
        env['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(
        ['git', '-C', str(root), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env)
    if result.returncode:
        raise MoveError(result.stderr.decode('utf-8', 'replace').strip()
                        or tr('move.git.failed') % args[0])
    return result.stdout


def _absolute(base, name):
    return Path(os.path.abspath(base / name))


def _no_symlinks(path, root):
    if not is_within(path, root):
        raise MoveError(tr('move.path.outside') % path)
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink():
            raise MoveError(tr('move.path.symlink') % item)


def _stamp(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


@dataclass
class FileChange:
    path: Path
    before: bytes
    after: bytes
    stamp: tuple
    edits: list
    address_receipt: object = None
    mode: object = None


@dataclass
class MovePlan:
    root: Path
    moves: dict
    changes: list
    notices: list
    index: Path
    index_before: bytes
    bulk: bool
    source_dirs: list
    reviews: object
    config: dict


# @trace docs/ru/move.md#scope
def _scope(root, cfg):
    """Фильтр перед чтением: свои правила входят, архив и подключения — нет."""
    skip = SkipDirs(root, cfg.get('skip_dirs', []), include_agents=True)
    boundaries = [root / LIPI_DIR]
    for connection in cfg.get('repos', {}).values():
        child = _absolute(root, connection['path'])
        if child != root and is_within(child, root):
            boundaries.append(child)
        resolved = child.resolve()
        if resolved != root and is_within(resolved, root):
            boundaries.append(resolved)
    managed = set()
    lock = root / LOCK_NAME
    if lock.is_file() and not lock.is_symlink():
        data = json.loads(lock.read_text(encoding='utf-8'))
        managed.update(_absolute(root, name) for name in data.get('files', {}))

    def allowed(path):
        if not is_within(path, root):
            return False
        parts = path.relative_to(root).parts
        return (not skip.excludes(path) and 'history' not in parts[:-1]
                and path not in managed
                and not any(is_within(path, base) for base in boundaries))
    return allowed


def _index_path(root):
    name = os.fsdecode(_git(root, 'rev-parse', '--git-path', 'index')).strip()
    return _absolute(root, name)


def _ensure_destination(old, new, root):
    _no_symlinks(old, root)
    _no_symlinks(new, root)
    if old == new:
        raise MoveError(tr('move.source.same') % old)
    if not old.is_file():
        raise MoveError(tr('move.source.missing') % old)
    if os.path.lexists(new):
        raise MoveError(tr('move.destination.exists') % new)
    parent = new.parent
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir():
        raise MoveError(tr('move.destination.parent') % parent)


def _pairs(cwd, root, old_arg, new_arg, from_file):
    if from_file is None:
        if old_arg is None or new_arg is None:
            raise MoveError(tr('move.arguments.paths'))
        return [(_absolute(cwd, old_arg), _absolute(cwd, new_arg))]
    if old_arg is not None or new_arg is not None:
        raise MoveError(tr('move.arguments.exclusive'))
    pairs = []
    for number, line in enumerate(_absolute(cwd, from_file).read_text(encoding='utf-8').splitlines(), 1):
        try:
            names = shlex.split(line, comments=True)
        except ValueError as error:
            raise MoveError(tr('move.batch.line') % (number, error)) from error
        if not names:
            continue
        if len(names) != 2:
            raise MoveError(tr('move.batch.line.two') % number)
        pairs.append(tuple(_absolute(root, name) for name in names))
    if not pairs:
        raise MoveError(tr('move.batch.empty'))
    return pairs


def _overlap(left, right):
    return is_within(left, right) or is_within(right, left)


def _expand(pairs, project, allowed, tracked, names, directories, standalone):
    """Зафиксировать источники до появления новых каталогов, не читая исключённое."""
    root = project.root
    moves, notices, source_dirs = {}, [], set()
    for pos, (old, new) in enumerate(pairs):
        directory = old in directories
        if not directory and old not in tracked:
            raise MoveError(tr('move.source.untracked') % old)
        if not allowed(old / '__file__' if directory else old):
            raise MoveError(tr('move.path.excluded') % old)
        _no_symlinks(old, root)
        _no_symlinks(new, root)
        if old == new:
            raise MoveError(tr('move.source.same') % old)
        for prior_old, prior_new in pairs[:pos]:
            if _overlap(old, prior_old):
                raise MoveError(tr('move.source.overlap') % (prior_old, old))
            if _overlap(new, prior_new):
                raise MoveError(tr('move.destination.overlap') % (prior_new, new))
        if not allowed(new / '__file__' if directory else new):
            raise MoveError(tr('move.path.excluded') % new)
        if os.path.lexists(new) or any(_overlap(new, path) for path in tracked):
            raise MoveError(tr('move.destination.unavailable') % new)
        if directory:
            selected = []
            for path in names:
                if not is_within(path, old):
                    continue
                if not allowed(path):
                    notices.append(tr('move.notice.excluded') % path.relative_to(root))
                elif path not in tracked:
                    notices.append(tr('move.notice.untracked') % path.relative_to(root))
                else:
                    selected.append(path)
            # Имена каталогов нужны только для удаления опустевших исходных папок.
            for path in selected:
                parent = path.parent
                while is_within(parent, old):
                    source_dirs.add(parent)
                    if parent == old:
                        break
                    parent = parent.parent
        else:
            selected = [old]
            if standalone and (old.suffix.lower() != '.md' or new.suffix.lower() != '.md'):
                raise MoveError(tr('move.arguments.markdown'))
        if not selected:
            raise MoveError(tr('move.source.no_tracked') % old)
        for path in selected:
            destination = new / path.relative_to(old) if directory else new
            if project.file_path(path) is None:
                raise MoveError(tr('move.source.not_available') % path)
            if not allowed(destination):
                raise MoveError(tr('move.destination.excluded') % destination)
            _ensure_destination(path, destination, root)
            if any(_overlap(destination, other) for other in tracked):
                raise MoveError(tr('move.destination.tracked') % destination)
            if path in moves:
                raise MoveError(tr('move.source.duplicate') % path)
            moves[path] = destination
    destinations = sorted(moves.values())
    for pos, path in enumerate(destinations):
        if any(_overlap(path, other) for other in destinations[:pos]):
            raise MoveError(tr('move.destination.collision') % path)
    return moves, notices, sorted(source_dirs, key=lambda p: len(p.parts), reverse=True)


# @trace docs/ru/move.md#plan
def _clean_affected(root, changes, tracked):
    paths = [change.path.relative_to(root).as_posix() for change in changes]
    # Porcelain diff может обновить stat-cache даже с OPTIONAL_LOCKS=0;
    # планирование обязано сохранять точные байты настоящего индекса.
    args = ('-c', 'diff.autoRefreshIndex=false', '--literal-pathspecs',
            'diff', '--relative', '--no-renames', '--no-ext-diff', '--no-textconv', '-z')
    staged = _git(root, *args, '--cached', '--name-only', '--', *paths)
    dirty = {_absolute(root, os.fsdecode(name)) for name in staged.split(b'\0') if name}
    records = _git(root, *args, '--raw', '--no-abbrev', '--', *paths).split(b'\0')
    candidates = []
    for header, name in zip(records[::2], records[1::2]):
        old_mode, new_mode, old_blob, _, status = header[1:].split()
        path = _absolute(root, os.fsdecode(name))
        if status == b'M' and old_mode == new_mode:
            candidates.append((path, old_blob))
        else:
            dirty.add(path)
    if candidates:
        # Raw diff и numstat могут принять устаревший stat-cache бинарного
        # файла за правку. Хеш сравнивает содержимое с индексом с учётом
        # фильтров Git и нормализации переводов строк, не обновляя индекс.
        hashes = _git(root, 'hash-object', '--',
                      *(path.relative_to(root).as_posix() for path, _ in candidates)).splitlines()
        dirty.update(path for (path, expected), actual in zip(candidates, hashes)
                     if actual != expected)
    affected = sorted(change.path for change in changes if change.path in dirty or change.path not in tracked)
    if affected:
        raise MoveError(tr('move.files.dirty') +
                        ', '.join(str(path.relative_to(root)) for path in affected))


def archive_present(project):
    roots = [project.root]
    if project.wf is not None:
        roots.append(project.wf)
    for directory in roots:
        archive = directory / HISTORY_DIR
        if not archive.is_symlink() and archive.is_dir():
            return True
    return any(HISTORY_DIR in path.relative_to(project.root).parts[:-1] and path.parent.is_dir()
               for path in project.git_files or ())


# @trace docs/ru/move.md#plan,ADR-017
def make_plan(cwd, old_arg=None, new_arg=None, *, from_file=None, pairs=None, config=None):
    cwd = Path(cwd).resolve()
    git_root = Path(os.fsdecode(_git(cwd, 'rev-parse', '--show-toplevel')).strip()).resolve()
    root = next((path for path in (cwd, *cwd.parents) if is_within(path, git_root)
                 and os.path.lexists(path / CONFIG_NAME)), git_root)
    internal = pairs is not None
    pairs = list(pairs) if internal else _pairs(cwd, git_root, old_arg, new_arg, from_file)
    _no_symlinks(root / CONFIG_NAME, root)
    cfg = load_config(root, None) if config is None else config
    errors = validate_settings(root, cfg)
    if errors:
        raise MoveError('; '.join('%s: %s' % item for item in errors))
    allowed = _scope(root, cfg)
    index = _index_path(root)
    index_before = index.read_bytes()
    project = Project(root, cfg)
    if project.git_files is None:
        raise MoveError(tr('move.git.list_failed'))
    tracked = {_absolute(root, os.fsdecode(name)) for name in
               _git(root, 'ls-files', '--cached', '-z', '--', '.').split(b'\0') if name}
    directories = {old for old, _ in pairs if is_within(old, root)
                   and any(old in path.parents for path in tracked)}
    bulk = internal or from_file is not None or bool(directories)
    moves, notices, source_dirs = _expand(pairs, project, allowed, tracked, sorted(project.git_files),
                                         directories, not bulk)
    changes = []
    move_addresses = frozenset(moves.items())
    extensions = {'.' + ext for ext in CODE_EXT.split('|')} | {'.md'}

    def target_allowed(path):
        return (project.file_path(path) is not None
                or project.file_path(path, directory=True) is not None)

    for path in project.walk_files(exclusions=project.target_skip_dirs, path_filter=allowed):
        try:
            _no_symlinks(path, root)
        except MoveError:
            if path in moves:
                raise
            continue
        if not path.is_file() or (path.suffix.lower() not in extensions and path not in moves):
            continue
        before_stamp = _stamp(path)
        data = path.read_bytes()
        edits, after = [], data
        if path.suffix.lower() in extensions:
            invalid_utf8 = False
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = data.decode('utf-8', errors='surrogateescape')
                invalid_utf8 = True
            edits = replacements(text, path=path, moves=moves, root=root,
                                 markdown=path.suffix.lower() == '.md', target_allowed=target_allowed)
            if edits or path in moves:
                if invalid_utf8:
                    if edits or not bulk:
                        raise MoveError(tr('move.file.encoding') % path)
                    # Массовый перенос допускает любые байты, пока файл не
                    # требует замены ссылок; расширение не делает его текстом.
                else:
                    for edit in reversed(edits):
                        text = text[:edit.start] + edit.after + text[edit.end:]
                    after = text.encode('utf-8')
        if edits or path in moves:
            receipt = AddressReceipt(root, path, data, after, move_addresses, tuple(edits))
            changes.append(FileChange(path, data, after, before_stamp, edits, receipt))
    if moves.keys() - {change.path for change in changes}:
        raise MoveError(tr('move.source.out_of_scope'))
    if os.path.lexists(root / REVIEWS_NAME):
        project = Project(root, cfg, git_file_filter=allowed)
    reviews = prepare_transfer(project, moves, changes)
    if reviews.before != reviews.after:
        review_path = root / REVIEWS_NAME
        _no_symlinks(review_path, root)
        changes.append(FileChange(review_path, reviews.before, reviews.after,
                                  _stamp(review_path), []))
    if bulk:
        _clean_affected(root, changes, tracked)
    notices.extend(reviews.notices)
    if not internal and archive_present(project):
        notices.append(tr('move.notice.history'))
    notices.append(tr('move.notice.external'))
    notices.extend(neighbor_notices(project, moves))
    plan = MovePlan(root, moves, changes, notices, index, index_before, bulk, source_dirs,
                    reviews, cfg)
    _validate(plan, project)
    return plan


def _writable(path, directory=False):
    bits = stat.S_IMODE(path.stat().st_mode)
    if not bits & 0o222 or not os.access(path, os.W_OK):
        raise MoveError(tr('move.file.write_access') % path)
    if directory and (not bits & 0o111 or not os.access(path, os.X_OK)):
        raise MoveError(tr('move.directory.access') % path)


# @trace docs/ru/move.md#plan
def _validate(plan, project):
    plan.reviews.validate(project)
    for old, new in plan.moves.items():
        _ensure_destination(old, new, plan.root)
    if plan.index.read_bytes() != plan.index_before:
        raise MoveError(tr('move.index.changed'))
    if Path(str(plan.index) + '.lock').exists():
        raise MoveError(tr('move.index.locked'))
    _writable(plan.index)
    _writable(plan.index.parent, directory=True)
    conflicts = _git(plan.root, 'ls-files', '--unmerged', '-z')
    conflict_paths = {record.split(b'\t', 1)[1] for record in conflicts.split(b'\0') if record}
    for change in plan.changes:
        path = change.path
        _no_symlinks(path, plan.root)
        if (_stamp(path) != change.stamp or path.read_bytes() != change.before):
            raise MoveError(tr('move.file.changed') % path)
        if os.fsencode(path.relative_to(plan.root).as_posix()) in conflict_paths:
            raise MoveError(tr('move.git.conflict') % path)
        if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
            raise MoveError(tr('move.file.regular') % path)
        _writable(path)
        if path == plan.root / REVIEWS_NAME:
            _writable(path.parent, directory=True)
    for old, new in plan.moves.items():
        _writable(old.parent, directory=True)
        parent = new.parent
        while not parent.exists():
            parent = parent.parent
        _writable(parent, directory=True)


# @trace docs/ru/move.md#apply,ADR-017
def apply_plan(plan):
    """Весь план проверяется до записи; git mv работает с временным индексом."""
    from lipi.review import registry_lock
    with registry_lock(plan.root) if plan.reviews.before is not None else nullcontext():
        _apply_plan(plan)


def _apply_plan(plan):
    from lipi.move_transaction import apply_transaction
    apply_transaction(plan, project_files_only=True)


# @trace docs/ru/move.md#plan
def print_plan(plan):
    for old, new in plan.moves.items():
        print('git mv %s → %s' % (old.relative_to(plan.root), new.relative_to(plan.root)))
    for change in plan.changes:
        if not change.edits:
            continue
        text = change.before.decode('utf-8')
        for edit in change.edits:
            print('%s:%d: %s → %s' % (
                change.path.relative_to(plan.root), text.count('\n', 0, edit.start) + 1,
                json.dumps(edit.before, ensure_ascii=False), json.dumps(edit.after, ensure_ascii=False)))
    for notice in plan.notices:
        print(notice)


# @trace docs/ru/move.md#paths
@cli_output
def main(argv=None):
    parser = ArgumentParser(prog='lipi mv', description=tr('move.help.description'))
    parser.add_argument('old', nargs='?', help=tr('move.help.old'))
    parser.add_argument('new', nargs='?', help=tr('move.help.new'))
    parser.add_argument('--from', dest='from_file', metavar=tr('move.help.file'),
                        help=tr('move.help.from'))
    parser.add_argument('--apply', action='store_true', help=tr('move.help.apply'))
    args = parser.parse_args(argv)
    try:
        plan = make_plan(Path.cwd(), args.old, args.new, from_file=args.from_file)
        print_plan(plan)
        if args.apply:
            apply_plan(plan)
            print(tr('move.notice.complete'))
        else:
            print(tr('move.notice.plan'))
        return 0
    except ReviewError as error:
        print('lipi mv: C1: %s' % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(tr('move.cli.interrupted'), file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print('lipi mv: %s' % error, file=sys.stderr)
        return 130 if isinstance(error.__cause__, KeyboardInterrupt) else 2


if __name__ == '__main__':
    sys.exit(main())
