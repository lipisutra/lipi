"""Настройки проекта и схемы файлов состояния."""
import difflib
import errno
import json
import os
import re
import stat
from collections import deque
from fnmatch import fnmatchcase
from pathlib import Path, PureWindowsPath

from lipi.i18n import quoted, tr
from .conventions import BASE_NAME, CONFIG_NAME, LOCK_NAME
from .model import git_worktree_root, has_symlink, is_within
from .report import CODE_LEVELS
from .paths import skip_entry

DEFAULTS = {
    "docs": "docs", "description": None, "workflow": "workflow",
    "enforce": False,
    "codes": {},
    "limits": {"docs_lines": 320, "docs_bytes": 24576,
               "workflow_lines": 600, "masterplan_lines": 150},
    "release_notes": None,
    "stale_days": {"active": 30, "review": 14, "issue": 60},
    "entry": [], "skip_dirs": [], "checks": [],
    "layers": {},
    "tests": ["test_*", "*_test.*", "*.test.*", "*.spec.*", "*Test.*"],
    "slice_budget": 60,
}


def code_layer(path, cfg):
    """First configured layer, or the file's top-level directory."""
    for pattern, name in cfg.get("layers", {}).items():
        if fnmatchcase(path, pattern):
            return name
    return path.split("/")[0] if "/" in path else "."


def is_configured_test_file(path, layer, cfg):
    """Classify a file using the layer and basename rules of map and slice."""
    name = Path(path).name
    return layer == "tests" or any(fnmatchcase(name, pattern)
                                   for pattern in cfg.get("tests", DEFAULTS["tests"]))


# --- Схема настроек (C1) ------------------------------------------------------
#
# Ошибка настроек — C1: неизвестный ключ, неверный тип или значение. Такой
# проверке нельзя доверять, поэтому чекер печатает все C1 и завершается с
# кодом 2, не запуская остальных проверок.

LIMITS_KEYS = ("docs_lines", "docs_bytes", "workflow_lines", "masterplan_lines")
STALE_KEYS = ("active", "review", "issue")
# Ключ checks: проверки, зависящие от стека проекта (ADR-008). Команда
# запускается без оболочки из корня проекта; mode решает, когда её запускать,
# timeout — необязательный предел времени в секундах.
CHECK_KEYS = ("name", "run", "mode", "timeout")
CHECK_MODES = ("quick", "audit")
# Ключ languages: языковые редакции описания. Страницы пары — один
# относительный путь внутри редакций; default — редакция по умолчанию (её
# каталог и есть каталог описания), required — редакции, где страница
# обязательна (L1). Пути меток и covers считаются от редакции по умолчанию.
LANG_KEYS = ("default", "editions", "required")
REPO_REQUIRED = ("path", "read")
REPO_KEYS = (*REPO_REQUIRED, "page_dirs")
REPO_READ = ("docs", "decisions", "code", "tests")


BASE_KEYS = ("schema", "entries")
BASE_ENTRY_KEYS = ("code", "file", "subject", "count")
_BAD_JSON = object()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonneg_int(value):
    return _is_int(value) and value >= 0


def _type_name(value):
    """Тип значения для сообщения об ошибке."""
    if value is None:
        return "null"
    names = {
        str: "checker.config.type_string",
        int: "checker.config.type_integer",
        float: "checker.config.type_number",
        bool: "checker.config.type_boolean",
        list: "checker.config.type_list",
        dict: "checker.config.type_object",
    }
    key = names.get(type(value))
    return tr(key) if key else type(value).__name__


def _describe(value):
    """Значение для сообщения: строки в кавычках, null и true/false как в JSON."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return quoted(value) if isinstance(value, str) else str(value)


def _suggest(key, keys):
    """«, имелось в виду «docs»?» для ближайшего ключа или пусто."""
    close = difflib.get_close_matches(key, list(keys), n=1)
    return tr("checker.config.did_you_mean") % close[0] if close else ""


def _check_str(value):
    return None if isinstance(value, str) else tr("checker.config.expected_string") % _type_name(value)


def _check_str_or_null(value):
    if value is None or isinstance(value, str):
        return None
    return tr("checker.config.expected_string_or_null") % _type_name(value)


# @trace docs/ru/codes.md#c1
def _check_decisions(value):
    if not isinstance(value, str):
        return tr("checker.config.expected_string") % _type_name(value)
    if not value.strip():
        return tr("checker.config.empty_decisions_path")
    if '\x00' in value:
        return tr("checker.config.nul_in_decisions_path")
    path = Path(value)
    if path.is_absolute() or os.path.normpath(value).split(os.sep)[0] == '..':
        return tr("checker.config.relative_path_inside_root")
    return None


def _check_bool(value):
    return (None if isinstance(value, bool)
            else tr("checker.config.expected_boolean") % _type_name(value))


def _check_limits(value):
    if not isinstance(value, dict):
        return tr("checker.config.expected_object") % _type_name(value)
    for key, item in value.items():
        if key not in LIMITS_KEYS:
            return tr("checker.config.unknown_key") % (key, _suggest(key, LIMITS_KEYS))
        if not _is_nonneg_int(item):
            return tr("checker.config.key_expected_nonnegative_integer") % (key, _describe(item))
    return None


def _check_stale(value):
    if not isinstance(value, dict):
        return tr("checker.config.expected_object") % _type_name(value)
    for key, item in value.items():
        if key not in STALE_KEYS:
            return tr("checker.config.unknown_key") % (key, _suggest(key, STALE_KEYS))
        if not _is_int(item):
            return tr("checker.config.key_expected_integer") % (key, _describe(item))
    return None


def _check_str_list(value):
    if not isinstance(value, list):
        return tr("checker.config.expected_string_list") % _type_name(value)
    for n, item in enumerate(value, 1):
        if not isinstance(item, str):
            return tr("checker.config.item_expected_string") % (n, _describe(item))
    return None


# @trace docs/ru/codes.md#c1
def _check_skip_dirs(value):
    problem = _check_str_list(value)
    if problem:
        return problem
    for number, entry in enumerate(value, 1):
        try:
            skip_entry(entry)
        except ValueError as error:
            return tr("checker.config.invalid_item") % (number, error)
    return None


def _check_entry(value):
    problem = _check_str_list(value)
    if problem:
        return problem
    for number, pattern in enumerate(value, 1):
        try:
            re.compile(pattern)
        except re.error as error:
            return tr("checker.config.item_invalid_regex") % (number, error)
    return None


def _check_layers(value):
    if not isinstance(value, dict):
        return tr("checker.config.expected_layers_object") % _type_name(value)
    for pattern, layer in value.items():
        if not pattern.strip():
            return tr("checker.config.empty_path_pattern")
        if not isinstance(layer, str):
            return tr("checker.config.key_expected_string") % (pattern, _describe(layer))
        if not layer.strip():
            return tr("checker.config.empty_layer_name") % pattern
    return None


def _check_tests(value):
    problem = _check_str_list(value)
    if problem:
        return problem
    if any(not item.strip() for item in value):
        return tr("checker.config.empty_filename_pattern")
    return None


def _check_slice_budget(value):
    if not (_is_int(value) and value >= 1):
        return tr("checker.config.expected_positive_integer") % _describe(value)
    return None


def _check_release_notes(value):
    """release_notes: путь страницы описания с записями о выпусках или null.

    Путь относительный, от каталога описания; существование файла не
    проверяется (страницы может ещё не быть) — D3 просто нечего пропускать.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return tr("checker.config.expected_string") % _type_name(value)
    if not value.strip():
        return tr("checker.config.empty_release_notes_path")
    return None


def _check_run(value):
    """run проверки проекта: непустой список непустых строк команды."""
    if not isinstance(value, list):
        return tr("checker.config.expected_string_list") % _type_name(value)
    if not value:
        return tr("checker.config.empty_command")
    for n, item in enumerate(value, 1):
        if not isinstance(item, str):
            return tr("checker.config.item_expected_string") % (n, _describe(item))
        if not item:
            return tr("checker.config.empty_item") % n
    return None


def _check_checks(value):
    """checks: список проверок проекта — name, run, mode, timeout."""
    if not isinstance(value, list):
        return tr("checker.config.expected_list") % _type_name(value)
    for n, item in enumerate(value, 1):
        where = tr("checker.config.item") % n
        if not isinstance(item, dict):
            return tr("checker.config.object_expected_at") % (where, _type_name(item))
        for key in item:
            if key not in CHECK_KEYS:
                return tr("checker.config.unknown_key_at") % (
                    where, key, _suggest(key, CHECK_KEYS))
        for key in ("name", "run"):
            if key not in item:
                return tr("checker.config.missing_key_at") % (where, key)
        if not isinstance(item["name"], str):
            return tr("checker.config.check_name_not_string") % (
                where, _type_name(item["name"]))
        if not item["name"].strip():
            return tr("checker.config.empty_check_name") % where
        problem = _check_run(item["run"])
        if problem:
            return "%s: %s: %s" % (where, quoted("run"), problem)
        mode = item.get("mode", "quick")
        if not isinstance(mode, str):
            return tr("checker.config.invalid_check_mode_type") % (
                where, _describe(mode))
        if mode not in CHECK_MODES:
            return tr("checker.config.invalid_check_mode_value") % (
                where, mode, _suggest(mode, CHECK_MODES))
        if "timeout" in item and not (_is_int(item["timeout"]) and item["timeout"] > 0):
            return tr("checker.config.invalid_check_timeout") % (
                where, _describe(item["timeout"]))
    return None


def _check_languages(value):
    """languages: языковые редакции — default, editions, required.

    default — имя редакции из editions; editions — объект «язык: каталог», пути
    непустые и разные; required (необязательный) — список имён из editions.
    """
    if not isinstance(value, dict):
        return tr("checker.config.expected_object") % _type_name(value)
    for key in value:
        if key not in LANG_KEYS:
            return tr("checker.config.unknown_key") % (key, _suggest(key, LANG_KEYS))
    for key in ("default", "editions"):
        if key not in value:
            return tr("checker.config.missing_key") % key
    editions = value["editions"]
    if not isinstance(editions, dict):
        return tr("checker.config.invalid_editions_type") % _type_name(editions)
    if not editions:
        return tr("checker.config.empty_editions")
    seen = {}
    for name, path in editions.items():
        if not name.strip():
            return tr("checker.config.empty_edition_name")
        if not isinstance(path, str):
            return tr("checker.config.edition_path_not_string") % (name, _type_name(path))
        if not path.strip():
            return tr("checker.config.empty_edition_path") % name
        norm = os.path.normpath(path)
        if norm in seen:
            return tr("checker.config.same_edition_directory") % (seen[norm], name, path)
        seen[norm] = name
    for norm, name in seen.items():
        for other, other_name in seen.items():
            if other != norm and (norm == "." or other.startswith(norm + os.sep)):
                return tr("checker.config.nested_edition_directory") % (
                    other, other_name, norm, name)
    default = value["default"]
    if not isinstance(default, str):
        return tr("checker.config.default_edition_not_string") % _type_name(default)
    if default not in editions:
        return tr("checker.config.default_edition_missing") % (
            default, _suggest(default, editions))
    if "required" in value:
        required = value["required"]
        if not isinstance(required, list):
            return tr("checker.config.required_editions_not_list") % _type_name(required)
        for n, name in enumerate(required, 1):
            if not isinstance(name, str):
                return tr("checker.config.required_edition_not_string") % (
                    n, _describe(name))
            if name not in editions:
                return tr("checker.config.required_edition_missing") % (
                    n, name, _suggest(name, editions))
    return None


# @trace docs/ru/codes.md#c1,ADR-012
def _check_codes(value):
    """Ключ codes (ADR-012): код проверки -> error, warning или off."""
    if not isinstance(value, dict):
        return tr("checker.config.codes_not_object") % _type_name(value)
    allowed = sorted(code for code in CODE_LEVELS if code not in ("C1", "V1"))
    for code, level in value.items():
        if code in ("C1", "V1"):
            return tr("checker.config.code_level_fixed") % code
        if code not in CODE_LEVELS:
            return tr("checker.config.unknown_check_code") % (code, ", ".join(allowed))
        if level not in ("error", "warning", "off"):
            return tr("checker.config.unknown_check_level") % (code, level)
    return None


# @trace docs/ru/codes.md#c1
def _check_page_dirs(value):
    problem = _check_str_list(value)
    if problem:
        return problem
    for number, entry in enumerate(value, 1):
        if not entry.strip():
            return tr("checker.config.empty_item") % number
        if '\0' in entry or PureWindowsPath(entry).anchor or Path(entry).is_absolute():
            return tr("checker.config.invalid_item") % (
                number, tr("checker.config.relative_path_inside_root"))
        depth = 0
        for part in Path(entry).parts:
            depth += -1 if part == ".." else 1
            if depth < 0:
                return tr("checker.config.invalid_item") % (
                    number, tr("checker.config.relative_path_inside_root"))
    return None


# @trace docs/ru/codes.md#c1
def _check_repos(value):
    """Явные подключения: имя, относительный путь и разрешённое чтение."""
    if not isinstance(value, dict):
        return tr("checker.config.expected_object") % _type_name(value)
    for alias, item in value.items():
        if not isinstance(alias, str) or re.fullmatch(r"[a-z0-9-]+", alias) is None:
            return tr("checker.config.invalid_repo_name") % alias
        if not isinstance(item, dict):
            return tr("checker.config.key_expected_object") % (alias, _type_name(item))
        for key in item:
            if key not in REPO_KEYS:
                return tr("checker.config.repo_unknown_key") % (
                    alias, key, _suggest(key, REPO_KEYS))
        for key in REPO_REQUIRED:
            if key not in item:
                return tr("checker.config.repo_missing_key") % (alias, key)
        path = item["path"]
        if not isinstance(path, str):
            return tr("checker.config.repo_path_not_string") % (alias, _type_name(path))
        if not path.strip():
            return tr("checker.config.empty_repo_path") % alias
        if "\0" in path or Path(path).is_absolute():
            return tr("checker.config.invalid_repo_path") % alias
        read = item["read"]
        problem = _check_str_list(read)
        if problem:
            return "%s: %s: %s" % (quoted(alias), quoted("read"), problem)
        if not read:
            return tr("checker.config.empty_repo_read") % alias
        seen = set()
        for capability in read:
            if capability not in REPO_READ:
                return tr("checker.config.unknown_repo_capability") % (
                    alias, capability, ", ".join(REPO_READ))
            if capability in seen:
                return tr("checker.config.repeated_repo_capability") % (alias, capability)
            seen.add(capability)
        if "page_dirs" in item:
            if "docs" not in seen:
                return tr("checker.config.repo_page_dirs_require_docs") % alias
            problem = _check_page_dirs(item["page_dirs"])
            if problem:
                return "%s: %s: %s" % (quoted(alias), quoted("page_dirs"), problem)
    return None


def _path_identity(path, *, directory=False):
    try:
        status = path.stat()
    except NotADirectoryError:
        if directory:
            raise
        return path
    except OSError:
        return path
    if directory and not stat.S_ISDIR(status.st_mode):
        raise NotADirectoryError(path)
    # resolve не нормализует регистр на всех файловых системах.
    return status.st_dev, status.st_ino


def resolve_page_dir(root, entry, *, path_allowed=None, follow_symlinks=True):
    """Разрешает компоненты пути, не переходя по ссылкам за границу."""
    relative = Path(entry)
    if relative.is_absolute():
        return None
    pending = deque(relative.parts)
    path = root
    links = 0
    while pending:
        part = pending.popleft()
        if part == "..":
            if path == root:
                return None
            path = path.parent
            continue
        path /= part
        if path_allowed is not None and not path_allowed(path, directory=True):
            return None
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISLNK(mode):
            raise NotADirectoryError(path)
        if not follow_symlinks or links == 40:
            return None
        links += 1
        target = path.readlink()
        if target.is_absolute():
            if not is_within(target, root):
                return None
            target = target.relative_to(root)
            path = root
        else:
            path = path.parent
        pending.extendleft(reversed(target.parts))
    return path


def _check_repo_page_dirs(root, alias, entries):
    errors, seen = [], {}
    for entry in entries:
        try:
            path = resolve_page_dir(root, entry)
            if path is not None:
                identity = _path_identity(path, directory=True)
        except NotADirectoryError:
            errors.append((CONFIG_NAME, tr("checker.config.repo_page_dir_not_directory") % (
                alias, _describe(entry))))
            continue
        except (OSError, RuntimeError, ValueError):
            path = None
        if path is None:
            errors.append((CONFIG_NAME, tr("checker.config.repo_page_dir_outside_root") % (
                alias, _describe(entry))))
            continue
        if identity in seen:
            errors.append((CONFIG_NAME, tr("checker.config.repo_duplicate_page_dir") % (
                alias, _describe(seen[identity]), _describe(entry))))
        else:
            seen[identity] = entry
    return errors


def _resolve_repo_root(path):
    try:
        return path.resolve(strict=True)
    except OSError as error:
        # Non-strict resolution can hide a symlink loop on Python 3.13+.
        # On Windows ERROR_CANT_RESOLVE_FILENAME has winerror 1921.
        if error.errno == errno.ELOOP or getattr(error, "winerror", None) == 1921:
            raise
        return path.resolve()


# @trace docs/ru/codes.md#c1
def _check_repo_roots(root, repos):
    """Физические корни уникальны; отсутствие соседа не ошибка настроек."""
    errors = []
    try:
        own_root = _resolve_repo_root(root)
    except (OSError, RuntimeError, ValueError) as error:
        return [(CONFIG_NAME, tr("checker.config.repos_root_unresolved") % error)]
    own_identity = _path_identity(own_root)
    seen = {}
    for alias, item in repos.items():
        try:
            directory = _resolve_repo_root(own_root / item["path"])
        except (OSError, RuntimeError, ValueError) as error:
            errors.append((CONFIG_NAME, tr("checker.config.repo_path_unresolved") % (
                alias, error)))
            continue
        physical = _path_identity(directory)
        if physical == own_identity:
            errors.append((CONFIG_NAME, tr("checker.config.repo_self_reference") % alias))
        elif physical in seen:
            errors.append((CONFIG_NAME, tr("checker.config.repo_duplicate_root") % (
                seen[physical], alias)))
        seen[physical] = alias
        errors.extend(_check_repo_page_dirs(directory, alias, item.get("page_dirs", ())))
    return errors


CONFIG_SCHEMA = {
    "docs": _check_str,
    "description": _check_str_or_null,
    "workflow": _check_str_or_null,
    "decisions": _check_decisions,
    "enforce": _check_bool,
    "limits": _check_limits,
    "release_notes": _check_release_notes,
    "stale_days": _check_stale,
    "entry": _check_entry,
    "layers": _check_layers,
    "tests": _check_tests,
    "slice_budget": _check_slice_budget,
    "skip_dirs": _check_skip_dirs,
    "languages": _check_languages,
    "checks": _check_checks,
    "codes": _check_codes,
    "repos": _check_repos,
}




def _read_json(path):
    """Объект из JSON-файла; _BAD_JSON, если файл не читается как JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return _BAD_JSON


# @trace docs/ru/codes.md#c1
def check_lock(root):
    """Ошибки C1 файла .agents/lipi/lipi.lock; файла нет — список пуст."""
    path = root / LOCK_NAME
    if not path.is_file():
        return []
    data = _read_json(path)
    if data is _BAD_JSON:
        return [(LOCK_NAME, tr("checker.config.invalid_json"))]
    if not isinstance(data, dict):
        return [(LOCK_NAME, tr("checker.config.expected_object") % _type_name(data))]
    errors = []
    for key in ("lipi", "files"):
        if key not in data:
            errors.append((LOCK_NAME, tr("checker.config.missing_key") % key))
    for key, value in data.items():
        if key == "lipi":
            if not isinstance(value, str):
                errors.append((LOCK_NAME, tr("checker.config.invalid_lock_lipi")
                               % _type_name(value)))
        elif key == "files":
            if not isinstance(value, dict):
                errors.append((LOCK_NAME, tr("checker.config.invalid_lock_files")
                               % _type_name(value)))
            else:
                for name, digest in value.items():
                    if not isinstance(digest, str):
                        errors.append((LOCK_NAME, tr("checker.config.invalid_lock_fingerprint")
                                       % (name, _type_name(digest))))
        elif key == "enforce":
            if not isinstance(value, bool):
                errors.append((LOCK_NAME, tr("checker.config.invalid_lock_enforce")
                               % _type_name(value)))
        else:
            message = tr("checker.config.unknown_key") % (key, _suggest(key, ("lipi", "files", "enforce")))
            errors.append((LOCK_NAME, message))
    return errors


# @trace docs/ru/codes.md#c1
def check_baseline(root):
    """Ошибки C1 файла .agents/lipi/baseline.json; файла нет — список пуст."""
    path = root / BASE_NAME
    if not path.is_file():
        return []
    data = _read_json(path)
    if data is _BAD_JSON:
        return [(BASE_NAME, tr("checker.config.invalid_json"))]
    if not isinstance(data, dict):
        return [(BASE_NAME, tr("checker.config.expected_object") % _type_name(data))]
    errors = []
    for key in BASE_KEYS:
        if key not in data:
            errors.append((BASE_NAME, tr("checker.config.missing_key") % key))
    for key, value in data.items():
        if key == "schema":
            if not (_is_int(value) and value == 1):
                errors.append((BASE_NAME, tr("checker.config.invalid_baseline_schema") % _describe(value)))
        elif key == "entries":
            if not isinstance(value, list):
                errors.append((BASE_NAME, tr("checker.config.invalid_baseline_entries")
                               % _type_name(value)))
                continue
            for n, entry in enumerate(value, 1):
                where = tr("checker.config.baseline_entry") % n
                if not isinstance(entry, dict):
                    errors.append((BASE_NAME, tr("checker.config.object_expected_at")
                                   % (where, _type_name(entry))))
                    continue
                for field in BASE_ENTRY_KEYS:
                    if field not in entry:
                        errors.append((BASE_NAME, tr("checker.config.missing_key_at") % (where, field)))
                for field, item in entry.items():
                    if field in ("code", "file", "subject"):
                        if not isinstance(item, str):
                            errors.append((BASE_NAME, tr("checker.config.string_expected_at")
                                           % (where, field, _type_name(item))))
                    elif field == "count":
                        if not _is_nonneg_int(item):
                            errors.append((BASE_NAME, tr("checker.config.invalid_baseline_count")
                                           % (where, _describe(item))))
                    else:
                        errors.append((BASE_NAME, tr("checker.config.unknown_key_at")
                                       % (where, field, _suggest(field, BASE_ENTRY_KEYS))))
        else:
            errors.append((BASE_NAME, tr("checker.config.unknown_key") % (key, _suggest(key, BASE_KEYS))))
    return errors


# @trace docs/ru/codes.md#c1
def validate_settings(root, cfg, *, repo_roots=True):
    """Ошибки C1 настроек, без чтения lock и базовой линии.

    У соседа repo_roots=False: схема его подключений проверяется, но пути
    третьих репозиториев не разрешаются и их содержимое не читается.
    """
    errors = []

    def err(path, msg):
        errors.append((path, msg))

    for key, value in cfg.items():
        check = CONFIG_SCHEMA.get(key)
        if check is None:
            err(CONFIG_NAME, tr("checker.config.unknown_key") % (key, _suggest(key, CONFIG_SCHEMA)))
            continue
        problem = check(value)
        if problem:
            err(CONFIG_NAME, tr("checker.config.invalid_key") % (key, problem))
    if 'decisions' in cfg and _check_decisions(cfg['decisions']) is None:
        directory = Path(os.path.abspath(root / cfg['decisions']))
        if (not is_within(directory, root) or has_symlink(directory, root)
                and (git_worktree_root(root) is not None or not is_within(directory.resolve(), root))):
            err(CONFIG_NAME, tr("checker.config.decisions_outside_root"))
    repos = cfg.get("repos", {})
    layers = cfg.get("layers", {})
    if repos and _check_layers(layers) is None and any('::' in name for name in layers.values()):
        err(CONFIG_NAME, tr("checker.config.reserved_layer_separator"))
    if repo_roots and repos and _check_repos(repos) is None:
        errors += _check_repo_roots(root, repos)
    # При языковых редакциях каталог описания — каталог редакции по умолчанию:
    # от него считаются пути меток и covers, поэтому он должен с ним совпадать.
    langs = cfg.get("languages")
    if _check_languages(langs) is None and isinstance(cfg.get("docs"), str):
        default = langs["default"]
        edition = langs["editions"][default]
        if os.path.normpath(cfg["docs"]) != os.path.normpath(edition):
            err(CONFIG_NAME, tr("checker.config.docs_not_default_edition")
                % (_describe(cfg["docs"]), default, _describe(edition)))
    return errors


# @trace docs/ru/codes.md#c1
def validate_config(root, cfg):
    """Ошибки C1 настроек, lock и базовой линии; останавливают чекер с кодом 2."""
    return validate_settings(root, cfg) + check_lock(root) + check_baseline(root) + check_reviews(root)


# @trace docs/ru/review.md#state,docs/ru/codes.md#c1
def check_reviews(root):
    from .reviews import REVIEWS_NAME, ReviewError, load_reviews
    try:
        load_reviews(root)
    except ReviewError as error:
        return [(REVIEWS_NAME, str(error))]
    return []


# @trace docs/ru/settings.md#workflow
def load_config(root, explicit):
    path = Path(explicit) if explicit else root / CONFIG_NAME
    cfg = json.loads(json.dumps(DEFAULTS))
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(tr("checker.config.object_required"))
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    elif explicit:
        raise ValueError(tr("checker.config.config_missing"))
    else:
        cfg["workflow"] = None
    return cfg
