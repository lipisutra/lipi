"""Аргументы и последовательность запуска проверок lipi."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from lipi.i18n import ArgumentParser, cli_output, current_language, tr, use_language
from lipi import __version__
from .audit import audit, review_base
from .commands import cmd_baseline, cmd_new, run_project_checks
from .config import _read_json, load_config, validate_config
from .conventions import CONFIG_NAME, INDEX, LOCK_NAME, MASTERPLAN, RE_DECISION_NAME, RE_DOC_NAME
from .docs import check_docs, check_edition_docs, check_edition_links, check_links
from .model import Project, is_within, walk_md_agents
from .report import FORMATS, Report, finding_item, json_output, level_of_project, print_gh
from .reviews import REVIEWS_NAME, ReviewError
from .state import apply_baseline, check_lipi_files, check_lipi_link, version_mismatch
from .structure import build_stale, build_structure
from .trace import check_drift, git_changed, scan_code
from .workflow import check_workflow, scan_workflow
from .workflow_index import (IndexErrorBase, IndexHeaderError, apply_index,
                             build_project_index, plan_index, read_index_files)
from .workflow_layout import latest_closed_date


def take_format(argv):
    """Вынимает --format ЗНАЧЕНИЕ из аргументов команды new.

    Аргументы new (тип документа и название) разбираются отдельно от ключей
    чекера, поэтому формат вынимается до разбора: он может стоять и до new,
    и после. Возвращает (формат или None, остаток); при ошибке — (None, None),
    сообщение уже напечатано.
    """
    fmt, rest, i = None, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--format":
            if i + 1 >= len(argv):
                print(tr("checker.runner.format_required"), file=sys.stderr)
                return None, None
            fmt, i = argv[i + 1], i + 2
            continue
        if arg.startswith("--format="):
            fmt, i = arg[len("--format="):], i + 1
            continue
        rest.append(arg)
        i += 1
    if fmt is not None and fmt not in FORMATS:
        print(tr("checker.runner.invalid_format") % fmt,
              file=sys.stderr)
        return None, None
    return fmt, rest


def _review_label(value):
    # Строковый разделитель и старый синтаксис команд GitHub Actions.
    return (json.dumps(value, ensure_ascii=False).replace("\x85", r"\u0085")
            .replace("\u2028", r"\u2028").replace("\u2029", r"\u2029")
            .replace("##[", r"\u0023#["))


def _print_reviewers(rows):
    for row in rows:
        print(tr("checker.runner.reviewer_summary")
              % (_review_label(row["reviewer"]), row["count"], row["last_reviewed_at"]))


@cli_output
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # --json удалён: машинный вывод — --format json. В new ключ тоже не
    # принимается, а argparse увидел бы его только до new.
    if "--json" in argv:
        print(tr("checker.runner.removed_json_flag"), file=sys.stderr)
        return 2
    new_args, new_fmt, baseline_args = None, None, None
    # new и baseline также могут быть именами Git-ревизий.
    command = next((i for i, arg in enumerate(argv) if arg in ("new", "baseline")
                    and (i == 0 or argv[i - 1] != "--reviews-since")), None)
    subcommand_options = []
    if command is not None:
        name = argv[command]
        argv, subcommand_args = argv[:command], argv[command + 1:]
        if name == "new":
            new_fmt, new_args = take_format(subcommand_args)
            if new_args is None:
                return 2
            subcommand_options = new_args[:1] + new_args[2:]  # Второй аргумент — заголовок.
        else:
            baseline_args = subcommand_args
            subcommand_options = baseline_args
    ap = ArgumentParser(description=tr("checker.runner.description"))
    ap.add_argument("--root", default=".", help=tr("checker.runner.root_help"))
    ap.add_argument("--config", help=tr("checker.runner.config_help") % CONFIG_NAME)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true",
                   help=tr("checker.runner.staged_help"))
    g.add_argument("--diff", metavar="RANGE",
                   help=tr("checker.runner.diff_help"))
    ap.add_argument("--audit", action="store_true", help=tr("checker.runner.audit_help"))
    ap.add_argument("--reviews-since", metavar="REV",
                    help=tr("checker.runner.reviews_since_help"))
    ap.add_argument("--write-index", action="store_true",
                    help=tr("checker.runner.write_index_help"))
    ap.add_argument("--no-baseline", action="store_true",
                    help=tr("checker.runner.no_baseline_help"))
    ap.add_argument("--format", choices=FORMATS, default="text",
                    help=tr("checker.runner.format_help"))
    ap.add_argument("--structure", action="store_true",
                    help=tr("checker.runner.structure_help"))
    ap.add_argument("--strict", action="store_true", help=tr("checker.runner.strict_help"))
    ap.add_argument("--version", action="version", version="lipi %s" % __version__)
    args = ap.parse_args(argv)
    if any(arg.split("=", 1)[0] == "--reviews-since" for arg in subcommand_options) or (
            args.reviews_since is not None
            and (not args.audit or command is not None or args.write_index)):
        ap.error(tr("checker.runner.reviews_since_requires_audit"))
    fmt = new_fmt or args.format
    # argparse accepts abbreviated options, so use the parsed format for the report.
    with use_language("en" if fmt == "json" else current_language()):
        return _check(args, fmt, new_args, baseline_args, ap)


def _check(args, fmt, new_args, baseline_args, ap):
    root = Path(args.root).resolve()
    try:
        cfg = load_config(root, args.config)
    except (ValueError, OSError) as e:
        print(tr("checker.runner.unreadable_settings") % e, file=sys.stderr)
        return 2
    c1 = validate_config(root, cfg)
    reviews_base = None
    if args.reviews_since is not None:
        try:
            reviews_base = review_base(root, args.reviews_since)
        except ReviewError as error:
            c1.append((REVIEWS_NAME, str(error)))
        except ValueError as error:
            ap.error("--reviews-since: %s" % error)
    if c1:
        if fmt == "json":
            errors = [finding_item((path, 0, "E", "C1", msg, "")) for path, msg in c1]
            print(json.dumps(json_output(errors, []), ensure_ascii=False))
        elif fmt == "github":
            print_gh((path, 0, "E", "C1", msg, "") for path, msg in c1)
        else:
            rep = Report()
            for path, msg in c1:
                rep.finding("C1", path, 0, msg)
            rep.dump()
        return 2
    pr = Project(root, cfg)
    pr.reviews_present = os.path.lexists(root / REVIEWS_NAME)
    pr.reviewed_pairs = set()
    if new_args is not None:
        return cmd_new(pr, new_args, fmt)
    if pr.docs is None and pr.wf is None and not (pr.decisions and pr.decisions.is_dir()):
        print(tr("checker.runner.no_project_directories"), file=sys.stderr)
        return 2

    rep = Report(level_of_project(pr.cfg))
    # @trace docs/ru/codes.md#v1
    # V1: версия установленного lipi против версии развёртывания (ADR-010).
    # Источник версии развёртывания — lock-файл.
    lock_path = root / LOCK_NAME
    data = _read_json(lock_path) if lock_path.is_file() else None
    if lock_path.is_file():
        deployed = data.get("lipi") if isinstance(data, dict) else None
        mismatch = version_mismatch(__version__, deployed)
        if mismatch is not None:
            level, message = mismatch
            # уровень V1 — по правилу совместимости, не из таблицы (см. CODE_LEVELS)
            rep.finding("V1", LOCK_NAME, 0, message, subject=LOCK_NAME, level=level)

    # @trace docs/ru/codes.md#v2,docs/ru/codes.md#v3
    if isinstance(data, dict):
        v2 = check_lipi_link(root)
        if v2 is not None:
            rep.finding("V2", v2[0], 0, v2[1], subject=v2[0])
        for name, msg, level in check_lipi_files(root, cfg):
            # уровень V3 — по правилу (enforce), не из таблицы (см. CODE_LEVELS)
            rep.finding("V3", name, 0, msg, subject=name, level=level)
    # @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
    pages, anchor_ids, covers, reachable = check_docs(pr, rep)
    # @trace docs/ru/codes.md#l1,docs/ru/codes.md#l2,docs/ru/codes.md#l3
    edition_pages = check_edition_docs(pr, rep)
    check_edition_links(pr, rep, edition_pages)
    docs, others = scan_workflow(pr, rep)
    latest_date = latest_closed_date()
    # @trace docs/ru/codes.md#w7
    index_files = {}
    if pr.wf is not None and not pr.target_skip_dirs.excludes(pr.wf, directory=True, base=pr.wf):
        try:
            previous = read_index_files(pr)
            index_files = build_project_index(pr, docs, previous=previous, latest_date=latest_date)
            index_plan = plan_index(pr, index_files, previous=previous)
            writable = (args.write_index or (fmt != "github" and not args.staged
                        and not args.diff and not os.environ.get("CI")))
            if writable:
                apply_index(pr, index_plan)
                others = sorted(set(others) | set(index_files))
                if index_plan.changes and fmt == "text" and not args.write_index:
                    for path in index_plan.changes:
                        print(tr("checker.runner.index_rebuilt") % pr.rel(path), file=sys.stderr)
            else:
                for path in index_plan.changes:
                    rep.finding("W7", pr.rel(path), 0,
                                tr("checker.runner.stale_index"))
        except IndexHeaderError:
            pass  # W3/W4 ниже; неполный комплект не записываем.
        except IndexErrorBase as error:
            rep.finding("W7", pr.rel(error.path), 0, error.message)
        except OSError as error:
            rep.finding("W7", pr.rel(pr.wf / INDEX), 0,
                        tr("checker.runner.index_write_failed") % error)
    mp_refs = check_workflow(pr, rep, docs, others, latest_date=latest_date)

    # правила исполнителя: ссылки
    rules = [root / "AGENTS.md", *walk_md_agents(pr)]
    if not is_within(pr.file_path(root / "README.md"), pr.docs):
        rules.append(root / "README.md")          # корневой README: только ссылки
    for p in rules:
        if pr.file_path(p) is not None and p.is_file():
            page = pr.page(p)
            if page is not None:
                check_links(pr, rep, page, "W6")

    # @trace docs/ru/codes.md#t1
    tags, tag_lines = scan_code(pr, rep)
    # @trace docs/ru/codes.md#p1
    # P1: команды проекта из ключа checks (ADR-008). Запускаются и при
    # `baseline`, чтобы ошибка проверки попадала в линию как обычная.
    run_project_checks(pr, rep, args.audit)
    if baseline_args is not None:
        return cmd_baseline(root, rep, baseline_args)
    changed = None
    if args.staged or args.diff:
        try:
            changed = git_changed(pr, args)
        except (OSError, subprocess.CalledProcessError) as e:
            msg = getattr(e, "stderr", b"") or b""
            print(tr("checker.runner.git_diff_failed") % (msg.decode("utf-8", "replace").strip() or e),
                  file=sys.stderr)
            return 2
    # @trace docs/ru/codes.md#t2
    if args.structure:
        extra = []
        for did, d in docs.items():
            extra.append({"page": d["page"], "source": did.upper(), "type": "work"})
            parent = d["page"].path.parent
            if parent != pr.decisions and (RE_DOC_NAME.match(parent.name)
                    or (d['prefix'] == 'adr' and RE_DECISION_NAME.fullmatch(parent.name))):
                for p in pr.walk_md(parent):
                    if pr.file_path(p) != d["page"].path:
                        extra.append({"page": pr.page(p), "source": did.upper(), "type": "work"})
        if pr.wf is not None:
            paths = {pr.wf / name for name in (INDEX, MASTERPLAN, "README.md")} | set(index_files)
            for fp in sorted(paths):
                fp = pr.file_path(fp)
                if fp is not None and fp.is_file() and not pr.target_skip_dirs.excludes(fp, base=pr.wf):
                    extra.append({"page": pr.page(fp), "source": pr.rel(fp), "type": "file"})
        for p in rules:
            if pr.file_path(p) is not None and p.is_file():
                extra.append({"page": pr.page(p), "source": pr.rel(p), "type": "rules"})
        structure = build_structure(pr, pages, anchor_ids, covers, docs, tag_lines,
                                    mp_refs, reachable, extra)
        if changed is not None:
            structure["stale"] = build_stale(pr, pages, anchor_ids, covers, tag_lines, docs, changed)
    else:
        structure = None
    if changed is not None:
        check_drift(pr, rep, pages, anchor_ids, covers, tag_lines, changed)
    # @trace docs/ru/review.md#summary
    if args.audit:
        try:
            audit(pr, rep, docs, anchor_ids, tags, tag_lines, reviews_base=reviews_base)
        except re.error as e:
            print(tr("checker.runner.invalid_entry_pattern") % e, file=sys.stderr)
            return 2
        except ReviewError as error:
            item = (REVIEWS_NAME, 0, "E", "C1", str(error), "")
            if fmt == "json":
                print(json.dumps(json_output([finding_item(item)], []), ensure_ascii=False))
            elif fmt == "github":
                print_gh([item])
            else:
                print(tr("checker.runner.review_error") % (REVIEWS_NAME, error))
            return 2

    # Базовая линия: покрытые ею ошибки не считаются и не печатаются, пока не
    # передан --no-baseline. Предупреждения линией не покрываются.
    baseline = None if args.no_baseline else apply_baseline(root, rep)
    e, w = rep.count("E"), rep.count("W")
    if fmt == "json":
        errors = [finding_item(i) for i in sorted(rep.items) if i[2] == "E"]
        warnings = [finding_item(i) for i in sorted(rep.items) if i[2] == "W"]
        summary = {"pages": len(pages), "docs": len(docs),
                   "tags": sum(len(v) for v in tags.values()),
                   "errors": e, "warnings": w}
        if args.audit:
            summary["ignored_trace_lines"] = pr.ignored_trace_lines
            if pr.reviews_since is not None:
                summary["reviews_since"] = pr.reviews_since
        if pr.reviews_present:
            summary["reviewed_pairs"] = len(pr.reviewed_pairs)
            if args.audit:
                summary.update(reviewed_obsolete=pr.reviewed_obsolete,
                               reviewed_unchecked=pr.reviewed_unchecked,
                               reviewed_by=pr.reviewed_by)
        print(json.dumps(json_output(errors, warnings, baseline, summary, structure),
                         ensure_ascii=False))
    elif fmt == "github":
        print_gh(rep.items)
    else:
        rep.dump()
        print(tr("checker.runner.summary")
              % (len(pages), len(docs), sum(len(v) for v in tags.values()), e, w))
        if baseline is not None:
            print(tr("checker.runner.baseline_summary") % baseline)
    if args.audit and fmt != "json":
        print(tr("checker.runner.ignored_trace_summary") % pr.ignored_trace_lines)
    if pr.reviews_present and fmt != "json":
        print(tr("checker.runner.reviewed_pairs_summary") % len(pr.reviewed_pairs))
        if args.audit:
            print(tr("checker.runner.obsolete_reviews_summary")
                  % (pr.reviewed_obsolete, pr.reviewed_unchecked))
            _print_reviewers(pr.reviewed_by)
    if args.audit and fmt != "json" and pr.reviews_since is not None:
        print(tr("checker.runner.reviews_since_summary")
              % (_review_label(pr.reviews_since["revision"]), pr.reviews_since["count"]))
        _print_reviewers(pr.reviews_since["by_reviewer"])
    return 1 if e or (args.strict and w) else 0
