#!/usr/bin/env python3
"""Применяет файлы установленного lipi к проекту (ADR-014).

Наличие .agents/lipi/lipi.lock отличает повторное применение от первого.
Первое сохраняет существующие файлы; повторное заменяет файлы lipi по
шаблонам пакета. Настройки, заготовки и базовая линия принадлежат проекту.
Установкой программы управляет установщик, init не обращается к сети.
"""
import datetime
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from argparse import SUPPRESS
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
# файлы lipi: правила и lock-файл живут в одном каталоге проекта
LIPI_DIR = ".agents/lipi"
LOCK_REL = ".agents/lipi/lipi.lock"
LIPI_README = LIPI_DIR + "/README.md"
# необязательный шаблон CI: файл lipi, но лежит не в .agents/lipi/, а
# там, куда его ждёт GitHub Actions. В шаблонах он — lipi/<слой>/ci/github.yml.
CI_REL = ".github/workflows/lipi.yml"
CI_TEMPLATE_REL = Path("ci/github.yml")
# Свой pre-commit узнаётся только по строке-метке «# lipi».
HOOK_REL = ".git/hooks/pre-commit"
RE_HOOK_MARK = re.compile(r"(?m)^# lipi[ \t]*\r?$")
RE_LINK = re.compile(r"\[([^\]]+)\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
RE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SRC))
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
from lipi import __version__ as VERSION  # noqa: E402
from lipi.checker.conventions import BASE_NAME  # noqa: E402
from lipi.checker.config import validate_config  # noqa: E402
from lipi.checker.model import git_worktree_root, has_symlink  # noqa: E402
from lipi.i18n import ArgumentParser, current_language, template_path, tr  # noqa: E402


def template_files(base, rel=()):
    """(относительный путь, файл) всех файлов под base: Traversable не умеет rglob."""
    for child in base.iterdir():
        if child.is_dir():
            yield from template_files(child, rel + (child.name,))
        elif child.is_file():
            yield rel + (child.name,), child


def is_lipi_rel(name):
    """Путь в проекте — файл lipi: .agents/lipi/* или подключённый шаблон CI?"""
    name = name.replace(os.sep, "/")
    return (name == CI_REL or name == LIPI_DIR
            or name.startswith(LIPI_DIR + "/"))


def drop_foreign_workflow(files, wf):
    """Убирает из каркаса чужие рабочие материалы: их проверка отключена.

    Файлы, которые каркас создал бы в чужом каталоге, не создаются; ссылки на
    них из остальных файлов становятся текстом, чтобы в проекте не появлялись
    ссылки на несуществующее.
    """
    files = {p: text for p, text in files.items() if wf not in p.parents}

    def outside(p, path):
        return wf == path or wf in path.parents

    for p in list(files):
        base = p.parent

        def repl(m):
            target = unquote(m.group(2).split("#")[0])
            if not target or RE_SCHEME.match(target):
                return m.group(0)
            if outside(p, (base / target).resolve()):
                return m.group(1)
            return m.group(0)

        files[p] = RE_LINK.sub(repl, files[p])
    return files


def _fill(text, dst, docs, wf, lipi_dir, docs_name, wf_name, descr_name, today):
    """Подстановки шаблона: имена каталогов, относительные пути, дата.

    Условия enforce и {{MAJOR}} подставляет _fill_strictness.
    """
    def to(target):
        return os.path.relpath(str(target), str(dst.parent)).replace(os.sep, "/")

    return (text.replace("{{DOCS_REL}}", to(docs))
            .replace("{{WORKFLOW_REL}}", to(wf))
            .replace("{{LIPI_REL}}", to(lipi_dir))
            .replace("../{{DOCS}}", to(docs))
            .replace("../{{WORKFLOW}}", to(wf))
            .replace("{{DOCS}}", docs_name).replace("{{WORKFLOW}}", wf_name)
            .replace("{{DESCRIPTION}}", descr_name or "")
            .replace("{{DATE}}", today))


def _fill_strictness(text, dst, ci_dst, enforce):
    """Строгость проекта (ADR-011): правила агента — прозой, шаблон CI —
    строкой `continue-on-error` шага проверки; {{MAJOR}} — первая цифра
    версии в теге установки (ADR-010)."""
    if dst == ci_dst:
        return (text.replace("{{MAJOR}}", VERSION.split(".")[0])
                    .replace("{{ENFORCE}}", "" if enforce else "        continue-on-error: true"))
    mode = "ON" if enforce else "OFF"
    return re.sub(r"(?m)^\{\{ENFORCE_(ON|OFF)\}\} ([^\n]*)(\n|$)",
                  lambda line: line[2] + line[3] if line[1] == mode else "", text)


def _dest(relp, root, docs, wf):
    """Куда попадает файл шаблона: docs/, workflow/ или корень проекта."""
    parts = relp.parts
    if parts[0] == "docs":
        return docs.joinpath(*parts[1:])
    if parts[0] == "workflow":
        return wf.joinpath(*parts[1:])
    return root.joinpath(*parts)


def render(root, kind, docs_name, wf_name, templates=None, enforce=False, *, language=None):
    """Файлы каркаса для проекта: {путь назначения: текст}.

    templates — переопределение каталога; по умолчанию используются шаблоны пакета. enforce —
    строгость проекта (ADR-011): по нему отрисовываются правила агента и
    шаблон CI. Файлы lipi (templates/lipi/) попадают в .agents/lipi/, кроме
    шаблона CI: он — файл lipi, но живёт в .github/workflows/lipi.yml, где его
    ждёт GitHub Actions. Файлы lipi всегда английские, заготовки (templates/seed/)
    копируются на выбранном языке. У приложения к documentation.md добавляется
    раздел про справку.
    """
    managed, seeds, description = _render(root, kind, docs_name, wf_name,
                                          (root / wf_name).resolve(), templates, enforce,
                                          language=language, include_seeds=True)
    return {**seeds, **managed}, description


def _render(root, kind, docs_name, wf_name, wf, templates, enforce, *, language=None,
            include_seeds=False):
    docs = (root / docs_name).resolve()
    lipi_dir = (root / LIPI_DIR).resolve()
    ci_dst = root.joinpath(*CI_REL.split("/"))
    descr_name = (docs_name + "/development") if kind == "app" else None
    today = datetime.date.today().isoformat()
    if language is None:
        language = current_language() if include_seeds else "en"

    def canonical(relative):
        if templates is not None:
            return templates.joinpath(*relative.parts)
        return template_path(relative, language="en")

    def render_file(relative, default_src, dst):
        src = default_src if templates is not None else template_path(relative, language=language)
        text = _fill(src.read_text(encoding="utf-8"), dst, docs, wf, lipi_dir,
                     docs_name, wf_name, descr_name, today)
        return _fill_strictness(text, dst, ci_dst, enforce)

    managed, seeds = {}, {}
    groups = [("lipi", managed)]
    if include_seeds:
        groups.append(("seed", seeds))
    for layer in ("common", kind):
        for group, files in groups:
            directory = Path(group, layer)
            base = canonical(directory)
            if not base.is_dir():
                continue
            for names, src in sorted(template_files(base), key=lambda item: item[0]):
                relp = Path(*names)
                if group == "seed":
                    dst = _dest(relp, root, docs, wf)
                elif relp.name.startswith(".agents-"):
                    continue
                elif relp == CI_TEMPLATE_REL:
                    dst = ci_dst
                else:
                    dst = lipi_dir / relp
                files[dst] = render_file(directory / relp, src, dst)

    extra = Path("lipi", kind, ".agents-documentation-extra.md")
    default_extra = canonical(extra)
    doc_rules = lipi_dir / "documentation.md"
    if default_extra.is_file() and doc_rules in managed:
        managed[doc_rules] = (managed[doc_rules].rstrip("\n") + "\n"
                              + render_file(extra, default_extra, doc_rules))
    return managed, seeds, descr_name


def _workflow_destination(root, workflow):
    wf = Path(os.path.abspath(root / (workflow or "workflow")))
    if has_symlink(wf, root) and git_worktree_root(root) is not None:
        raise ValueError(tr('init.workflow_symlink') % wf)
    try:
        wf = wf.resolve()
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    if workflow is not None and not wf.is_relative_to(root):
        raise ValueError(tr('init.external_workflow'))
    return wf


def deployment_files(root, kind, docs, workflow, enforce, old_files, *,
                     ci=None, templates=None, include_seeds=False, foreign_workflow=False,
                     workflow_path=None):
    """Render the files init can write and the exact fingerprint map for the lock."""
    wf_name = workflow or "workflow"
    wf = _workflow_destination(root, workflow) if workflow_path is None else workflow_path
    managed, seeds, description = _render(root, kind, docs or ".", wf_name, wf,
                                          templates, enforce, include_seeds=include_seeds)
    files = {**seeds, **managed}
    if workflow is None or foreign_workflow:
        files = drop_foreign_workflow(files, wf)
    ci_owned = ci == "github" or CI_REL in old_files
    expected = {}
    for path in managed.keys() & files.keys():
        name = rel_name(root, path)
        if is_lipi_rel(name) and (name != CI_REL or ci_owned):
            expected[name] = template_digest(files[path])
        else:
            del files[path]
    return files, expected, description


def sha256_hex(path):
    """Отпечаток файла для lock: sha256 в hex."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock(root):
    """Версия, ожидаемые отпечатки и enforce; повреждённый lock — ошибка."""
    path = root / LOCK_REL
    if not path.exists() and not path.is_symlink():
        return None, {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(tr('init.lock_json') % LOCK_REL) from exc
    return parse_lock(data)


def parse_lock(data):
    if not isinstance(data, dict):
        raise ValueError(tr('init.lock_object') % LOCK_REL)
    version, files = data.get("lipi"), data.get("files")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(tr('init.lock_version') % LOCK_REL)
    if (not isinstance(files, dict)
            or any(not isinstance(digest, str)
                   or not re.fullmatch(r"[0-9a-f]{64}", digest)
                   for digest in files.values())):
        raise ValueError(tr('init.lock_digests') % LOCK_REL)
    if set(data) - {"lipi", "files", "enforce"}:
        raise ValueError(tr('init.lock_key') % LOCK_REL)
    if not isinstance(data.get("enforce", False), bool):
        raise ValueError(tr('init.lock_enforce') % LOCK_REL)
    return version, files, data.get("enforce", False)


def lock_text(version, files, enforce):
    """Канонический lock с ожидаемыми отпечатками шаблонов."""
    return json.dumps({"lipi": version, "files": files, "enforce": enforce},
                      sort_keys=True, indent=2) + "\n"


def write_lock(root, version, files, enforce=False):
    """Записывает lock только при изменении его содержимого."""
    path = root / LOCK_REL
    text = lock_text(version, files, enforce)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rel_name(root, path):
    """Путь файла в проекте так, как он пишется в lock: всегда через «/»."""
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def template_digest(text):
    """Отпечаток новой версии шаблона: тот, что будет у файла после записи.

    Файлы пишутся в текстовом режиме, и «\\n» на Windows становится CRLF;
    отпечаток считается по тем же байтам, иначе следующий init счёл бы
    файл, записанный шаблоном, изменённым.
    """
    data = text.encode("utf-8")
    if os.linesep != "\n":
        data = data.replace(b"\n", os.linesep.encode("utf-8"))
    return hashlib.sha256(data).hexdigest()


def hook_text():
    message = shlex.quote(tr('init.hook_missing_command'))
    return (
        "#!/bin/sh\n"
        "# lipi\n"
        "if ! command -v lipi >/dev/null 2>&1; then\n"
        f"  echo {message} >&2\n"
        "  exit 1\n"
        "fi\n"
        "exec lipi check --staged\n"
    )


def is_lipi_hook(text):
    """Свой pre-commit содержит строку-метку «# lipi»."""
    return bool(RE_HOOK_MARK.search(text))


# @trace ADR-011
def hook_plan(root, enforce):
    """Что делать с pre-commit: действие или None, если делать нечего.

    created — поставить свой хук, updated — заменить свой, kept — свой уже стоит, removed — убрать свой при enforce:
    false, foreign — чужой хук без метки (не трогаем, сообщаем), no-git —
    enforce: true, а в проекте нет .git.
    """
    hook = root / HOOK_REL
    if not (root / ".git").is_dir():
        return "no-git" if enforce else None
    if not hook.is_file():
        return "created" if enforce else None
    try:
        text = hook.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "foreign"
    own = is_lipi_hook(text)
    if enforce:
        if not own:
            return "foreign"
        return "kept" if text == hook_text() and os.access(hook, os.X_OK) else "updated"
    return "removed" if own else "foreign"


def sync_hook(root, enforce, dry_run=False):
    """Приводит pre-commit в соответствие с enforce (ADR-011).

    enforce: true — ставит (или заменяет) свой хук; false — убирает свой.
    Чужой хук без метки не трогает. Возвращает действие hook_plan; при
    dry_run ничего не пишет.
    """
    action = hook_plan(root, enforce)
    hook = root / HOOK_REL
    if action in ("created", "updated"):
        if not dry_run:
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text(hook_text(), encoding="utf-8")
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                       | stat.S_IXOTH)
    elif action == "removed" and not dry_run:
        hook.unlink()
    return action


HOOK_KEYS = {
    "created": ("init.hook_created", "init.hook_create_plan"),
    "updated": ("init.hook_updated", "init.hook_update_plan"),
    "kept": ("init.hook_kept", None),
    "removed": ("init.hook_removed", "init.hook_remove_plan"),
    "foreign": ("init.hook_foreign", None),
}


def show_hook(action, dry_run=False):
    """Строка сообщения о pre-commit для действия hook_plan (или ничего)."""
    if action == "no-git":
        print(tr('init.hook_no_git'))
    elif action in HOOK_KEYS:
        key, plan_key = HOOK_KEYS[action]
        print(tr(plan_key if dry_run and plan_key else key) % HOOK_REL)


def show_replaced(name, dry_run):
    key = 'init.replace_plan' if dry_run else 'init.replaced'
    print(tr(key) % name)


# @trace docs/ru/commands.md#ci
def ci_text(root, cfg, templates=None, *, language=None):
    """Отрисованный шаблон задания CI: (путь в проекте, текст) или (None, None).

    cfg — настройки проекта из lipi.json: render строит пути от них.
    """
    kind = "app" if cfg.get("description") else "package"
    files, _ = render(root, kind, cfg.get("docs") or "docs",
                      cfg.get("workflow") or "workflow", templates=templates,
                      enforce=cfg.get("enforce") is True, language=language)
    for path, text in files.items():
        if rel_name(root, path) == CI_REL:
            return path, text
    return None, None


def add_ci(root, templates=None, dry_run=False):
    """Подключает управляемый CI, сохраняя остальные файлы проекта."""
    try:
        cfg, exists, version, lock_files, lock_enforce = project_state(root)
        if not exists or version is None:
            raise ValueError(tr('init.ci_needs_init'))
        dst, text = ci_text(root, cfg, templates=templates)
        if dst is None:
            raise ValueError(tr('init.ci_missing'))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    digest = template_digest(text)
    changed = not dst.is_file() or sha256_hex(dst) != digest
    try:
        check_destinations(([dst] if changed else []) + [root / LOCK_REL])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if changed:
        if dst.is_file() and CI_REL in lock_files and sha256_hex(dst) != lock_files[CI_REL]:
            show_replaced(CI_REL, dry_run)
        if dst.exists():
            key = 'init.ci_update_plan' if dry_run else 'init.ci_updated'
        else:
            key = 'init.ci_create_plan' if dry_run else 'init.ci_created'
        print(tr(key) % CI_REL)
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
    lock_files[CI_REL] = digest
    if not dry_run:
        write_lock(root, version, lock_files, lock_enforce)
    print(tr('init.ci_summary_plan' if dry_run else 'init.ci_summary') % VERSION)
    return 0


# каталоги типов рабочих документов (ADR-004)
TYPE_DIRS = ("plan", "issue", "discussion", "adr", "audit")
# файлы каркаса в корне каталога рабочих материалов и архив
WF_DOC_ROOT = ("README.md", "INDEX.md", "masterplan.md", "migrate.json")
WF_HISTORY = "history"


# @trace docs/ru/commands.md#update
def read_config(root):
    """Настройки и наличие файла; повреждённый файл — ошибка до записи."""
    path = root / "lipi.json"
    if not path.exists() and not path.is_symlink():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(tr('init.config_json')) from exc
    if not isinstance(data, dict):
        raise ValueError(tr('init.config_object'))
    return data, True


def project_state(root):
    """Проверяет настройки и версию до любых записей в проект."""
    cfg, exists = read_config(root)
    version, lock_files, lock_enforce = read_lock(root)
    if version is not None and int(version.split(".")[0]) > int(VERSION.split(".")[0]):
        raise ValueError(tr('init.newer_project') % version)
    if version is not None and not exists:
        raise ValueError(tr('init.config_missing'))
    errors = validate_config(root, cfg)
    if errors:
        raise ValueError("\n".join("%s: %s" % item for item in errors))
    return cfg, exists, version, lock_files, lock_enforce


def foreign_workflow_paths(root, wf):
    """Документы другого формата в каталоге рабочих материалов.

    Планы по каталогам статусов (current/, completed/, backlog/) и прочий
    Markdown вне каталогов типов plan/, issue/, … переносит lipi migrate.
    Архив, указатели и файлы каркаса не участвуют в определении формата.
    """
    from lipi.checker.model import Project
    project = Project(root, {"workflow": str(wf)})
    found = []
    try:
        paths = sorted(project.walk_md(wf))
    except OSError:
        return []
    for path in paths:
        if not path.is_file():
            continue
        rel = path.relative_to(wf)
        if rel.parts[0] in TYPE_DIRS or rel.parts[0] in (WF_HISTORY, "index"):
            continue
        if len(rel.parts) == 1 and rel.name in WF_DOC_ROOT:
            continue
        found.append(rel.as_posix())
    return found


def baseline_errors(path):
    """Сколько ошибок записано в базовой линии; 0, если файла нет или записей нет."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    entries = data.get("entries") if isinstance(data, dict) else None
    total = 0
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, dict):
            count = entry.get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                total += count
    return total


def check_destinations(files, directories=()):
    """Обычные файлы и доступные каталоги проверяются до первой записи."""
    for path in files:
        if path.exists() and not path.is_file():
            raise ValueError(tr('init.destination_not_file') % path)
        if path.is_file() and not os.access(path, os.W_OK):
            raise ValueError(tr('init.destination_unwritable') % path)
    for path in list(directories) + [p.parent for p in files]:
        while not path.exists():
            if path.is_symlink():
                raise ValueError(tr('init.destination_broken_symlink') % path)
            path = path.parent
        if not path.is_dir():
            raise ValueError(tr('init.destination_not_directory') % path)
        if not os.access(path, os.W_OK | os.X_OK):
            raise ValueError(tr('init.destination_inaccessible') % path)


# @trace docs/ru/commands.md#update,ADR-014
def initialize(root, *, kind=None, docs=None, workflow=None, enforce=None,
               ci=None, dry_run=False, templates=None):
    """Первое или повторное применение установленного lipi по ADR-014."""
    root = Path(root).resolve()
    if not root.is_dir():
        print(tr('init.project_missing') % root, file=sys.stderr)
        return 2
    try:
        cfg, cfg_exists, old, old_files, _ = project_state(root)
        if cfg_exists:
            actual = {"type": "app" if cfg.get("description") else "package",
                      "docs": cfg.get("docs", "docs"),
                      "workflow": cfg.get("workflow", "workflow"),
                      "enforce": cfg.get("enforce", False)}
            for option, value in (("type", kind), ("docs", docs),
                                  ("workflow", workflow), ("enforce", enforce)):
                if value is not None and value != actual[option]:
                    key = "description" if option == "type" else option
                    raise ValueError(tr('init.option_conflict')
                                     % (option, key))
            kind, docs, workflow, enforce = (actual["type"], actual["docs"],
                                            actual["workflow"], actual["enforce"])
        else:
            kind, docs = kind or "package", docs if docs is not None else "docs"
            workflow = workflow if workflow is not None else "workflow"
            enforce = bool(enforce)
        if kind not in ("package", "app") or ci not in (None, "github"):
            raise ValueError(tr('init.invalid_type_or_ci'))
        docs_name = docs or "."
        wf_name = workflow or "workflow"
        wf = _workflow_destination(root, workflow)
        foreign_wf = (workflow is None if cfg_exists else bool(foreign_workflow_paths(root, wf)))
        files, expected, descr_name = deployment_files(
            root, kind, docs, workflow, enforce, old_files, ci=ci, templates=templates,
            include_seeds=not cfg_exists, foreign_workflow=foreign_wf, workflow_path=wf)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    repeat = old is not None
    changes, replaced = [], []
    for name, digest in sorted(expected.items()):
        path = root / name
        exists = path.exists()
        if exists and not repeat:
            print(tr('init.existing_file') % name)
            continue
        if path.is_file() and sha256_hex(path) == digest:
            print(tr('init.matching_template') % name)
            continue
        if path.is_file() and name in old_files and sha256_hex(path) != old_files[name]:
            replaced.append(name)
        changes.append((path, files[path]))

    if not cfg_exists:
        changes.extend((p, text) for p, text in sorted(files.items())
                       if rel_name(root, p) not in expected and not p.exists())
        new_cfg = {"docs": docs_name, "workflow": None if foreign_wf else wf_name,
                   "enforce": enforce}
        if descr_name:
            new_cfg["description"] = descr_name
        errors = validate_config(root, new_cfg)
        if errors:
            print("\n".join("%s: %s" % item for item in errors), file=sys.stderr)
            return 2
        changes.append((root / "lipi.json",
                        json.dumps(new_cfg, ensure_ascii=False, indent=2) + "\n"))
    removed = sorted(set(old_files) - set(expected))
    if removed:
        print(tr('init.removed_templates'))
        for name in removed:
            print("  %s" % name)
    lock_path = root / LOCK_REL
    new_lock = lock_text(VERSION, expected, enforce)
    if not lock_path.is_file() or lock_path.read_text(encoding="utf-8") != new_lock:
        changes.append((lock_path, new_lock))

    baseline = root / BASE_NAME
    index = wf / "INDEX.md"
    hook_action = hook_plan(root, enforce)
    extra_files, directories = [], []
    if not cfg_exists and not foreign_wf:
        directories = [wf / name for name in TYPE_DIRS]
        if not index.exists():
            extra_files.append(index)
    create_baseline = not repeat and not baseline.exists()
    if create_baseline:
        extra_files.append(baseline)
    if hook_action in ("created", "updated"):
        extra_files.append(root / HOOK_REL)
    elif hook_action == "removed":
        directories.append((root / HOOK_REL).parent)
    try:
        check_destinations([p for p, _ in changes] + extra_files, directories)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Повторное применение и частичный каркас переводятся одним планом,
    # включая правила, lock, указатели, состояние и управляемый hook.
    try:
        from lipi.layout_migration import prepare_layout, apply_layout
        hook_change = None
        if hook_action in ("created", "updated"):
            hook_path = root / HOOK_REL
            mode = stat.S_IMODE(hook_path.stat().st_mode) if hook_path.is_file() else 0o644
            hook_change = (hook_path, hook_text().encode("utf-8"), mode | 0o111)
        elif hook_action == "removed":
            hook_change = (root / HOOK_REL, None, None)
        external_seeds = {path for path, _ in changes
                          if not cfg_exists and not path.is_relative_to(root)}
        if external_seeds:
            from lipi.move import _no_symlinks
            lexical_docs = Path(os.path.abspath(root / docs_name))
            _no_symlinks(lexical_docs, Path(lexical_docs.anchor))
        layout = prepare_layout(root, cfg if cfg_exists else new_cfg,
                                changes, hook=hook_change,
                                external_creates=external_seeds)
        layout.directories = [wf / name for name in TYPE_DIRS] if not cfg_exists and not foreign_wf else []
        if create_baseline and dry_run and layout.config.get('checks'):
            print(tr('init.baseline_checks_on_apply'))
        from lipi.move_transaction import _validate
        _validate(layout)
        from lipi.move import print_plan
        print_plan(layout)
        for change in layout.changes:
            if change.before != change.after:
                key = 'init.change_plan' if dry_run else 'init.changing'
                print(tr(key) % rel_name(root, layout.moves.get(change.path, change.path)))
        if not dry_run:
            apply_layout(layout, create_baseline=create_baseline)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    for name in replaced:
        show_replaced(name, dry_run)
    if not repeat:
        if dry_run:
            key = 'init.baseline_create_plan' if create_baseline else 'init.baseline_keep_plan'
            print(tr(key) % BASE_NAME)
        else:
            print(tr('init.baseline') % BASE_NAME)
    agents = root / "AGENTS.md"
    if agents.is_file():
        try:
            linked = re.search(r"\]\(\s*<?" + re.escape(LIPI_README)
                               + r"(?:#[^)\s>]*)?>?\s*\)", agents.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            linked = False
        if not linked:
            print(tr('init.agents_link') % LIPI_README)
    show_hook(hook_action, dry_run)
    if foreign_wf and not cfg_exists:
        print(tr('init.foreign_workflow') % (wf_name, wf_name))
    if dry_run:
        print(tr('init.dry_run_summary') % VERSION)
    else:
        print(tr('init.summary') % VERSION)
    return 0


def main():
    ap = ArgumentParser(
        prog="lipi init", allow_abbrev=False,
        description=tr('init.help'))
    ap.add_argument("project", nargs="?", default=".",
                    help=tr('init.help_project'))
    ap.add_argument("--type", choices=("package", "app"), default=None,
                    help=tr('init.help_type'))
    ap.add_argument("--docs", default=None, help=tr('init.help_docs'))
    ap.add_argument("--workflow", default=None, help=tr('init.help_workflow'))
    ap.add_argument("--enforce", action="store_true", default=None,
                    help=tr('init.help_enforce'))
    ap.add_argument("--ci", choices=("github",), help=tr('init.help_ci'))
    ap.add_argument("--ci-only", action="store_true", help=SUPPRESS)
    ap.add_argument("--dry-run", action="store_true", help=tr('init.help_dry_run'))
    args = ap.parse_args()
    root = Path(args.project).resolve()
    if args.ci_only:
        if not args.ci:
            ap.error(tr('init.ci_only_needs_provider'))
        return add_ci(root, dry_run=args.dry_run)
    return initialize(root, kind=args.type, docs=args.docs, workflow=args.workflow,
                      enforce=args.enforce, ci=args.ci, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
