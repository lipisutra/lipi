"""Применение одного плана: адреса, содержимое, режимы и точный индекс Git."""
import os
from pathlib import Path
import stat
import tempfile

from .i18n import tr


def _state(path):
    """Состояние обычного файла; отсутствие отличается от пустых байтов."""
    if not os.path.lexists(path):
        return None, None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        from .move import MoveError
        raise MoveError(tr('move.file.no_links') % path)
    return path.read_bytes(), stat.S_IMODE(info.st_mode)


def _write(path, data, mode):
    """Атомарная замена; временный файл никогда не остаётся в плане."""
    if data is None:
        path.unlink()
        return
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix='.lipi-write-', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parents(path, created):
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        created.append(directory)  # До mkdir: прерывание может прийти после записи.
        try:
            directory.mkdir()
        except FileExistsError:
            created.pop()  # Каталог создал другой процесс; он нам не принадлежит.
            raise


def _file_scope(plan, path):
    """Только init может добавить точные новые seed-файлы вне корня."""
    from .move import _no_symlinks
    if path.is_relative_to(plan.root):
        _no_symlinks(path, plan.root)
        return
    if path not in getattr(plan, 'external_creates', ()):
        _no_symlinks(path, plan.root)  # Обычный mv сохраняет прежний отказ.
    _no_symlinks(path, Path(path.anchor))


def _validate(plan, *, project_files_only=False):
    from .move import MoveError, _no_symlinks, _stamp, _writable, _git, _scope
    from .checker.model import Project
    from .checker.reviews import REVIEWS_NAME
    for path, expected in getattr(plan, 'guards', {}).items():
        _no_symlinks(path, plan.root)
        if _state(path)[0] != expected:
            raise MoveError(tr('move.file.changed_after_read') % path)
    reviews = getattr(plan, 'reviews', None)
    if reviews is not None or project_files_only:
        project = Project(plan.root, plan.config,
                          git_file_filter=_scope(plan.root, plan.config))
        if project_files_only and project.git_files is None:
            raise MoveError(tr('move.git.list_failed'))
        if reviews is not None:
            reviews.validate(project)
    changes = {change.path: change for change in plan.changes}
    if len(changes) != len(plan.changes):
        raise MoveError(tr('move.plan.duplicate_path'))
    destinations = set(plan.moves.values())
    if len(destinations) != len(plan.moves) or destinations & set(plan.moves):
        raise MoveError(tr('move.plan.overlap'))
    if destinations & set(changes):
        raise MoveError(tr('move.plan.destination_changed'))
    for directory in getattr(plan, 'directories', ()):
        _no_symlinks(directory, plan.root)
        parent = directory
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise MoveError(tr('move.parent.not_dir') % parent)
        _writable(parent, directory=True)
    before = {}
    conflicts = set()
    if plan.index is not None:
        if _state(plan.index)[0] != plan.index_before:
            raise MoveError(tr('move.index.changed'))
        if Path(str(plan.index) + '.lock').exists():
            raise MoveError(tr('move.index.locked'))
        if plan.index.exists():
            _writable(plan.index)
        _writable(plan.index.parent, directory=True)
        conflicts = {record.split(b'\t', 1)[1] for record in
                     _git(plan.root, 'ls-files', '--unmerged', '-z').split(b'\0') if record}
    for directory in plan.source_dirs:
        _no_symlinks(directory, plan.root)
        if directory == plan.root:
            raise MoveError(tr('move.project.root'))
    for change in plan.changes:
        path = change.path
        if any(value is not None and not isinstance(value, bytes)
               for value in (change.before, change.after)):
            raise MoveError(tr('move.file.data_type') % path)
        if (project_files_only and path != plan.root / REVIEWS_NAME
                and project.file_path(path) is None):
            raise MoveError(tr('move.file.out_of_scope') % path)
        _file_scope(plan, path)
        if not path.is_relative_to(plan.root) and (change.before is not None or change.after is None):
            raise MoveError(tr('move.file.seed') % path)
        state = _state(path)
        if state[0] != change.before or (change.before is not None and
                (change.stamp is None or _stamp(path) != change.stamp)):
            raise MoveError(tr('move.file.changed') % path)
        if path.is_relative_to(plan.root) and os.fsencode(path.relative_to(plan.root).as_posix()) in conflicts:
            raise MoveError(tr('move.git.conflict') % path)
        mode = getattr(change, 'mode', None)
        if mode is not None and (not isinstance(mode, int) or isinstance(mode, bool)
                                 or not 0 <= mode <= 0o7777):
            raise MoveError(tr('move.file.mode') % path)
        if change.before is not None:
            _writable(path)
        before[path] = state
    for old, new in plan.moves.items():
        _no_symlinks(old, plan.root)
        if old not in changes or changes[old].before is None:
            raise MoveError(tr('move.source.snapshot') % old)
        _no_symlinks(new, plan.root)
        if os.path.lexists(new):
            raise MoveError(tr('move.destination.exists') % new)
    for path in set(changes) | set(plan.moves) | destinations:
        parent = path.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise MoveError(tr('move.parent.not_dir') % parent)
        _writable(parent, directory=True)
    return before


def apply_transaction(plan, *, project_files_only=False, final_file=None):
    """Применить MovePlan; None в before/after означает создание/удаление.

    mode задаёт конечные права; без него сохраняются прежние, новые — 0644.
    changes адресованы исходными путями. moves меняет только адреса в индексе;
    правки, создания и удаления остаются для просмотра и явного git add.
    Registry lock удерживает вызывающий код. Ошибка или Ctrl-C откатывает
    только затронутые пути, без reset/checkout репозитория.
    """
    from .move import MoveError, _git, _no_symlinks
    before = _validate(plan, project_files_only=project_files_only)
    created, moved, written, removed = [], [], [], []
    temporary = None
    lock = Path(str(plan.index) + '.lock') if plan.index is not None else None
    own_lock = installing = False
    index_after = None
    index_mode = _state(plan.index)[1] if plan.index is not None else None
    try:
        for directory in getattr(plan, 'directories', ()):
            _no_symlinks(directory, plan.root)
            _parents(directory / '__planned_directory__', created)
        if plan.index is not None and plan.moves:
            descriptor, name = tempfile.mkstemp(prefix='lipi-mv-', dir=plan.index.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(plan.index_before)
        for old, new in plan.moves.items():
            _no_symlinks(old, plan.root)
            _no_symlinks(new, plan.root)
            if _state(old) != before[old] or os.path.lexists(new):
                raise MoveError(tr('move.paths.changed_during') % old)
            _parents(new, created)
            moved.append((old, new))
            if plan.index is None:
                old.rename(new)
            else:
                _git(plan.root, 'mv', '--', old.relative_to(plan.root).as_posix(),
                     new.relative_to(plan.root).as_posix(), index=temporary)
        for change in plan.changes:
            path = plan.moves.get(change.path, change.path)
            previous = before[change.path]
            mode = getattr(change, 'mode', None)
            after = (change.after, (mode if mode is not None else
                                   previous[1] if previous[1] is not None else 0o644)
                     if change.after is not None else None)
            _file_scope(plan, path)
            if _state(path) != previous:
                raise MoveError(tr('move.file.changed_during') % path)
            if previous == after:
                continue
            _parents(path, created)
            written.append((path, previous, after))
            _write(path, *after)
        for directory in sorted(plan.source_dirs, key=lambda p: len(p.parts), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                removed.append((directory, stat.S_IMODE(directory.stat().st_mode)))
                directory.rmdir()
        if plan.index is not None:
            if _state(plan.index)[0] != plan.index_before:
                raise MoveError(tr('move.index.changed_during'))
        if temporary is not None:
            index_after = temporary.read_bytes()
            with lock.open('xb') as stream:
                own_lock = True
                if _state(plan.index)[0] != plan.index_before:
                    raise MoveError(tr('move.index.changed_during'))
                stream.write(index_after)
            lock.chmod(index_mode)
            Path(str(temporary) + '.lock').unlink(missing_ok=True)
            temporary.unlink()
            temporary = None
            installing = True  # До replace: оно могло успеть до KeyboardInterrupt.
            os.replace(lock, plan.index)
            own_lock = False
        if final_file is not None:
            # First init needs the finished worktree and index to calculate the baseline.
            path, contents = final_file
            try:
                data = contents(plan.root)
            except Exception as error:
                raise MoveError(str(error)) from error
            _file_scope(plan, path)
            if os.path.lexists(path):
                raise MoveError(tr('move.file.changed_during') % path)
            _parents(path, created)
            written.append((path, (None, None), (data, 0o644)))
            _write(path, data, 0o644)
    except (OSError, ValueError, KeyboardInterrupt) as error:
        failures = []

        def restore(action):
            try:
                action()
            except (OSError, ValueError, KeyboardInterrupt) as failure:
                failures.append(str(failure))

        # Сначала вернуть каталоги: удалённые файлы могут лежать внутри них.
        for directory, mode in reversed(removed):
            def restore_directory(directory=directory, mode=mode):
                if directory.exists():
                    if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) != mode:
                        raise MoveError(tr('move.rollback.directory') % directory)
                    return
                directory.mkdir(mode=mode)
                directory.chmod(mode)
            restore(restore_directory)
        for path, previous, after in reversed(written):
            def restore_file(path=path, previous=previous, after=after):
                _file_scope(plan, path)
                current = _state(path)
                if current == previous:
                    return
                # Windows chmod only controls read-only; stat synthesizes other bits.
                data, mode = current
                expected_data, expected_mode = after
                if os.name == 'nt' and mode is not None and expected_mode is not None:
                    mode &= stat.S_IWRITE
                    expected_mode &= stat.S_IWRITE
                if data != expected_data or mode != expected_mode:
                    raise MoveError(tr('move.rollback.file') % path)
                _write(path, *previous)
            restore(restore_file)
        for old, new in reversed(moved):
            def restore_move(old=old, new=new):
                _no_symlinks(old, plan.root)
                _no_symlinks(new, plan.root)
                old_state, new_state = _state(old), _state(new)
                if old_state == before[old] and new_state[0] is None:
                    return
                if old_state[0] is not None or new_state != before[old]:
                    raise MoveError(tr('move.rollback.paths') % old)
                new.rename(old)
            restore(restore_move)
        if installing:
            def restore_index():
                nonlocal own_lock
                current = _state(plan.index)[0]
                if current == plan.index_before:
                    return
                if current != index_after:
                    raise MoveError(tr('move.rollback.index'))
                with lock.open('xb') as stream:
                    own_lock = True
                    if _state(plan.index)[0] != index_after:
                        raise MoveError(tr('move.rollback.index'))
                    stream.write(plan.index_before)
                lock.chmod(index_mode)
                os.replace(lock, plan.index)
                own_lock = False
            restore(restore_index)
        for directory in reversed(created):
            if directory.exists():
                restore(directory.rmdir)
        cleanup = [lock] if own_lock else []
        if temporary is not None:
            cleanup += [temporary, Path(str(temporary) + '.lock')]
        for path in cleanup:
            restore(lambda path=path: path.unlink(missing_ok=True))
        detail = tr('move.rollback.incomplete') + '; '.join(failures) if failures else tr('move.rollback.complete')
        message = tr('move.interrupted') if isinstance(error, KeyboardInterrupt) else str(error)
        raise MoveError(tr('move.failed') % (message, detail)) from error
