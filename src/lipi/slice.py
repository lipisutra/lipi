#!/usr/bin/env python3
"""lipi slice — срез карты проекта под одну задачу, без записи файлов."""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lipi.i18n import ArgumentParser, cli_output, tr
from lipi.checker.config import load_config, validate_config
from lipi.checker.conventions import CONFIG_NAME
from lipi.checker.model import Project
from lipi.checker.report import Report, finding_item, json_output
from lipi.checker.reviews import REVIEWS_NAME, ReviewError
from lipi.slice_output import BLOCK_KINDS, render_text, select_response


def _only(value):
    kinds = value.split(",")
    if any(kind not in BLOCK_KINDS for kind in kinds):
        raise argparse.ArgumentTypeError(tr('slice.arguments.only') % ", ".join(BLOCK_KINDS))
    return kinds


def parser():
    ap = ArgumentParser(
        prog="lipi slice", description=tr('slice.help.description'),
        epilog=tr('slice.help.epilog'))
    ap.add_argument("query", nargs="?", metavar=tr('slice.help.target'), help=tr('slice.help.query'))
    changes = ap.add_mutually_exclusive_group()
    changes.add_argument("--diff", metavar=tr('slice.help.base'), help=tr('slice.help.diff'))
    changes.add_argument("--staged", action="store_true", help=tr('slice.help.staged'))
    ap.add_argument("--format", choices=("text", "json"), default="text", help=tr('output.help.format'))
    ap.add_argument("--full", action="store_true", help=tr('slice.help.full'))
    ap.add_argument("--depth", type=int, choices=(2, 3), default=1,
                    help=tr('slice.help.depth'))
    ap.add_argument("--layer", action="append", help=tr('slice.help.layer'))
    ap.add_argument("--only", type=_only, metavar=tr('slice.help.blocks'), help=tr('slice.help.only'))
    return ap


def _config_errors(errors, fmt):
    if fmt == "json":
        items = [finding_item((path, 0, "E", "C1", message, "")) for path, message in errors]
        print(json.dumps(json_output(items, []), ensure_ascii=False))
    else:
        report = Report()
        for path, message in errors:
            report.finding("C1", path, 0, message)
        report.dump()


# @trace docs/ru/slice.md#exit
@cli_output
def main(argv=None):
    ap = parser()
    args = ap.parse_args(argv)
    if (args.query is not None) + (args.diff is not None or args.staged) != 1:
        ap.error(tr('slice.arguments.query'))
    root = Path.cwd().resolve()
    try:
        cfg = load_config(root, None)
    except (ValueError, OSError) as error:
        _config_errors([(CONFIG_NAME, tr('config.read.query') % error)], args.format)
        return 2
    errors = validate_config(root, cfg)
    if errors:
        _config_errors(errors, args.format)
        return 2
    # Не вызываем runner: срезу нужны только модель и чтение связей.
    from lipi.slice_query import build_diff_slice, build_slice
    from lipi.repo_index import RepoConfigError

    project = Project(root, cfg)
    if args.diff is not None or args.staged:
        try:
            response, code = build_diff_slice(project, base=args.diff, staged=args.staged,
                                              depth=args.depth, layers=args.layer)
        except RepoConfigError as error:
            _config_errors([(CONFIG_NAME, str(error))], args.format)
            return 2
        except ReviewError as error:
            _config_errors([(REVIEWS_NAME, str(error))], args.format)
            return 2
        except ValueError as error:
            response = {"schema": 1, "error": "invalid-diff", "message": str(error)}
            print(json.dumps(response, ensure_ascii=False) if args.format == "json"
                  else tr('slice.diff.error') % error)
            return 2
    else:
        try:
            response, code = build_slice(project, args.query, depth=args.depth, layers=args.layer)
        except RepoConfigError as error:
            _config_errors([(CONFIG_NAME, str(error))], args.format)
            return 2
        except ReviewError as error:
            _config_errors([(REVIEWS_NAME, str(error))], args.format)
            return 2
    response = select_response(response, cfg["slice_budget"], args.full, args.only)
    print(json.dumps(response, ensure_ascii=False) if args.format == "json" else render_text(response))
    return code


if __name__ == "__main__":
    sys.exit(main())
