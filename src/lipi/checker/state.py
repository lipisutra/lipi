"""Версии, файлы lipi и базовая линия."""

import hashlib
import json
import re

from lipi.i18n import tr
from .config import BASE_ENTRY_KEYS, _describe, _is_nonneg_int, _read_json
from .conventions import BASE_NAME, CONFIG_NAME, LOCK_NAME, RE_LIPI_LINK, LIPI_README
from .model import read_text


RE_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")
BASELINE_EXCLUDED_CODES = frozenset({"C1", "V2"})


def version_parts(value):
    """Номер версии числом: (первая цифра, (части)); None — не разобрать."""
    if not isinstance(value, str):
        return None
    found = RE_VERSION.search(value.strip())
    if found is None:
        return None
    parts = tuple(int(part or 0) for part in found.groups())
    return parts[0], parts


# @trace docs/ru/codes.md#v1,ADR-010
def version_mismatch(installed, deployed):
    """V1 по ADR-010: (уровень, сообщение) или None, если версии совместимы.

    В пределах одной первой цифры более свежая версия проекта даёт
    предупреждение. Разные первые цифры несовместимы: примените обновление
    по CHANGELOG или проверьте проект отдельной копией lipi его линии.
    """
    installed_key = version_parts(installed)
    deployed_key = version_parts(deployed)
    if installed_key is None or deployed_key is None:
        return None
    installed_major, installed_number = installed_key
    deployed_major, deployed_number = deployed_key
    if deployed_major < installed_major:
        return ("E", tr("checker.state.incompatible_older_project")
                % (deployed_major, deployed_major, deployed_major, deployed_major,
                   ".".join(map(str, installed_number))))
    if deployed_major > installed_major:
        return ("E", tr("checker.state.upgrade_lipi"))
    if deployed_number > installed_number:
        return ("W", tr("checker.state.upgrade_lipi"))
    return None


#
# Существующий долг проекта: ошибки, найденные при подключении. В линию
# входят только ошибки, не предупреждения и не C1 (с неверными настройками
# проверке нельзя доверять — она завершается с кодом 2 до разбора линии).
# Сопоставление — по (code, file, subject): ни номер строки, ни текст
# сообщения в линию не входят, поэтому переформулировка и сдвиг строк её не
# ломают; ошибка новая, если повторов в линии меньше, чем найдено.

# @trace docs/ru/commands.md#baseline
def read_baseline(root):
    """Записи .agents/lipi/baseline.json; None, если файла нет или он не читается.

    Ошибки схемы (C1) находятся отдельно в check_baseline; сюда они не
    попадают. Отсутствие файла — не ошибка.
    """
    path = root / BASE_NAME
    if not path.is_file():
        return None
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    entries = []
    for item in data["entries"]:
        if not isinstance(item, dict):
            continue
        if not all(field in item for field in BASE_ENTRY_KEYS):
            continue
        if not all(isinstance(item[field], str) for field in ("code", "file", "subject")):
            continue
        if not _is_nonneg_int(item["count"]):
            continue
        entries.append({field: item[field] for field in BASE_ENTRY_KEYS})
    return entries


def baseline_text(entries):
    data = {"schema": 1,
            "entries": sorted(entries, key=lambda e: (e["code"], e["file"], e["subject"]))}
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_baseline(root, entries):
    """Записывает линию: сортированные ключи и записи (ADR-006, ADR-003)."""
    path = root / BASE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline_text(entries), encoding="utf-8")


# @trace docs/ru/commands.md#baseline
def baseline_counts(rep):
    """Ошибки, включаемые в базовую линию, по (code, file, subject) с числом повторов."""
    counts = {}
    for path, _, level, code, _, subject in rep.items:
        if level != "E" or code in BASELINE_EXCLUDED_CODES:
            continue
        key = (code, path, subject)
        counts[key] = counts.get(key, 0) + 1
    return [{"code": code, "file": path, "subject": subject, "count": n}
            for (code, path, subject), n in sorted(counts.items())]


# @trace docs/ru/commands.md#baseline,docs/ru/codes.md#v2
def apply_baseline(root, rep):
    """Убирает из отчёта ошибки, покрытые линией; возвращает (в линии, исправлено).

    Возвращает None, если базовой линии нет: тогда учитываются все ошибки.
    В отчёте остаются все предупреждения и только новые ошибки — те, для
    которых в линии повторов меньше, чем найдено.
    """
    entries = read_baseline(root)
    if entries is None:
        return None
    known, total = {}, 0
    for entry in entries:
        if entry["code"] in BASELINE_EXCLUDED_CODES:
            continue
        key = (entry["code"], entry["file"], entry["subject"])
        known[key] = known.get(key, 0) + entry["count"]
        total += entry["count"]
    found = {}
    for index, item in enumerate(rep.items):
        if item[2] == "E":
            found.setdefault((item[3], item[0], item[5]), []).append(index)
    keep_new = set()
    for key, indexes in found.items():
        for index in indexes[known.get(key, 0):]:
            keep_new.add(index)
    in_line = sum(min(known.get(key, 0), len(indexes)) for key, indexes in found.items())
    rep.items = [item for index, item in enumerate(rep.items)
                 if item[2] != "E" or index in keep_new]
    return in_line, total - in_line


# --- Файлы lipi (V2, V3) -----------------------------------------------------
#
# ADR-009: файлы lipi принадлежат lipi, проект их не правит. V2 проверяет,
# что AGENTS.md проекта ссылается на правила lipi (иначе агент проекта о них
# не узнает), V3 — что lock-файл хранит отпечатки и файлы lipi им соответствуют.
# Обе проверки — ошибки быстрого режима: целостность каркаса важна
# до того, как чекеру можно доверять. Неподходящее правило lipi не правится на
# месте: заводится замечание к lipi. main запускает их при наличии lock-файла,
# в том числе в репозитории самого lipi после lipi init.

def has_lipi_link(text):
    """Есть ли в тексте markdown-ссылка на .agents/lipi/README.md."""
    return bool(RE_LIPI_LINK.search(text))


# @trace docs/ru/codes.md#v2
def check_lipi_link(root):
    """V2: (путь, сообщение) или None. AGENTS.md проекта ссылается на правила lipi.

    Ссылку содержит новая заготовка AGENTS.md; в существующий файл её
    добавляет проект. Нет AGENTS.md или ссылки в нём — ошибка: агент проекта
    правил lipi не найдёт.
    """
    text = read_text(root / "AGENTS.md")
    if text is not None and has_lipi_link(text):
        return None
    return "AGENTS.md", tr("checker.state.missing_lipi_rules_link") % LIPI_README


def sha256_file(path):
    """SHA-256 файла; None, если файла нет или он не читается."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# @trace docs/ru/codes.md#v4
def check_rule_updates(root, cfg, lock, installed):
    """Compare the deployed manifest with the one a repeat init would write."""
    from lipi.init import deployment_files, parse_lock, project_state

    if not (root / CONFIG_NAME).is_file():
        return
    try:
        if cfg is None:
            # A check-only --config can set severity. Plain init always reads lipi.json.
            cfg, _, deployed, previous, _ = project_state(root)
        else:
            deployed, previous, _ = parse_lock(lock)
        if not previous or version_mismatch(installed, deployed) is not None:
            return
        kind = "app" if cfg.get("description") else "package"
        _, expected, _ = deployment_files(root, kind, cfg.get("docs", "docs"),
                                          cfg.get("workflow", "workflow"),
                                          cfg.get("enforce", False), previous)
    except (ValueError, OSError, RuntimeError):
        # An invalid lock or unresolvable deployment path has no applicable init plan.
        return
    for name in sorted(previous.keys() | expected.keys()):
        if previous.get(name) == expected.get(name):
            continue
        if name not in expected:
            message = tr("checker.state.rule_retired") % installed
        else:
            path = root / name
            actual = sha256_file(path) if path.is_file() else None
            if actual == expected[name]:
                message = tr("checker.state.rule_record") % installed
            else:
                key = "checker.state.rule_updated" if name in previous else "checker.state.rule_added"
                message = tr(key) % installed
                if actual is not None and actual != previous.get(name):
                    message += " " + tr("checker.state.preserve_edits")
                else:
                    message += " " + tr("checker.state.apply_rule")
        yield name, message


# @trace docs/ru/codes.md#v3
def check_lipi_files(root, cfg=None):
    """V3: [(путь, сообщение, уровень)] — состояние файлов lipi по lock.

    Пустой список отпечатков — ошибка, иначе сверяются все записи lock-файла
    о файлах lipi. Без lock-файла проверка молчит. Схему lock-файла проверяет C1.

    Правила агента отрисовываются по enforce (ADR-011), поэтому lock-файл
    хранит значение, с которым их отрисовал init: расхождение с lipi.json
    значит, что правила устарели и нужен lipi init. Это предупреждение, а не
    ошибка: enforce не меняет код возврата lipi check (ADR-011), а после
    lipi init файлы перерисуются и расхождение уйдёт.
    """
    path = root / LOCK_NAME
    if not path.is_file():
        return []
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return []
    cfg = cfg or {}
    errors = []
    if not data["files"]:
        errors.append((LOCK_NAME, tr("checker.state.missing_lock_fingerprints"), "E"))
    rendered = data.get("enforce", False) is True
    enforced = cfg.get("enforce") is True
    if rendered != enforced:
        errors.append((LOCK_NAME,
                       tr("checker.state.enforce_mismatch")
                       % (_describe(rendered), _describe(enforced)), "W"))
    for name, digest in sorted(data["files"].items()):
        if sha256_file(root / name) != digest:
            errors.append((name, tr("checker.state.fingerprint_mismatch")
                            % name, "E"))
    return errors
