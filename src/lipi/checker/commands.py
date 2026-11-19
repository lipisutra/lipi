"""Создание документов, базовая линия и команды проверок проекта."""

from pathlib import Path
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

from lipi.i18n import current_language, tr
from .conventions import (
    BASE_NAME,
    CONFIG_NAME,
    DECISION_HEADING,
    ISSUE_KINDS,
    K_ADDRESSEE,
    K_CREATED,
    K_KIND,
    K_STATUS,
    K_UPDATED,
    REQUIRED_SECTIONS,
    STATUSES,
    TYPES,
)
from .model import feedback_dir, has_symlink, is_within
from .report import Report, level_of_project
from .state import baseline_counts, read_baseline, write_baseline
from .targets import target_excluded
from .workflow_layout import document_directory
from .workflow import decision_names, next_number, scan_workflow, slugify
from .workflow_index import IndexErrorBase, refresh_index


def cmd_baseline(root, rep, argv):
    """baseline [--prune]: записать ошибки в линию или убрать исправленное."""
    extra = [a for a in argv if a != "--prune"]
    if extra:
        print(tr("checker.commands.baseline_usage"), file=sys.stderr)
        return 2
    prune = "--prune" in argv
    current = {}
    for entry in baseline_counts(rep):
        key = (entry["code"], entry["file"], entry["subject"])
        current[key] = current.get(key, 0) + entry["count"]
    old = read_baseline(root)
    if prune:
        if old is None:
            print(tr("checker.commands.baseline_missing") % BASE_NAME,
                  file=sys.stderr)
            return 2
        old_counts, old_total = {}, 0
        for entry in old:
            key = (entry["code"], entry["file"], entry["subject"])
            old_counts[key] = old_counts.get(key, 0) + entry["count"]
            old_total += entry["count"]
        # Только убрать исправленное и уменьшить завышенное; новое не добавляется.
        entries = [{"code": key[0], "file": key[1], "subject": key[2],
                    "count": min(count, current.get(key, 0))}
                   for key, count in sorted(old_counts.items())
                   if min(count, current.get(key, 0)) > 0]
        write_baseline(root, entries)
        new_total = sum(entry["count"] for entry in entries)
        print(tr("checker.commands.baseline_pruned")
              % (old_total, old_total - new_total, new_total))
        return 0
    entries = [{"code": key[0], "file": key[1], "subject": key[2], "count": count}
               for key, count in sorted(current.items())]
    write_baseline(root, entries)
    print(tr("checker.commands.baseline_written")
          % (BASE_NAME, sum(entry["count"] for entry in entries)))
    return 0


# --- Новый документ ----------------------------------------------------------

SKELETON = {
    "pln": ("checker.commands.skeleton_plan", tuple(REQUIRED_SECTIONS[("pln", "in progress")])),
    "aud": ("checker.commands.skeleton_audit", ()),
    "dsc": ("checker.commands.skeleton_discussion", ()),
    "adr": ("checker.commands.skeleton_decision", (DECISION_HEADING,)),
    "iss": ("checker.commands.skeleton_issue", tuple(REQUIRED_SECTIONS[("iss", "open")])),
}


def similar_issues(pr, title, path, docs):
    """До пяти открытых замечаний по совпадению слов заголовка."""
    def words(text):
        return {word for word in re.findall(r"[^\W_]+", text.casefold())
                if len(word) >= 3}

    wanted = words(title)
    if not wanted:
        return []
    ranked = []
    for doc in docs.values():
        candidate = doc["page"].path
        status = doc["header"].get(K_STATUS, "").strip("* .").lower()
        if (doc.get("ambiguous") or doc["prefix"] != "iss" or status not in ("open", "in progress")
                or candidate.resolve() == path.resolve()
                or (is_within(candidate, pr.root) and target_excluded(pr, candidate))):
            continue
        tokens = words(doc["title"])
        common = len(wanted & tokens)
        score = common / len(wanted | tokens)
        if wanted != tokens and (common < 2 or score < 0.5):
            continue
        item = {"id": doc["id"].upper(), "path": pr.rel(candidate),
                "title": doc["title"], "status": status}
        ranked.append((score, item))
    ranked.sort(key=lambda row: (-row[0], row[1]["id"], row[1]["path"]))
    return [item for _, item in ranked[:5]]


def cmd_new(pr, argv, fmt="text"):
    if len(argv) < 2 or argv[0] not in TYPES:
        print(tr("checker.commands.new_usage") % "|".join(TYPES),
              file=sys.stderr)
        return 2
    prefix, title = argv[0], argv[1]
    to_lipi = len(argv) > 3 and argv[3].strip().lower() == "lipi"
    feedback = False
    if pr.wf is None and not (prefix == 'adr' and pr.decisions is not None):
        # Без рабочих материалов место есть только у замечания к lipi.
        if prefix != "iss" or not to_lipi:
            print(tr("checker.commands.workflow_disabled")
                  % CONFIG_NAME, file=sys.stderr)
            return 2
        feedback = True
    kind = None
    if prefix == "iss":
        kind = argv[2].lower() if len(argv) > 2 else ISSUE_KINDS[0]
        if kind not in ISSUE_KINDS:
            print(tr("checker.commands.issue_kind") % ", ".join(ISSUE_KINDS), file=sys.stderr)
            return 2
    num = next_number(pr, prefix)
    today = datetime.date.today().isoformat()
    tdir = document_directory(pr, prefix, today, feedback=feedback)
    boundary = pr.root if is_within(tdir, pr.root) else pr.wf
    if pr.git_root is not None and has_symlink(tdir, boundary):
        print(tr("checker.commands.new_path_symlink") % tdir, file=sys.stderr)
        return 2
    file_prefix, file_num = prefix + '-', num
    if prefix == 'adr':
        names = decision_names(pr) or decision_names(pr, include_archived=True)
        widths = [width for _, width, bare in names if bare]
        if widths:
            file_prefix, file_num = '', str(int(num)).zfill(max(widths))
    path = tdir / ("%s%s-%s.md" % (file_prefix, file_num, slugify(title)))
    if pr.git_root is not None and has_symlink(path, boundary):
        print(tr("checker.commands.new_path_symlink") % path, file=sys.stderr)
        return 2
    tdir.mkdir(parents=True, exist_ok=True)
    head = ["# %s" % title, "", "- %s: %s" % (K_CREATED, today), "- %s: %s" % (K_UPDATED, today)]
    if prefix in STATUSES:
        head.append("- %s: %s" % (K_STATUS, STATUSES[prefix][0]))
    if prefix == "iss":
        head.append("- %s: %s" % (K_KIND, kind))
        if len(argv) > 3:
            head.append("- %s: %s" % (K_ADDRESSEE, argv[3]))
    skeleton, required_headings = SKELETON[prefix]
    body = tr(skeleton, language=current_language()) % required_headings
    path.write_text("\n".join(head) + "\n\n" + body, encoding="utf-8")
    pr.refresh_git_files()
    pr.pages.pop(path, None)
    pr.mark_work_index = None
    index_updated = not feedback and pr.wf is not None
    if index_updated or prefix == "iss":
        rep = Report(level_of_project(pr.cfg))
        docs, _ = scan_workflow(pr, rep)
    if index_updated:
        for d in docs.values():
            d["status"] = d["header"].get(K_STATUS, "").strip("* .").lower()
        try:
            refresh_index(pr, docs)
        except (IndexErrorBase, OSError) as error:
            print(tr("checker.commands.index_update_failed") % error, file=sys.stderr)
            return 2
    similar = similar_issues(pr, title, path, docs) if prefix == "iss" else []
    if fmt == "json":
        result = {"path": pr.rel(path), "id": "%s-%s" % (prefix.upper(), num),
                  "index_updated": index_updated}
        if prefix == "iss":
            result["similar"] = similar
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(tr("checker.commands.document_created") % (pr.rel(path), prefix.upper(), num,
                                   tr("checker.commands.index_updated") if index_updated else ""))
    fill = {"iss": tr("checker.commands.fill_observation"),
            "pln": tr("checker.commands.fill_plan_sections")}.get(prefix)
    if fill:
        print(fill)
    if similar:
        print(tr("checker.commands.similar_open_issues"))
        for item in similar:
            print("- %s — %s (%s)" % (item["id"], item["title"], item["path"]))
    return 0


# @trace docs/ru/codes.md#p1
def run_project_checks(pr, rep, audit_mode):
    """P1: команды проекта из ключа checks — ненулевой код, время, вывод.

    ADR-008: проверки, зависящие от стека, lipi не встраивает — проект
    перечисляет их командами. quick запускается при каждой проверке, audit —
    только с --audit; команда запускается без оболочки из корня проекта.
    Ошибка P1 входит в отчёт без файла: subject — имя проверки, поэтому
    базовая линия покрывает её как обычную ошибку. Типы ключа checks к этому
    моменту проверены схемой (C1), иначе main до проверок не дошёл бы.
    """
    for item in pr.cfg.get("checks") or []:
        name = item["name"]
        if item.get("mode", "quick") == "audit" and not audit_mode:
            continue
        exe = resolve_command(pr.root, item["run"][0])
        if exe is None:
            rep.finding("P1", "", 0, tr("checker.commands.project_check_missing_executable")
                    % (name, item["run"][0]), subject=name)
            continue
        timeout = item.get("timeout")
        try:
            # Команда проекта может быть скриптом Python: на Windows консоль
            # cp1252, и печать не-ASCII в дочернем процессе падает с
            # UnicodeEncodeError. lipi всегда печатает в UTF-8 — того же ждёт
            # от команд проекта (PYTHONIOENCODING не трогает не-Python команды).
            child_env = dict(os.environ)
            child_env["PYTHONIOENCODING"] = "utf-8"
            done = subprocess.run([exe] + item["run"][1:], cwd=str(pr.root),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout, env=child_env)
        except subprocess.TimeoutExpired as e:
            rep.finding("P1", "", 0, check_message(name, tr("checker.commands.check_timeout") % timeout, e.output),
                    subject=name)
            continue
        except OSError as e:
            rep.finding("P1", "", 0, tr("checker.commands.project_check_start_failed") % (name, e),
                    subject=name)
            continue
        if done.returncode:
            rep.finding("P1", "", 0, check_message(
                name, tr("checker.commands.check_exit_code") % done.returncode, done.stdout), subject=name)


def resolve_command(root, exe):
    """Первый элемент run: путь от корня проекта (со слэшем) или команда из PATH.

    Слэш (в том числе обратный, как на Windows) означает путь от корня
    проекта — так задают vendor/bin/phpstan. Без слэша — shutil.which: на
    Windows он находит composer.bat по расширениям из PATHEXT. None — не
    найдено.
    """
    if "/" in exe or "\\" in exe:
        path = Path(root) / exe
        return str(path) if path.is_file() else None
    return shutil.which(exe)


def tail_lines(output, limit=20):
    """Последние строки вывода для сообщения P1; пустой вывод — пустая строка."""
    if not output:
        return ""
    text = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
    lines = [s.rstrip() for s in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines[-limit:])


def check_message(name, what, output):
    """Сообщение P1: имя проверки, что случилось, конец вывода."""
    tail = tail_lines(output)
    msg = tr("checker.commands.check_result") % (name, what)
    return "%s: %s" % (msg, tail) if tail else msg
