"""История областей кода и описания для проверки устаревания."""

from concurrent.futures import ThreadPoolExecutor
import os
import re
import shutil
import subprocess
import sys
import time

from lipi.i18n import tr
from .marks import standalone_trace


class BlameIncompleteError(RuntimeError):
    """Область не проверена: ограниченный прогрев не дал точной даты или верхней границы."""


# @trace docs/ru/codes.md#a4
class GitBlame:
    """Точные даты с -C; дешёвый blame служит только фильтром перед сравнением."""

    def __init__(self, root, *, uncommitted_time=None):
        self.root = root
        # Все незакоммиченные строки одного запуска одновременны, даже если
        # отдельные blame и точный/дешёвый проходы разделены секундами.
        self._uncommitted_time = time.time() if uncommitted_time is None else uncommitted_time
        self._git = shutil.which("git") or "git"
        if sys.platform == "darwin" and self._git == "/usr/bin/git":
            # /usr/bin/git — Apple launcher: он заново ищет toolchain на каждый
            # файл. xcrun выбирает тот же Git с учётом DEVELOPER_DIR/xcode-select.
            try:
                selected = subprocess.run(
                    ["/usr/bin/xcrun", "--find", "git"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, check=True
                ).stdout.decode("utf-8").strip()
                if selected.startswith("/") and shutil.which(selected):
                    self._git = selected
            except (OSError, subprocess.CalledProcessError, UnicodeError):
                pass
        self.cache = {}
        self.cheap_cache = {}
        self.uncommitted = set()
        self._unchanged_since = {}
        self._history_checked = False
        self._file_times = {}
        self._inventory_checked = False
        self._clean_paths = set()
        self._prefix = ""
        self._unsafe_until = None
        self._limited = False
        self._limited_precise = set()
        self._limited_cheap = set()

    def _lines(self, relpath, *, copies):
        cache = self.cache if copies else self.cheap_cache
        if relpath not in cache:
            try:
                out = subprocess.run(
                    [self._git, "-C", str(self.root), "blame", "-w", "-M",
                     *(["-C"] if copies else []), "--line-porcelain", "--", relpath],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
                ).stdout.decode("utf-8", "replace")
                rows, timestamp, uncommitted = [], None, False
                for line in out.split("\n"):
                    if line.startswith("committer-time "):
                        timestamp = int(line[15:])
                    elif line.startswith("\t"):
                        rows.append((self._uncommitted_time if uncommitted else timestamp, line[1:]))
                    elif match := re.fullmatch(r"([0-9a-f]{40}|[0-9a-f]{64}) \d+ \d+(?: \d+)?", line):
                        uncommitted = not match[1].strip("0")
                        timestamp = None
                        if uncommitted:
                            self.uncommitted.add(relpath)
                cache[relpath] = rows
            except (OSError, subprocess.CalledProcessError, ValueError):
                cache[relpath] = None
        return cache[relpath]

    def lines(self, relpath):
        """Полная точная история файла, включая переносы между файлами."""
        return self._lines(relpath, copies=True)

    def cheap_lines(self, relpath):
        """История без -C: её даты нельзя выдавать как точные даты изменения."""
        return self._lines(relpath, copies=False)

    @staticmethod
    def _region_time(rows, start, starts, *, code):
        if not rows:
            return None
        end = min((line - 1 for line in starts if line > start), default=len(rows))
        begin = start - 1
        if code and begin < len(rows):
            # Исключаем только отдельный комментарий с меткой. Код рядом
            # с inline-меткой остаётся частью области и должен давать A4.
            if standalone_trace(rows[begin][1]):
                begin += 1
        return max([timestamp for timestamp, _ in rows[begin:end]
                    if timestamp is not None] or [0]) or None

    def region_time(self, relpath, start, starts, *, code=False):
        """Точная дата до следующей границы или EOF, без порогового фильтра."""
        return self._region_time(self.lines(relpath), start, starts, code=code)

    def lines_time(self, relpath, line_numbers):
        """Точная дата выбранных строк (с 1), включая разрывные области."""
        rows = self.lines(relpath)
        if not rows:
            return None
        return max((rows[line - 1][0] for line in line_numbers
                    if 1 <= line <= len(rows) and rows[line - 1][0] is not None),
                   default=0) or None

    def _read_history(self):
        """Один log: граф дат и последние изменения всех файлов с NUL-именами."""
        if self._history_checked:
            return
        self._history_checked = True
        try:
            out = subprocess.run(
                [self._git, "-C", str(self.root), "log", "--raw", "-z", "--root",
                 "--format=%x00%H%x00%ct%x00%P", "--no-renames", "--no-color",
                 "--no-show-signature", "--no-notes", "HEAD", "--"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
            ).stdout
            if not out.endswith(b"\0"):
                return
            fields = out.split(b"\0")
            commits, file_times = {}, {}
            pos, timestamp = 0, None
            while pos < len(fields) - 1:
                if fields[pos] == b"":
                    oid = fields[pos + 1].decode("ascii")
                    timestamp = int(fields[pos + 2])
                    parents = fields[pos + 3].decode("ascii").split()
                    commits[oid] = (timestamp, parents)
                    pos += 4
                else:
                    # Единственный LF добавлен Git перед raw diff, а не перед
                    # именем. Следующий NUL-token — путь целиком, даже «123»
                    # или имя с ведущим LF; его содержимое не разбирается.
                    record = fields[pos]
                    if record.startswith(b"\n"):
                        record = record[1:]
                    parts = record.split()
                    if (timestamp is None or len(parts) != 5 or not parts[0].startswith(b":")
                            or parts[0].startswith(b"::") or parts[4] not in (b"A", b"D", b"M", b"T")):
                        return
                    path = os.fsdecode(fields[pos + 1])
                    if not path:
                        return
                    file_times[path] = max(timestamp, file_times.get(path, timestamp))
                    pos += 2
            if not commits or not all(parent in commits for _, parents in commits.values()
                                      for parent in parents):
                return
            latest = max(value for value, _ in commits.values())
            reverse = any(commits[parent][0] > value
                          for value, parents in commits.values() for parent in parents)
            self._unsafe_until = (latest if reverse or latest > time.time() else
                                  max((value for value, parents in commits.values()
                                       if len(parents) > 1), default=0))
            self._file_times = file_times
        except (OSError, subprocess.CalledProcessError, ValueError, UnicodeError, IndexError):
            pass

    def _safe_filter(self, since):
        """Безопасная верхняя граница после merge, обратных и будущих дат.

        На линейной истории с возрастающими датами -C уводит только назад.
        После merge разные родители безопасны лишь для более нового описания;
        обратные даты требуют границы не раньше максимальной даты истории.
        Неизвестный родитель или ошибка чтения отключает фильтр.
        """
        self._read_history()
        return self._unsafe_until is not None and since >= self._unsafe_until

    def _needs_precise(self, relpath, start, starts, since, *, code):
        if relpath in self.cache:
            return False
        bound = self._unchanged_since.get(relpath)
        if bound is not None and since >= bound:
            return False
        rows = self.cheap_cache.get(relpath)
        timestamp = self._region_time(rows, start, starts, code=code)
        return (rows is None or relpath in self.uncommitted or
                (timestamp is not None and timestamp > since) or
                self._unsafe_until is None or since < self._unsafe_until)

    def region_checked(self, relpath, start, starts, *, since, code=True):
        """Чистое чтение: точный blame получен либо уже доказано отсутствие A4."""
        if relpath in self.cache:
            return self.cache[relpath] is not None
        bound = self._unchanged_since.get(relpath)
        if bound is not None and since >= bound:
            return True
        rows = self.cheap_cache.get(relpath)
        if (rows is None or relpath in self.uncommitted or not self._history_checked
                or self._unsafe_until is None or since < self._unsafe_until):
            return False
        timestamp = self._region_time(rows, start, starts, code=code)
        return timestamp is None or timestamp <= since

    def stale_region_time(self, relpath, start, starts, *, since, code=True):
        """Точная дата новее since либо None; непроверенная область вызывает ошибку."""
        if self._limited and not self.region_checked(relpath, start, starts, since=since, code=code):
            raise BlameIncompleteError(tr("checker.history.unchecked_region") % (relpath, start))
        if not self._limited and relpath not in self.cache and not self.region_checked(
                relpath, start, starts, since=since, code=code):
            self.cheap_lines(relpath)
            self._safe_filter(since)
        if self._needs_precise(relpath, start, starts, since, code=code):
            self.lines(relpath)
        if relpath not in self.cache:
            return None
        timestamp = self.region_time(relpath, start, starts, code=code)
        return timestamp if timestamp is not None and timestamp > since else None

    def _unchanged_files(self, paths):
        """Верхняя граница каждого чистого файла для любого порога его раздела.

        Последняя дата файла, с поправкой на опасные даты графа, сравнивается
        с since каждой области. Эти доказанные отрицательные результаты не
        расходуют лимиты blame. Индекс и рабочее дерево читаются один раз.
        """
        self._read_history()
        if self._unsafe_until is None:
            return
        if not self._inventory_checked:
            self._inventory_checked = True
            try:
                prefix = subprocess.run(
                    [self._git, "-C", str(self.root), "rev-parse", "--show-prefix"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
                ).stdout
                if not prefix.endswith(b"\n"):
                    return
                prefix = os.fsdecode(prefix[:-1])
                status = subprocess.run(
                    [self._git, "--no-optional-locks", "-C", str(self.root), "status", "--porcelain=v1", "-z",
                     "--untracked-files=all", "--no-renames", "--"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
                ).stdout
                tracked = subprocess.run(
                    [self._git, "-C", str(self.root), "ls-files", "-v", "-z", "--full-name", "--"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
                ).stdout
                if any(output and not output.endswith(b"\0") for output in (status, tracked)):
                    return
                clean, changed = set(), set()
                for entry in tracked.split(b"\0"):
                    if not entry:
                        continue
                    if len(entry) < 3 or entry[1:2] != b" ":
                        return
                    # assume-unchanged/skip-worktree скрывают правки от status,
                    # но blame их видит: безопасен только обычный флаг H.
                    if entry[:1] == b"H":
                        clean.add(os.fsdecode(entry[2:]))
                for entry in status.split(b"\0"):
                    if not entry:
                        continue
                    if len(entry) < 4 or entry[2:3] != b" " or any(
                            value not in b" MADRCUT?!" for value in entry[:2]):
                        return
                    changed.add(os.fsdecode(entry[3:]))
                self._prefix = prefix
                self._clean_paths = clean - changed
            except (OSError, subprocess.CalledProcessError):
                return
        for path in paths:
            full_path = self._prefix + path
            if full_path in self._clean_paths and full_path in self._file_times:
                self._unchanged_since[path] = max(self._file_times[full_path], self._unsafe_until)

    def preload_staleness(self, requests, workers=8, *, max_cheap_files=None, max_precise_files=None):
        """Прогреть (path, start, starts, since); пределы — число файлов за запуск.

        Подозрительные файлы выбираются по первому появлению в requests. При
        ограничении оставшиеся области нужно проверять через region_checked;
        stale_region_time не запускает для них дополнительный точный blame.
        По умолчанию прогрев полный, как требуется аудиту.
        """
        if any(limit is not None and limit < 0 for limit in (max_cheap_files, max_precise_files)):
            raise ValueError(tr("checker.history.negative_blame_limit"))
        self._limited = max_cheap_files is not None or max_precise_files is not None
        requests = list(requests)
        paths = list(dict.fromkeys(path for path, _, _, _ in requests if path not in self.cache))
        if not paths:
            return

        def warm(reader, selected):
            if len(selected) == 1:
                reader(selected[0])
            elif selected:
                with ThreadPoolExecutor(max_workers=min(workers, len(selected))) as pool:
                    for _ in pool.map(reader, selected):
                        pass

        self._unchanged_files(paths)
        candidates = {path for path, _, _, since in requests if path not in self.cache
                      and (path not in self._unchanged_since or since < self._unchanged_since[path])}
        paths = [path for path in paths if path in candidates]
        unread = [path for path in paths if path not in self.cheap_cache]
        if max_cheap_files is not None:
            remaining = max(0, max_cheap_files - len(self._limited_cheap))
            unread = unread[:remaining]
            self._limited_cheap.update(unread)
        warm(self.cheap_lines, unread)
        suspect_paths = {path for path, start, starts, since in requests
                         if path in self.cheap_cache and
                         self._needs_precise(path, start, starts, since, code=True)}
        suspects = [path for path in paths if path in suspect_paths]
        if max_precise_files is not None:
            remaining = max(0, max_precise_files - len(self._limited_precise))
            suspects = suspects[:remaining]
            self._limited_precise.update(suspects)
        # -L меняет score -M/-C: даже соседняя строка за границей области
        # может решить, распознает ли Git перенос. Для подозрительных файлов
        # сохраняем полный контекст, объединяя все области одним точным blame.
        warm(self.lines, suspects)
