#!/usr/bin/env python3
"""migrate.py — перенос рабочих материалов существующего проекта на правила lipi.

    python3 src/lipi/migrate.py [каталог]           # показать план, ничего не менять
    python3 src/lipi/migrate.py [каталог] --apply   # выполнить перенос

Из установленного пакета — команды lipi migrate и lipi migrate --apply.

Существующий проект держит планы, замечания и аудиты по каталогам статусов
(current/, completed/, backlog/) или просто папками. lipi требует каталог по
типу документа и году создания (plan/ГГГГ/, issue/ГГГГ/,
discussion/ГГГГ/, audit/ГГГГ/), ADR остаются в adr/. Нужна шапка со
статусом. Команда переносит такие документы:

- тип — из имени (pln-001-…, iss-002-…), иначе по каталогу (current,
  completed, backlog, plan*, audit, discussion, adr, issue); остальное —
  в history/, включая прежний журнал, мастер-план и отчёты;
- номер сохраняется, если он есть; «ветки» вида 011-1 и документы без номера
  получают следующий свободный номер своего типа (конфликт — тоже следующий);
- статус — из каталога (completed → «completed», backlog → «deferred») или из
  шапки по словам; не распознан — «new» (у замечания «open») с пометкой
  в отчёте;
- даты — из шапки (Created и Updated или «Дата создания» и «Дата обновления»
  в любом регистре; единственная «Дата:» годится для обеих), иначе первый и
  последний коммит файла;
- завершённый план без строки «Result» получает «- Result: не записан
  (перенесено ГГГГ-ММ-ДД)»; замечанию без распознанного вида ставится
  «question»;
- относительные ссылки во всех Markdown-файлах проекта переписываются на
  новые пути с учётом относительности;
- прежний журнал и мастер-план уходят в history/, создаётся пустой
  мастер-план по шаблону src/lipi/locale/ru/templates/seed/common/workflow/masterplan.md
  и, если его нет, workflow/README.md по заготовке; таблица «старый путь → новый
  путь → ID» пишется в history/MIGRATION.md.

Работает только в git: каталог рабочих материалов должен лежать в
git-репозитории с чистым рабочим деревом, перенос идёт командой git mv, чтобы
его можно было просмотреть и откатить. Вне git — отказ с объяснением.

Каталог по умолчанию берётся из lipi.json (ключ workflow). Если каталог
передан явно и отличается, после переноса lipi.json обновляется ключом
workflow, иначе чекер его не увидит.

Файл migrate.json в каталоге рабочих материалов переопределяет тип, статус и
номер отдельных документов:

    {"files": {"current/roadmap.md": {"type": "pln", "status": "in progress",
                                      "number": 7}}}

В ключе «files» — пути относительно каталога материалов; типы — pln, aud,
dsc, adr, iss; статус — из списка своего типа; номер — целое больше нуля. Неизвестный ключ, тип или статус —
отказ с кодом 2.

После переноса пересобирается указатель: запускается check.py из репозитория
lipi (не копия проекта — она может быть старой) с --root проекта и
--write-index.
"""
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote

# На Windows stdout по умолчанию в кодировке консоли (cp1252), и русские
# сообщения роняли бы печать. Скрипты lipi всегда печатают в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SRC))

from lipi.checker.conventions import (
    CONFIG_NAME, HISTORY_DIR, INDEX, ISSUE_KINDS, K_CLOSED, K_CREATED, K_KIND,
    K_RESULT, K_SOURCE, K_STATUS, K_UPDATED, LIPI_DIR, MASTERPLAN, NEED_RESULT,
    RE_DOC_NAME, SOURCE_EXTERNAL, STATUSES, TYPES,
)
from lipi.checker.model import Page, Project, has_symlink, mask_code
from lipi.i18n import ArgumentParser, template_path, tr
from lipi.legacy_format import (
    LEGACY_FIELDS, LEGACY_KINDS, LEGACY_SECTIONS, LEGACY_SOURCE_EXTERNAL,
    LEGACY_STATUSES, historical_status,
)


README_NAME = "README.md"
MIGRATE_CONFIG = "migrate.json"
MIGRATION = "MIGRATION.md"
CHECK_REL = ".agents/lipi/check.py"
DEFAULT_WORKFLOW = "workflow"
DEFAULT_DOCS = "docs"
# Начальное состояние каждого типа; у аудита статуса нет.
NEW_STATUS = {prefix: statuses[0] for prefix, statuses in STATUSES.items()}
# Канонический статус по общему слову, подходящий типу документа.
STATUS_BY_WORD = {
    "completed": {"pln": "completed", "iss": "closed", "adr": "accepted",
                  "dsc": "closed"},
    "deferred": {"pln": "deferred", "iss": "open", "adr": "proposed",
                 "dsc": "open"},
    "in progress": {"pln": "in progress", "iss": "in progress", "adr": "proposed",
                    "dsc": "open"},
    "new": NEW_STATUS,
}
STATUS_WORDS = [
    ("in progress", {"progress", "inprogress", "wip", "doing", "active",
                     "работе", "работа"}),
    ("completed", {"completed", "complete", "done", "finished", "closed",
                  "готово", "готов", "закрыт", "закрыто", "закрыта",
                  "закрытые", "завершен", "завершено", "завершена",
                  "завершение", "выполнено"}),
    ("completed", {"accepted", "accept", "approved", "принят", "принято",
                  "принята", "приняты", "утверждено"}),
    ("deferred", {"backlog", "deferred", "postponed", "later", "отложен", "отложено",
                 "отложена", "отложили"}),
    ("new", {"new", "todo", "новый", "новая", "новое", "новые"}),
]
TYPE_DIRS = {"plan": "pln", "audit": "aud", "discussion": "dsc",
             "adr": "adr", "issue": "iss", "issues": "iss"}
STATUS_DIRS = {"current": None, "completed": "completed", "backlog": "deferred"}
PASSTHROUGH_FIELDS = LEGACY_FIELDS | {name.casefold(): name for name in LEGACY_FIELDS.values()}
RE_PREFIXED = re.compile(
    r"^(%s)[-_](\d{1,4})((?:[-_.]\d+)*)(?:[-_. ]+(.+))?$" % "|".join(TYPES),
    re.I)
RE_NUMERIC = re.compile(r"^(\d{1,4})((?:[-_.]\d+)*)(?:[-_. ]+(.+))?$")
RE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
RE_HEADER_ENTRY = re.compile(r"^[-*+]\s+([^:]+):(.*)$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_LINK = re.compile(r"(\[[^\]]*\]\(\s*)(<?)([^)\s>]*)(>?)((?:\s+\"[^\"]*\")?\s*\))")
RE_H1 = re.compile(r"^#\s+\S")

TRANSLIT = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m",
                     "n", "o", "p", "r", "s", "t", "u", "f", "h", "c", "ch", "sh",
                     "sch", "", "y", "", "e", "yu", "ya"]))
TRANSLIT["ё"] = "e"


class MigrateError(Exception):
    """Отказ с объяснением: печатается в stderr, код возврата 2."""


# --- Мелкие утилиты ----------------------------------------------------------

def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def slugify(title):
    """Имя документа латиницей: до шести слов через дефис (как в check.py)."""
    s = "".join(TRANSLIT.get(ch, ch) for ch in title.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return "-".join(s.split("-")[:6])


def is_within(path, base):
    return base is not None and (path == base or base in path.parents)


def display(root, path):
    """Путь для печати: относительный от корня проекта, если это возможно."""
    try:
        return relative(path, root)
    except ValueError:
        return str(path)


def relative(path, base):
    return os.path.relpath(str(path), str(base)).replace(os.sep, "/")


def git(top, *args):
    """git с аргументами; (код возврата, stdout+stderr строкой)."""
    proc = subprocess.run(["git", "-C", str(top)] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    return proc.returncode, out


# --- git: репозиторий, чистота, даты -----------------------------------------

def repo_top(path):
    """Вершина git-репозитория, в котором лежит path; None вне git."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.decode("utf-8", "replace").strip()
    return Path(out).resolve() if out else None


def dirty_lines(top):
    """Строки git status --porcelain; None, если команда не выполнилась."""
    code, out = git(top, "status", "--porcelain")
    if code != 0:
        return None
    return [line for line in out.split("\n") if line.strip()]


def tracked_paths(top):
    """Файлы под версионным контролем (абсолютные); None, если git не ответил."""
    proc = subprocess.run(
        ["git", "-C", str(top), "ls-files", "-z", "--cached"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        return None
    return {top / name for name in os.fsdecode(proc.stdout).split("\0")
            if name}


def untracked_moves(plan, top):
    """Файлы переноса, которых нет в git: их нельзя перенести git mv."""
    tracked = tracked_paths(top)
    if tracked is None:
        raise MigrateError(tr('migrate.git_tracked_files'))
    folders = [(move["old"], move["new"]) for move in plan["moves"] if move["kind"] == "folder"]
    missing = set()
    for move in plan["moves"]:
        if move["kind"] == "file":
            path = move["old"]
            original = next((old / path.relative_to(new) for old, new in folders
                             if is_within(path, new)), path)
            if original not in tracked:
                missing.add(original)
    if folders:
        # git mv каталога унесёт и игнорируемое. Для отказа нужны только имена.
        proc = subprocess.run(
            ["git", "-C", str(top), "--literal-pathspecs", "ls-files", "--others", "-z", "--",
             *(relative(old, top) for old, _ in folders)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise MigrateError(tr('migrate.git_tracked_directory'))
        missing.update(top / name for name in os.fsdecode(proc.stdout).split("\0") if name)
    return sorted(missing)


def commit_dates(top, path):
    """(первый, последний) коммит файла по дате коммита; (None, None) без git."""
    code, out = git(top, "log", "--follow", "--format=%cI", "--",
                    relative(path, top))
    if code != 0:
        return None, None
    dates = []
    for line in out.split("\n"):
        value = line.strip()[:10]
        if RE_DATE.match(value):
            try:
                datetime.date.fromisoformat(value)
            except ValueError:
                continue
            dates.append(value)
    if not dates:
        return None, None
    return dates[-1], dates[0]


# --- Имя, тип, каталог, статус ----------------------------------------------

def parse_name(stem):
    """(префикс, номер, имя) из имени файла или папки.

    Номер сохраняется, если он есть. «Ветка» вида 011-1 номер не сохраняет:
    такое имя получает следующий свободный номер. Префикс понимается и без
    дефиса (ADR_007_…), и в любом регистре.
    """
    stem = stem.strip()
    m = RE_DOC_NAME.match(stem)
    if m:
        return m.group(1), int(m.group(2)), m.group(3)
    m = RE_PREFIXED.match(stem)
    if m:
        prefix = m.group(1).lower()
        branch = bool(m.group(3))
        number = None if branch else int(m.group(2))
        slug = slugify(m.group(4)) if m.group(4) else None
        return prefix, number, slug
    m = RE_NUMERIC.match(stem)
    if m:
        branch = bool(m.group(2))
        number = None if branch else int(m.group(1))
        slug = slugify(m.group(3)) if m.group(3) else None
        return None, number, slug
    return None, None, None


def parts_info(parts):
    """(тип, статус каталога) по компонентам пути: current/completed/backlog/plan*…"""
    prefix, status = None, None
    for part in parts:
        low = part.lower()
        if low in STATUS_DIRS:
            if status is None:
                status = STATUS_DIRS[low]
            if prefix is None:
                prefix = "pln"
            continue
        if prefix is None:
            if low in TYPE_DIRS:
                prefix = TYPE_DIRS[low]
            elif low == "plan" or low.startswith("plan"):
                prefix = "pln"
    return prefix, status


def normalize_status(value):
    """Текст статуса для сравнения: без разметки, регистра и ё."""
    s = value.strip().lower().replace("ё", "е")
    s = re.sub(r"[`*_\"'«»]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,:;!—-–")


def generic_status(raw):
    """Общее слово статуса: «завершён», «принят», «отложен», «в работе», «новый»."""
    s = normalize_status(raw)
    if not s:
        return None
    if "in progress" in s or "in-progress" in s:
        return "in progress"
    words = set(re.findall(r"[a-zа-я0-9]+", s))
    for name, known in STATUS_WORDS:
        if words & known:
            return name
    return None


def resolve_status(raw, prefix):
    """(канонический статус типа, распознан?) по значению из шапки."""
    if prefix not in STATUSES:
        return None, True
    norm = normalize_status(raw)
    canonical = LEGACY_STATUSES.get(norm, norm)
    if canonical in STATUSES[prefix]:
        return canonical, True
    word = generic_status(raw)
    if word is None:
        return NEW_STATUS[prefix], False
    return STATUS_BY_WORD[word][prefix], True


def parse_date(value):
    """Дата ГГГГ-ММ-ДД из строки шапки; None, если не разобрать."""
    for pattern, order in ((r"(\d{4})-(\d{2})-(\d{2})", "ymd"),
                           (r"(\d{1,2})[./](\d{1,2})[./](\d{4})", "dmy")):
        m = re.search(pattern, value)
        if not m:
            continue
        try:
            if order == "ymd":
                return datetime.date(int(m.group(1)), int(m.group(2)),
                                     int(m.group(3))).isoformat()
            return datetime.date(int(m.group(3)), int(m.group(2)),
                                 int(m.group(1))).isoformat()
        except ValueError:
            continue
    return None


# --- Шапка документа ---------------------------------------------------------

def parse_header(text):
    """Заголовок первого уровня и шапка: строки «- Ключ: значение» сразу после него."""
    lines = text.split("\n")
    h1 = None
    for i, line in enumerate(lines):
        if RE_H1.match(line):
            h1 = i
            break
    result = {"h1": h1, "entries": [], "body": 0, "lines": lines}
    if h1 is None:
        return result
    i = h1 + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    entries = []
    while i < len(lines):
        m = RE_HEADER_ENTRY.match(lines[i])
        if m:
            entries.append({"key": m.group(1).strip(),
                            "value": m.group(2).strip()})
            i += 1
        elif lines[i].startswith((" ", "\t")) and entries and lines[i].strip():
            entries[-1]["value"] = (entries[-1]["value"] + " "
                                    + lines[i].strip()).strip()
            i += 1
        else:
            break
    result["entries"] = entries
    result["body"] = i
    return result


def header_kind(key, prefix):
    """Что это за строка шапки; None — незнакомая (сохраняется как есть)."""
    k = re.sub(r"\s+", " ", key.strip().lower().replace("ё", "е"))
    if "создан" in k or "created" in k:
        return "created"
    if "закрыт" in k or "closed" in k:
        return "closed"
    if "обновл" in k or "updated" in k or "modified" in k:
        return "updated"
    if k in ("дата", "date"):
        return "date"
    if "статус" in k or "status" in k:
        return "status" if prefix in STATUSES else None
    if "итог" in k or "result" in k or "outcome" in k:
        return "result"
    if prefix == "iss" and ("вид" in k or "kind" in k):
        return "kind"
    return None


def doc_title(header, fallback):
    """Заголовок первого уровня без разметки; fallback, если его нет."""
    if header["h1"] is None:
        return fallback
    title = re.sub(r"^#{1,6}\s+", "", header["lines"][header["h1"]]).strip()
    title = re.sub(r"\s*<a\s+id=[^>]*>\s*(</a>)?", "", title).strip()
    return title or fallback


def canonical_header_line(kind, meta):
    """Строка шапки по правилам для известного поля или None, если её нет."""
    if kind == "created":
        return "- %s: %s" % (K_CREATED, meta["created"])
    if kind == "updated":
        return "- %s: %s" % (K_UPDATED, meta["updated"])
    if kind == "closed" and meta.get("closed"):
        return "- %s: %s" % (K_CLOSED, meta["closed"])
    if kind == "status" and meta["status"]:
        return "- %s: %s" % (K_STATUS, meta["status"])
    if kind == "kind" and meta["prefix"] == "iss":
        return "- %s: %s" % (K_KIND, meta["kind"])
    if kind == "result" and meta.get("result") is not None:
        return "- %s: %s" % (K_RESULT, meta["result"])
    return None


def migrate_headings(body, prefix):
    """Заголовки формата вне блоков кода; явные якоря и текст сохраняются."""
    mapping = LEGACY_SECTIONS.get(prefix)
    if not mapping:
        return body
    for index, line in enumerate(mask_code("\n".join(body)).split("\n")):
        heading = re.match(r"^#{2,6}[ \t]+(.+?)(?=\s*(?:<a\s|#*\s*$))", line)
        if heading and heading[1] in mapping:
            start, end = heading.span(1)
            body[index] = body[index][:start] + mapping[heading[1]] + body[index][end:]
    return body


def rebuild_document(meta):
    """Текст документа с шапкой и обязательными заголовками по правилам lipi.

    Порядок знакомых строк шапки сохраняется, незнакомые переносятся как есть:
    уже правильный документ не переписывается зря.
    """
    header = meta["header"]
    lines = header["lines"]
    header_lines, emitted = [], set()

    def emit(kind):
        if kind in emitted:
            return
        if kind == "date":
            emitted.add("created")
            emitted.add("updated")
            header_lines.append(canonical_header_line("created", meta))
            header_lines.append(canonical_header_line("updated", meta))
            return
        line = canonical_header_line(kind, meta)
        if line is not None:
            emitted.add(kind)
            header_lines.append(line)

    for entry in header["entries"]:
        kind = header_kind(entry["key"], meta["prefix"])
        if kind is not None:
            emit(kind)
            continue
        key = PASSTHROUGH_FIELDS.get(entry["key"].casefold(), entry["key"])
        value = entry["value"]
        if key == K_SOURCE:
            source_type, separator, source_id = value.partition(" ")
            if source_type.casefold() in (LEGACY_SOURCE_EXTERNAL, SOURCE_EXTERNAL):
                value = SOURCE_EXTERNAL + separator + source_id
        header_lines.append("- %s: %s" % (key, value))
    for kind in ("created", "updated", "status", "kind", "result", "closed"):
        emit(kind)
    if header["h1"] is None:
        head = ["# %s" % meta["title"]]
        body = list(lines)
    else:
        head = lines[:header["h1"] + 1]
        body = lines[header["body"]:]
    while body and not body[0].strip():
        body.pop(0)
    out = head + [""] + header_lines
    if body:
        out += [""] + migrate_headings(body, meta["prefix"])
    return "\n".join(out).rstrip("\n") + "\n"


# --- Ссылки ------------------------------------------------------------------

def rewrite_links(text, old_file, new_file, resolve, select):
    """Переписывает относительные ссылки файла по таблице переносов.

    Путь назначения берётся относительно старого расположения файла, новый —
    относительно нового: так ссылка остаётся верной и когда файл переехал, и
    когда переехала её цель. Внешние, абсолютные, ссылки на якоря и на файлы
    вне таблицы не трогаются. Возвращает (текст, сколько ссылок изменено).
    """
    changed = [0]

    def replace(match):
        dest = match.group(3)
        if not dest or dest.startswith("#") or dest.startswith("/"):
            return match.group(0)
        if RE_SCHEME.match(dest):
            return match.group(0)
        path_part, sep, anchor = dest.partition("#")
        if not path_part:
            return match.group(0)
        old_target = select(old_file.parent / unquote(path_part))
        if old_target is None or not old_target.exists():
            return match.group(0)
        new_target = resolve(old_target)
        if new_target == old_target and new_file == old_file:
            return match.group(0)
        rel = relative(new_target, new_file.parent)
        if dest.endswith("/") and not rel.endswith("/"):
            rel += "/"
        if " " in rel:
            rel = quote(rel, safe="/")
        new_dest = rel + (("#" + anchor) if sep else "")
        if new_dest == dest:
            return match.group(0)
        changed[0] += 1
        return match.group(1) + match.group(2) + new_dest + match.group(4) + match.group(5)

    return RE_LINK.sub(replace, text), changed[0]


def walk_markdown(project, workflow_project):
    """Все Markdown-файлы проекта (и каталога материалов, если он снаружи)."""
    seen = set()
    scopes = ((project, ()),) if workflow_project is project else (
        (project, (workflow_project.root,)), (workflow_project, ()))
    for scope, skip in scopes:
        for candidate in scope.walk_md(scope.root, skip=skip, exclusions=scope.target_skip_dirs):
            path = scope.file_path(candidate)
            if path is not None and path not in seen:
                seen.add(path)
                yield path


# --- Настройки: migrate.json и lipi.json -------------------------------------

def load_overrides(wf, select):
    """Переопределения из wf/migrate.json: {абсолютный путь: dict}."""
    path = wf / MIGRATE_CONFIG
    if path.is_symlink():
        raise MigrateError(tr('migrate.override_symlink') % path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise MigrateError(tr('migrate.invalid_json') % (MIGRATE_CONFIG, e))
    if not isinstance(data, dict):
        raise MigrateError(tr('migrate.override_object') % MIGRATE_CONFIG)
    extra = [key for key in data if key != "files"]
    if extra:
        raise MigrateError(tr('migrate.override_key')
                          % (MIGRATE_CONFIG, extra[0]))
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise MigrateError(tr('migrate.override_files_object') % MIGRATE_CONFIG)
    result = {}
    for key, value in files.items():
        if not isinstance(value, dict):
            raise MigrateError(tr('migrate.override_entry_object') % (MIGRATE_CONFIG, key))
        extra = [field for field in value if field not in ("type", "status", "number")]
        if extra:
            raise MigrateError(tr('migrate.override_entry_key') % (MIGRATE_CONFIG, key, extra[0]))
        if "type" in value and value["type"] not in TYPES:
            raise MigrateError(tr('migrate.override_type')
                              % (MIGRATE_CONFIG, key, value["type"],
                                 ", ".join(TYPES)))
        if "number" in value and not (isinstance(value["number"], int)
                                      and not isinstance(value["number"], bool)
                                      and value["number"] > 0):
            raise MigrateError(tr('migrate.override_number')
                              % (MIGRATE_CONFIG, key))
        target = select(wf / key)
        if target is None or not is_within(target, wf) or not target.exists():
            raise MigrateError(tr('migrate.override_path_missing') % (MIGRATE_CONFIG, key))
        result[target] = value
    return result


def read_project_config(root):
    """(настройки проекта, был ли файл). Неверный lipi.json — отказ."""
    path = root / CONFIG_NAME
    if not path.is_file():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise MigrateError(tr('migrate.invalid_json') % (CONFIG_NAME, e))
    if not isinstance(data, dict):
        raise MigrateError(tr('migrate.config_object') % CONFIG_NAME)
    return data, True


def catalog_path(root, raw):
    path = Path(os.path.abspath(root / raw))
    if is_within(path, root) and has_symlink(path, root):
        raise MigrateError(tr('migrate.catalog_symlink') % path)
    return path.resolve()


def resolve_catalog(root, cfg, explicit):
    """Каталог рабочих материалов: аргумент или ключ workflow из lipi.json."""
    if explicit:
        raw = explicit
    else:
        raw = cfg.get("workflow", DEFAULT_WORKFLOW)
        if raw is None:
            raise MigrateError(tr('migrate.catalog_disabled') % CONFIG_NAME)
        if not isinstance(raw, str):
            raise MigrateError(tr('migrate.catalog_type')
                              % CONFIG_NAME)
    if not isinstance(raw, str) or not raw.strip():
        raise MigrateError(tr('migrate.catalog_unspecified'))
    wf = catalog_path(root, raw)
    if not wf.is_dir():
        raise MigrateError(tr('migrate.catalog_missing') % display(root, wf))
    if wf == root:
        raise MigrateError(tr('migrate.catalog_is_root') % wf)
    return wf


# --- Сканирование каталога материалов ---------------------------------------

def is_journal(name, at_root):
    """Прежний журнал (в корне материалов) или мастер-план: уходят в history/."""
    low = name.lower()
    if low.startswith("masterplan"):
        return True
    return at_root and (low.startswith("журнал") or low.startswith("journal")
                        or low.startswith("log") or low.startswith("history"))


def folder_main(folder, children):
    """Основной файл папки-документа: readme.md или файл <имя>-readme.md."""
    md = sorted(path for path in children if path.suffix.lower() == ".md" and path.is_file())
    for f in md:
        stem = f.stem.lower()
        if stem == "readme" or stem.endswith("-readme") or stem == folder.name.lower():
            return f
    return md[0] if len(md) == 1 else None


def scan_units(wf, overrides, project):
    """Документы и то, что уходит в history/: единицы переноса."""
    docs, history, used_overrides = [], [], set()
    children = {}
    for path in project.walk_files(wf, skip=(wf / HISTORY_DIR,), exclusions=project.target_skip_dirs):
        if path.is_symlink():
            continue
        for entry in (path, *path.parents):
            if entry == wf:
                break
            children.setdefault(entry.parent, set()).add(entry)

    def take_override(path):
        value = overrides.get(path)
        if value is not None:
            used_overrides.add(path)
        return value

    def add_history(entry):
        history.append({"kind": "history", "old": entry,
                        "main": entry, "is_dir": False, "folder": None,
                        "old_rel": relative(entry, wf)})

    def add_file(entry, rel, parts):
        name = entry.name
        override = take_override(entry)
        if override is None and (is_journal(name, entry.parent == wf)
                                 or name == README_NAME):
            add_history(entry)              # журнал, мастер-план, README
            return
        dir_prefix, status_hint = parts_info(parts[:-1])
        name_prefix, number, slug = parse_name(entry.stem)
        if override and override.get("type"):
            prefix = override["type"]
        else:
            prefix = name_prefix or dir_prefix
        if prefix is None:
            if override:
                raise MigrateError(tr('migrate.override_needs_type')
                                   % (MIGRATE_CONFIG, relative(entry, wf)))
            add_history(entry)
            return
        docs.append({"kind": "doc", "old": entry,
                     "main": entry, "is_dir": False, "folder": None,
                     "old_rel": relative(entry, wf),
                     "prefix": prefix, "name_number": number, "number": None,
                     "name_slug": slug, "status_hint": status_hint,
                     "override": override or {}, "notes": []})

    def add_folder(entry, rel, folder_type):
        override = take_override(entry)
        main = folder_main(entry, children.get(entry, ()))
        name_prefix, number, slug = parse_name(entry.name)
        if override and override.get("type"):
            prefix = override["type"]
        else:
            prefix = name_prefix or folder_type
        if main is None or prefix is None:
            if override:
                raise MigrateError(tr('migrate.override_missing_main')
                                  % (MIGRATE_CONFIG, relative(entry, wf)))
            return False
        docs.append({"kind": "doc", "old": entry,
                     "main": main, "is_dir": True, "folder": entry,
                     "old_rel": relative(entry, wf),
                     "prefix": prefix, "name_number": number, "number": None,
                     "name_slug": slug, "status_hint": folder_type_status(rel),
                     "override": override or {}, "notes": []})
        return True

    def folder_type_status(rel):
        _, status = parts_info(rel.parts[:-1])
        return status

    def visit(directory):
        for entry in sorted(children.get(directory, ())):
            name = entry.name
            if name.startswith("."):
                continue
            if directory == wf and name in (HISTORY_DIR, README_NAME, INDEX, "index",
                                            MIGRATE_CONFIG):
                continue
            rel = Path(relative(entry, wf))
            if entry in children:
                folder_prefix, _ = parts_info(rel.parts[:-1])
                name_prefix, _, _ = parse_name(entry.name)
                override = overrides.get(entry)
                # Папка-документ — только по имени схемы (aud-001-tema) или
                # переопределению: прочие папки — каталоги, их файлы
                # переносятся поодиночке.
                candidate = bool((override or {}).get("type") or name_prefix)
                if candidate and not is_journal(name, entry.parent == wf):
                    if add_folder(entry, rel, folder_prefix):
                        continue
                if override:
                    raise MigrateError(tr('migrate.override_not_document')
                                      % (MIGRATE_CONFIG, rel.as_posix()))
                visit(entry)
            else:
                if entry.suffix.lower() == ".md":
                    add_file(entry, rel, rel.parts)
                else:
                    add_history(entry)

    visit(wf)
    unused = [path for path in overrides if path not in used_overrides]
    if unused:
        raise MigrateError(tr('migrate.override_unused')
                          % (MIGRATE_CONFIG, relative(unused[0], wf)))
    return docs, history


def free_target(target, planned):
    """Свободный путь в history/: если занят, добавляется -2, -3, …"""
    target = Path(target)
    if not os.path.lexists(target) and target not in planned:
        planned.add(target)
        return target
    n = 2
    while True:
        candidate = target.with_name("%s-%d%s" % (target.stem, n, target.suffix))
        if not os.path.lexists(candidate) and candidate not in planned:
            planned.add(candidate)
            return candidate
        n += 1


# --- Сборка плана ------------------------------------------------------------

def build_plan(root, wf, top, cfg, today):
    """Всё, что нужно для плана и переноса: документы, переносы, ссылки."""
    from lipi.checker.workflow_layout import latest_closed_date

    latest_date = latest_closed_date().isoformat()
    docs_name = cfg.get("docs") if isinstance(cfg.get("docs"), str) else DEFAULT_DOCS
    project = Project(root, dict(cfg, docs=docs_name, workflow=str(wf)))
    workflow_project = (project if is_within(wf, root) and project.git_root == top
                        else Project(wf, {}))

    def select(path):
        lexical = project.lexical_path(path)
        scope = workflow_project if is_within(lexical, wf) else project
        return scope.file_path(lexical) or scope.file_path(lexical, directory=True)

    overrides = load_overrides(wf, select)
    docs, history = scan_units(wf, overrides, workflow_project)

    # Номера: сначала переопределённые, потом из имени, потом следующие свободные.
    used = {prefix: set() for prefix in TYPES}

    def assign(doc, want):
        taken = used[doc["prefix"]]
        if want is not None and want not in taken:
            number = want
        else:
            number = max(taken) + 1 if taken else 1
            if want is not None:
                doc["notes"].append(tr('migrate.number_collision')
                                    % (want, number))
        taken.add(number)
        doc["number"] = number

    ordered = sorted(docs, key=lambda d: d["old_rel"])
    for doc in ordered:
        want = doc["override"].get("number")
        if want is not None:
            assign(doc, want)
    for doc in ordered:
        if doc["number"] is None and doc["name_number"] is not None:
            assign(doc, doc["name_number"])
    for doc in ordered:
        if doc["number"] is None:
            assign(doc, None)

    # Тип, статус, номер: проверка переопределений и имена новых путей.
    for doc in ordered:
        override = doc["override"]
        prefix = doc["prefix"]
        if "status" in override:
            allowed = STATUSES.get(prefix, [])
            if not allowed:
                raise MigrateError(tr('migrate.override_audit_status')
                                  % (MIGRATE_CONFIG, doc["old_rel"], prefix))
            raw = override["status"]
            key = normalize_status(raw) if isinstance(raw, str) else ""
            canonical = LEGACY_STATUSES.get(key, key)
            if canonical not in allowed:
                raise MigrateError(tr('migrate.override_status')
                                  % (MIGRATE_CONFIG, doc["old_rel"],
                                     override["status"], prefix,
                                     ", ".join(allowed)))
            doc["status_override"] = canonical
        slug = doc["name_slug"]
        if not slug:
            stem = Path(doc["old_rel"]).name
            if doc["is_dir"]:
                stem = stem
            else:
                stem = Path(stem).stem
            slug = slugify(stem)
            if re.match(r"^(%s)[-_]\d" % "|".join(TYPES), stem, re.I):
                slug = ""
            slug = slug or "doc"
        doc["slug"] = slug
        # Дата выбирается до пути: её год определяет каталог.
        prepare_document(doc, top, today, latest_date)
        type_dir = wf / TYPES[prefix][0]
        if prefix != "adr":
            type_dir /= doc["created"][:4]
        base = "%s-%03d-%s" % (prefix, doc["number"], slug)
        if doc["is_dir"]:
            doc["new_folder"] = type_dir / base
            doc["new_main"] = doc["new_folder"] / ("%s-%03d-readme.md"
                                                   % (prefix, doc["number"]))
        else:
            doc["new_folder"] = None
            doc["new_main"] = type_dir / (base + ".md")

    moves, file_map, folder_moves = [], {}, []
    for doc in ordered:
        if doc["is_dir"]:
            if doc["new_folder"] != doc["folder"]:
                moves.append({"old": doc["folder"], "new": doc["new_folder"],
                              "kind": "folder"})
                folder_moves.append((doc["folder"], doc["new_folder"]))
                file_map[doc["main"]] = doc["new_main"]
                inner = doc["new_folder"] / doc["main"].name
                if inner != doc["new_main"]:
                    moves.append({"old": inner, "new": doc["new_main"],
                                  "kind": "file"})
            elif doc["new_main"] != doc["main"]:
                moves.append({"old": doc["main"], "new": doc["new_main"],
                              "kind": "file"})
                file_map[doc["main"]] = doc["new_main"]
        elif doc["new_main"] != doc["main"]:
            moves.append({"old": doc["main"], "new": doc["new_main"],
                          "kind": "file"})
            file_map[doc["main"]] = doc["new_main"]

    planned = set()
    history_rows = []
    for unit in history:
        path = wf / HISTORY_DIR / unit["old_rel"]
        if has_symlink(path.parent, wf):
            raise MigrateError(tr('migrate.move_symlink') % path)
        target = free_target(path, planned)
        moves.append({"old": unit["old"], "new": target, "kind": "file"})
        file_map[unit["old"]] = target
        history_rows.append({"old": unit["old_rel"],
                             "new": relative(target, wf), "id": "—"})

    masterplan_abs = wf / MASTERPLAN
    readme_path = wf / README_NAME
    migration_path = wf / HISTORY_DIR / MIGRATION
    generated = {masterplan_abs, readme_path, migration_path}
    generated -= workflow_project.git_ignored_paths(generated)
    for path in (*generated, *(move["new"] for move in moves)):
        if has_symlink(path, wf):
            raise MigrateError(tr('migrate.move_symlink') % path)
    masterplan_needed = (masterplan_abs in generated and
                         (not masterplan_abs.is_file() or any(m["old"] == masterplan_abs for m in moves)))
    readme_needed = readme_path in generated and not readme_path.is_file()

    def resolve(path):
        path = Path(path)
        if masterplan_needed and path == masterplan_abs:
            # пустой мастер-план создаётся по тому же пути: ссылки на него
            # остаются верными, прежний мастер-план уходит в history/ отдельно
            return path
        if path in file_map:
            return file_map[path]
        for old_dir, new_dir in folder_moves:
            if path == old_dir or old_dir in path.parents:
                return new_dir / path.relative_to(old_dir)
        return path

    # Тексты: шапка документа, затем переписанные ссылки во всех .md проекта.
    header_texts = {}
    for doc in ordered:
        if doc.get("text") is not None and doc["text"] != doc.get("old_text"):
            header_texts[doc["main"]] = doc["text"]
    updates, link_count, link_files = {}, 0, 0
    for path in walk_markdown(project, workflow_project):
        old_text = read_text(path)
        if old_text is None:
            continue
        base_text = header_texts.get(path, old_text)
        new_file = resolve(path)
        new_text, changed = rewrite_links(base_text, path, new_file, resolve, select)
        if new_text != old_text:
            updates[path] = new_text
        link_count += changed
        if changed:
            link_files += 1

    # Таблица переноса для history/MIGRATION.md.
    rows = []
    for doc in ordered:
        if doc["is_dir"]:
            if doc["new_folder"] != doc["folder"]:
                rows.append({"old": doc["old_rel"] + "/",
                             "new": relative(doc["new_folder"], wf) + "/",
                             "id": "%s-%03d" % (doc["prefix"].upper(),
                                                doc["number"])})
        elif doc["new_main"] != doc["main"]:
            rows.append({"old": doc["old_rel"],
                         "new": relative(doc["new_main"], wf),
                         "id": "%s-%03d" % (doc["prefix"].upper(),
                                            doc["number"])})
    rows += history_rows
    rows.sort(key=lambda r: r["old"])
    # Таблицу переноса не перезаписываем пустой: повторный запуск не должен
    # терять следы первого переноса.
    migration_needed = migration_path in generated and (bool(rows) or not migration_path.is_file())

    # Что сообщить в отчёте.
    notes = []
    for doc in ordered:
        for note in doc["notes"]:
            notes.append(tr('migrate.document_note') % (doc["old_rel"], note))
        if doc.get("status_unknown"):
            notes.append(tr('migrate.unknown_status')
                         % (doc["old_rel"], doc["status_unknown"], doc["status"]))
        if doc.get("kind_defaulted"):
            notes.append(tr('migrate.unknown_kind')
                         % doc["old_rel"])
        if doc.get("result_added"):
            notes.append(tr('migrate.result_added')
                         % ("%s-%03d" % (doc["prefix"].upper(), doc["number"]),
                            K_RESULT, doc["result"]))
        if doc.get("dates_from_git"):
            notes.append(tr('migrate.dates_from_git')
                         % doc["old_rel"])
        if doc.get("dates_fixed"):
            notes.append(tr('migrate.dates_corrected') % doc["old_rel"])

    docs_dir = project.catalog_path(docs_name) or project.lexical_path(docs_name)
    templates = Path("seed/common/workflow")
    readme_template = template_path(templates / "README.md").read_text(encoding="utf-8")
    masterplan_template = template_path(templates / MASTERPLAN).read_text(encoding="utf-8")
    readme_text = render_template(readme_template, wf / "README.md", root,
                                  wf, docs_dir, today)
    # Шаблон ссылается на описание: если его нет, ссылка стала бы битой (W6).
    docs_readme = docs_dir / "README.md"
    selected_readme = select(docs_readme)
    if selected_readme is None or not selected_readme.is_file():
        link = relative(docs_readme, wf)
        readme_text = re.sub(
            r"\[([^\]]+)\]\(%s(?:#[a-z0-9-]+)?\)" % re.escape(link), r"\1",
            readme_text)
    masterplan_text = render_template(masterplan_template, wf / MASTERPLAN,
                                      root, wf, docs_dir, today)

    config_update = None
    current = cfg.get("workflow", DEFAULT_WORKFLOW) if "workflow" in cfg \
        else DEFAULT_WORKFLOW
    try:
        current_abs = (project.catalog_path(current)
                       if isinstance(current, str) else None)
    except (OSError, ValueError):
        current_abs = None
    if current_abs != wf:
        config_update = relative(wf, root)

    return {"root": root, "wf": wf, "top": top, "today": today,
            "docs": ordered, "moves": moves, "folder_moves": folder_moves,
            "file_map": file_map, "updates": updates, "rows": rows,
            "notes": notes, "link_count": link_count, "link_files": link_files,
            "masterplan_needed": masterplan_needed,
            "readme_needed": readme_needed,
            "migration_needed": migration_needed,
            "readme_text": readme_text, "masterplan_text": masterplan_text,
            "config_update": config_update, "cfg": cfg}


def prepare_document(doc, top, today, latest_date):
    """Шапка документа: даты, статус, итог, вид. Готовит новый текст."""
    text = read_text(doc["main"])
    if text is None:
        raise MigrateError(tr('migrate.document_not_utf8') % doc["old_rel"])
    doc["old_text"] = text
    header = parse_header(text)
    found = {}
    for entry in header["entries"]:
        kind = header_kind(entry["key"], doc["prefix"])
        if kind == "closed" and kind in found:
            raise MigrateError(tr('migrate.closed_repeated')
                               % doc["old_rel"])
        if kind and kind not in found:
            found[kind] = entry["value"]

    # Статус: переопределение, каталог, шапка, «новый».
    status = None
    status_unknown = None
    if doc.get("status_override"):
        status = doc["status_override"]
    elif doc["status_hint"]:
        status = STATUS_BY_WORD[doc["status_hint"]][doc["prefix"]] \
            if doc["prefix"] in STATUSES else None
    elif found.get("status"):
        status, recognized = resolve_status(found["status"], doc["prefix"])
        if not recognized:
            status_unknown = found["status"]
    elif doc["prefix"] in NEW_STATUS:
        status = NEW_STATUS[doc["prefix"]]
    doc["status"] = status
    doc["status_unknown"] = status_unknown

    # Вид замечания: из шапки, иначе «вопрос» с пометкой.
    doc["kind"] = None
    doc["kind_defaulted"] = False
    if doc["prefix"] == "iss":
        raw_kind = normalize_status(found.get("kind", ""))
        kind = LEGACY_KINDS.get(raw_kind, raw_kind)
        if kind in ISSUE_KINDS:
            doc["kind"] = kind
        else:
            doc["kind"] = "question"
            doc["kind_defaulted"] = True

    # Итог: сохраняется; у завершённого плана и закрытого замечания дописывается.
    result = found.get("result")
    doc["result_added"] = False
    if not result and (doc["prefix"], status) in NEED_RESULT:
        result = tr('migrate.result_missing') % today
        doc["result_added"] = True
    doc["result"] = result
    if doc["result_added"]:
        doc["result"] = result

    # Только migrate восстанавливает отсутствующую/неверную дату создания.
    created = parse_date(found.get("created", ""))
    updated = parse_date(found.get("updated", ""))
    single = parse_date(found.get("date", ""))
    created = created or single
    updated = updated or single
    doc["created_origin"] = tr('migrate.header_origin') if created else None
    doc["dates_from_git"] = False
    if created is None or updated is None:
        first, last = commit_dates(top, doc["main"])
        doc["dates_from_git"] = bool(first or last)
        if created is None:
            created = first or today
            doc["created_origin"] = tr('migrate.commit_origin' if first else 'migrate.migration_origin')
        updated = updated or last or created
    doc["dates_fixed"] = updated < created
    if doc["dates_fixed"]:
        updated = created
    doc["created"], doc["updated"] = created, updated

    from lipi.checker.workflow_layout import is_final
    doc["closed"] = None
    if "closed" in found:
        closed = (parse_date(found["closed"])
                  if RE_DATE.fullmatch(found["closed"]) else None)
        if closed is None or closed < created or closed > latest_date:
            raise MigrateError(tr('migrate.closed_invalid')
                               % (doc["old_rel"], found["closed"], created, latest_date))
        doc["closed"], doc["closed_origin"] = closed, tr('migrate.closed_kept')
    elif is_final(doc["prefix"], status):
        source_status = historical_status(Page(doc["main"], text).header())
        if not is_final(doc["prefix"], source_status):
            # У неоформленного материала статус получен из имени каталога,
            # английского слова или override; история канонической шапки
            # не доказывает закрытие. Это fallback migrate, не переводчика init.
            if not created <= updated <= latest_date:
                raise MigrateError(tr('migrate.invalid_closed_fallback') % (doc["old_rel"], updated))
            doc["closed"] = updated
            doc["closed_origin"] = tr('migrate.updated_origin')
        else:
            from lipi.layout_migration import infer_closed_date
            try:
                doc["closed"], doc["closed_origin"] = infer_closed_date(
                    top, doc["main"], doc["prefix"], created, updated, latest_date)
            except ValueError as exc:
                raise MigrateError("%s: %s" % (doc["old_rel"], exc)) from exc

    doc["header"] = header
    fallback = Path(doc["old_rel"]).name
    if not doc["is_dir"]:
        fallback = Path(fallback).stem
    doc["title"] = doc_title(header, fallback)
    doc["text"] = rebuild_document(doc)


def render_template(text, dst, root, wf, docs, today):
    """Подстановки шаблона: каталоги, путь чекера и дата.

    Те же имена, что в src/lipi/init.py: {{DOCS}}, {{DOCS_REL}}, {{WORKFLOW}},
    {{WORKFLOW_REL}}, {{LIPI_REL}}, {{CHECK}}, {{DATE}} и относительные ссылки
    ../{{DOCS}} и ../{{WORKFLOW}}.
    """
    def to(target):
        return relative(target, dst.parent)

    text = text.replace("../{{DOCS}}", to(docs))
    text = text.replace("../{{WORKFLOW}}", to(wf))
    text = (text.replace("{{DOCS_REL}}", to(docs))
            .replace("{{WORKFLOW_REL}}", to(wf))
            .replace("{{LIPI_REL}}", to(root / LIPI_DIR))
            .replace("{{DOCS}}", relative(docs, root) if is_within(
                docs, root) else str(docs))
            .replace("{{WORKFLOW}}", relative(wf, root))
            .replace("{{DESCRIPTION}}", "")
            .replace("{{CHECK}}", CHECK_REL)
            .replace("{{DATE}}", today))
    return text


# --- Печать плана и отчёта ---------------------------------------------------

def print_plan(plan):
    wf, root, top = plan["wf"], plan["root"], plan["top"]
    print(tr('migrate.plan') % display(root, wf))
    if top != root:
        print(tr('migrate.git_repository') % top)
    moved = [d for d in plan["docs"] if doc_moved(d)]
    stayed = [d for d in plan["docs"] if not doc_moved(d)]
    if moved:
        print(tr('migrate.documents_plan') % len(moved))
        for doc in moved:
            print("  %s → %s  (%s, %s, %s)" % (
                doc["old_rel"], display(wf, doc["new_main"]),
                "%s-%03d" % (doc["prefix"].upper(), doc["number"]),
                tr(TYPES[doc["prefix"]][1]).lower(), doc["status"] or tr('migrate.no_status')))
    if stayed:
        print(tr('migrate.already_placed_plan') % len(stayed))
        for doc in stayed:
            print("  %s  (%s, %s)" % (
                doc["old_rel"], "%s-%03d" % (doc["prefix"].upper(), doc["number"]),
                doc["status"] or tr('migrate.no_status')))
    if plan["docs"]:
        print(tr('migrate.date_explanations'))
        for doc in plan["docs"]:
            layout = (tr('migrate.adr_no_year') if doc["prefix"] == "adr"
                      else tr('migrate.year') % doc["created"][:4])
            print("  %s: %s = %s (%s); %s" % (
                doc["old_rel"], K_CREATED, doc["created"], doc["created_origin"], layout))
            if doc.get("closed"):
                print("    %s = %s (%s)" % (
                    K_CLOSED, doc["closed"], doc["closed_origin"]))
    history = [row for row in plan["rows"] if row["id"] == "—"]
    if history:
        print(tr('migrate.archived_plan') % len(history))
        for row in history:
            print("  %s → %s" % (row["old"], row["new"]))
    creates = []
    if plan["masterplan_needed"]:
        creates.append(display(wf, wf / MASTERPLAN))
    if plan["readme_needed"]:
        creates.append(display(wf, wf / "README.md"))
    if plan["migration_needed"]:
        creates.append(tr('migrate.migration_table_plan')
                       % display(wf, wf / HISTORY_DIR / MIGRATION))
    if creates:
        print(tr('migrate.create_plan') % ", ".join(creates))
    print(tr('migrate.rewrite_plan') % (plan["link_count"], plan["link_files"]))
    if plan["config_update"]:
        print(tr('migrate.config_update_plan')
              % (CONFIG_NAME, plan["config_update"]))
    else:
        print(tr('migrate.config_keep_plan') % CONFIG_NAME)
    if plan["notes"]:
        print(tr('migrate.notes') % len(plan["notes"]))
        for note in plan["notes"]:
            print("  %s" % note)
    command = ["lipi", "migrate", display(Path.cwd(), wf), "--apply"]
    command = (subprocess.list2cmdline(command) if os.name == "nt"
               else shlex.join(command))
    print(tr('migrate.apply_hint') % command)


def doc_moved(doc):
    return doc["new_main"] != doc["main"] or (doc["is_dir"]
                                              and doc["new_folder"] != doc["folder"])


def apply_plan(plan):
    """Выполняет план: файлы, git mv, новые файлы, настройки, указатель."""
    root, wf, top = plan["root"], plan["wf"], plan["top"]
    for path, text in sorted(plan["updates"].items()):
        path.write_text(text, encoding="utf-8")
    for move in plan["moves"]:
        move["new"].parent.mkdir(parents=True, exist_ok=True)
        code, out = git(top, "mv", "--", relative(move["old"], top),
                        relative(move["new"], top))
        if code != 0:
            raise MigrateError(tr('migrate.git_move_failed') % out.strip())
    if plan["readme_needed"]:
        (wf / "README.md").write_text(plan["readme_text"], encoding="utf-8")
    if plan["masterplan_needed"]:
        (wf / MASTERPLAN).write_text(plan["masterplan_text"], encoding="utf-8")
    if plan["migration_needed"]:
        history = wf / HISTORY_DIR
        history.mkdir(parents=True, exist_ok=True)
        (history / MIGRATION).write_text(migration_text(plan), encoding="utf-8")
    cleanup_empty_dirs(wf, plan["moves"])
    if plan["config_update"]:
        cfg = dict(plan["cfg"])
        cfg["workflow"] = plan["config_update"]
        (root / CONFIG_NAME).write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    # Первый запуск создаёт указатель; второй — проверка по готовому каркасу:
    # ссылка из README на INDEX.md до первого запуска ещё не ведёт в файл.
    run_check(root, write_index=True)
    return run_check(root, write_index=False)


def migration_text(plan):
    lines = [tr('migrate.migration_log_title'), "",
             tr('migrate.migration_log_intro') % plan["today"], "",
             tr('migrate.migration_log_table'), "| --- | --- | --- |"]
    for row in plan["rows"]:
        lines.append("| `%s` | `%s` | %s |"
                     % (row["old"].replace("|", "\\|"),
                        row["new"].replace("|", "\\|"), row["id"]))
    return "\n".join(lines) + "\n"


def cleanup_empty_dirs(wf, moves):
    """Убирает опустевшие прежние каталоги (current/, reports/ …)."""
    keep = {wf, *(wf / directory for directory, _ in TYPES.values())}
    candidates = {parent for move in moves for parent in move["old"].parents
                  if is_within(parent, wf) and not is_within(parent, wf / HISTORY_DIR)} - keep
    if not candidates:
        return
    candidates -= Project(wf, {}).git_ignored_paths(candidates)
    for here in sorted(candidates, key=lambda path: (-len(path.parts), path)):
        if has_symlink(here, wf):
            continue
        try:
            here.rmdir()
        except OSError:
            pass


def run_check(root, write_index=True):
    """Чекер из репозитория lipi (не копия проекта); с --write-index — указатель."""
    script = HERE / "check.py"
    cmd = [sys.executable, "-B", str(script), "--root", str(root)]
    if write_index:
        cmd.append("--write-index")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace").strip()
    return proc.returncode, out


def print_report(plan, check_code, check_out):
    """Отчёт по итогам --apply: что перенесено и что осталось сделать."""
    root, wf = plan["root"], plan["wf"]
    moved = [d for d in plan["docs"] if doc_moved(d)]
    stayed = [d for d in plan["docs"] if not doc_moved(d)]
    history_count = len(plan["rows"]) - len(moved)
    print(tr('migrate.applied') % display(root, wf))
    history = [row for row in plan["rows"] if row["id"] == "—"]
    if moved:
        print(tr('migrate.documents_moved') % len(moved))
        for doc in moved:
            print("  %s → %s  (%s, %s, %s)" % (
                doc["old_rel"], relative(doc["new_main"], wf),
                "%s-%03d" % (doc["prefix"].upper(), doc["number"]),
                tr(TYPES[doc["prefix"]][1]).lower(), doc["status"] or tr('migrate.no_status')))
    if stayed:
        print(tr('migrate.already_placed') % len(stayed))
    print(tr('migrate.moved_summary')
          % (len(moved), len(stayed), max(history_count, 0)))
    if history:
        print(tr('migrate.archived'))
        for row in history:
            print("  %s → %s" % (row["old"], row["new"]))
    if plan["notes"]:
        print(tr('migrate.notes') % len(plan["notes"]))
        for note in plan["notes"]:
            print("  %s" % note)
    print(tr('migrate.links_rewritten')
          % (plan["link_count"], plan["link_files"]))
    if plan["readme_needed"]:
        print(tr('migrate.created') % display(wf, wf / "README.md"))
    if plan["masterplan_needed"]:
        print(tr('migrate.created') % display(wf, wf / MASTERPLAN))
    if plan["migration_needed"]:
        print(tr('migrate.written') % display(wf, wf / HISTORY_DIR / MIGRATION))
    if plan["config_update"]:
        print(tr('migrate.config_updated') % (CONFIG_NAME, plan["config_update"]))
    else:
        print(tr('migrate.config_kept') % CONFIG_NAME)
    print(tr('migrate.index_rebuilt') % (HERE / "check.py"))
    if check_code == 0:
        print(tr('migrate.check_ok'))
    else:
        print(tr('migrate.check_baseline'))
        if check_out:
            print(check_out)


# --- Запуск ------------------------------------------------------------------

def project_root_for(wf):
    """Ближайший каталог с lipi.json вверх от каталога материалов; иначе None."""
    for directory in [wf] + list(wf.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return None


def make_plan(root, explicit, today):
    """Проверки и сборка плана; отказ — MigrateError."""
    if explicit:
        candidate = catalog_path(root, explicit)
        found = project_root_for(candidate)
        if found is not None:
            root = found
        explicit = str(candidate)       # дальше путь не зависит от нового корня
    cfg, _ = read_project_config(root)
    wf = resolve_catalog(root, cfg, explicit)
    top = repo_top(wf)
    if top is None:
        raise MigrateError(
            tr('migrate.git_required') % wf)
    dirty = dirty_lines(top)
    if dirty is None:
        raise MigrateError(tr('migrate.git_status_failed') % top)
    if dirty:
        raise MigrateError(
            tr('migrate.git_dirty') % (top, "\n".join(dirty[:10])))
    plan = build_plan(root, wf, top, cfg, today)
    missing = untracked_moves(plan, top)
    if missing:
        raise MigrateError(
            tr('migrate.git_untracked')
            % "\n".join(display(root, path) for path in missing[:10]))
    return plan


def main():
    parser = ArgumentParser(
        prog="lipi migrate",
        description=tr('migrate.help'))
    parser.add_argument("workflow", nargs="?",
                        help=tr('migrate.help_workflow'))
    parser.add_argument("--apply", action="store_true",
                        help=tr('migrate.help_apply'))
    args = parser.parse_args()

    root = Path.cwd().resolve()
    today = datetime.date.today().isoformat()
    try:
        plan = make_plan(root, args.workflow, today)
        if not args.apply:
            print_plan(plan)
            return 0
        check_code, check_out = apply_plan(plan)
        print_report(plan, check_code, check_out)
        return 0
    except MigrateError as e:
        print(str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print(tr('migrate.failed') % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
