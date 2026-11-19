#!/usr/bin/env python3
"""doctor.py — диагностика развёртывания lipi в проекте.

    python3 src/lipi/doctor.py [каталог]

Из установленного пакета — команда lipi doctor.

Проверяет и печатает по строке на пункт:

    Python         версия интерпретатора (нужен 3.9+);
    lipi           версия установленного lipi;
    lipi.json      есть ли настройки (нет — проект lipi не найден);
    lock-файл      .agents/lipi/lipi.lock: версия проекта и совместимость
                   с установленным lipi по первой цифре (ADR-010);
    pre-commit     .git/hooks/pre-commit — по ключу enforce (ADR-011);
    раскладка      годовые каталоги и соответствие дате создания;
    шапки          обязательные поля и даты рабочих документов;
    указатель      актуален ли указатель рабочих материалов (запускается
                   чекер lipi);
    базовая линия  .agents/lipi/baseline.json: сколько записей и ошибок.

Проблемы — несовместимые версии, отсутствие файлов, устаревший указатель.
Каждая строка кончается на «— ок» или «— [проблема] <что сделать>».
Код возврата: 0 — проблем нет, 1 — есть хоть одна. В каталоге без lipi.json
печатается, что запустить (lipi init). Команда только читает: ничего не
создаёт, не правит и не пишет, поэтому её можно запускать в проекте в любом
состоянии.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# На Windows stdout по умолчанию в кодировке консоли (cp1252), и русские
# сообщения роняли бы печать. Скрипты lipi всегда печатают в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

HERE = Path(__file__).resolve().parent
CHECK = HERE / "check.py"
CONFIG_NAME = "lipi.json"
LOCK_REL = ".agents/lipi/lipi.lock"
BASE_REL = ".agents/lipi/baseline.json"
HOOK_REL = ".git/hooks/pre-commit"
RE_HOOK_MARK = re.compile(r"(?m)^# lipi[ \t]*\r?$")

sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
from lipi import __version__ as VERSION  # noqa: E402
from lipi.checker.state import version_mismatch  # noqa: E402
from lipi.i18n import tr  # noqa: E402


def show(path, root):
    """Путь для человека: относительно корня проекта, с «/» на всех ОС."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


class Report:
    """Строки отчёта и счёт проблем."""

    def __init__(self):
        self.problems = 0

    def item(self, name, value, hint=None):
        """Строка «пункт: значение — ок» или «— [проблема] <что сделать>»."""
        line = "%s: %s" % (name, value)
        if hint is None:
            print(tr('doctor.ok_line') % line)
            return
        self.problems += 1
        print("%s — %s %s" % (line, tr('doctor.problem'), hint))


def check_lock(root, rep):
    path = root / LOCK_REL
    if not path.is_file():
        rep.item(tr('doctor.lock_file'), tr('doctor.absent'), tr('doctor.lock_create') % LOCK_REL)
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        rep.item(tr('doctor.lock_file'), tr('doctor.invalid_json'),
                 tr('doctor.lock_restore'))
        return
    version = data.get("lipi") if isinstance(data, dict) else None
    if not isinstance(version, str):
        rep.item(tr('doctor.lock_file'), tr('doctor.lock_no_version'),
                 tr('doctor.lock_restore'))
        return
    mismatch = version_mismatch(VERSION, version)
    if mismatch is None:
        rep.item(tr('doctor.lock_file'), tr('doctor.lock_version') % (version, VERSION))
        return
    level, message = mismatch
    rep.item(tr('doctor.lock_file'), tr('doctor.lock_version') % (version, VERSION), message)


def read_enforce(root):
    """Ключ enforce из lipi.json (ADR-011): по умолчанию false."""
    try:
        data = json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    return data.get("enforce") is True if isinstance(data, dict) else False


def check_hook(root, rep, enforce):
    hook = root / HOOK_REL
    if not hook.is_file():
        if enforce:
            rep.item("pre-commit", tr('doctor.absent'),
                     tr('doctor.hook_install'))
        else:
            rep.item("pre-commit", tr('doctor.hook_absent'))
        return
    try:
        text = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        rep.item("pre-commit", tr('doctor.hook_unreadable'), tr('doctor.hook_fix') % HOOK_REL)
        return
    if RE_HOOK_MARK.search(text):
        if enforce:
            rep.item("pre-commit", tr('doctor.hook_managed'))
        else:
            rep.item("pre-commit", tr('doctor.hook_managed'),
                     tr('doctor.hook_remove'))
        return
    if enforce:
        rep.item("pre-commit", tr('doctor.hook_foreign'),
                 tr('doctor.hook_foreign_replace'))
    else:
        rep.item("pre-commit", tr('doctor.hook_foreign_kept'))


def check_index(root, rep):
    """Указатель: чекер текущей версии из lipi ищем W7 в его выводе."""
    # CI=1: чекер не пересобирает указатель сам (doctor только читает), и W7
    # остаётся видимой для диагностики
    proc = subprocess.run(
        [sys.executable, "-B", str(CHECK), "--root", str(root), "--no-baseline"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=dict(os.environ, CI="1"))
    out = proc.stdout.decode("utf-8", "replace")
    layout = [line.strip() for line in out.splitlines()
              if re.search(r"\bW(?:10|11)\]", line)]
    headers = [line.strip() for line in out.splitlines()
               if re.search(r"\bW(?:3|4)\]", line)]
    for label, findings in ((tr('doctor.layout'), layout), (tr('doctor.headers'), headers)):
        if findings:
            for finding in findings:
                rep.item(label, finding, tr('doctor.fix_document'))
        else:
            rep.item(label, tr('doctor.no_findings'))
    if "W7]" in out:
        rep.item(tr('doctor.index'), tr('doctor.index_stale'), tr('doctor.index_refresh'))
    elif proc.returncode == 2:
        rep.item(tr('doctor.index'), tr('doctor.index_check_failed'), tr('doctor.index_run_check'))
    else:
        rep.item(tr('doctor.index'), tr('doctor.index_current'))


def check_baseline(root, rep):
    path = root / BASE_REL
    if not path.is_file():
        rep.item(tr('doctor.baseline'), tr('doctor.absent'))
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        rep.item(tr('doctor.baseline'), tr('doctor.invalid_json'), tr('doctor.baseline_rebuild'))
        return
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        rep.item(tr('doctor.baseline'), tr('doctor.baseline_no_entries'), tr('doctor.baseline_rebuild'))
        return
    total = 0
    for entry in entries:
        if isinstance(entry, dict):
            count = entry.get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                total += count
    rep.item(tr('doctor.baseline'), tr('doctor.baseline_totals') % (len(entries), total))


def main():
    argv = sys.argv[1:]
    root = Path(argv[0] if argv else ".").resolve()
    rep = Report()

    version = sys.version.split()[0]
    if sys.version_info < (3, 9):
        rep.item("Python", version, tr('doctor.python_required'))
    else:
        rep.item("Python", version)
    rep.item("lipi", VERSION)

    if not (root / CONFIG_NAME).is_file():
        rep.item(tr('doctor.project'), tr('doctor.project_missing') % CONFIG_NAME,
                 tr('doctor.project_init'))
    else:
        rep.item(CONFIG_NAME, tr('doctor.present'))
        check_lock(root, rep)
        check_hook(root, rep, read_enforce(root))
        check_index(root, rep)
        check_baseline(root, rep)

    if rep.problems:
        print(tr('doctor.problems_summary') % rep.problems)
        return 1
    print(tr('doctor.no_problems_summary'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
